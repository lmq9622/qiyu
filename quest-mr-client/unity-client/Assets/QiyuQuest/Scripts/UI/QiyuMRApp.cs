using System;
using System.Collections.Generic;
using System.Text;
using Meta.XR.MRUtilityKit;
using Newtonsoft.Json.Linq;
using Qiyu.Quest.Avatar;
using Qiyu.Quest.Networking;
using Qiyu.Quest.Perception;
using Qiyu.Quest.Spatial;
using Qiyu.Quest.Voice;
using UnityEngine;
using UnityEngine.UI;

namespace Qiyu.Quest.UI
{
    /// <summary>
    /// Qiyu Quest MR 主界面：liquid glass 圆角卡片 + 标签页。
    ///
    /// 页面：首页 / 对话 / 环境 / 角色 / 设置 / 模型决策 / 调试
    /// 交互：右手手柄射线（或头部视线）+ 扳机/A 键点击；左摇杆滚动。
    /// </summary>
    public class QiyuMRApp : MonoBehaviour
    {
        [Header("依赖")]
        [SerializeField] private QiyuQuestWebSocketClient webSocketClient;
        [SerializeField] private QuestMicrophoneCapture microphone;
        [SerializeField] private QuestTtsPlayer ttsPlayer;
        [SerializeField] private PassthroughFrameSource frameSource;
        [SerializeField] private MrukSceneSummary sceneSummary;
        [SerializeField] private RoomNavMeshBuilder navMeshBuilder;
        [SerializeField] private ObjectDetectionProjector objectDetector;
        [SerializeField] private AvatarIntentRouter avatarRouter;
        [SerializeField] private MrukWorldStatePublisher worldStatePublisher;
        [SerializeField] private Transform followTarget;

        [Header("面板")]
        [SerializeField] private float distance = 1.9f;
        [SerializeField] private float panelScale = 0.00105f;
        [SerializeField] private bool visible = true;

        private const float CanvasWidth = 1680f;
        private const float CanvasHeight = 1050f;

        private Canvas _canvas;
        private RectTransform _canvasRect;
        private RectTransform _content;
        private ScrollRect _scrollRect;
        private Text _connPill;
        private Text _sessionText;
        private Text _bottomStatus;
        private Text _homeMruk;
        private Text _homeReply;
        private Text _perceptionText;
        private Text _brainText;
        private Text _debugText;
        private Text _chatHistory;
        private Text _avatarStatus;
        private readonly Dictionary<string, QiyuUIButton> _tabButtons =
            new Dictionary<string, QiyuUIButton>();
        private string _activeTab = "首页";
        private string _lastSpeech = "";
        private string _lastTranscript = "";
        private string _lastError = "";
        private string _lastEvent = "";
        private string _lastAvatarIntent = "";
        private string _lastSpatialAction = "";
        private readonly List<string> _chatLines = new List<string>();
        private float _nextRefreshAt;

        private static readonly string[] Tabs =
        {
            "首页", "对话", "环境", "角色", "设置", "模型决策", "调试"
        };

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
            BuildShell();
            ShowTab("首页");
            if (webSocketClient != null)
            {
                webSocketClient.OnMessage += HandleMessage;
                webSocketClient.OnAgentSpeech += HandleSpeech;
                webSocketClient.SessionEstablished += ApplySettingsToServer;
            }
            microphone?.SetVadThreshold(QiyuSettings.VadThreshold);
            microphone?.SetGain(QiyuSettings.MicGain);
            Debug.Log("[QiyuMRApp] UI 初始化完成");
        }

        private void OnDestroy()
        {
            if (webSocketClient != null)
            {
                webSocketClient.OnMessage -= HandleMessage;
                webSocketClient.OnAgentSpeech -= HandleSpeech;
                webSocketClient.SessionEstablished -= ApplySettingsToServer;
            }
            if (_canvasRect != null)
            {
                Destroy(_canvasRect.gameObject);
            }
        }

        private void ApplySettingsToServer()
        {
            if (webSocketClient == null)
            {
                return;
            }
            webSocketClient.SendAsync(new QuestEnvelope("client.tts_config",
                new JObject { ["enabled"] = QiyuSettings.TtsEnabled },
                webSocketClient.SessionId));
        }

        private void HandleMessage(QuestEnvelope envelope)
        {
            _lastEvent = $"{envelope.type} @ {DateTime.Now:HH:mm:ss}";
            switch (envelope.type)
            {
                case "server.voice_transcript":
                    _lastTranscript = envelope.payload.Value<string>("text") ?? "";
                    AddChat("我", _lastTranscript);
                    break;
                case "server.error":
                    _lastError = $"{envelope.payload.Value<string>("code")}: " +
                                 $"{envelope.payload.Value<string>("message")}";
                    break;
                case "avatar.intent":
                    _lastAvatarIntent =
                        $"{envelope.payload.Value<string>("emotion")} / " +
                        $"{envelope.payload.Value<string>("action")}";
                    break;
                case "spatial.action":
                    _lastSpatialAction =
                        $"{envelope.payload.Value<string>("action")} → " +
                        $"{envelope.payload.Value<string>("target_id")}";
                    break;
            }
        }

