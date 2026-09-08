using System.Text;
using Newtonsoft.Json.Linq;
using Qiyu.Quest.Networking;
using Qiyu.Quest.Perception;
using Qiyu.Quest.Voice;
using UnityEngine;
using UnityEngine.UI;

namespace Qiyu.Quest.UI
{
    /// <summary>
    /// VR 世界空间调试面板（不用 IMGUI；URP+XR 下 OnGUI 不可靠）。
    ///
    /// 面板跟随头部，显示连接/MRUK/STT/回复/错误；
    /// 操作走手柄按键（不依赖射线 UI）：
    ///   A  = 发送“你好，你在吗？”
    ///   B  = 发送“你能看到桌子上有什么吗？”
    ///   X  = 抓帧识别
    ///   Y  = 打断 TTS
    ///   左摇杆按下 = 重连
    ///   右摇杆按下 = TTS 开关
    /// </summary>
    public class QuestWorldSpaceUI : MonoBehaviour
    {
        [Header("依赖")]
        [SerializeField] private QiyuQuestWebSocketClient webSocketClient;
        [SerializeField] private QuestMicrophoneCapture microphone;
        [SerializeField] private QuestTtsPlayer ttsPlayer;
        [SerializeField] private PassthroughFrameSource frameSource;
        [SerializeField] private MrukSceneSummary sceneSummary;

        [Header("面板")]
        [SerializeField] private Transform followTarget;
        [SerializeField] private float distance = 1.7f;
        [SerializeField] private Vector3 localOffset = new Vector3(0f, -0.12f, 0f);
        [SerializeField] private float panelScale = 0.0011f;
        [SerializeField] private bool followUser = true;

        private Text _statusText;
        private Text _mrukText;
        private Text _dialogText;
        private Text _hintText;
        private string _lastEvent = "";
        private string _lastSpeech = "";
        private string _lastTranscript = "";
        private string _lastError = "";
        private bool _ttsEnabled = true;
        private Transform _canvasTransform;
        private readonly StringBuilder _builder = new StringBuilder();

        private void Start()
        {
            if (followTarget == null)
            {
                var centerEye = GameObject.Find("CenterEyeAnchor");
                if (centerEye != null)
                {
                    followTarget = centerEye.transform;
                }
            }
            BuildPanel();
            Debug.Log($"[QuestUI] 世界空间面板已创建 followTarget={(followTarget != null ? followTarget.name : "null")}");
            if (webSocketClient != null)
            {
                webSocketClient.OnMessage += HandleMessage;
                webSocketClient.OnAgentSpeech += HandleSpeech;
            }
        }

        private void OnDestroy()
        {
            if (webSocketClient != null)
            {
                webSocketClient.OnMessage -= HandleMessage;
                webSocketClient.OnAgentSpeech -= HandleSpeech;
            }
            if (_canvasTransform != null)
            {
                Destroy(_canvasTransform.gameObject);
            }
        }

        private void HandleMessage(QuestEnvelope envelope)
        {
            _lastEvent = $"{envelope.type} @ {System.DateTime.Now:HH:mm:ss}";
            if (envelope.type == "server.voice_transcript")
            {
                _lastTranscript = envelope.payload.Value<string>("text") ?? "";
            }
            else if (envelope.type == "server.error")
            {
                _lastError = $"{envelope.payload.Value<string>("code")}: " +
                             $"{envelope.payload.Value<string>("message")}";
            }
        }

        private void HandleSpeech(JObject payload)
        {
            _lastSpeech = payload.Value<string>("text") ?? "";
        }

        private void Update()
        {
            UpdateStatus();
            HandleButtons();
        }

        private void LateUpdate()
        {
            if (!followUser || followTarget == null || _canvasTransform == null)
            {
                return;
            }
            var forward = followTarget.forward;
            forward.y = 0f;
            if (forward.sqrMagnitude < 0.001f)
            {
                forward = Vector3.forward;
            }
            forward.Normalize();
            var position = followTarget.position + forward * distance +
                           followTarget.right * localOffset.x +
                           Vector3.up * localOffset.y;
            _canvasTransform.position = position;
            // Canvas 正面是 +Z；要面向用户，+Z 必须指向用户（即 -forward）。
            _canvasTransform.rotation = Quaternion.LookRotation(-forward, Vector3.up);
        }

        private void HandleButtons()
        {
            if (webSocketClient == null)
            {
                return;
            }
            if (OVRInput.GetDown(OVRInput.Button.One))
            {
                _ = webSocketClient.SendUserTextAsync("你好，你在吗？");
            }
            else if (OVRInput.GetDown(OVRInput.Button.Two))
            {
                _ = webSocketClient.SendUserTextAsync("你能看到桌子上有什么吗？");
            }
            else if (OVRInput.GetDown(OVRInput.Button.Three))
            {
                frameSource?.CaptureAndSend("桌子上有什么");
            }
            else if (OVRInput.GetDown(OVRInput.Button.Four))
            {
                ttsPlayer?.StopPlayback(true);
                _ = webSocketClient.SendBargeInAsync("debug_button");
            }
            else if (OVRInput.GetDown(OVRInput.Button.PrimaryThumbstick))
            {
                _ = webSocketClient.ConnectAsync();
            }
            else if (OVRInput.GetDown(OVRInput.Button.SecondaryThumbstick))
            {
                _ttsEnabled = !_ttsEnabled;
                var payload = new JObject { ["enabled"] = _ttsEnabled };
                _ = webSocketClient.SendAsync(new QuestEnvelope(
                    "client.tts_config", payload, webSocketClient.SessionId));
            }
        }

