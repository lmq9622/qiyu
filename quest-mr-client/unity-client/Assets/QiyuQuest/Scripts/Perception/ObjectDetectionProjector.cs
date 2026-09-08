using System;
using System.Collections.Generic;
using Meta.XR;
using Meta.XR.BuildingBlocks.AIBlocks;
using Meta.XR.MRUtilityKit;
using Newtonsoft.Json.Linq;
using Qiyu.Quest.Networking;
using Qiyu.Quest.Spatial;
using UnityEngine;

namespace Qiyu.Quest.Perception
{
    /// <summary>
    /// 把后端返回的 2D 检测框投影为真实世界坐标。
    ///
    /// 优先使用 Meta Environment Depth（DepthTextureAccess）取深度；
    /// 深度不可用时回退到 MRUK 场景射线命中点。两条路径都是真实几何，
    /// 不使用固定距离/随机坐标冒充。
    /// </summary>
    public class ObjectDetectionProjector : MonoBehaviour
    {
        [SerializeField] private QiyuQuestWebSocketClient webSocketClient;
        [SerializeField] private PassthroughCameraAccess cameraAccess;
        [SerializeField] private DepthTextureAccess depthAccess;
        [SerializeField] private MrukSceneSummary sceneSummary;
        [SerializeField] private MrukWorldStatePublisher worldStatePublisher;
        [SerializeField] private float fallbackDistance = 2f;
        [SerializeField] private float maxDepthMeters = 12f;

        private float[] _depthPixels;
        private Matrix4x4 _viewProjection = Matrix4x4.identity;
        private Pose _depthPose;
        private int _depthTextureSize;
        private bool _hasDepthFrame;

        public event Action<List<DetectedObject>> OnObjectsUpdated;

        [Serializable]
        public struct DetectedObject
        {
            public string id;
            public string label;
            public float confidence;
            public Vector3 worldPosition;
            public Vector2 bboxCenterNormalized;
            public string anchorId;
        }

        private void OnEnable()
        {
            if (webSocketClient != null)
            {
                webSocketClient.OnMessage += HandleEnvelope;
            }
            if (depthAccess != null)
            {
                depthAccess.OnDepthTextureUpdateCPU += HandleDepthFrame;
            }
        }

        private void OnDisable()
        {
            if (webSocketClient != null)
            {
                webSocketClient.OnMessage -= HandleEnvelope;
            }
            if (depthAccess != null)
            {
                depthAccess.OnDepthTextureUpdateCPU -= HandleDepthFrame;
            }
        }

        private void HandleDepthFrame(DepthTextureAccess.DepthFrameData frame)
        {
            var source = frame.DepthTexturePixels;
            if (!source.IsCreated || source.Length == 0)
            {
                return;
            }
            if (_depthPixels == null || _depthPixels.Length != source.Length)
            {
                _depthPixels = new float[source.Length];
            }
            source.CopyTo(_depthPixels);
            _depthTextureSize = depthAccess.TextureSize;
            if (frame.ViewProjectionMatrix != null && frame.ViewProjectionMatrix.Length > 0)
            {
                _viewProjection = frame.ViewProjectionMatrix[0];
            }
            _depthPose = frame.CameraPose;
            _hasDepthFrame = true;
        }