        private void HandleSpeech(JObject payload)
        {
            _lastSpeech = payload.Value<string>("text") ?? "";
            if (!string.IsNullOrEmpty(_lastSpeech))
            {
                AddChat("栖语", _lastSpeech);
            }
        }

        private void AddChat(string speaker, string text)
        {
            if (string.IsNullOrWhiteSpace(text))
            {
                return;
            }
            _chatLines.Add($"{speaker}：{text}");
            if (_chatLines.Count > 12)
            {
                _chatLines.RemoveAt(0);
            }
        }

        private void Update()
        {
            FollowUser();
            UpdateTopBar();
            UpdateActivePanel();
            ScrollWithThumbstick();
        }

        private void FollowUser()
        {
            if (!visible || followTarget == null || _canvasRect == null)
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
            _canvasRect.position = followTarget.position + forward * distance +
                                   Vector3.up * -0.08f;
            _canvasRect.rotation = Quaternion.LookRotation(-forward, Vector3.up);
        }

        private void ScrollWithThumbstick()
        {
            if (_scrollRect == null)
            {
                return;
            }
            var axis = OVRInput.Get(OVRInput.Axis2D.PrimaryThumbstick);
            if (Mathf.Abs(axis.y) > 0.15f)
            {
                _scrollRect.verticalNormalizedPosition =
                    Mathf.Clamp01(_scrollRect.verticalNormalizedPosition + axis.y * 0.02f);
            }
        }

        private void UpdateTopBar()
        {
            var connected = webSocketClient != null && webSocketClient.IsConnected;
            var handshake = webSocketClient != null && webSocketClient.HandshakeDone;
            if (_connPill != null)
            {
                _connPill.text = connected
                    ? (handshake ? "● 已连接" : "● 握手中")
                    : "● 未连接";
                _connPill.color = connected
                    ? (handshake ? QiyuUI.Success : QiyuUI.Warning)
                    : QiyuUI.Danger;
            }
            if (_sessionText != null)
            {
                var session = webSocketClient != null ? webSocketClient.SessionId : "";
                _sessionText.text = string.IsNullOrEmpty(session)
                    ? "session: -"
                    : $"session: {session.Substring(0, Mathf.Min(8, session.Length))}…";
            }
            if (_bottomStatus != null)
            {
                var mic = microphone != null && microphone.IsCapturing ? "麦克风开" : "麦克风关";
                var tts = ttsPlayer != null && ttsPlayer.IsPlaying ? "TTS 播放中" : "TTS 空闲";
                _bottomStatus.text = $"{mic}   |   {tts}   |   " +
                                     $"最近: {_lastEvent}";
            }
        }

        private void UpdateActivePanel()
        {
            if (Time.unscaledTime < _nextRefreshAt)
            {
                return;
            }
            _nextRefreshAt = Time.unscaledTime + 0.5f;
            switch (_activeTab)
            {
                case "首页":
                    RefreshHome();
                    break;
                case "对话":
                    RefreshChat();
                    break;
                case "环境":
                    RefreshPerception();
                    break;
                case "角色":
                    RefreshAvatar();
                    break;
                case "模型决策":
                    RefreshBrain();
                    break;
                case "调试":
                    RefreshDebug();
                    break;
            }
        }

        // ---------------- Shell ----------------

