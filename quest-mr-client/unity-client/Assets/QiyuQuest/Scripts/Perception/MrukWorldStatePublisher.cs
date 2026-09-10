using System;
using System.Collections.Generic;
using Meta.XR.MRUtilityKit;
using Newtonsoft.Json.Linq;
using Qiyu.Quest.Networking;
using Qiyu.Quest.Spatial;
using Qiyu.Quest.Voice;
using UnityEngine;

namespace Qiyu.Quest.Perception
{
    /// <summary>
    /// 把 MRUK 房间语义 + 用户头手位姿转换为冻结的 WorldState v1 并上报。
    ///
    /// 边界：
    /// - Floor/Wall/Table/Chair 等语义来自 MRUK/Scene API，不交给 YOLO；
    /// - Scene Mesh 几何仍保留在 Quest 本地，只上报语义锚点位姿/包围盒；
    /// - 杯子/手机等 Scene API 未建模物体由 P4 ObjectDetector 写入 objects。
    /// </summary>
    public class MrukWorldStatePublisher : MonoBehaviour
    {
        [Header("依赖")]
        [SerializeField] private QiyuQuestWebSocketClient webSocketClient;
        [SerializeField] private MrukSceneSummary sceneSummary;
        [SerializeField] private RoomNavMeshBuilder navMeshBuilder;

        [Header("上报")]
        [Tooltip("即使场景无变化，也按此间隔重发一次心跳级 WorldState")]
        [SerializeField] private float publishIntervalSeconds = 5f;
        [SerializeField] private bool includeHands = true;
        [Tooltip("可选：角色 Avatar 根节点；为空时自动查找 QiyuAvatar")]
        [SerializeField] private Transform avatarRoot;
        [SerializeField] private QuestMicrophoneCapture microphone;
        [SerializeField] private QuestTtsPlayer ttsPlayer;

        private int _sceneVersion;
        private float _lastPublishedAt;
        private JObject _latestPayload;
        private string _latestSignature = "";
        private MRUKRoom _room;
        private Transform _head;
        private Transform _leftHand;
        private Transform _rightHand;
        private JArray _detectedObjects = new JArray();
        private Vector3 _lastUserPosition;
        private float _lastUserSampleAt = -1f;
        private Vector3 _userVelocity;
        private bool _userSpeaking;
        private long _lastSpokeAtMs;
        private readonly Dictionary<string, Vector3> _objectPositions =
            new Dictionary<string, Vector3>();
        private readonly Dictionary<string, float> _objectSeenAt =
            new Dictionary<string, float>();

        public int SceneVersion => _sceneVersion;
        public JObject LatestPayload => _latestPayload;

        /// <summary>P4 ObjectDetectionProjector 写入的真实检测物体。</summary>
        public void SetDetectedObjects(JArray objects)
        {
            _detectedObjects = objects ?? new JArray();
            if (webSocketClient != null && webSocketClient.HandshakeDone)
            {
                RebuildAndPublish(force: false);
            }
        }

        /// <summary>QiyuUserBodyTracker 写入的用户身体骨架，供 LLM 判断用户位置。</summary>
        public void SetUserBody(JObject body)
        {
            _userBody = body;
        }

        private JObject _userBody;

        private void OnEnable()
        {
            ResolveUserTransforms();
            ResolveAuxiliary();
            if (sceneSummary != null)
            {
                sceneSummary.OnSummaryChanged += HandleRoomChanged;
            }
            if (webSocketClient != null)
            {
                webSocketClient.SessionEstablished += HandleSessionEstablished;
            }
            if (microphone != null)
            {
                microphone.OnSpeechStart += HandleSpeechStart;
                microphone.OnSpeechEnd += HandleSpeechEnd;
            }
            if (ttsPlayer != null)
            {
                ttsPlayer.OnSpeechSegmentStart += HandleTtsStart;
                ttsPlayer.OnSpeechSegmentEnd += HandleTtsEnd;
            }
        }