        private void UpdateStatus()
        {
            if (_statusText == null)
            {
                return;
            }
            var connected = webSocketClient != null && webSocketClient.IsConnected;
            var handshake = webSocketClient != null && webSocketClient.HandshakeDone;
            _builder.Clear();
            _builder.AppendLine($"Qiyu Quest  |  连接:{(connected ? "是" : "否")}  握手:{(handshake ? "是" : "否")}");
            _builder.AppendLine($"session: {(webSocketClient != null ? Short(webSocketClient.SessionId) : "")}");
            _builder.AppendLine($"Gateway: {(webSocketClient != null ? webSocketClient.ServerUrl : "")}");
            _builder.AppendLine($"麦克风: {(microphone != null && microphone.IsCapturing ? "采集中" : "关")}" +
                                $"  说话: {(microphone != null && microphone.IsSpeaking ? "是" : "否")}" +
                                $"  RMS: {(microphone != null ? microphone.LastRms : 0f):F3}");
            _builder.AppendLine($"TTS: {(ttsPlayer != null && ttsPlayer.IsPlaying ? "播放中" : "空闲")}" +
                                $"  开关: {(_ttsEnabled ? "开" : "关")}" +
                                $"  口型: {(ttsPlayer != null ? ttsPlayer.MouthAmplitude : 0f):F2}");
            _builder.Append($"最近事件: {_lastEvent}");
            _statusText.text = _builder.ToString();

            if (_mrukText != null)
            {
                _mrukText.text = sceneSummary != null
                    ? sceneSummary.Summary
                    : "MRUK: 未挂接";
            }
            if (_dialogText != null)
            {
                var dialog = new StringBuilder();
                if (!string.IsNullOrEmpty(_lastTranscript))
                {
                    dialog.AppendLine($"STT: {_lastTranscript}");
                }
                if (!string.IsNullOrEmpty(_lastSpeech))
                {
                    dialog.AppendLine($"回复: {_lastSpeech}");
                }
                if (!string.IsNullOrEmpty(_lastError))
                {
                    dialog.AppendLine($"错误: {_lastError}");
                }
                _dialogText.text = dialog.ToString();
            }
        }

        private static string Short(string value)
        {
            if (string.IsNullOrEmpty(value))
            {
                return "";
            }
            return value.Length > 12 ? value.Substring(0, 12) + "..." : value;
        }

        private void BuildPanel()
        {
            var canvasObject = new GameObject("QiyuDebugCanvas");
            canvasObject.transform.SetParent(null, false);
            _canvasTransform = canvasObject.transform;
            var canvas = canvasObject.AddComponent<Canvas>();
            canvas.renderMode = RenderMode.WorldSpace;
            canvas.sortingOrder = 100;
            var rect = canvasObject.GetComponent<RectTransform>();
            rect.sizeDelta = new Vector2(1000f, 760f);
            canvasObject.transform.localScale = Vector3.one * panelScale;

            var background = canvasObject.AddComponent<Image>();
            background.color = new Color(0.02f, 0.02f, 0.05f, 0.88f);

            var font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            if (font == null)
            {
                font = Resources.GetBuiltinResource<Font>("Arial.ttf");
            }
            if (font == null)
            {
                Debug.LogWarning("[QuestUI] 内置字体不可用，尝试系统字体");
                font = Font.CreateDynamicFontFromOSFont("Arial", 24);
            }
            if (font == null)
            {
                Debug.LogError("[QuestUI] 找不到任何可用字体，面板文字无法显示");
            }

            _statusText = CreateText(canvasObject.transform, font, 26,
                new Vector2(0f, 1f), new Vector2(1f, 1f),
                new Vector2(0f, 0f), new Vector2(-24f, -330f), TextAnchor.UpperLeft);
            _mrukText = CreateText(canvasObject.transform, font, 22,
                new Vector2(0f, 0f), new Vector2(1f, 0f),
                new Vector2(0f, 250f), new Vector2(-24f, -250f), TextAnchor.UpperLeft);
            _dialogText = CreateText(canvasObject.transform, font, 22,
                new Vector2(0f, 0f), new Vector2(1f, 0f),
                new Vector2(0f, 0f), new Vector2(-24f, -250f), TextAnchor.LowerLeft);
            _hintText = CreateText(canvasObject.transform, font, 20,
                new Vector2(0f, 1f), new Vector2(1f, 1f),
                new Vector2(0f, -430f), new Vector2(-24f, -300f), TextAnchor.UpperLeft);
            _hintText.color = new Color(0.7f, 0.85f, 1f, 1f);
            _hintText.text =
                "手柄操作：\n" +
                "A = 你好，你在吗？\n" +
                "B = 你能看到桌子上有什么吗？\n" +
                "X = 抓帧识别\n" +
                "Y = 打断 TTS\n" +
                "左摇杆按下 = 重连   右摇杆按下 = TTS 开关";
        }

        private static Text CreateText(Transform parent, Font font, int size,
            Vector2 anchorMin, Vector2 anchorMax, Vector2 offsetMin, Vector2 offsetMax,
            TextAnchor alignment)
        {
            var textObject = new GameObject("Text", typeof(RectTransform), typeof(Text));
            textObject.transform.SetParent(parent, false);
            var rect = textObject.GetComponent<RectTransform>();
            rect.anchorMin = anchorMin;
            rect.anchorMax = anchorMax;
            rect.offsetMin = offsetMin;
            rect.offsetMax = offsetMax;
            var text = textObject.GetComponent<Text>();
            text.font = font;
            text.fontSize = size;
            text.color = Color.white;
            text.alignment = alignment;
            text.horizontalOverflow = HorizontalWrapMode.Wrap;
            text.verticalOverflow = VerticalWrapMode.Overflow;
            return text;
        }
    }
}
