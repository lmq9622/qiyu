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
using TMPro;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.UI;

namespace Qiyu.Quest.UI
{
    /// <summary>
    /// Qiyu Quest MR 主界面。
    ///
    /// 设计语言：visionOS 风格 liquid glass，大圆角、厚玻璃、柔和投影、果冻高光。
    /// 交互：手柄射线 / 手部捏合 / 视线，A/扳机确认，左摇杆滚动，摇杆按下重新居中。
    ///
    /// 页面：首页 / 对话 / 环境 / 角色 / 设置 / 模型决策 / 调试
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
        [SerializeField] private float panelScale = 0.00105f;
        [SerializeField] private bool visible = true;

        private const float CanvasWidth = 1680f;
        private const float CanvasHeight = 1050f;
        private const float Outer = 24f;
        private const float TopBarHeight = 88f;
        private const float TabBarHeight = 68f;
        private const float BottomBarHeight = 52f;

        private static readonly string[] Tabs =
        {
            "首页", "对话", "环境", "角色", "设置", "模型决策", "调试"
        };

        private Canvas _canvas;
        private RectTransform _canvasRect;
        private RectTransform _content;
        private ScrollRect _scrollRect;
        private QiyuVirtualKeyboard _keyboard;
        private QiyuRenderQuality _renderQuality;
        private QiyuUIButton _modeButton;
        private RectTransform _dragHandle;
        private bool _dragging;
        private Vector3 _dragStartCanvasPosition;
        private Vector3 _dragStartHitPoint;
        private Vector3 _dragPlaneNormal;

        private TMP_Text _connText;
        private Image _connDot;
        private TMP_Text _sessionText;
        private TMP_Text _bottomStatus;
        private TMP_Text _homeMruk;
        private TMP_Text _homeReply;
        private TMP_Text _homeSystem;
        private TMP_Text _perceptionText;
        private TMP_Text _navText;
        private TMP_Text _objectText;
        private TMP_Text _brainText;
        private TMP_Text _debugText;
        private TMP_Text _chatHistory;
        private TMP_Text _avatarStatus;
        private TMP_Text _avatarIntentText;
        private TMP_Text _avatarPreviewText;
        private QiyuUIInputField _chatInput;
        private QiyuUIInputField _avatarUrlInput;
        private Image _roomChip;
        private Image _anchorChip;
        private Image _objectChip;

        private readonly Dictionary<string, QiyuUITab> _tabButtons =
            new Dictionary<string, QiyuUITab>();
        private string _activeTab = "首页";
        private string _lastSpeech = "";
        private string _lastTranscript = "";
        private string _lastError = "";
        private string _lastEvent = "";
        private string _lastAvatarIntent = "";
        private string _lastSpatialAction = "";
        private readonly List<string> _chatLines = new List<string>();
        private float _nextRefreshAt;
        private float _smoothedFps = 72f;

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
            Recenter();
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
            webSocketClient?.SendAsync(new QuestEnvelope("client.tts_config",
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
            if (_chatLines.Count > 40)
            {
                _chatLines.RemoveAt(0);
            }
        }

        private void Update()
        {
            _smoothedFps = Mathf.Lerp(_smoothedFps, 1f / Mathf.Max(0.0001f,
                Time.unscaledDeltaTime), 0.08f);
            UpdatePanelTransform();
            UpdateTopBar();
            UpdateActivePanel();
            if (QiyuGazeInteractor.ModalRoot == null)
            {
                ScrollWithThumbstick();
                if (OVRInput.GetDown(OVRInput.Button.PrimaryThumbstick))
                {
                    Recenter();
                }
            }
        }

        private void UpdatePanelTransform()
        {
            if (!visible || _canvasRect == null)
            {
                return;
            }
            if (_dragging)
            {
                return;
            }
            if (QiyuSettings.PanelMode == (int)QiyuPanelMode.Motion3DoF &&
                followTarget != null)
            {
                PlaceInFrontOfUser();
            }
        }

        public void Recenter()
        {
            if (_canvasRect == null || followTarget == null)
            {
                return;
            }
            PlaceInFrontOfUser();
        }

        private void PlaceInFrontOfUser()
        {
            var forward = followTarget.forward;
            forward.y = 0f;
            if (forward.sqrMagnitude < 0.001f)
            {
                forward = Vector3.forward;
            }
            forward.Normalize();
            var distanceValue = Mathf.Clamp(QiyuSettings.PanelDistance, 1.2f, 3.0f);
            _canvasRect.position = followTarget.position + forward * distanceValue +
                                   Vector3.up * -0.06f;
            // Canvas 正面朝 -Z；+Z 指向用户前方，用户看到的是正面。
            _canvasRect.rotation = Quaternion.LookRotation(forward, Vector3.up);
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
                _scrollRect.verticalNormalizedPosition = Mathf.Clamp01(
                    _scrollRect.verticalNormalizedPosition + axis.y * 0.025f);
            }
        }

