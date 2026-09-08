using System;
using Meta.XR.MRUtilityKit;
using Newtonsoft.Json.Linq;
using Qiyu.Quest.Networking;
using UnityEngine;

namespace Qiyu.Quest.Perception
{
    /// <summary>
    /// P1：把 MRUK 房间语义转换为冻结的 WorldState v1 JSON 并上报。
    /// 只发送语义 anchor 的位姿与标签，Scene Mesh/几何仍保留在 Quest 本地；
    /// 杯子/手机等 Scene API 未建模物体由 P4 ObjectDetector 补充。
    /// </summary>
    public class MrukWorldStatePublisher : MonoBehaviour
    {
        [SerializeField] private QiyuQuestWebSocketClient webSocketClient;
        [SerializeField] private MrukSceneSummary sceneSummary;
        [SerializeField] private float publishIntervalSeconds = 5f;

        private int _sceneVersion;
        private float _lastPublishedAt;
        private JObject _latestPayload;

        private void OnEnable()
        {
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
            if (_latestPayload != null && Time.unscaledTime - _lastPublishedAt >= publishIntervalSeconds)
            {
                Publish(_latestPayload);
            }
        }

        private void HandleRoomChanged(string summary, MRUKRoom room)
        {
            _latestPayload = BuildPayload(room);
            if (webSocketClient != null && webSocketClient.HandshakeDone)
            {
                Publish(_latestPayload);
            }
        }

        private void HandleSessionEstablished()
        {
            if (_latestPayload != null)
            {
                Publish(_latestPayload);
            }
        }

        private JObject BuildPayload(MRUKRoom room)
        {
            _sceneVersion++;
            var anchors = new JArray();
            if (room != null)
            {
                foreach (var anchor in room.Anchors)
                {
                    anchors.Add(AnchorToJson(anchor));
                }
            }

            return new JObject
            {
                ["protocol_version"] = "1.0.0",
                ["ts"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                ["room_id"] = room != null ? room.name : "",
                ["scene_version"] = _sceneVersion,
                ["status"] = room != null ? "ready" : "scanning",
                ["anchors"] = anchors,
                ["objects"] = new JArray(),
                ["user"] = new JObject
                {
                    ["head"] = PoseToJson(Camera.main != null ? Camera.main.transform : null),
                    ["source"] = "headset"
                },
                ["avatar"] = new JObject
                {
                    ["id"] = "qiyu_avatar",
                    ["pose"] = new JObject(),
                    ["visible"] = false,
                    ["state"] = "hidden"
                },
                ["navmesh"] = new JObject
                {
                    ["generated"] = false,
                    ["version"] = 0,
                    ["walkable_area_m2"] = 0f
                }
            };
        }

        private void Publish(JObject payload)
        {
            if (webSocketClient == null || !webSocketClient.HandshakeDone)
            {
                return;
            }
            _lastPublishedAt = Time.unscaledTime;
            var envelope = new QuestEnvelope("client.world_state", payload, webSocketClient.SessionId);
            _ = webSocketClient.SendAsync(envelope);
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
                ["mesh_available"] = anchor.gameObject.GetComponentInChildren<MeshFilter>() != null,
                ["updated_at_ms"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()
            };
            var bounds = GetLocalBounds(anchor);
            if (bounds != null)
            {
                json["extents"] = bounds;
            }
            return json;
        }

        private static JObject PoseToJson(Transform transform)
        {
            if (transform == null)
            {
                return null;
            }
            var p = transform.position;
            var r = transform.rotation;
            return new JObject
            {
                ["position"] = new JObject { ["x"] = p.x, ["y"] = p.y, ["z"] = p.z },
                ["rotation"] = new JObject { ["x"] = r.x, ["y"] = r.y, ["z"] = r.z, ["w"] = r.w }
            };
        }

        private static JObject GetLocalBounds(MRUKAnchor anchor)
        {
            var renderers = anchor.GetComponentsInChildren<Renderer>();
            if (renderers == null || renderers.Length == 0)
            {
                return null;
            }
            var bounds = renderers[0].bounds;
            foreach (var renderer in renderers)
            {
                bounds.Encapsulate(renderer.bounds);
            }
            var min = bounds.min;
            var max = bounds.max;
            var ext = bounds.size;
            return new JObject
            {
                ["min"] = new JObject { ["x"] = min.x, ["y"] = min.y, ["z"] = min.z },
                ["max"] = new JObject { ["x"] = max.x, ["y"] = max.y, ["z"] = max.z },
                ["size"] = new JObject { ["x"] = ext.x, ["y"] = ext.y, ["z"] = ext.z }
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
