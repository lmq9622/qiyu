using System;
using System.Collections.Generic;
using Meta.XR.MRUtilityKit;
using Newtonsoft.Json.Linq;
using Qiyu.Quest.Networking;
using Qiyu.Quest.Spatial;
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

        private int _sceneVersion;
        private float _lastPublishedAt;
        private JObject _latestPayload;
        private string _latestSignature = "";
        private MRUKRoom _room;
        private Transform _head;
        private Transform _leftHand;
        private Transform _rightHand;
        private JArray _detectedObjects = new JArray();

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

        private void OnEnable()
        {
            ResolveUserTransforms();
            if (sceneSummary != null)
            {
                sceneSummary.OnSummaryChanged += HandleRoomChanged;
            }
            if (webSocketClient != null)
            {
                webSocketClient.SessionEstablished += HandleSessionEstablished;
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
                ["ts"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                ["room_id"] = room != null ? room.name : "",
                ["scene_version"] = _sceneVersion,
                ["status"] = room != null && room.Anchors.Count > 0 ? "ready" : "scanning",
                ["anchors"] = anchors,
                ["objects"] = _detectedObjects.DeepClone(),
                ["user"] = BuildUserPose(),
                ["avatar"] = BuildAvatarPose(),
                ["navmesh"] = BuildNavmeshInfo(room)
            };
            return payload;
        }

        private JObject BuildUserPose()
        {
            ResolveUserTransforms();
            var user = new JObject
            {
                ["head"] = PoseToJson(_head),
                ["gaze_direction"] = DirectionToJson(_head != null ? _head.forward : Vector3.zero),
                ["source"] = "headset"
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
                ["pose"] = PoseToJson(avatarRoot),
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