        private void BuildShell()
        {
            var canvasObject = new GameObject("QiyuMRAppCanvas");
            canvasObject.transform.SetParent(null, false);
            _canvas = canvasObject.AddComponent<Canvas>();
            _canvas.renderMode = RenderMode.WorldSpace;
            _canvas.sortingOrder = 200;
            _canvasRect = (RectTransform)canvasObject.transform;
            _canvasRect.sizeDelta = new Vector2(CanvasWidth, CanvasHeight);
            _canvasRect.localScale = Vector3.one * panelScale;

            var background = QiyuUI.Card(canvasObject.transform, "Root", true, 34);
            QiyuUI.Stretch(background.rectTransform);

            // 顶部栏
            var top = QiyuUI.CreateRect(canvasObject.transform, "TopBar");
            QiyuUI.SetAnchored(top, new Vector2(0, 1), new Vector2(1, 1),
                new Vector2(26, -96), new Vector2(-26, -22));
            var logo = QiyuUI.Label(top, "Logo", "栖", 40, QiyuUI.TextPrimary,
                TextAnchor.MiddleCenter, FontStyle.Bold);
            QiyuUI.SetAnchored(logo.rectTransform, new Vector2(0, 0), new Vector2(0, 1),
                new Vector2(0, 0), new Vector2(56, 0));
            var title = QiyuUI.Label(top, "Title", "栖语 Quest", 34, QiyuUI.TextPrimary,
                TextAnchor.MiddleLeft, FontStyle.Bold);
            QiyuUI.SetAnchored(title.rectTransform, new Vector2(0, 0), new Vector2(0.5f, 1),
                new Vector2(70, 12), new Vector2(0, -6));
            var subtitle = QiyuUI.Label(top, "Subtitle", "MR Companion Runtime", 18,
                QiyuUI.TextTertiary, TextAnchor.UpperLeft);
            QiyuUI.SetAnchored(subtitle.rectTransform, new Vector2(0, 0), new Vector2(0.5f, 1),
                new Vector2(72, 0), new Vector2(0, -46));
            _connPill = QiyuUI.Label(top, "ConnPill", "● 未连接", 20, QiyuUI.Danger,
                TextAnchor.MiddleRight, FontStyle.Bold);
            QiyuUI.SetAnchored(_connPill.rectTransform, new Vector2(0.5f, 0), new Vector2(0.78f, 1),
                Vector2.zero, Vector2.zero);
            _sessionText = QiyuUI.Label(top, "Session", "session: -", 18,
                QiyuUI.TextTertiary, TextAnchor.MiddleRight);
            QiyuUI.SetAnchored(_sessionText.rectTransform, new Vector2(0.78f, 0), new Vector2(1, 1),
                Vector2.zero, Vector2.zero);

            // 标签栏
            var tabBar = QiyuUI.CreateRect(canvasObject.transform, "TabBar");
            QiyuUI.SetAnchored(tabBar, new Vector2(0, 1), new Vector2(1, 1),
                new Vector2(26, -170), new Vector2(-26, -104));
            var tabLayout = tabBar.gameObject.AddComponent<HorizontalLayoutGroup>();
            tabLayout.spacing = 10f;
            tabLayout.childControlWidth = true;
            tabLayout.childControlHeight = true;
            tabLayout.childForceExpandWidth = true;
            tabLayout.childForceExpandHeight = true;
            foreach (var tab in Tabs)
            {
                var captured = tab;
                var button = QiyuUI.Button(tabBar, $"Tab_{tab}", tab,
                    () => ShowTab(captured),
                    QiyuUI.ButtonVariant.Ghost, 21, 52);
                _tabButtons[tab] = button;
            }

            // 内容区
            var scrollRoot = QiyuUI.ScrollView(canvasObject.transform, "Content",
                out _content);
            QiyuUI.SetAnchored((RectTransform)scrollRoot.transform,
                new Vector2(0, 0), new Vector2(1, 1),
                new Vector2(26, 88), new Vector2(-26, -180));
            _scrollRect = scrollRoot.GetComponent<ScrollRect>();

            // 底部状态栏
            var bottom = QiyuUI.Card(canvasObject.transform, "BottomBar", false, 20);
            QiyuUI.SetAnchored(bottom.rectTransform, new Vector2(0, 0), new Vector2(1, 0),
                new Vector2(26, 20), new Vector2(-26, 78));
            _bottomStatus = QiyuUI.Label(bottom.rectTransform, "Status", "", 19,
                QiyuUI.TextSecondary, TextAnchor.MiddleLeft);
            QiyuUI.Stretch(_bottomStatus.rectTransform, 18f, 0f);

            var interactor = canvasObject.AddComponent<QiyuGazeInteractor>();
        }

        private void ShowTab(string tab)
        {
            _activeTab = tab;
            foreach (var kv in _tabButtons)
            {
                var image = kv.Value.GetComponent<Image>();
                var active = kv.Key == tab;
                image.color = active ? new Color(1f, 1f, 1f, 0.92f) : Color.white;
                var label = kv.Value.GetComponentInChildren<Text>();
                if (label != null)
                {
                    label.color = active ? new Color(0.07f, 0.07f, 0.08f) : QiyuUI.TextSecondary;
                }
            }
            foreach (Transform child in _content)
            {
                Destroy(child.gameObject);
            }
            _homeMruk = null;
            _homeReply = null;
            _perceptionText = null;
            _brainText = null;
            _debugText = null;
            _chatHistory = null;
            _avatarStatus = null;
            switch (tab)
            {
                case "首页":
                    BuildHome();
                    break;
                case "对话":
                    BuildChat();
                    break;
                case "环境":
                    BuildPerception();
                    break;
                case "角色":
                    BuildAvatar();
                    break;
                case "设置":
                    BuildSettings();
                    break;
                case "模型决策":
                    BuildBrain();
                    break;
                case "调试":
                    BuildDebug();
                    break;
            }
            _scrollRect.verticalNormalizedPosition = 1f;
        }

