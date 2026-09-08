using System;
using System.Collections.Generic;
using Meta.XR;
using Newtonsoft.Json.Linq;
using Qiyu.Quest.Networking;
using UnityEngine;

namespace Qiyu.Quest.Perception
{
    /// <summary>
    /// P4：Meta 官方 Passthrough Camera Access 取帧 → JPEG → 二进制上行。
    /// 不自造相机后端；帧率/分辨率可配，默认 2Hz、最长边 640，控制带宽与推理成本。
    /// </summary>
    public class PassthroughFrameSource : MonoBehaviour
    {
        [SerializeField] private QiyuQuestWebSocketClient webSocketClient;
        [SerializeField] private PassthroughCameraAccess cameraAccess;
        [SerializeField] private bool autoCapture = false;
        [SerializeField] private float captureIntervalSeconds = 0.5f;
        [SerializeField] private int maxDimension = 640;
        [SerializeField, Range(30, 95)] private int jpegQuality = 80;

        private float _lastCaptureAt;
        private uint _sequence;
        private RenderTexture _renderTexture;
        private Texture2D _readback;
        private bool _busy;

        public bool IsReady => cameraAccess != null && cameraAccess.IsPlaying;
        public event Action<byte[]> OnJpegCaptured;

        private void OnEnable()
        {
            if (webSocketClient != null)
            {
                webSocketClient.OnMessage += HandleEnvelope;
            }
        }

        private void OnDisable()
        {
            if (webSocketClient != null)
            {
                webSocketClient.OnMessage -= HandleEnvelope;
            }
        }

        private void HandleEnvelope(QuestEnvelope envelope)
        {
            if (envelope.type != "server.vision_request")
            {
                return;
            }
            var prompt = envelope.payload.Value<string>("prompt") ?? "";
            Debug.Log($"[QuestVision] 后端请求抓帧: {prompt}");
            CaptureAndSend(prompt);
        }

        private void Update()
        {
            if (!autoCapture || _busy || webSocketClient == null ||
                !webSocketClient.HandshakeDone || !IsReady)
            {
                return;
            }
            if (Time.unscaledTime - _lastCaptureAt < captureIntervalSeconds)
            {
                return;
            }
            _lastCaptureAt = Time.unscaledTime;
            CaptureAndSend("");
        }

        /// <summary>取一帧并发送；prompt 非空时同时触发后端物体识别。</summary>
        public void CaptureAndSend(string prompt)
        {
            if (_busy || !IsReady || webSocketClient == null || !webSocketClient.HandshakeDone)
            {
                return;
            }
            _busy = true;
            try
            {
                var jpeg = CaptureJpeg(out var width, out var height);
                if (jpeg == null || jpeg.Length == 0)
                {
                    return;
                }
                var pose = cameraAccess.GetCameraPose();
                var intrinsics = cameraAccess.Intrinsics;
                var meta = new JObject
                {
                    ["frame_id"] = $"vf-{_sequence}",
                    ["width"] = width,
                    ["height"] = height,
                    ["timestamp_ms"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                    ["camera_position"] = VectorToJson(pose.position),
                    ["camera_rotation"] = QuaternionToJson(pose.rotation),
                    ["focal_length"] = VectorToJson(intrinsics.FocalLength),
                    ["principal_point"] = VectorToJson(intrinsics.PrincipalPoint),
                    ["sensor_resolution"] = new JObject
                    {
                        ["x"] = intrinsics.SensorResolution.x,
                        ["y"] = intrinsics.SensorResolution.y
                    }
                };
                _ = SendFrameAsync(meta, jpeg, prompt);
                OnJpegCaptured?.Invoke(jpeg);
            }
            finally
            {
                _busy = false;
            }
        }

        private async System.Threading.Tasks.Task SendFrameAsync(
            JObject meta, byte[] jpeg, string prompt)
        {
            await webSocketClient.SendAsync(new QuestEnvelope(
                "client.vision_frame_meta", meta, webSocketClient.SessionId));
            var frame = QuestBinaryProtocol.Pack(
                QuestBinaryProtocol.KindVisionJpeg, _sequence++, jpeg);
            await webSocketClient.SendBinaryAsync(frame);
            if (!string.IsNullOrEmpty(prompt))
            {
                var query = new JObject { ["prompt"] = prompt };
                await webSocketClient.SendAsync(new QuestEnvelope(
                    "client.vision_query", query, webSocketClient.SessionId));
            }
        }

        private byte[] CaptureJpeg(out int width, out int height)
        {
            width = 0;
            height = 0;
            var source = cameraAccess.GetTexture();
            if (source == null)
            {
                return null;
            }
            var sourceWidth = source.width;
            var sourceHeight = source.height;
            var scale = maxDimension > 0
                ? Mathf.Min(1f, maxDimension / (float)Mathf.Max(sourceWidth, sourceHeight))
                : 1f;
            width = Mathf.Max(2, Mathf.RoundToInt(sourceWidth * scale));
            height = Mathf.Max(2, Mathf.RoundToInt(sourceHeight * scale));
            EnsureBuffers(width, height);
            Graphics.Blit(source, _renderTexture);
            var previous = RenderTexture.active;
            RenderTexture.active = _renderTexture;
            _readback.ReadPixels(new Rect(0, 0, width, height), 0, 0);
            _readback.Apply(false);
            RenderTexture.active = previous;
            return _readback.EncodeToJPG(jpegQuality);
        }

        private void EnsureBuffers(int width, int height)
        {
            if (_renderTexture == null || _renderTexture.width != width ||
                _renderTexture.height != height)
            {
                if (_renderTexture != null)
                {
                    Destroy(_renderTexture);
                }
                _renderTexture = new RenderTexture(width, height, 0, RenderTextureFormat.ARGB32);
                _renderTexture.Create();
            }
            if (_readback == null || _readback.width != width || _readback.height != height)
            {
                if (_readback != null)
                {
                    Destroy(_readback);
                }
                _readback = new Texture2D(width, height, TextureFormat.RGB24, false);
            }
        }

        private static JObject VectorToJson(Vector3 v)
        {
            return new JObject { ["x"] = v.x, ["y"] = v.y, ["z"] = v.z };
        }

        private static JObject VectorToJson(Vector2 v)
        {
            return new JObject { ["x"] = v.x, ["y"] = v.y };
        }

        private static JObject QuaternionToJson(Quaternion q)
        {
            return new JObject { ["x"] = q.x, ["y"] = q.y, ["z"] = q.z, ["w"] = q.w };
        }

        private void OnDestroy()
        {
            if (_renderTexture != null)
            {
                Destroy(_renderTexture);
            }
            if (_readback != null)
            {
                Destroy(_readback);
            }
        }
    }
}
