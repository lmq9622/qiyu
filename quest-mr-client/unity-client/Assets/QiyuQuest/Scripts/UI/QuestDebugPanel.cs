using Newtonsoft.Json.Linq;
using Qiyu.Quest.Networking;
using Qiyu.Quest.Perception;
using Qiyu.Quest.Voice;
using UnityEngine;

namespace Qiyu.Quest.UI
{
    /// <summary>
    /// 真机联调面板：连接状态、预置测试句、抓帧识别、打断、TTS 开关。
    /// 目的：Quest 上不方便打字时也能完成端到端验收。
    /// 按手柄 A/X 或键盘 Tab 显示/隐藏。
    /// </summary>
    public class QuestDebugPanel : MonoBehaviour
    {
        [SerializeField] private QiyuQuestWebSocketClient webSocketClient;
        [SerializeField] private QuestMicrophoneCapture microphone;
        [SerializeField] private QuestTtsPlayer ttsPlayer;
        [SerializeField] private PassthroughFrameSource frameSource;
        [SerializeField] private MrukSceneSummary sceneSummary;
        [SerializeField] private bool visible = true;
        [SerializeField] private float panelScale = 1.4f;

        private string _serverUrlInput = "";
        private string _lastEvent = "";
        private string _lastSpeech = "";
        private string _lastTranscript = "";
        private string _lastError = "";
        private Vector2 _scroll;

        private static readonly string[] QuickPhrases =
        {
            "你好，你在吗？",
            "你能看到桌子上有什么吗？",
            "你看看我手里有什么？",
            "往后退一点。",
            "走到桌子旁边。",
        };

        private void Start()
        {
            if (webSocketClient != null)
            {
                _serverUrlInput = webSocketClient.ServerUrl;
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
        }

        private void Update()
        {
            // 只用手柄 A/X 切换；不要用 UnityEngine.Input，
            // 本项目启用 Input System package，读旧 Input 会每帧抛异常。
            if (OVRInput.GetDown(OVRInput.Button.One))
            {
                visible = !visible;
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

        private void OnGUI()
        {
            if (!visible)
            {
                return;
            }
            var previousScale = GUI.matrix;
            GUI.matrix = Matrix4x4.TRS(Vector3.zero,
                Quaternion.identity, new Vector3(panelScale, panelScale, 1f));
            var width = Screen.width / panelScale - 24f;
            var height = Screen.height / panelScale - 24f;
            GUILayout.BeginArea(new Rect(12f, 12f, width, height), GUI.skin.box);
            _scroll = GUILayout.BeginScrollView(_scroll);

            var header = new GUIStyle(GUI.skin.label) { fontSize = 18, fontStyle = FontStyle.Bold };
            GUILayout.Label("Qiyu Quest 调试面板（A/X 或 Tab 隐藏）", header);
            var connected = webSocketClient != null && webSocketClient.IsConnected;
            var handshake = webSocketClient != null && webSocketClient.HandshakeDone;
            GUILayout.Label($"连接：{(connected ? "已连接" : "未连接")}   " +
                            $"握手：{(handshake ? "完成" : "未完成")}");
            GUILayout.Label($"session：{(webSocketClient != null ? webSocketClient.SessionId : "")}");
            GUILayout.Label($"麦克风：{(microphone != null && microphone.IsCapturing ? "采集中" : "未采集")}   " +
                            $"说话：{(microphone != null && microphone.IsSpeaking ? "是" : "否")}   " +
                            $"RMS：{(microphone != null ? microphone.LastRms : 0f):F3}");
            GUILayout.Label($"TTS 播放：{(ttsPlayer != null && ttsPlayer.IsPlaying ? "是" : "否")}   " +
                            $"口型：{(ttsPlayer != null ? ttsPlayer.MouthAmplitude : 0f):F2}");
            GUILayout.Label($"最近事件：{_lastEvent}");
            if (!string.IsNullOrEmpty(_lastTranscript))
            {
                GUILayout.Label($"STT：{_lastTranscript}");
            }
            if (!string.IsNullOrEmpty(_lastSpeech))
            {
                GUILayout.Label($"回复：{_lastSpeech}");
            }
            if (!string.IsNullOrEmpty(_lastError))
            {
                GUILayout.Label($"错误：{_lastError}");
            }
            GUILayout.Space(6f);
            GUILayout.Label("Gateway 地址");
            GUILayout.BeginHorizontal();
            _serverUrlInput = GUILayout.TextField(_serverUrlInput ?? "", GUILayout.MinWidth(360f));
            if (GUILayout.Button("应用并重连", GUILayout.Width(120f)) && webSocketClient != null)
            {
                webSocketClient.SetServerUrl(_serverUrlInput);
            }
            GUILayout.EndHorizontal();
            if (GUILayout.Button("立即重连", GUILayout.Height(34f)) && webSocketClient != null)
            {
                _ = webSocketClient.ConnectAsync();
            }

            GUILayout.Space(6f);
            GUILayout.Label("文本测试（走同一条大脑链路）");
            foreach (var phrase in QuickPhrases)
            {
                if (GUILayout.Button(phrase, GUILayout.Height(32f)) && webSocketClient != null)
                {
                    _ = webSocketClient.SendUserTextAsync(phrase);
                }
            }

            GUILayout.Space(6f);
            GUILayout.Label("视觉 / 打断");
            GUILayout.BeginHorizontal();
            if (GUILayout.Button("抓帧识别", GUILayout.Height(34f)) && frameSource != null)
            {
                frameSource.CaptureAndSend("桌子上有什么");
            }
            if (GUILayout.Button("打断 TTS", GUILayout.Height(34f)) && webSocketClient != null)
            {
                ttsPlayer?.StopPlayback(true);
                _ = webSocketClient.SendBargeInAsync("debug_panel");
            }
            if (GUILayout.Button("TTS 开关", GUILayout.Height(34f)) && webSocketClient != null)
            {
                var enabled = ttsPlayer == null || !ttsPlayer.IsPlaying;
                var payload = new JObject { ["enabled"] = enabled };
                _ = webSocketClient.SendAsync(new QuestEnvelope(
                    "client.tts_config", payload, webSocketClient.SessionId));
            }
            GUILayout.EndHorizontal();

            GUILayout.Space(6f);
            GUILayout.Label("MRUK 场景");
            GUILayout.Label(sceneSummary != null ? sceneSummary.Summary : "（未挂接）");

            GUILayout.EndScrollView();
            GUILayout.EndArea();
            GUI.matrix = previousScale;
        }
    }
}