        private void OnDisable()
        {
            if (sceneSummary != null)
            {
                sceneSummary.OnSummaryChanged -= HandleRoomChanged;
            }
            if (webSocketClient != null)
            {
                webSocketClient.SessionEstablished -= HandleSessionEstablished;
            }
            if (microphone != null)
            {
                microphone.OnSpeechStart -= HandleSpeechStart;
                microphone.OnSpeechEnd -= HandleSpeechEnd;
            }
            if (ttsPlayer != null)
            {
                ttsPlayer.OnSpeechSegmentStart -= HandleTtsStart;
                ttsPlayer.OnSpeechSegmentEnd -= HandleTtsEnd;
            }
        }

        private void Start()
        {
            ResolveAuxiliary();
        }

        private void Update()
        {
            if (webSocketClient == null || !webSocketClient.HandshakeDone)
            {
                return;
            }
            // 用户位姿在变化：按固定间隔刷新同一场景版本下的 user 字段。
            if (_room != null && Time.unscaledTime - _lastPublishedAt >= publishIntervalSeconds)
            {
                RebuildAndPublish(force: false);
            }
        }

        private void HandleRoomChanged(string summary, MRUKRoom room)
        {
            _room = room;
            RebuildAndPublish(force: true);
        }

        private void HandleSessionEstablished()
        {
            RebuildAndPublish(force: true);
        }

        private void RebuildAndPublish(bool force)
        {
            if (webSocketClient == null || !webSocketClient.HandshakeDone)
            {
                return;
            }
            var payload = BuildPayload(_room);
            var signature = payload["anchors"]?.ToString(Newtonsoft.Json.Formatting.None) ?? "";
            if (force || signature != _latestSignature)
            {
                _sceneVersion++;
                payload["scene_version"] = _sceneVersion;
                _latestSignature = signature;
            }
            payload["scene_version"] = _sceneVersion;
            _latestPayload = payload;
            Publish(payload);
        }