        // ---------------- Panels ----------------

        private void BuildHome()
        {
            var quick = QiyuUI.Card(_content, "QuickActions", true);
            var quickLayout = quick.gameObject.AddComponent<VerticalLayoutGroup>();
            quickLayout.spacing = 12f;
            quickLayout.padding = new RectOffset(18, 18, 18, 18);
            quickLayout.childControlWidth = true;
            quickLayout.childControlHeight = false;
            quickLayout.childForceExpandWidth = true;
            var quickFitter = quick.gameObject.AddComponent<ContentSizeFitter>();
            quickFitter.verticalFit = ContentSizeFitter.FitMode.PreferredSize;
            QiyuUI.Label(quick.transform, "Title", "快捷操作", 24, QiyuUI.TextPrimary,
                TextAnchor.MiddleLeft, FontStyle.Bold).gameObject
                .AddComponent<LayoutElement>().minHeight = 34;
            var row1 = QiyuUI.HBox(quick.transform, "Row1");
            row1.gameObject.AddComponent<LayoutElement>().minHeight = 60;
            QiyuUI.Button(row1, "Hello", "你好，你在吗？",
                () => webSocketClient?.SendUserTextAsync("你好，你在吗？"),
                QiyuUI.ButtonVariant.Primary, 21, 58);
            QiyuUI.Button(row1, "Vision", "桌子上有什么？",
                () => webSocketClient?.SendUserTextAsync("你能看到桌子上有什么吗？"),
                QiyuUI.ButtonVariant.Glass, 21, 58);
            var row2 = QiyuUI.HBox(quick.transform, "Row2");
            row2.gameObject.AddComponent<LayoutElement>().minHeight = 60;
            QiyuUI.Button(row2, "Capture", "抓帧识别",
                () => frameSource?.CaptureAndSend("桌子上有什么"),
                QiyuUI.ButtonVariant.Glass, 21, 58);
            QiyuUI.Button(row2, "Barge", "打断 TTS", () =>
            {
                ttsPlayer?.StopPlayback(true);
                webSocketClient?.SendBargeInAsync("ui_button");
            }, QiyuUI.ButtonVariant.Danger, 21, 58);

            var status = QiyuUI.Card(_content, "Status", true);
            var statusLayout = status.gameObject.AddComponent<VerticalLayoutGroup>();
            statusLayout.spacing = 10f;
            statusLayout.padding = new RectOffset(18, 18, 18, 18);
            statusLayout.childControlWidth = true;
            statusLayout.childControlHeight = false;
            statusLayout.childForceExpandWidth = true;
            var fitter = status.gameObject.AddComponent<ContentSizeFitter>();
            fitter.verticalFit = ContentSizeFitter.FitMode.PreferredSize;
            QiyuUI.Label(status.transform, "Title", "运行状态", 24, QiyuUI.TextPrimary,
                TextAnchor.MiddleLeft, FontStyle.Bold).gameObject
                .AddComponent<LayoutElement>().minHeight = 34;
            _homeMruk = QiyuUI.Label(status.transform, "Mruk", "", 21,
                QiyuUI.TextSecondary, TextAnchor.UpperLeft);
            _homeMruk.gameObject.AddComponent<LayoutElement>().minHeight = 150;
            _homeReply = QiyuUI.Label(status.transform, "Reply", "", 21,
                QiyuUI.TextSecondary, TextAnchor.UpperLeft);
            _homeReply.gameObject.AddComponent<LayoutElement>().minHeight = 90;
        }

        private void RefreshHome()
        {
            if (_homeMruk != null)
            {
                var room = sceneSummary != null ? sceneSummary.CurrentRoom : null;
                _homeMruk.text = room == null
                    ? "MRUK：尚未加载房间"
                    : $"MRUK：{room.name}\n锚点 {room.Anchors.Count} 个   " +
                      $"墙 {room.WallAnchors.Count}   地面 {room.FloorAnchors.Count}   " +
                      $"天花板 {room.CeilingAnchors.Count}";
            }
            if (_homeReply != null)
            {
                _homeReply.text = string.IsNullOrEmpty(_lastSpeech)
                    ? "最近回复：-"
                    : $"最近回复：{_lastSpeech}";
            }
        }