        private void UpdateTopBar()
        {
            var connected = webSocketClient != null && webSocketClient.IsConnected;
            var handshake = webSocketClient != null && webSocketClient.HandshakeDone;
            if (_connText != null)
            {
                _connText.text = connected
                    ? (handshake ? "已连接" : "握手中")
                    : "未连接";
                _connText.color = connected
                    ? (handshake ? QiyuUI.Success : QiyuUI.Warning)
                    : QiyuUI.Danger;
            }
            if (_connDot != null)
            {
                _connDot.color = connected
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
                _bottomStatus.text = $"{mic}   ·   {tts}   ·   {_smoothedFps:F0} FPS   ·   " +
                                     $"最近事件：{(_lastEvent.Length > 0 ? _lastEvent : "无")}";
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

        // ---------------- 主壳 ----------------

        private void BuildShell()
        {
            var canvasObject = new GameObject("QiyuMRAppCanvas");
            canvasObject.transform.SetParent(null, false);
            _canvas = canvasObject.AddComponent<Canvas>();
            _canvas.renderMode = RenderMode.WorldSpace;
            _canvas.sortingOrder = 200;
            _canvas.pixelPerfect = false;
            _canvas.additionalShaderChannels |= AdditionalCanvasShaderChannels.TexCoord1 |
                                                AdditionalCanvasShaderChannels.Normal |
                                                AdditionalCanvasShaderChannels.Tangent;
            _canvasRect = (RectTransform)canvasObject.transform;
            _canvasRect.sizeDelta = new Vector2(CanvasWidth, CanvasHeight);
            _canvasRect.localScale = Vector3.one * panelScale;

            var raycaster = canvasObject.AddComponent<OVRRaycaster>();
            raycaster.sortOrder = 200;
            if (followTarget != null)
            {
                var eyeCamera = followTarget.GetComponent<Camera>();
                if (eyeCamera != null)
                {
                    _canvas.worldCamera = eyeCamera;
                }
            }

            var root = QiyuUI.Panel(canvasObject.transform, "Root", true,
                QiyuUI.RadiusPanel, 1f);
            QiyuUI.Stretch(root.rectTransform);

            BuildTopBar(canvasObject.transform);
            BuildTabBar(canvasObject.transform);

            var scrollRoot = QiyuUI.ScrollView(canvasObject.transform, "Content", out _content,
                QiyuUI.Space6);
            QiyuUI.SetAnchored((RectTransform)scrollRoot.transform,
                new Vector2(0f, 0f), new Vector2(1f, 1f),
                new Vector2(Outer, 88f),
                new Vector2(-Outer, -(Outer + TopBarHeight + 20f + TabBarHeight + 16f)));
            _scrollRect = scrollRoot.GetComponent<ScrollRect>();

            BuildBottomBar(canvasObject.transform);
            BuildDragHandle(canvasObject.transform);

            var keyboardObject = new GameObject("QiyuVirtualKeyboard",
                typeof(RectTransform), typeof(QiyuVirtualKeyboard));
            keyboardObject.transform.SetParent(canvasObject.transform, false);
            _keyboard = keyboardObject.GetComponent<QiyuVirtualKeyboard>();
            _keyboard.Build(_canvasRect);

            _renderQuality = canvasObject.AddComponent<QiyuRenderQuality>();
            _renderQuality.ApplyFromSettings();
            ApplyPanelMode();
        }

        private void BuildTopBar(Transform parent)
        {
            var top = QiyuUI.CreateRect(parent, "TopBar");
            QiyuUI.SetAnchored(top, new Vector2(0f, 1f), new Vector2(1f, 1f),
                new Vector2(Outer, -TopBarHeight - Outer),
                new Vector2(-Outer, -Outer));

            var logo = QiyuUI.Panel(top, "LogoMark", true, 20);
            QiyuUI.SetAnchored(logo.rectTransform, new Vector2(0f, 0.5f), new Vector2(0f, 0.5f),
                new Vector2(0f, -28f), new Vector2(56f, 28f));
            var logoLabel = QiyuUI.Label(logo.rectTransform, "Glyph", "栖", 26,
                QiyuUI.TextPrimary, TextAnchor.MiddleCenter, true);
            QiyuUI.Stretch(logoLabel.rectTransform);

            var title = QiyuUI.Label(top, "Title", "栖语", 24, QiyuUI.TextPrimary,
                TextAnchor.UpperLeft, true);
            QiyuUI.SetAnchored(title.rectTransform, new Vector2(0f, 0f), new Vector2(0.45f, 1f),
                new Vector2(72f, 24f), new Vector2(0f, -4f));
            var subtitle = QiyuUI.Label(top, "Subtitle", "Quest MR Companion", 12,
                QiyuUI.TextTertiary, TextAnchor.LowerLeft);
            QiyuUI.SetAnchored(subtitle.rectTransform, new Vector2(0f, 0f),
                new Vector2(0.45f, 1f), new Vector2(74f, 6f), new Vector2(0f, -46f));

            _sessionText = QiyuUI.Label(top, "Session", "session: -", 15,
                QiyuUI.TextTertiary, TextAnchor.MiddleRight, false, false);
            QiyuUI.SetAnchored(_sessionText.rectTransform, new Vector2(0.28f, 0f),
                new Vector2(0.55f, 1f), Vector2.zero, Vector2.zero);

            var chip = QiyuUI.Panel(top, "ConnChip", false, 16);
            QiyuUI.SetAnchored(chip.rectTransform, new Vector2(1f, 0.5f), new Vector2(1f, 0.5f),
                new Vector2(-540f, -20f), new Vector2(-350f, 20f));
            var dot = QiyuUI.CreateRect(chip.rectTransform, "Dot");
            QiyuUI.SetAnchored(dot, new Vector2(0f, 0.5f), new Vector2(0f, 0.5f),
                new Vector2(16f, -7f), new Vector2(30f, 7f));
            _connDot = dot.gameObject.AddComponent<Image>();
            _connDot.sprite = QiyuUI.RadialSprite(64, Color.white,
                new Color(1f, 1f, 1f, 0f));
            _connDot.raycastTarget = false;
            _connText = QiyuUI.Label(chip.rectTransform, "Text", "未连接", 18,
                QiyuUI.Danger, TextAnchor.MiddleLeft, true);
            QiyuUI.SetAnchored(_connText.rectTransform, new Vector2(0f, 0f),
                new Vector2(1f, 1f), new Vector2(38f, 0f), new Vector2(-12f, 0f));

            _modeButton = QiyuUI.Button(top, "PanelMode", "固定 6DoF", TogglePanelMode,
                QiyuButtonVariant.Glass, 16, 44);
            QiyuUI.SetAnchored((RectTransform)_modeButton.transform,
                new Vector2(1f, 0.5f), new Vector2(1f, 0.5f),
                new Vector2(-340f, -22f), new Vector2(-175f, 22f));

            var recenter = QiyuUI.Button(top, "Recenter", "重置位置", Recenter,
                QiyuButtonVariant.Glass, 16, 44);
            QiyuUI.SetAnchored((RectTransform)recenter.transform,
                new Vector2(1f, 0.5f), new Vector2(1f, 0.5f),
                new Vector2(-165f, -22f), new Vector2(-5f, 22f));
        }

        private void BuildTabBar(Transform parent)
        {
            var bar = QiyuUI.CreateRect(parent, "TabBar");
            QiyuUI.SetAnchored(bar, new Vector2(0f, 1f), new Vector2(1f, 1f),
                new Vector2(Outer, -TopBarHeight - Outer - 20f - TabBarHeight),
                new Vector2(-Outer, -TopBarHeight - Outer - 20f));
            var background = QiyuUI.Panel(bar, "BarBackground", false, 24);
            QiyuUI.Stretch(background.rectTransform);
            var row = QiyuUI.HBox(bar, "TabRow", 8f, 6);
            QiyuUI.Stretch(row, 6f);
            foreach (var tab in Tabs)
            {
                var captured = tab;
                _tabButtons[tab] = QiyuUI.Tab(row, $"Tab_{tab}", tab,
                    () => ShowTab(captured));
            }
        }

        private void BuildBottomBar(Transform parent)
        {
            var bottom = QiyuUI.Panel(parent, "BottomBar", false, 20);
            QiyuUI.SetAnchored(bottom.rectTransform, new Vector2(0f, 0f),
                new Vector2(1f, 0f), new Vector2(Outer, Outer),
                new Vector2(-Outer, Outer + BottomBarHeight));
            _bottomStatus = QiyuUI.Label(bottom.rectTransform, "Status", "", 16,
                QiyuUI.TextSecondary, TextAnchor.MiddleLeft, false, false);
            QiyuUI.SetAnchored(_bottomStatus.rectTransform, new Vector2(0f, 0f),
                new Vector2(0.78f, 1f), new Vector2(22f, 0f), Vector2.zero);
            var hint = QiyuUI.Label(bottom.rectTransform, "Hint",
                "左摇杆滚动 · 摇杆按下重新居中 · 手柄扳机 / 手部捏合点击", 15,
                QiyuUI.TextTertiary, TextAnchor.MiddleRight, false, false);
            QiyuUI.SetAnchored(hint.rectTransform, new Vector2(0.72f, 0f),
                new Vector2(1f, 1f), Vector2.zero, new Vector2(-22f, 0f));
        }

        /// <summary>visionOS 风格窗口顶部拖动条；只在 6DoF 固定模式显示。</summary>
        private void BuildDragHandle(Transform parent)
        {
            _dragHandle = QiyuUI.CreateRect(parent, "DragHandle");
            QiyuUI.SetAnchored(_dragHandle, new Vector2(0.5f, 1f), new Vector2(0.5f, 1f),
                new Vector2(-58f, -20f), new Vector2(58f, -8f));
            var handleImage = _dragHandle.gameObject.AddComponent<Image>();
            handleImage.sprite = QiyuUI.RoundedSprite(12,
                new Color(1f, 1f, 1f, 0.13f), new Color(1f, 1f, 1f, 0.055f),
                new Color(1f, 1f, 1f, 0.22f), new Color(1f, 1f, 1f, 0.06f), 1.1f);
            handleImage.type = Image.Type.Sliced;
            handleImage.raycastTarget = true;
            var label = QiyuUI.Label(_dragHandle, "Glyph", "•••", 16,
                QiyuUI.TextTertiary, TextAnchor.MiddleCenter, true, false);
            QiyuUI.Stretch(label.rectTransform);
            var drag = _dragHandle.gameObject.AddComponent<QiyuPanelDragHandle>();
            drag.Initialize(this);
        }

        private void TogglePanelMode()
        {
            QiyuSettings.PanelMode = QiyuSettings.PanelMode ==
                                     (int)QiyuPanelMode.Fixed6DoF
                ? (int)QiyuPanelMode.Motion3DoF
                : (int)QiyuPanelMode.Fixed6DoF;
            ApplyPanelMode();
        }

        private void ApplyPanelMode()
        {
            var fixedMode = QiyuSettings.PanelMode == (int)QiyuPanelMode.Fixed6DoF;
            _modeButton?.SetLabel(fixedMode ? "固定 6DoF" : "运动 3DoF");
            if (_dragHandle != null)
            {
                _dragHandle.gameObject.SetActive(fixedMode);
            }
            if (!fixedMode)
            {
                Recenter();
            }
        }

        public void BeginPanelDrag(PointerEventData eventData)
        {
            if (_canvasRect == null ||
                QiyuSettings.PanelMode != (int)QiyuPanelMode.Fixed6DoF)
            {
                return;
            }
            _dragging = true;
            _dragStartCanvasPosition = _canvasRect.position;
            _dragPlaneNormal = -_canvasRect.forward;
            var ray = GetPointerRay(eventData);
            var plane = new Plane(_dragPlaneNormal, _canvasRect.position);
            _dragStartHitPoint = plane.Raycast(ray, out var enter)
                ? ray.GetPoint(enter)
                : _canvasRect.position;
        }

        public void DragPanel(PointerEventData eventData)
        {
            if (!_dragging || _canvasRect == null)
            {
                return;
            }
            var ray = GetPointerRay(eventData);
            var plane = new Plane(_dragPlaneNormal, _dragStartCanvasPosition);
            if (!plane.Raycast(ray, out var enter))
            {
                return;
            }
            var newHit = ray.GetPoint(enter);
            var newPosition = _dragStartCanvasPosition + (newHit - _dragStartHitPoint);
            if (followTarget != null)
            {
                var head = followTarget.position;
                var toPanel = newPosition - head;
                var distance = toPanel.magnitude;
                if (distance < 0.6f)
                {
                    newPosition = head + toPanel.normalized * 0.6f;
                }
                else if (distance > 5f)
                {
                    newPosition = head + toPanel.normalized * 5f;
                }
            }
            _canvasRect.position = newPosition;
        }

        public void EndPanelDrag(PointerEventData eventData)
        {
            _dragging = false;
        }

        private static Ray GetPointerRay(PointerEventData eventData)
        {
            if (eventData is OVRPointerEventData vrData &&
                vrData.worldSpaceRay.direction.sqrMagnitude > 0.0001f)
            {
                return vrData.worldSpaceRay;
            }
            var camera = eventData.pressEventCamera ?? Camera.main;
            if (camera != null)
            {
                return camera.ScreenPointToRay(eventData.position);
            }
            return new Ray(Vector3.zero, Vector3.forward);
        }

        private void ShowTab(string tab)
        {
            _activeTab = tab;
            foreach (var kv in _tabButtons)
            {
                kv.Value.SetActive(kv.Key == tab);
            }
            if (_keyboard != null)
            {
                _keyboard.Hide();
            }
            foreach (Transform child in _content)
            {
                Destroy(child.gameObject);
            }
            ResetPanelReferences();
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

        private void ResetPanelReferences()
        {
            _homeMruk = null;
            _homeReply = null;
            _homeSystem = null;
            _perceptionText = null;
            _navText = null;
            _objectText = null;
            _brainText = null;
            _debugText = null;
            _chatHistory = null;
            _avatarStatus = null;
            _avatarIntentText = null;
            _avatarPreviewText = null;
            _chatInput = null;
            _avatarUrlInput = null;
            _debugWorldText = null;
            _roomChip = null;
            _anchorChip = null;
            _objectChip = null;
        }

        // ---------------- 首页 ----------------

        private void BuildHome()
        {
            var hero = QiyuUI.Card(_content, "Hero", true, QiyuUI.RadiusCard, 32, 24);
            QiyuUI.CardHeader(hero.transform, "欢迎回来",
                "栖语正在你的真实房间里待命", "运行中", QiyuUI.Success);

            var chips = QiyuUI.HBox(hero.transform, "Stats", 16f);
            QiyuUI.Layout(chips.gameObject, 96f);
            _roomChip = QiyuUI.StatChip(chips, "RoomChip", "房间", "-", QiyuUI.Accent);
            _anchorChip = QiyuUI.StatChip(chips, "AnchorChip", "锚点", "-", QiyuUI.Success);
            _objectChip = QiyuUI.StatChip(chips, "ObjectChip", "识别物体", "-", QiyuUI.AccentWarm);

            var row1 = QiyuUI.HBox(hero.transform, "Actions1", 16f);
            QiyuUI.Layout(row1.gameObject, 78f);
            QiyuUI.Button(row1, "Hello", "打个招呼\n你好，你在吗？",
                () => webSocketClient?.SendUserTextAsync("你好，你在吗？"),
                QiyuButtonVariant.Primary, 19, 74);
            QiyuUI.Button(row1, "Vision", "看看桌子\n桌上有什么？",
                () => webSocketClient?.SendUserTextAsync("你能看到桌子上有什么吗？"),
                QiyuButtonVariant.Glass, 19, 74);
            var row2 = QiyuUI.HBox(hero.transform, "Actions2", 16f);
            QiyuUI.Layout(row2.gameObject, 78f);
            QiyuUI.Button(row2, "Capture", "抓帧识别\n杯子 / 手机 / 小物体",
                () => frameSource?.CaptureAndSend("桌子上有什么"),
                QiyuButtonVariant.Accent, 19, 74);
            QiyuUI.Button(row2, "Barge", "打断说话\n立即停止 TTS",
                () =>
                {
                    ttsPlayer?.StopPlayback(true);
                    webSocketClient?.SendBargeInAsync("ui_button");
                }, QiyuButtonVariant.Danger, 19, 74);

            var reply = QiyuUI.Card(_content, "Reply", true, QiyuUI.RadiusCard, 32, 18);
            QiyuUI.CardHeader(reply.transform, "最近回复", "语音与文字对话结果");
            _homeReply = BodyLabel(reply.transform, "Text", 22, QiyuUI.TextPrimary, 110);

            var status = QiyuUI.Card(_content, "System", false, QiyuUI.RadiusCard, 32, 18);
            QiyuUI.CardHeader(status.transform, "系统状态", "MRUK / 连接 / 语音");
            _homeMruk = BodyLabel(status.transform, "Mruk", 20, QiyuUI.TextSecondary, 96);
            QiyuUI.Divider(status.transform);
            _homeSystem = BodyLabel(status.transform, "SystemInfo", 19,
                QiyuUI.TextSecondary, 110);
        }

        private void RefreshHome()
        {
            var room = sceneSummary != null ? sceneSummary.CurrentRoom : null;
            SetChipValue(_roomChip, room == null ? "-" : "已加载");
            SetChipValue(_anchorChip, room == null ? "-" : room.Anchors.Count.ToString());
            SetChipValue(_objectChip,
                objectDetector != null && objectDetector.LastObjects != null
                    ? objectDetector.LastObjects.Count.ToString()
                    : "0");

            if (_homeMruk != null)
            {
                _homeMruk.text = room == null
                    ? "MRUK：尚未加载房间。请环视四周完成空间扫描。"
                    : $"MRUK：{room.name}\n墙 {room.WallAnchors.Count}   ·   " +
                      $"地面 {room.FloorAnchors.Count}   ·   " +
                      $"天花板 {room.CeilingAnchors.Count}   ·   " +
                      $"锚点 {room.Anchors.Count}";
            }
            if (_homeReply != null)
            {
                _homeReply.text = string.IsNullOrEmpty(_lastSpeech)
                    ? "还没有回复。戴上头显直接说话，或点上面的快捷操作。"
                    : _lastSpeech;
            }
            if (_homeSystem != null)
            {
                var connected = webSocketClient != null && webSocketClient.IsConnected;
                var handshake = webSocketClient != null && webSocketClient.HandshakeDone;
                var mic = microphone != null && microphone.IsCapturing;
                var tts = ttsPlayer != null && ttsPlayer.IsPlaying;
                _homeSystem.text =
                    $"Gateway   {(connected ? (handshake ? "已连接" : "握手中") : "未连接")}\n" +
                    $"麦克风    {(mic ? "采集中" : "关闭")}   ·   " +
                    $"TTS {(tts ? "播放中" : "空闲")}\n" +
                    $"渲染      {QiyuSettings.RenderScale:0.00}x   ·   " +
                    $"{_smoothedFps:F0} FPS";
            }
        }

        // ---------------- 对话 ----------------

        private void BuildChat()
        {
            var card = QiyuUI.Card(_content, "Chat", true, QiyuUI.RadiusCard, 32, 20);
            QiyuUI.CardHeader(card.transform, "对话", "语音优先；文字输入用于调试与精确指令",
                "实时", QiyuUI.Success);
            _chatHistory = BodyLabel(card.transform, "History", 21, QiyuUI.TextPrimary, 420);
            _chatHistory.textWrappingMode = TextWrappingModes.Normal;

            var inputRow = QiyuUI.HBox(card.transform, "InputRow", 12f);
            QiyuUI.Layout(inputRow.gameObject, 60f);
            _chatInput = QiyuUI.Input(inputRow, "ChatInput", "输入文字，或直接说话…", "",
                _ => { }, 58);
            var send = QiyuUI.Button(inputRow, "Send", "发送", SendChatInput,
                QiyuButtonVariant.Primary, 19, 58);
            QiyuUI.Layout(send.gameObject, 58f, 58f, 0f);
            var sendLayout = send.GetComponent<LayoutElement>();
            sendLayout.preferredWidth = 150f;
            sendLayout.minWidth = 150f;
            sendLayout.flexibleWidth = 0f;

            var actions = QiyuUI.HBox(card.transform, "Actions", 12f);
            QiyuUI.Layout(actions.gameObject, 58f);
            QiyuUI.Button(actions, "Mic", "麦克风常开 · VAD 自动断句", null,
                QiyuButtonVariant.Ghost, 18, 58);
            QiyuUI.Button(actions, "Clear", "清空对话显示", () =>
            {
                _chatLines.Clear();
                RefreshChat();
            }, QiyuButtonVariant.Glass, 18, 58);

            var tips = QiyuUI.Card(_content, "Tips", false, QiyuUI.RadiusCard, 28, 14);
            QiyuUI.CardHeader(tips.transform, "对话技巧", null);
            BodyLabel(tips.transform, "Text", 19, QiyuUI.TextSecondary, 96).text =
                "• 直接说话即可，本地 VAD 会自动判断一句话的开始和结束。\n" +
                "• TTS 播放时继续说话会触发 barge-in，栖语会立刻停下来听你说。\n" +
                "• 复杂任务由后端自动升级到 MainBrain，Quest 端不会另起一套 Agent。";
        }

        private void SendChatInput()
        {
            if (_chatInput == null || webSocketClient == null)
            {
                return;
            }
            var text = _chatInput.Input.text;
            if (string.IsNullOrWhiteSpace(text))
            {
                return;
            }
            AddChat("我", text);
            _ = webSocketClient.SendUserTextAsync(text);
            _chatInput.Input.text = "";
            _chatInput.Input.caretPosition = 0;
            RefreshChat();
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
            _chatHistory.text = builder.Length == 0
                ? "还没有对话记录。\n戴上头显直接说话，或在输入框里输入一句话。"
                : builder.ToString();
        }

        // ---------------- 环境 ----------------

        private void BuildPerception()
        {
            var roomCard = QiyuUI.Card(_content, "Room", true, QiyuUI.RadiusCard, 32, 20);
            QiyuUI.CardHeader(roomCard.transform, "房间理解",
                "MRUK / Scene API 语义（不需要 YOLO 也能理解墙、地面、桌椅）",
                "Scene", QiyuUI.Accent);
            var stats = QiyuUI.HBox(roomCard.transform, "Stats", 12f);
            QiyuUI.Layout(stats.gameObject, 96f);
            _roomChip = QiyuUI.StatChip(stats, "Walls", "墙", "-", QiyuUI.Accent);
            _anchorChip = QiyuUI.StatChip(stats, "Floors", "地面", "-", QiyuUI.Success);
            _objectChip = QiyuUI.StatChip(stats, "Anchors", "锚点", "-", QiyuUI.AccentWarm);
            _perceptionText = BodyLabel(roomCard.transform, "Info", 20,
                QiyuUI.TextSecondary, 190);

            var navCard = QiyuUI.Card(_content, "Nav", false, QiyuUI.RadiusCard, 32, 18);
            QiyuUI.CardHeader(navCard.transform, "导航网格", "运行时 NavMesh，用于自然走动与避障");
            _navText = BodyLabel(navCard.transform, "Info", 20, QiyuUI.TextSecondary, 96);
            var navRow = QiyuUI.HBox(navCard.transform, "Actions", 12f);
            QiyuUI.Layout(navRow.gameObject, 58f);
            QiyuUI.Button(navRow, "Rescan", "重新扫描房间", () =>
            {
                _ = MRUK.Instance?.LoadSceneFromDevice();
            }, QiyuButtonVariant.Glass, 19, 58);
            QiyuUI.Button(navRow, "Rebuild", "重建 NavMesh", () =>
            {
                navMeshBuilder?.Build();
            }, QiyuButtonVariant.Primary, 19, 58);

            var objectCard = QiyuUI.Card(_content, "Objects", false, QiyuUI.RadiusCard, 32, 18);
            QiyuUI.CardHeader(objectCard.transform, "物体识别",
                "Passthrough Camera → 视觉模型 → 3D 空间投影", "按需", QiyuUI.AccentWarm);
            _objectText = BodyLabel(objectCard.transform, "Info", 20,
                QiyuUI.TextSecondary, 150);
            var objectRow = QiyuUI.HBox(objectCard.transform, "Actions", 12f);
            QiyuUI.Layout(objectRow.gameObject, 58f);
            QiyuUI.Button(objectRow, "Detect", "抓帧识别小物体",
                () => frameSource?.CaptureAndSend("识别房间里的杯子、手机等小物体"),
                QiyuButtonVariant.Accent, 19, 58);
            QiyuUI.Button(objectRow, "Depth", "深度状态",
                () => ShowTab("调试"), QiyuButtonVariant.Glass, 19, 58);
        }

        private void RefreshPerception()
        {
            var room = sceneSummary != null ? sceneSummary.CurrentRoom : null;
            if (_perceptionText != null)
            {
                if (room == null)
                {
                    _perceptionText.text = "尚未加载房间。\n环视四周并等待空间扫描完成后，MRUK 会给出语义锚点。";
                }
                else
                {
                    var builder = new StringBuilder();
                    builder.AppendLine($"房间：{room.name}");
                    builder.AppendLine($"锚点总数 {room.Anchors.Count}   ·   " +
                                       $"墙 {room.WallAnchors.Count}   ·   " +
                                       $"地面 {room.FloorAnchors.Count}   ·   " +
                                       $"天花板 {room.CeilingAnchors.Count}");
                    var counts = new Dictionary<string, int>();
                    foreach (var anchor in room.Anchors)
                    {
                        var label = anchor.Label.ToString();
                        counts[label] = counts.TryGetValue(label, out var c) ? c + 1 : 1;
                    }
                    builder.Append("语义物体：");
                    var any = false;
                    foreach (var kv in counts)
                    {
                        if (kv.Key.Contains("WALL") || kv.Key.Contains("FLOOR") ||
                            kv.Key.Contains("CEILING"))
                        {
                            continue;
                        }
                        builder.Append($"{kv.Key} {kv.Value}   ");
                        any = true;
                    }
                    if (!any)
                    {
                        builder.Append("暂无桌椅等语义锚点");
                    }
                    _perceptionText.text = builder.ToString();
                }
            }
            if (_roomChip != null)
            {
                SetChipValue(_roomChip, room == null ? "-" : room.WallAnchors.Count.ToString());
            }
            if (_anchorChip != null)
            {
                SetChipValue(_anchorChip, room == null ? "-" : room.FloorAnchors.Count.ToString());
            }
            if (_objectChip != null)
            {
                SetChipValue(_objectChip, room == null ? "-" : room.Anchors.Count.ToString());
            }
            if (_navText != null)
            {
                _navText.text = navMeshBuilder != null && navMeshBuilder.Generated
                    ? $"已生成 v{navMeshBuilder.Version}\n" +
                      $"可行走面积 {navMeshBuilder.WalkableAreaM2:F2} m²\n" +
                      "角色可沿 NavMesh 自然走动、绕开真实家具。"
                    : "尚未生成。加载房间后会自动根据 MRUK 地面/家具生成。";
            }
            if (_objectText != null)
            {
                var objects = objectDetector != null ? objectDetector.LastObjects : null;
                if (objects == null || objects.Count == 0)
                {
                    _objectText.text = "暂无识别结果。\n点“抓帧识别小物体”把当前画面交给视觉模型。";
                }
                else
                {
                    var builder = new StringBuilder();
                    foreach (var item in objects)
                    {
                        builder.AppendLine($"{item.label}   {item.confidence:P0}   " +
                                           $"({item.worldPosition.x:F1}, " +
                                           $"{item.worldPosition.y:F1}, " +
                                           $"{item.worldPosition.z:F1})");
                    }
                    _objectText.text = builder.ToString();
                }
            }
        }

        // ---------------- 角色 ----------------

        private void BuildAvatar()
        {
            var preview = QiyuUI.Card(_content, "AvatarPreview", true,
                QiyuUI.RadiusCard, 32, 20);
            QiyuUI.CardHeader(preview.transform, "角色", "VRM / GLB / Live2D 与未来角色系统",
                "Avatar", QiyuUI.Accent);

            var frame = QiyuUI.Panel(preview.transform, "PreviewFrame", false, 24, 0.7f);
            QiyuUI.Layout(frame.gameObject, 300f);
            var frameGlow = QiyuUI.CreateRect(frame.rectTransform, "Glow");
            QiyuUI.Stretch(frameGlow, 40f);
            var glowImage = frameGlow.gameObject.AddComponent<Image>();
            glowImage.sprite = QiyuUI.RadialSprite(256,
                new Color(0.39f, 0.82f, 1f, 0.16f), new Color(0.39f, 0.82f, 1f, 0f));
            glowImage.raycastTarget = false;
            frameGlow.gameObject.AddComponent<LayoutElement>().ignoreLayout = true;
            _avatarPreviewText = QiyuUI.Label(frame.rectTransform, "Placeholder",
                "尚未导入模型\n导入后角色会站在真实房间里", 22, QiyuUI.TextTertiary,
                TextAnchor.MiddleCenter);
            QiyuUI.Stretch(_avatarPreviewText.rectTransform, 24f);
            _avatarPreviewText.gameObject.AddComponent<LayoutElement>().ignoreLayout = true;

            _avatarStatus = BodyLabel(preview.transform, "Status", 20,
                QiyuUI.TextSecondary, 120);

            var import = QiyuUI.Card(_content, "AvatarImport", false,
                QiyuUI.RadiusCard, 32, 18);
            QiyuUI.CardHeader(import.transform, "模型导入",
                "支持本地 StreamingAssets、URL 下载、后端下发");
            _avatarUrlInput = QiyuUI.Input(import.transform, "AvatarUrl",
                "VRM / GLB 地址或本地路径", QiyuSettings.AvatarUrl,
                value => QiyuSettings.AvatarUrl = value);
            var importRow = QiyuUI.HBox(import.transform, "ImportRow", 12f);
            QiyuUI.Layout(importRow.gameObject, 58f);
            QiyuUI.Button(importRow, "Import", "导入模型", () =>
            {
                GetComponent<QuestAvatarModelImporter>()?.ImportFromConfiguredSource();
            }, QiyuButtonVariant.Primary, 19, 58);
            QiyuUI.Button(importRow, "Remove", "移除模型", () =>
            {
                GetComponent<QuestAvatarModelImporter>()?.RemoveModel();
            }, QiyuButtonVariant.Danger, 19, 58);
            QiyuUI.Slider(import.transform, "Scale", "模型缩放", 0.3f, 2.5f,
                QiyuSettings.AvatarScale, value => QiyuSettings.AvatarScale = value, "x");
            QiyuUI.Slider(import.transform, "Height", "高度偏移", -1f, 1f,
                QiyuSettings.AvatarHeight, value => QiyuSettings.AvatarHeight = value, "m");
            QiyuUI.Slider(import.transform, "Rotation", "朝向修正", -180f, 180f,
                QiyuSettings.AvatarRotation, value => QiyuSettings.AvatarRotation = value, "°");

            var intent = QiyuUI.Card(_content, "AvatarIntent", false,
                QiyuUI.RadiusCard, 32, 18);
            QiyuUI.CardHeader(intent.transform, "表情与动作",
                "由后端 AvatarIntent 驱动，LLM 不直接控制骨骼");
            _avatarIntentText = BodyLabel(intent.transform, "Info", 20,
                QiyuUI.TextSecondary, 110);
            var intentRow = QiyuUI.HBox(intent.transform, "Actions", 12f);
            QiyuUI.Layout(intentRow.gameObject, 58f);
            QiyuUI.Button(intentRow, "Smile", "对我笑一下",
                () => webSocketClient?.SendUserTextAsync("对我笑一下"),
                QiyuButtonVariant.Glass, 18, 58);
            QiyuUI.Button(intentRow, "Wave", "挥挥手",
                () => webSocketClient?.SendUserTextAsync("向我挥挥手"),
                QiyuButtonVariant.Glass, 18, 58);
            QiyuUI.Button(intentRow, "Look", "看着我",
                () => webSocketClient?.SendUserTextAsync("看着我"),
                QiyuButtonVariant.Primary, 18, 58);
        }

        private void RefreshAvatar()
        {
            var importer = GetComponent<QuestAvatarModelImporter>();
            var loaded = importer != null && importer.IsModelLoaded;
            if (_avatarPreviewText != null)
            {
                _avatarPreviewText.text = loaded
                    ? $"已加载\n{importer.CurrentModelName}"
                    : "尚未导入模型\n导入后角色会站在真实房间里";
                _avatarPreviewText.color = loaded ? QiyuUI.TextPrimary : QiyuUI.TextTertiary;
            }
            if (_avatarStatus != null)
            {
                var builder = new StringBuilder();
                builder.AppendLine(loaded
                    ? $"当前模型：{importer.CurrentModelName}"
                    : "当前没有可见角色，只有空间与对话能力。");
                builder.AppendLine($"表情 {avatarRouter?.CurrentEmotion ?? "-"}   ·   " +
                                   $"动作 {avatarRouter?.CurrentAction ?? "-"}   ·   " +
                                   $"说话 {(avatarRouter != null && avatarRouter.IsSpeaking ? "是" : "否")}");
                builder.Append("支持格式：VRM 1.0 / VRM 0.x / GLB（UniVRM / glTFast）");
                _avatarStatus.text = builder.ToString();
            }
            if (_avatarIntentText != null)
            {
                _avatarIntentText.text =
                    $"最近 AvatarIntent：{(_lastAvatarIntent.Length > 0 ? _lastAvatarIntent : "-")}\n" +
                    $"最近 SpatialAction：{(_lastSpatialAction.Length > 0 ? _lastSpatialAction : "-")}";
            }
        }

        // ---------------- 设置 ----------------

        private void BuildSettings()
        {
            var conn = QiyuUI.Card(_content, "Connection", true, QiyuUI.RadiusCard, 32, 18);
            QiyuUI.CardHeader(conn.transform, "连接", "Qiyu Gateway WebSocket",
                "v1", QiyuUI.Success);
            QiyuUI.Input(conn.transform, "Gateway", "Gateway WebSocket 地址",
                QiyuSettings.GatewayUrl, value => QiyuSettings.GatewayUrl = value);
            var ids = QiyuUI.HBox(conn.transform, "Ids", 12f);
            QiyuUI.Layout(ids.gameObject, 58f);
            QiyuUI.Input(ids, "UserId", "user_id", QiyuSettings.UserId,
                value => QiyuSettings.UserId = value);
            QiyuUI.Input(ids, "CharId", "char_id", QiyuSettings.CharId,
                value => QiyuSettings.CharId = value);
            QiyuUI.Toggle(conn.transform, "AutoConnect", "启动时自动连接",
                QiyuSettings.AutoConnect, value => QiyuSettings.AutoConnect = value);
            QiyuUI.Toggle(conn.transform, "FixedMode",
                "固定屏幕模式 6DoF（关闭 = 运动模式 3DoF 跟随头部）",
                QiyuSettings.PanelMode == (int)QiyuPanelMode.Fixed6DoF, value =>
                {
                    QiyuSettings.PanelMode = value
                        ? (int)QiyuPanelMode.Fixed6DoF
                        : (int)QiyuPanelMode.Motion3DoF;
                    ApplyPanelMode();
                });
            var connRow = QiyuUI.HBox(conn.transform, "Actions", 12f);
            QiyuUI.Layout(connRow.gameObject, 58f);
            QiyuUI.Button(connRow, "Recenter", "重新居中", Recenter,
                QiyuButtonVariant.Glass, 18, 58);
            QiyuUI.Button(connRow, "Apply", "应用并重连", () =>
            {
                webSocketClient?.SetServerUrl(QiyuSettings.GatewayUrl);
            }, QiyuButtonVariant.Primary, 18, 58);
            QiyuUI.Button(connRow, "Ping", "心跳测试", () =>
            {
                webSocketClient?.SendAsync(new QuestEnvelope("client.echo",
                    new JObject { ["probe"] = "ui" }, webSocketClient.SessionId));
            }, QiyuButtonVariant.Glass, 18, 58);

            var voice = QiyuUI.Card(_content, "Voice", false, QiyuUI.RadiusCard, 32, 18);
            QiyuUI.CardHeader(voice.transform, "语音", "麦克风 / VAD / TTS");
            QiyuUI.Toggle(voice.transform, "Tts", "启用服务端 TTS",
                QiyuSettings.TtsEnabled, value =>
                {
                    QiyuSettings.TtsEnabled = value;
                    webSocketClient?.SendAsync(new QuestEnvelope("client.tts_config",
                        new JObject { ["enabled"] = value }, webSocketClient.SessionId));
                });
            QiyuUI.Slider(voice.transform, "Vad", "麦克风灵敏度（VAD 阈值）",
                0.005f, 0.2f, QiyuSettings.VadThreshold, value =>
                {
                    QiyuSettings.VadThreshold = value;
                    microphone?.SetVadThreshold(value);
                });
            QiyuUI.Slider(voice.transform, "Gain", "麦克风增益", 0.2f, 4f,
                QiyuSettings.MicGain, value =>
                {
                    QiyuSettings.MicGain = value;
                    microphone?.SetGain(value);
                });

            var render = QiyuUI.Card(_content, "Render", false, QiyuUI.RadiusCard, 32, 18);
            QiyuUI.CardHeader(render.transform, "渲染与清晰度",
                "抗锯齿 / 渲染倍率 / 注视点渲染");
            QiyuUI.Slider(render.transform, "RenderScale", "渲染倍率（越高越清晰，越耗性能）",
                1f, 1.4f, QiyuSettings.RenderScale, value =>
                {
                    QiyuSettings.RenderScale = value;
                    _renderQuality?.ApplyFromSettings();
                }, "x");
            QiyuUI.Toggle(render.transform, "Foveation", "低强度注视点渲染（关闭最清晰）",
                QiyuSettings.LowFoveation, value =>
                {
                    QiyuSettings.LowFoveation = value;
                    _renderQuality?.ApplyFromSettings();
                });
            QiyuUI.Slider(render.transform, "PanelDistance", "面板距离", 1.2f, 3f,
                QiyuSettings.PanelDistance, value =>
                {
                    QiyuSettings.PanelDistance = value;
                    Recenter();
                }, "m");

            var conversation = QiyuUI.Card(_content, "Conversation", false,
                QiyuUI.RadiusCard, 32, 18);
            QiyuUI.CardHeader(conversation.transform, "对话", "回复风格与声音");
            QiyuUI.Slider(conversation.transform, "Temp", "回复温度", 0f, 1.5f,
                QiyuSettings.Temperature, value => QiyuSettings.Temperature = value);
            QiyuUI.Input(conversation.transform, "VoiceId", "voice_id（留空 = 后端默认）",
                QiyuSettings.Voice, value => QiyuSettings.Voice = value);

            var advanced = QiyuUI.Card(_content, "Advanced", false,
                QiyuUI.RadiusCard, 32, 18);
            QiyuUI.CardHeader(advanced.transform, "高级", "诊断与重置");
            var advancedRow = QiyuUI.HBox(advanced.transform, "Actions", 12f);
            QiyuUI.Layout(advancedRow.gameObject, 58f);
            QiyuUI.Button(advancedRow, "Reset", "恢复默认设置", () =>
            {
                QiyuSettings.ResetAll();
                ShowTab("设置");
            }, QiyuButtonVariant.Danger, 18, 58);
            QiyuUI.Button(advancedRow, "Debug", "打开调试页", () => ShowTab("调试"),
                QiyuButtonVariant.Glass, 18, 58);
        }

        // ---------------- 模型决策 ----------------

        private void BuildBrain()
        {
            var pipeline = QiyuUI.Card(_content, "Pipeline", true, QiyuUI.RadiusCard, 32, 20);
            QiyuUI.CardHeader(pipeline.transform, "模型决策链路",
                "Quest 负责实时空间计算与执行，LLM 只输出高层意图",
                "Qiyu 架构", QiyuUI.Accent);
            var line1 = QiyuUI.HBox(pipeline.transform, "Line1", 8f);
            QiyuUI.Layout(line1.gameObject, 44f);
            FlowChip(line1, "Quest MR", QiyuUI.Accent);
            FlowArrow(line1);
            FlowChip(line1, "Gateway", QiyuUI.Success);
            FlowArrow(line1);
            FlowChip(line1, "MessageGateway", QiyuUI.Success);
            FlowArrow(line1);
            FlowChip(line1, "BrainPipeline", QiyuUI.Success);
            var line2 = QiyuUI.HBox(pipeline.transform, "Line2", 8f);
            QiyuUI.Layout(line2.gameObject, 44f);
            FlowChip(line2, "MiniMind-O", QiyuUI.Accent);
            FlowArrow(line2);
            FlowChip(line2, "BrainDecision", QiyuUI.AccentWarm);
            FlowArrow(line2);
            FlowChip(line2, "MainBrain（按需）", QiyuUI.Warning);
            FlowArrow(line2);
            FlowChip(line2, "ResponseEvent", QiyuUI.Success);
            FlowArrow(line2);
            FlowChip(line2, "Quest 执行", QiyuUI.Accent);
            BodyLabel(pipeline.transform, "Note", 19, QiyuUI.TextSecondary, 86).text =
                "MiniMind-O 与 MainBrain 仍由现有 Qiyu 后端托管，Quest 只是新增 WebSocket 入口。\n" +
                "AvatarIntent / SpatialAction 是唯一的下行接口，骨骼和路径永远由本地执行层决定。";

            var status = QiyuUI.Card(_content, "BrainStatus", false,
                QiyuUI.RadiusCard, 32, 18);
            QiyuUI.CardHeader(status.transform, "运行状态", "最近事件与意图");
            _brainText = BodyLabel(status.transform, "Info", 20, QiyuUI.TextSecondary, 180);
            var brainRow = QiyuUI.HBox(status.transform, "Actions", 12f);
            QiyuUI.Layout(brainRow.gameObject, 58f);
            QiyuUI.Button(brainRow, "Test", "测试完整主脑链路", () =>
                webSocketClient?.SendUserTextAsync("测试一下完整主脑链路"),
                QiyuButtonVariant.Primary, 18, 58);
            QiyuUI.Button(brainRow, "MiniMind", "接入 MiniMind-O（主体完工后）", null,
                QiyuButtonVariant.Ghost, 18, 58);
        }

        private void RefreshBrain()
        {
            if (_brainText == null)
            {
                return;
            }
            var connected = webSocketClient != null && webSocketClient.IsConnected;
            var handshake = webSocketClient != null && webSocketClient.HandshakeDone;
            _brainText.text =
                $"Gateway：{(connected ? (handshake ? "已连接" : "握手中") : "未连接")}\n" +
                $"最近事件：{(_lastEvent.Length > 0 ? _lastEvent : "-")}\n" +
                $"AvatarIntent：{(_lastAvatarIntent.Length > 0 ? _lastAvatarIntent : "-")}\n" +
                $"SpatialAction：{(_lastSpatialAction.Length > 0 ? _lastSpatialAction : "-")}";
        }

        // ---------------- 调试 ----------------

        private void BuildDebug()
        {
            var diag = QiyuUI.Card(_content, "Diagnostics", true, QiyuUI.RadiusCard, 32, 18);
            QiyuUI.CardHeader(diag.transform, "运行诊断", "Passthrough / XR / 连接",
                "Live", QiyuUI.Warning);
            _debugText = BodyLabel(diag.transform, "Info", 18, QiyuUI.TextSecondary, 360);
            _debugText.textWrappingMode = TextWrappingModes.Normal;

            var world = QiyuUI.Card(_content, "WorldState", false,
                QiyuUI.RadiusCard, 32, 18);
            QiyuUI.CardHeader(world.transform, "WorldState", "最近一帧上报内容");
            var worldText = BodyLabel(world.transform, "Json", 16, QiyuUI.TextTertiary, 260);
            worldText.textWrappingMode = TextWrappingModes.Normal;
            var worldRow = QiyuUI.HBox(world.transform, "Actions", 12f);
            QiyuUI.Layout(worldRow.gameObject, 58f);
            QiyuUI.Button(worldRow, "Send", "立即上报 WorldState", () =>
            {
                if (worldStatePublisher != null && worldStatePublisher.LatestPayload != null)
                {
                    webSocketClient?.SendWorldStateAsync(worldStatePublisher.LatestPayload);
                }
            }, QiyuButtonVariant.Primary, 18, 58);
            QiyuUI.Button(worldRow, "Reconnect", "重连 Gateway", () =>
                webSocketClient?.ConnectAsync(), QiyuButtonVariant.Glass, 18, 58);
            _debugWorldText = worldText;
        }

        private TMP_Text _debugWorldText;

        private void RefreshDebug()
        {
            if (_debugText != null)
            {
                var builder = new StringBuilder();
                builder.AppendLine("Passthrough");
                builder.AppendLine(PassthroughDiagnostics.LastSnapshot);
                builder.AppendLine();
                builder.AppendLine("连接");
                builder.AppendLine($"gateway：{webSocketClient?.ServerUrl}");
                builder.AppendLine($"session：{webSocketClient?.SessionId}");
                builder.AppendLine($"connected：{webSocketClient?.IsConnected}   " +
                                   $"handshake：{webSocketClient?.HandshakeDone}");
                builder.AppendLine();
                builder.AppendLine("性能");
                builder.AppendLine($"FPS {_smoothedFps:F0}   ·   " +
                                   $"渲染倍率 {QiyuSettings.RenderScale:0.00}x   ·   " +
                                   $"MSAA 4x");
                _debugText.text = builder.ToString();
            }
            if (_debugWorldText != null)
            {
                var payload = worldStatePublisher != null
                    ? worldStatePublisher.LatestPayload
                    : null;
                if (payload == null)
                {
                    _debugWorldText.text = "（尚未生成 WorldState）";
                }
                else
                {
                    var text = payload.ToString(Newtonsoft.Json.Formatting.None);
                    _debugWorldText.text = text.Length > 1200
                        ? text.Substring(0, 1200) + "…"
                        : text;
                }
            }
        }

        // ---------------- 小工具 ----------------

        private static TMP_Text BodyLabel(Transform parent, string name, int size,
                                          Color color, float minHeight)
        {
            var label = QiyuUI.Label(parent, name, "", size, color, TextAnchor.UpperLeft);
            QiyuUI.Layout(label.gameObject, minHeight);
            return label;
        }

        private static void SetChipValue(Image chip, string value)
        {
            if (chip == null)
            {
                return;
            }
            var label = chip.transform.Find("Value")?.GetComponent<TMP_Text>();
            if (label != null)
            {
                label.text = value ?? "-";
            }
        }

        private static void FlowChip(Transform parent, string text, Color color)
        {
            var pill = QiyuUI.Pill(parent, "Chip_" + text, text, color, 15, 34f);
            var layout = pill.GetComponent<LayoutElement>();
            layout.flexibleWidth = 1f;
        }

        private static void FlowArrow(Transform parent)
        {
            var label = QiyuUI.Label(parent, "Arrow", "→", 20, QiyuUI.TextTertiary,
                TextAnchor.MiddleCenter, true, false);
            QiyuUI.Layout(label.gameObject, 34f, 34f, 0f);
            var layout = label.GetComponent<LayoutElement>();
            layout.preferredWidth = 34f;
            layout.minWidth = 24f;
            layout.flexibleWidth = 0f;
        }
    }
}