        private JObject BuildPayload(MRUKRoom room)
        {
            var anchors = new JArray();
            if (room != null)
            {
                foreach (var anchor in room.Anchors)
                {
                    var json = AnchorToJson(anchor);
                    if (json != null)
                    {
                        anchors.Add(json);
                    }
                }
                var roomJson = RoomAnchorToJson(room);
                if (roomJson != null)
                {
                    anchors.Add(roomJson);
                }
            }

            var payload = new JObject
            {
                ["protocol_version"] = "1.0.0",
                ["schema_version"] = "1.1",
                ["ts"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                ["room_id"] = room != null ? room.name : "",
                ["world_epoch"] = _sceneVersion,
                ["scene_version"] = _sceneVersion,
                ["status"] = room != null && room.Anchors.Count > 0 ? "ready" : "scanning",
                ["anchors"] = anchors,
                ["objects"] = EnrichObjects(_detectedObjects),
                ["user"] = BuildUserPose(),
                ["avatar"] = BuildAvatarPose(),
                ["navmesh"] = BuildNavmeshInfo(room),
                ["interaction"] = BuildInteraction(),
                ["debug_passthrough"] = BuildPassthroughDebug()
            };
            return payload;
        }

        private static JObject BuildPassthroughDebug()
        {
            var manager = OVRManager.instance;
            var layers = UnityEngine.Object.FindObjectsByType<OVRPassthroughLayer>(
                FindObjectsInactive.Include, FindObjectsSortMode.None);
            var centerEye = GameObject.Find("CenterEyeAnchor");
            var camera = centerEye != null ? centerEye.GetComponent<Camera>() : null;
            return new JObject
            {
                ["want"] = manager != null && manager.isInsightPassthroughEnabled,
                ["supported"] = OVRManager.IsInsightPassthroughSupported(),
                ["initialized"] = OVRManager.IsInsightPassthroughInitialized(),
                ["layers"] = layers != null ? layers.Length : 0,
                ["camera_clear"] = camera != null ? camera.clearFlags.ToString() : "none",
                ["camera_alpha"] = camera != null ? camera.backgroundColor.a : -1f
            };
        }

        private JObject BuildUserPose()
        {
            ResolveUserTransforms();
            UpdateUserVelocity();
            var user = new JObject
            {
                ["head"] = PoseToJson(_head),
                ["gaze_direction"] = DirectionToJson(_head != null ? _head.forward : Vector3.zero),
                ["velocity"] = VectorToJson(_userVelocity),
                ["source"] = "headset",
                ["is_speaking"] = _userSpeaking,
                ["gaze_target_id"] = ResolveGazeTargetId(),
                ["pointing_target_id"] = ResolvePointingTargetId(),
                ["last_spoke_at_ms"] = _lastSpokeAtMs
            };
        if (includeHands)
            {
                if (_leftHand != null)
                {
                    user["left_hand"] = PoseToJson(_leftHand);
                }
                if (_rightHand != null)
                {
                    user["right_hand"] = PoseToJson(_rightHand);
                }
            }
            if (_userBody != null)
            {
                user["body"] = _userBody;
            }
            return user;
        }

        private JObject BuildAvatarPose()
        {
            if (avatarRoot == null)
            {
                var found = GameObject.Find("QiyuAvatar");
                if (found != null)
                {
                    avatarRoot = found.transform;
                }
            }
            return new JObject
            {
                ["id"] = "qiyu_avatar",
                // AvatarPose.pose 在 schema 里是必填对象；没有角色模型时给空对象用默认值，
                // 不能给 null（Pydantic 会判定 model_type 错误）。
                ["pose"] = PoseToJson(avatarRoot) ?? new JObject(),
                ["visible"] = avatarRoot != null && avatarRoot.gameObject.activeInHierarchy,
                ["state"] = avatarRoot != null && avatarRoot.gameObject.activeInHierarchy
                    ? "idle" : "hidden"
            };
        }

        private JObject BuildNavmeshInfo(MRUKRoom room)
        {
            var info = new JObject
            {
                ["generated"] = navMeshBuilder != null && navMeshBuilder.Generated,
                ["version"] = navMeshBuilder != null ? navMeshBuilder.Version : 0,
                ["walkable_area_m2"] = navMeshBuilder != null
                    ? navMeshBuilder.WalkableAreaM2 : 0f
            };
            if (navMeshBuilder != null && navMeshBuilder.Generated)
            {
                info["bounds"] = BoundsToJson(navMeshBuilder.Bounds);
            }
            else if (room != null)
            {
                var bounds = room.GetRoomBounds();
                info["bounds"] = BoundsToJson(bounds);
            }
            return info;
        }

        private JObject BuildInteraction()
        {
            var payload = new JObject();
            if (_head == null)
            {
                payload["user_distance_m"] = 0f;
                payload["user_approach_speed_mps"] = 0f;
                payload["user_relative_angle_deg"] = 0f;
                payload["occluded"] = false;
                payload["collision_risk"] = 0f;
                payload["nearest_obstacle_m"] = 0f;
                payload["navmesh_reachable"] = false;
                return payload;
            }
            var avatar = avatarRoot != null ? avatarRoot : transform;
            var toUser = _head.position - avatar.position;
            toUser.y = 0f;
            var distance = toUser.magnitude;
            var forward = avatar.forward;
            forward.y = 0f;
            var angle = toUser.sqrMagnitude > 0.001f
                ? Vector3.SignedAngle(forward, toUser.normalized, Vector3.up)
                : 0f;
            var approach = toUser.sqrMagnitude > 0.001f
                ? Vector3.Dot(_userVelocity, toUser.normalized)
                : 0f;
            var occluded = false;
            if (distance > 0.2f)
            {
                var origin = avatar.position + Vector3.up * 1.5f;
                var hits = Physics.RaycastAll(origin,
                    (_head.position - origin).normalized, distance,
                    ~0, QueryTriggerInteraction.Ignore);
                foreach (var hit in hits)
                {
                    if (hit.collider == null || hit.collider.transform.root == avatar.root)
                    {
                        continue;
                    }
                    if (hit.distance < distance - 0.2f)
                    {
                        occluded = true;
                        break;
                    }
                }
            }
            payload["user_distance_m"] = distance;
            payload["user_approach_speed_mps"] = Mathf.Max(0f, approach);
            payload["user_relative_angle_deg"] = angle;
            payload["occluded"] = occluded;
            payload["collision_risk"] = 0f;
            payload["nearest_obstacle_m"] = 0f;
            payload["navmesh_reachable"] = navMeshBuilder != null && navMeshBuilder.Generated;
            return payload;
        }

        private JArray EnrichObjects(JArray source)
        {
            var result = new JArray();
            var now = Time.realtimeSinceStartup;
            var nowMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            if (source == null)
            {
                return result;
            }
            foreach (var raw in source)
            {
                if (!(raw is JObject item))
                {
                    continue;
                }
                var clone = (JObject)item.DeepClone();
                var id = clone.Value<string>("id") ?? "";
                var position = ReadVector(clone["position"] as JObject);
                if (!string.IsNullOrEmpty(id))
                {
                    if (_objectPositions.TryGetValue(id, out var previous) &&
                        _objectSeenAt.TryGetValue(id, out var seenAt))
                    {
                        var dt = Mathf.Max(0.001f, now - seenAt);
                        clone["velocity"] = VectorToJson((position - previous) / dt);
                    }
                    else
                    {
                        clone["velocity"] = VectorToJson(Vector3.zero);
                    }
                    _objectPositions[id] = position;
                    _objectSeenAt[id] = now;
                    clone["last_seen_at_ms"] = nowMs;
                    clone["state"] = "visible";
                    if (clone["affordances"] == null)
                    {
                        clone["affordances"] = new JArray();
                    }
                }
                result.Add(clone);
            }
            return result;
        }

        private void UpdateUserVelocity()
        {
            if (_head == null)
            {
                return;
            }
            var now = Time.realtimeSinceStartup;
            if (_lastUserSampleAt > 0f)
            {
                var dt = Mathf.Max(0.001f, now - _lastUserSampleAt);
                var measured = (_head.position - _lastUserPosition) / dt;
                _userVelocity = Vector3.Lerp(_userVelocity, measured, 0.35f);
            }
            _lastUserPosition = _head.position;
            _lastUserSampleAt = now;
        }

        private string ResolveGazeTargetId()
        {
            if (_head == null)
            {
                return "";
            }
            return ResolveClosestTargetAlongRay(_head.position, _head.forward, 35f);
        }

        private string ResolvePointingTargetId()
        {
            if (_rightHand == null)
            {
                return "";
            }
            return ResolveClosestTargetAlongRay(_rightHand.position, _rightHand.forward, 45f);
        }

        private string ResolveClosestTargetAlongRay(Vector3 origin, Vector3 direction,
                                                    float maxAngleDegrees)
        {
            if (direction.sqrMagnitude < 0.001f)
            {
                return "";
            }
            var bestId = "";
            var bestScore = float.MinValue;
            foreach (var raw in _detectedObjects)
            {
                if (!(raw is JObject item))
                {
                    continue;
                }
                var id = item.Value<string>("id") ?? "";
                var position = ReadVector(item["position"] as JObject);
                if (string.IsNullOrEmpty(id) || position == Vector3.zero)
                {
                    continue;
                }
                var toTarget = position - origin;
                if (toTarget.sqrMagnitude < 0.01f)
                {
                    continue;
                }
                var angle = Vector3.Angle(direction.normalized, toTarget.normalized);
                if (angle > maxAngleDegrees)
                {
                    continue;
                }
                var score = 1f - angle / Mathf.Max(1f, maxAngleDegrees) -
                            Mathf.Clamp01(toTarget.magnitude / 8f) * 0.15f;
                if (score > bestScore)
                {
                    bestScore = score;
                    bestId = id;
                }
            }
            return bestId;
        }

        private void HandleSpeechStart()
        {
            _userSpeaking = true;
            _lastSpokeAtMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        }

        private void HandleSpeechEnd()
        {
            _userSpeaking = false;
            _lastSpokeAtMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        }

        private void HandleTtsStart(string text)
        {
            _lastSpokeAtMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        }

        private void HandleTtsEnd(string responseId, bool interrupted)
        {
            _lastSpokeAtMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        }

        private void Publish(JObject payload)
        {
            if (webSocketClient == null || !webSocketClient.HandshakeDone)
            {
                return;
            }
            _lastPublishedAt = Time.unscaledTime;
            var envelope = new QuestEnvelope(
                "client.world_state", payload, webSocketClient.SessionId);
            _ = webSocketClient.SendAsync(envelope);
        }

        private void ResolveUserTransforms()
        {
            if (_head == null)
            {
                _head = FindByName("CenterEyeAnchor") ?? (Camera.main != null ? Camera.main.transform : null);
            }
            if (_leftHand == null)
            {
                _leftHand = FindByName("LeftHandAnchor");
            }
            if (_rightHand == null)
            {
                _rightHand = FindByName("RightHandAnchor");
            }
        }

        private void ResolveAuxiliary()
        {
            if (microphone == null)
            {
                microphone = FindFirstObjectByType<QuestMicrophoneCapture>();
            }
            if (ttsPlayer == null)
            {
                ttsPlayer = FindFirstObjectByType<QuestTtsPlayer>();
            }
        }

        private static Transform FindByName(string objectName)
        {
            var all = UnityEngine.Object.FindObjectsByType<Transform>(
                FindObjectsInactive.Include, FindObjectsSortMode.None);
            foreach (var t in all)
            {
                if (t.name == objectName)
                {
                    return t;
                }
            }
            return null;
        }

        private static JObject AnchorToJson(MRUKAnchor anchor)
        {
            if (anchor == null)
            {
                return null;
            }
            var json = new JObject
            {
                ["id"] = anchor.gameObject.name,
                ["label"] = NormalizeLabel(anchor.Label.ToString()),
                ["pose"] = PoseToJson(anchor.transform),
                ["mesh_available"] = anchor.VolumeBounds.HasValue || anchor.PlaneRect.HasValue ||
                                    anchor.gameObject.GetComponentInChildren<MeshFilter>() != null,
                ["updated_at_ms"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()
            };
            if (anchor.ParentAnchor != null)
            {
                json["parent_id"] = anchor.ParentAnchor.gameObject.name;
            }

            var localSize = Vector3.zero;
            Bounds worldBounds;
            if (anchor.VolumeBounds.HasValue)
            {
                var local = anchor.VolumeBounds.Value;
                localSize = local.size;
                worldBounds = TransformBounds(anchor.transform, local);
            }
            else if (anchor.PlaneRect.HasValue)
            {
                var rect = anchor.PlaneRect.Value;
                localSize = new Vector3(rect.width, rect.height, 0f);
                worldBounds = TransformBounds(anchor.transform,
                    new Bounds(rect.center, new Vector3(rect.width, rect.height, 0f)));
            }
            else
            {
                worldBounds = GetRendererBounds(anchor.gameObject);
                localSize = worldBounds.size;
            }
            json["extents"] = VectorToJson(localSize);
            json["bounds"] = BoundsToJson(worldBounds);
            return json;
        }

        private static JObject RoomAnchorToJson(MRUKRoom room)
        {
            if (room == null)
            {
                return null;
            }
            var bounds = room.GetRoomBounds();
            return new JObject
            {
                ["id"] = $"room-{room.name}",
                ["label"] = "room",
                ["pose"] = PoseToJsonFromPosition(bounds.center, Quaternion.identity),
                ["extents"] = VectorToJson(bounds.size),
                ["bounds"] = BoundsToJson(bounds),
                ["mesh_available"] = true,
                ["updated_at_ms"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()
            };
        }

        private static Bounds GetRendererBounds(GameObject go)
        {
            var renderers = go.GetComponentsInChildren<Renderer>();
            if (renderers == null || renderers.Length == 0)
            {
                return new Bounds(go.transform.position, Vector3.zero);
            }
            var bounds = renderers[0].bounds;
            for (var i = 1; i < renderers.Length; i++)
            {
                bounds.Encapsulate(renderers[i].bounds);
            }
            return bounds;
        }

        private static Bounds TransformBounds(Transform t, Bounds local)
        {
            var center = t.TransformPoint(local.center);
            var ext = local.extents;
            var axisX = t.TransformVector(new Vector3(ext.x, 0f, 0f));
            var axisY = t.TransformVector(new Vector3(0f, ext.y, 0f));
            var axisZ = t.TransformVector(new Vector3(0f, 0f, ext.z));
            var worldExtents = new Vector3(
                Mathf.Abs(axisX.x) + Mathf.Abs(axisY.x) + Mathf.Abs(axisZ.x),
                Mathf.Abs(axisX.y) + Mathf.Abs(axisY.y) + Mathf.Abs(axisZ.y),
                Mathf.Abs(axisX.z) + Mathf.Abs(axisY.z) + Mathf.Abs(axisZ.z));
            return new Bounds(center, worldExtents * 2f);
        }

        private static JObject PoseToJson(Transform transform)
        {
            if (transform == null)
            {
                return null;
            }
            return PoseToJsonFromPosition(transform.position, transform.rotation);
        }

        private static JObject PoseToJsonFromPosition(Vector3 position, Quaternion rotation)
        {
            return new JObject
            {
                ["position"] = VectorToJson(position),
                ["rotation"] = new JObject
                {
                    ["x"] = rotation.x,
                    ["y"] = rotation.y,
                    ["z"] = rotation.z,
                    ["w"] = rotation.w
                }
            };
        }

        private static JObject VectorToJson(Vector3 v)
        {
            return new JObject { ["x"] = v.x, ["y"] = v.y, ["z"] = v.z };
        }

        private static Vector3 ReadVector(JObject value)
        {
            if (value == null)
            {
                return Vector3.zero;
            }
            return new Vector3(
                value.Value<float?>("x") ?? 0f,
                value.Value<float?>("y") ?? 0f,
                value.Value<float?>("z") ?? 0f);
        }

        private static JObject DirectionToJson(Vector3 v)
        {
            if (v.sqrMagnitude > 0.0001f)
            {
                v.Normalize();
            }
            return VectorToJson(v);
        }

        private static JObject BoundsToJson(Bounds bounds)
        {
            return new JObject
            {
                ["min"] = VectorToJson(bounds.min),
                ["max"] = VectorToJson(bounds.max)
            };
        }

        private static string NormalizeLabel(string raw)
        {
            var value = (raw ?? "").Trim().ToUpperInvariant();
            return value switch
            {
                "ROOM" => "room",
                "FLOOR" or "FLOOR_FACE" => "floor",
                "WALL" or "WALL_FACE" or "WALL_ART" => "wall",
                "CEILING" => "ceiling",
                "TABLE" => "table",
                "COUCH" => "sofa",
                "CHAIR" => "chair",
                "DOOR_FRAME" or "DOOR" => "door",
                "WINDOW_FRAME" or "WINDOW" => "window",
                "STORAGE" => "storage",
                "PLANT" => "plant",
                "SCREEN" => "screen",
                _ => "unknown"
            };
        }
    }
}