        private void BuildChat()
        {
            var card = QiyuUI.Card(_content, "Chat", true);
            var layout = card.gameObject.AddComponent<VerticalLayoutGroup>();
            layout.spacing = 12f;
            layout.padding = new RectOffset(18, 18, 18, 18);
            layout.childControlWidth = true;
            layout.childControlHeight = false;
            layout.childForceExpandWidth = true;
            var fitter = card.gameObject.AddComponent<ContentSizeFitter>();
            fitter.verticalFit = ContentSizeFitter.FitMode.PreferredSize;
            QiyuUI.Label(card.transform, "Title", "对话", 24, QiyuUI.TextPrimary,
                TextAnchor.MiddleLeft, FontStyle.Bold).gameObject
                .AddComponent<LayoutElement>().minHeight = 34;
            _chatHistory = QiyuUI.Label(card.transform, "History", "", 21,
                QiyuUI.TextSecondary, TextAnchor.UpperLeft);
            _chatHistory.gameObject.AddComponent<LayoutElement>().minHeight = 320;
            var row = QiyuUI.HBox(card.transform, "Actions");
            row.gameObject.AddComponent<LayoutElement>().minHeight = 60;
            QiyuUI.Button(row, "Mic", "语音输入（麦克风）", null, QiyuUI.ButtonVariant.Primary, 21, 58);
            QiyuUI.Button(row, "Clear", "清空显示", () =>
            {
                _chatLines.Clear();
                RefreshChat();
            }, QiyuUI.ButtonVariant.Glass, 21, 58);
        }

        private void RefreshChat()
        {
            if (_chatHistory == null)
            {
                return;
            }
            var builder = new StringBuilder();
            foreach (var line in _chatLines)
            {
                builder.AppendLine(line);
                builder.AppendLine();
            }
            if (!string.IsNullOrEmpty(_lastError))
            {
                builder.AppendLine($"错误：{_lastError}");
            }
            _chatHistory.text = builder.Length == 0 ? "还没有对话记录。戴上头显直接说话，或回首页点快捷操作。" : builder.ToString();
        }

        private void BuildPerception()
        {
            var card = QiyuUI.Card(_content, "Perception", true);
            var layout = card.gameObject.AddComponent<VerticalLayoutGroup>();
            layout.spacing = 12f;
            layout.padding = new RectOffset(18, 18, 18, 18);
            layout.childControlWidth = true;
            layout.childControlHeight = false;
            layout.childForceExpandWidth = true;
            var fitter = card.gameObject.AddComponent<ContentSizeFitter>();
            fitter.verticalFit = ContentSizeFitter.FitMode.PreferredSize;
            QiyuUI.Label(card.transform, "Title", "环境感知", 24, QiyuUI.TextPrimary,
                TextAnchor.MiddleLeft, FontStyle.Bold).gameObject
                .AddComponent<LayoutElement>().minHeight = 34;
            _perceptionText = QiyuUI.Label(card.transform, "Info", "", 21,
                QiyuUI.TextSecondary, TextAnchor.UpperLeft);
            _perceptionText.gameObject.AddComponent<LayoutElement>().minHeight = 360;
            var row = QiyuUI.HBox(card.transform, "Actions");
            row.gameObject.AddComponent<LayoutElement>().minHeight = 60;
            QiyuUI.Button(row, "Rescan", "重新扫描房间", () =>
            {
                _ = MRUK.Instance?.LoadSceneFromDevice();
            }, QiyuUI.ButtonVariant.Glass, 20, 58);
            QiyuUI.Button(row, "Detect", "抓帧物体识别",
                () => frameSource?.CaptureAndSend("识别房间里的杯子、手机等小物体"),
                QiyuUI.ButtonVariant.Primary, 20, 58);
        }

        private void RefreshPerception()
        {
            if (_perceptionText == null)
            {
                return;
            }
            var builder = new StringBuilder();
            var room = sceneSummary != null ? sceneSummary.CurrentRoom : null;
            if (room == null)
            {
                builder.AppendLine("MRUK：尚未加载房间");
            }
            else
            {
                builder.AppendLine($"房间：{room.name}");
                builder.AppendLine($"锚点总数：{room.Anchors.Count}   " +
                                   $"墙 {room.WallAnchors.Count}   " +
                                   $"地面 {room.FloorAnchors.Count}   " +
                                   $"天花板 {room.CeilingAnchors.Count}");
                var counts = new Dictionary<string, int>();
                foreach (var anchor in room.Anchors)
                {
                    var label = anchor.Label.ToString();
                    counts[label] = counts.TryGetValue(label, out var c) ? c + 1 : 1;
                }
                foreach (var kv in counts)
                {
                    if (kv.Key.Contains("WALL") || kv.Key.Contains("FLOOR") ||
                        kv.Key.Contains("CEILING"))
                    {
                        continue;
                    }
                    builder.AppendLine($"  {kv.Key}: {kv.Value}");
                }
            }
            builder.AppendLine();
            builder.AppendLine("导航：");
            if (navMeshBuilder != null && navMeshBuilder.Generated)
            {
                builder.AppendLine($"  已生成 v{navMeshBuilder.Version}  " +
                                   $"可行走面积 {navMeshBuilder.WalkableAreaM2:F2} m²");
            }
            else
            {
                builder.AppendLine("  未生成");
            }
            builder.AppendLine();
            builder.AppendLine("识别物体：");
            var objects = objectDetector != null ? objectDetector.LastObjects : null;
            if (objects == null || objects.Count == 0)
            {
                builder.AppendLine("  暂无（点“抓帧物体识别”）");
            }
            else
            {
                foreach (var item in objects)
                {
                    builder.AppendLine($"  {item.label}  {item.confidence:P0}  " +
                                       $"({item.worldPosition.x:F1},{item.worldPosition.y:F1}," +
                                       $"{item.worldPosition.z:F1})");
                }
            }
            _perceptionText.text = builder.ToString();
        }