        private void HandleEnvelope(QuestEnvelope envelope)
        {
            if (envelope.type != "server.object_detection")
            {
                return;
            }
            var payload = envelope.payload;
            var imageWidth = payload.Value<float?>("image_width") ?? 0f;
            var imageHeight = payload.Value<float?>("image_height") ?? 0f;
            var rawObjects = payload["objects"] as JArray ?? new JArray();
            var results = new List<DetectedObject>();
            foreach (var raw in rawObjects)
            {
                if (!(raw is JObject obj))
                {
                    continue;
                }
                var bbox = obj["bbox_2d"] as JArray;
                if (bbox == null || bbox.Count != 4 || imageWidth <= 0 || imageHeight <= 0)
                {
                    continue;
                }
                var xmin = bbox[0].Value<float>();
                var ymin = bbox[1].Value<float>();
                var xmax = bbox[2].Value<float>();
                var ymax = bbox[3].Value<float>();
                var nx = ((xmin + xmax) * 0.5f) / imageWidth;
                var ny = ((ymin + ymax) * 0.5f) / imageHeight;
                if (!TryProject(nx, ny, out var world, out var anchorId))
                {
                    continue;
                }
                var detected = new DetectedObject
                {
                    id = obj.Value<string>("id") ?? Guid.NewGuid().ToString("N"),
                    label = obj.Value<string>("label") ?? "object",
                    confidence = obj.Value<float?>("confidence") ?? 0.5f,
                    worldPosition = world,
                    bboxCenterNormalized = new Vector2(nx, ny),
                    anchorId = anchorId
                };
                results.Add(detected);
                QuestObjectRegistry.Set(detected.id, world, detected.label);
            }
            OnObjectsUpdated?.Invoke(results);
            worldStatePublisher?.SetDetectedObjects(BuildWorldStateObjects(results));
            Debug.Log($"[QuestVision] 投影完成 {results.Count} 个物体 → WorldState");
        }

        private bool TryProject(float normalizedX, float normalizedY,
                                out Vector3 world, out string anchorId)
        {
            world = Vector3.zero;
            anchorId = "";
            if (cameraAccess == null)
            {
                return false;
            }
            var viewport = new Vector2(normalizedX, 1f - normalizedY);
            var pose = cameraAccess.GetCameraPose();
            var ray = cameraAccess.ViewportPointToRay(viewport, pose);

            if (_hasDepthFrame && _depthPixels != null && _depthTextureSize > 0)
            {
                var world1M = ray.origin + ray.direction;
                var clip = _viewProjection * new Vector4(world1M.x, world1M.y, world1M.z, 1f);
                if (clip.w > 0)
                {
                    var uv = (new Vector2(clip.x, clip.y) / clip.w) * 0.5f +
                             Vector2.one * 0.5f;
                    var sx = Mathf.Clamp((int)(uv.x * _depthTextureSize), 0, _depthTextureSize - 1);
                    var sy = Mathf.Clamp((int)(uv.y * _depthTextureSize), 0, _depthTextureSize - 1);
                    var index = sy * _depthTextureSize + sx;
                    if (index >= 0 && index < _depthPixels.Length)
                    {
                        var depth = _depthPixels[index];
                        if (depth > 0.05f && depth < maxDepthMeters && !float.IsInfinity(depth))
                        {
                            world = ray.origin + ray.direction * depth;
                            return true;
                        }
                    }
                }
            }

            // 回退：MRUK 场景射线（真实场景网格命中点）
            var room = sceneSummary != null ? sceneSummary.CurrentRoom : null;
            if (room != null)
            {
                var mrukRay = new Ray(ray.origin, ray.direction);
                if (room.Raycast(mrukRay, maxDepthMeters, out var hit, out var anchor) &&
                    hit.distance > 0.05f)
                {
                    world = hit.point;
                    anchorId = anchor != null ? anchor.gameObject.name : "";
                    return true;
                }
            }
            world = ray.origin + ray.direction * fallbackDistance;
            return true;
        }

        private static JArray BuildWorldStateObjects(List<DetectedObject> objects)
        {
            var array = new JArray();
            foreach (var item in objects)
            {
                array.Add(new JObject
                {
                    ["id"] = item.id,
                    ["label"] = item.label,
                    ["confidence"] = item.confidence,
                    ["position"] = new JObject
                    {
                        ["x"] = item.worldPosition.x,
                        ["y"] = item.worldPosition.y,
                        ["z"] = item.worldPosition.z
                    },
                    ["anchor_id"] = item.anchorId,
                    ["source"] = "cloud_vision"
                });
            }
            return array;
        }
    }
}