        private void BuildAvatar()
        {
            var card = QiyuUI.Card(_content, "Avatar", true);
            var layout = card.gameObject.AddComponent<VerticalLayoutGroup>();
            layout.spacing = 12f;
            layout.padding = new RectOffset(18, 18, 18, 18);
            layout.childControlWidth = true;
            layout.childControlHeight = false;
            layout.childForceExpandWidth = true;
            var fitter = card.gameObject.AddComponent<ContentSizeFitter>();
            fitter.verticalFit = ContentSizeFitter.FitMode.PreferredSize;
            QiyuUI.Label(card.transform, "Title", "角色 / 模型", 24, QiyuUI.TextPrimary,
                TextAnchor.MiddleLeft, FontStyle.Bold).gameObject
                .AddComponent<LayoutElement>().minHeight = 34;
            _avatarStatus = QiyuUI.Label(card.transform, "Status", "", 21,
                QiyuUI.TextSecondary, TextAnchor.UpperLeft);
            _avatarStatus.gameObject.AddComponent<LayoutElement>().minHeight = 120;

            QiyuUI.Label(card.transform, "ImportTitle", "导入模型（VRM / GLB）", 21,
                QiyuUI.TextPrimary, TextAnchor.MiddleLeft, FontStyle.Bold).gameObject
                .AddComponent<LayoutElement>().minHeight = 32;
            QiyuUI.Input(card.transform, "AvatarUrl",
                "模型地址或本地路径（预留）", QiyuSettings.AvatarUrl,
                value => QiyuSettings.AvatarUrl = value);
            var row = QiyuUI.HBox(card.transform, "ImportRow");
            row.gameObject.AddComponent<LayoutElement>().minHeight = 60;
            QiyuUI.Button(row, "Import", "导入模型", () =>
            {
                var importer = GetComponent<QuestAvatarModelImporter>();
                importer?.ImportFromConfiguredSource();
            }, QiyuUI.ButtonVariant.Primary, 21, 58);
            QiyuUI.Button(row, "Remove", "移除模型", () =>
            {
                GetComponent<QuestAvatarModelImporter>()?.RemoveModel();
            }, QiyuUI.ButtonVariant.Danger, 21, 58);

            QiyuUI.Slider(card.transform, "Scale", "模型缩放", 0.3f, 2.5f,
                QiyuSettings.AvatarScale, value => QiyuSettings.AvatarScale = value, "x");
            QiyuUI.Slider(card.transform, "Height", "高度偏移", -1f, 1f,
                QiyuSettings.AvatarHeight, value => QiyuSettings.AvatarHeight = value, "m");
        }

        private void RefreshAvatar()
        {
            if (_avatarStatus == null)
            {
                return;
            }
            var importer = GetComponent<QuestAvatarModelImporter>();
            var loaded = importer != null && importer.IsModelLoaded;
            var builder = new StringBuilder();
            builder.AppendLine(loaded
                ? $"已加载：{importer.CurrentModelName}"
                : "未导入模型（当前只有空间能力，没有可见角色）");
            builder.AppendLine($"表情：{avatarRouter?.CurrentEmotion ?? "-"}   " +
                               $"动作：{avatarRouter?.CurrentAction ?? "-"}   " +
                               $"说话：{(avatarRouter != null && avatarRouter.IsSpeaking ? "是" : "否")}");
            builder.AppendLine($"AvatarIntent：{(_lastAvatarIntent.Length > 0 ? _lastAvatarIntent : "-")}");
            builder.AppendLine($"SpatialAction：{(_lastSpatialAction.Length > 0 ? _lastSpatialAction : "-")}");
            builder.AppendLine();
            builder.AppendLine("支持格式：VRM 1.0 / VRM 0.x / GLB（通过 UniVRM / glTFast）");
            builder.AppendLine("模型可来自：本地 StreamingAssets、URL 下载、或未来 Qiyu 后端下发。");
            _avatarStatus.text = builder.ToString();
        }

        private void BuildSettings()
        {
            var card = QiyuUI.Card(_content, "Settings", true);
            var layout = card.gameObject.AddComponent<VerticalLayoutGroup>();
            layout.spacing = 10f;
            layout.padding = new RectOffset(18, 18, 18, 18);
            layout.childControlWidth = true;
            layout.childControlHeight = false;
            layout.childForceExpandWidth = true;
            var fitter = card.gameObject.AddComponent<ContentSizeFitter>();
            fitter.verticalFit = ContentSizeFitter.FitMode.PreferredSize;
            QiyuUI.Label(card.transform, "Title", "设置", 24, QiyuUI.TextPrimary,
                TextAnchor.MiddleLeft, FontStyle.Bold).gameObject
                .AddComponent<LayoutElement>().minHeight = 34;

            Section(card.transform, "连接");
            QiyuUI.Input(card.transform, "Gateway", "Gateway WebSocket 地址",
                QiyuSettings.GatewayUrl, value => QiyuSettings.GatewayUrl = value);
            QiyuUI.Input(card.transform, "UserId", "user_id", QiyuSettings.UserId,
                value => QiyuSettings.UserId = value);
            QiyuUI.Input(card.transform, "CharId", "char_id", QiyuSettings.CharId,
                value => QiyuSettings.CharId = value);
            QiyuUI.Toggle(card.transform, "AutoConnect", "启动时自动连接",
                QiyuSettings.AutoConnect, value => QiyuSettings.AutoConnect = value);
            var connRow = QiyuUI.HBox(card.transform, "ConnRow");
            connRow.gameObject.AddComponent<LayoutElement>().minHeight = 60;
            QiyuUI.Button(connRow, "Apply", "应用并重连", () =>
            {
                webSocketClient?.SetServerUrl(QiyuSettings.GatewayUrl);
            }, QiyuUI.ButtonVariant.Primary, 20, 58);
            QiyuUI.Button(connRow, "Ping", "心跳测试", () =>
            {
                webSocketClient?.SendAsync(new QuestEnvelope("client.echo",
                    new JObject { ["probe"] = "ui" }, webSocketClient.SessionId));
            }, QiyuUI.ButtonVariant.Glass, 20, 58);

            Section(card.transform, "语音");
            QiyuUI.Toggle(card.transform, "Tts", "启用服务端 TTS",
                QiyuSettings.TtsEnabled, value =>
                {
                    QiyuSettings.TtsEnabled = value;
                    webSocketClient?.SendAsync(new QuestEnvelope("client.tts_config",
                        new JObject { ["enabled"] = value }, webSocketClient.SessionId));
                });
            QiyuUI.Slider(card.transform, "Vad", "麦克风灵敏度（VAD 阈值）",
                0.005f, 0.2f, QiyuSettings.VadThreshold, value =>
                {
                    QiyuSettings.VadThreshold = value;
                    if (microphone != null)
                    {
                        microphone.SetVadThreshold(value);
                    }
                });
            QiyuUI.Slider(card.transform, "MicGain", "麦克风增益", 0.2f, 4f,
                QiyuSettings.MicGain, value =>
                {
                    QiyuSettings.MicGain = value;
                    microphone?.SetGain(value);
                });

            Section(card.transform, "对话");
            QiyuUI.Slider(card.transform, "Temp", "回复温度", 0f, 1.5f,
                QiyuSettings.Temperature, value => QiyuSettings.Temperature = value);

            var resetRow = QiyuUI.HBox(card.transform, "ResetRow");
            resetRow.gameObject.AddComponent<LayoutElement>().minHeight = 60;
            QiyuUI.Button(resetRow, "Reset", "恢复默认设置", () =>
            {
                QiyuSettings.ResetAll();
                ShowTab("设置");
            }, QiyuUI.ButtonVariant.Danger, 20, 58);
        }

        private static void Section(Transform parent, string title)
        {
            var label = QiyuUI.Label(parent, $"Section_{title}", title, 19,
                QiyuUI.TextTertiary, TextAnchor.MiddleLeft, FontStyle.Bold);
            label.gameObject.AddComponent<LayoutElement>().minHeight = 40;
        }

        private void BuildBrain()
        {
            var card = QiyuUI.Card(_content, "Brain", true);
            var layout = card.gameObject.AddComponent<VerticalLayoutGroup>();
            layout.spacing = 12f;
            layout.padding = new RectOffset(18, 18, 18, 18);
            layout.childControlWidth = true;
            layout.childControlHeight = false;
            layout.childForceExpandWidth = true;
            var fitter = card.gameObject.AddComponent<ContentSizeFitter>();
            fitter.verticalFit = ContentSizeFitter.FitMode.PreferredSize;
            QiyuUI.Label(card.transform, "Title", "模型决策", 24, QiyuUI.TextPrimary,
                TextAnchor.MiddleLeft, FontStyle.Bold).gameObject
                .AddComponent<LayoutElement>().minHeight = 34;
            _brainText = QiyuUI.Label(card.transform, "Info", "", 21,
                QiyuUI.TextSecondary, TextAnchor.UpperLeft);
            _brainText.gameObject.AddComponent<LayoutElement>().minHeight = 360;
            var row = QiyuUI.HBox(card.transform, "Actions");
            row.gameObject.AddComponent<LayoutElement>().minHeight = 60;
            QiyuUI.Button(row, "MiniMind", "接入 MiniMind-O", null,
                QiyuUI.ButtonVariant.Ghost, 20, 58);
            QiyuUI.Button(row, "MainBrain", "测试 MainBrain", () =>
                webSocketClient?.SendUserTextAsync("测试一下完整主脑链路"),
                QiyuUI.ButtonVariant.Glass, 20, 58);
        }

        private void RefreshBrain()
        {
            if (_brainText == null)
            {
                return;
            }
            var builder = new StringBuilder();
            builder.AppendLine("链路：Quest → Gateway → MessageGateway → BrainPipeline");
            builder.AppendLine("            → MiniMind-O → BrainDecision → MainBrain（需要时）");
            builder.AppendLine();
            builder.AppendLine($"最近事件：{_lastEvent}");
            builder.AppendLine($"AvatarIntent：{(_lastAvatarIntent.Length > 0 ? _lastAvatarIntent : "-")}");
            builder.AppendLine($"SpatialAction：{(_lastSpatialAction.Length > 0 ? _lastSpatialAction : "-")}");
            builder.AppendLine();
            builder.AppendLine("MiniMind-O：由 Qiyu 后端托管，本页预留接入状态显示。");
            builder.AppendLine("MainBrain：复杂任务时由后端自动升级，Quest 端不另起 Agent。");
            builder.AppendLine("说明：LLM 只输出 AvatarIntent / SpatialAction 高层意图，");
            builder.AppendLine("      骨骼与路径由 Quest 本地执行层决定。");
            _brainText.text = builder.ToString();
        }

        private void BuildDebug()
        {
            var card = QiyuUI.Card(_content, "Debug", true);
            var layout = card.gameObject.AddComponent<VerticalLayoutGroup>();
            layout.spacing = 12f;
            layout.padding = new RectOffset(18, 18, 18, 18);
            layout.childControlWidth = true;
            layout.childControlHeight = false;
            layout.childForceExpandWidth = true;
            var fitter = card.gameObject.AddComponent<ContentSizeFitter>();
            fitter.verticalFit = ContentSizeFitter.FitMode.PreferredSize;
            QiyuUI.Label(card.transform, "Title", "调试", 24, QiyuUI.TextPrimary,
                TextAnchor.MiddleLeft, FontStyle.Bold).gameObject
                .AddComponent<LayoutElement>().minHeight = 34;
            _debugText = QiyuUI.Label(card.transform, "Info", "", 19,
                QiyuUI.TextSecondary, TextAnchor.UpperLeft);
            _debugText.gameObject.AddComponent<LayoutElement>().minHeight = 420;
            var row = QiyuUI.HBox(card.transform, "Actions");
            row.gameObject.AddComponent<LayoutElement>().minHeight = 60;
            QiyuUI.Button(row, "Reconnect", "重连", () =>
                webSocketClient?.ConnectAsync(), QiyuUI.ButtonVariant.Primary, 20, 58);
            QiyuUI.Button(row, "World", "立即上报 WorldState", () =>
            {
                if (worldStatePublisher != null && worldStatePublisher.LatestPayload != null)
                {
                    webSocketClient?.SendWorldStateAsync(worldStatePublisher.LatestPayload);
                }
            }, QiyuUI.ButtonVariant.Glass, 20, 58);
        }

        private void RefreshDebug()
        {
            if (_debugText == null)
            {
                return;
            }
            var builder = new StringBuilder();
            builder.AppendLine("Passthrough：");
            builder.AppendLine($"  {PassthroughDiagnostics.LastSnapshot}");
            builder.AppendLine();
            builder.AppendLine("连接：");
            builder.AppendLine($"  gateway: {webSocketClient?.ServerUrl}");
            builder.AppendLine($"  session: {webSocketClient?.SessionId}");
            builder.AppendLine($"  connected: {webSocketClient?.IsConnected}   " +
                               $"handshake: {webSocketClient?.HandshakeDone}");
            builder.AppendLine();
            builder.AppendLine("WorldState（最近一帧）：");
            var payload = worldStatePublisher != null ? worldStatePublisher.LatestPayload : null;
            if (payload != null)
            {
                var text = payload.ToString(Newtonsoft.Json.Formatting.None);
                builder.AppendLine(text.Length > 1400 ? text.Substring(0, 1400) + "…" : text);
            }
            else
            {
                builder.AppendLine("  （尚未生成）");
            }
            _debugText.text = builder.ToString();
        }
    }
}
