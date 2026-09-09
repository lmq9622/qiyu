using System;
using System.Collections.Generic;
using TMPro;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.UI;

namespace Qiyu.Quest.UI
{
    public interface IQiyuUIInteractable
    {
        RectTransform Rect { get; }
        void SetHover(bool hover);
        void Activate();
    }

    /// <summary>液体玻璃按钮：弹性 hover / 按下回弹 / 高光增强。</summary>
    public class QiyuUIButton : MonoBehaviour, IQiyuUIInteractable,
        IPointerEnterHandler, IPointerExitHandler, IPointerDownHandler,
        IPointerUpHandler, IPointerClickHandler
    {
        private Image _root;
        private Image _body;
        private Image _extrusion;
        private Image _gloss;
        private Image _hoverOverlay;
        private TMP_Text _label;
        private Action _onClick;
        private float _scale = 1f;
        private float _scaleVelocity;
        private float _hoverAlpha;
        private float _hoverTarget;
        private float _extrusionOffset = -5f;
        private float _extrusionVelocity;
        private bool _hover;

        public RectTransform Rect => (RectTransform)transform;

        public void Configure(Image root, Image body, Image extrusion, Image gloss,
                              TMP_Text label, Action onClick, int height)
        {
            _root = root;
            _body = body;
            _extrusion = extrusion;
            _gloss = gloss;
            _label = label;
            _onClick = onClick;

            var hover = QiyuUI.CreateRect(transform, "Hover");
            QiyuUI.Stretch(hover, 1.5f);
            _hoverOverlay = hover.gameObject.AddComponent<Image>();
            _hoverOverlay.sprite = QiyuUI.RoundedSprite(
                Mathf.Min(QiyuUI.RadiusButton, Mathf.Max(8, height / 2)),
                Color.white, Color.white, 0f);
            _hoverOverlay.type = Image.Type.Sliced;
            _hoverOverlay.color = new Color(1f, 1f, 1f, 0f);
            _hoverOverlay.raycastTarget = false;
            hover.gameObject.AddComponent<LayoutElement>().ignoreLayout = true;

            QiyuGazeInteractor.Register(this);
        }

        private void OnDestroy()
        {
            QiyuGazeInteractor.Unregister(this);
        }

        public void SetHover(bool hover)
        {
            _hover = hover;
            _hoverTarget = hover ? 0.13f : 0f;
        }

        public void SetLabel(string text)
        {
            if (_label != null)
            {
                _label.text = text ?? "";
            }
        }

        private void Update()
        {
            var dt = Mathf.Max(0.0001f, Time.unscaledDeltaTime);
            var targetScale = _hover ? 1.045f : 1f;
            _scale = Mathf.SmoothDamp(_scale, targetScale, ref _scaleVelocity, 0.075f,
                Mathf.Infinity, dt);
            transform.localScale = new Vector3(_scale, _scale, 1f);

            _hoverAlpha = Mathf.SmoothDamp(_hoverAlpha, _hoverTarget, ref _hoverAlphaVelocity,
                0.06f, Mathf.Infinity, dt);
            if (_hoverOverlay != null)
            {
                _hoverOverlay.color = new Color(1f, 1f, 1f, _hoverAlpha);
            }
            if (_gloss != null)
            {
                var c = _gloss.color;
                c.a = Mathf.Lerp(1f, 1.35f, _hover ? 1f : 0f);
                _gloss.color = c;
            }
            var extrusionTarget = _hover ? -7f : -5f;
            _extrusionOffset = Mathf.SmoothDamp(_extrusionOffset, extrusionTarget,
                ref _extrusionVelocity, 0.07f, Mathf.Infinity, dt);
            if (_extrusion != null)
            {
                _extrusion.rectTransform.anchoredPosition = new Vector2(0f, _extrusionOffset);
            }
        }

        private float _hoverAlphaVelocity;

        public void Activate()
        {
            _onClick?.Invoke();
            _scale = 0.955f;
            _scaleVelocity = 0f;
            QiyuGazeInteractor.HapticPulse();
        }

        public void OnPointerEnter(PointerEventData eventData)
        {
            SetHover(true);
        }

        public void OnPointerExit(PointerEventData eventData)
        {
            SetHover(false);
        }

        public void OnPointerDown(PointerEventData eventData)
        {
            _scale = 0.965f;
            _scaleVelocity = 0f;
        }

        public void OnPointerUp(PointerEventData eventData)
        {
        }

        public void OnPointerClick(PointerEventData eventData)
        {
            Activate();
        }
    }

    /// <summary>顶部标签页：白色胶囊滑动式激活态。</summary>
    public class QiyuUITab : MonoBehaviour, IQiyuUIInteractable,
        IPointerEnterHandler, IPointerExitHandler, IPointerClickHandler
    {
        private Image _background;
        private TMP_Text _label;
        private Image _dot;
        private Action _onClick;
        private bool _active;
        private bool _hover;
        private float _backgroundAlpha;
        private float _backgroundVelocity;
        private float _scale = 1f;
        private float _scaleVelocity;

        public RectTransform Rect => (RectTransform)transform;

        public void Configure(Image background, TMP_Text label, Image dot, Action onClick)
        {
            _background = background;
            _label = label;
            _dot = dot;
            _onClick = onClick;
            ApplyImmediate();
            QiyuGazeInteractor.Register(this);
        }

        private void OnDestroy()
        {
            QiyuGazeInteractor.Unregister(this);
        }

        public void SetActive(bool active)
        {
            _active = active;
            ApplyImmediate();
        }

        public void SetHover(bool hover)
        {
            _hover = hover;
        }

        public void Activate()
        {
            _onClick?.Invoke();
            QiyuGazeInteractor.HapticPulse();
        }

        private void ApplyImmediate()
        {
            if (_label != null)
            {
                _label.color = _active ? new Color(0.04f, 0.04f, 0.05f)
                    : QiyuUI.TextOnDarkSecondary;
                _label.fontStyle = _active ? FontStyles.Bold : FontStyles.Normal;
            }
            if (_dot != null)
            {
                _dot.color = new Color(0.04f, 0.04f, 0.05f, _active ? 0.85f : 0f);
            }
            _backgroundAlpha = _active ? 0.97f : 0f;
        }

        private void Update()
        {
            var dt = Mathf.Max(0.0001f, Time.unscaledDeltaTime);
            var targetAlpha = _active ? 0.97f : (_hover ? 0.12f : 0f);
            _backgroundAlpha = Mathf.SmoothDamp(_backgroundAlpha, targetAlpha,
                ref _backgroundVelocity, 0.08f, Mathf.Infinity, dt);
            if (_background != null)
            {
                _background.color = new Color(1f, 1f, 1f, _backgroundAlpha);
            }
            if (_label != null && !_active)
            {
                _label.color = Color.Lerp(QiyuUI.TextOnDarkSecondary,
                    QiyuUI.TextOnDarkPrimary,
                    _hover ? 0.8f : 0f);
            }
            var targetScale = _hover ? 1.035f : 1f;
            _scale = Mathf.SmoothDamp(_scale, targetScale, ref _scaleVelocity, 0.075f,
                Mathf.Infinity, dt);
            transform.localScale = new Vector3(_scale, _scale, 1f);
        }

        public void OnPointerEnter(PointerEventData eventData)
        {
            SetHover(true);
        }

        public void OnPointerExit(PointerEventData eventData)
        {
            SetHover(false);
        }

        public void OnPointerClick(PointerEventData eventData)
        {
            Activate();
        }
    }

    /// <summary>液体玻璃开关。</summary>
    public class QiyuUIToggle : MonoBehaviour, IQiyuUIInteractable,
        IPointerEnterHandler, IPointerExitHandler, IPointerClickHandler
    {
        private Image _track;
        private Image _knobImage;
        private RectTransform _knob;
        private Action<bool> _onChanged;
        private bool _value;
        private bool _hover;
        private float _knobT;
        private float _knobVelocity;

        public RectTransform Rect => (RectTransform)transform;
        public bool Value => _value;

        public void Configure(Image track, Image knobImage, RectTransform knob,
                              bool initial, Action<bool> onChanged)
        {
            _track = track;
            _knobImage = knobImage;
            _knob = knob;
            _onChanged = onChanged;
            _value = initial;
            _knobT = initial ? 1f : 0f;
            Apply();
            QiyuGazeInteractor.Register(this);
        }

        private void OnDestroy()
        {
            QiyuGazeInteractor.Unregister(this);
        }

        public void SetHover(bool hover)
        {
            _hover = hover;
            if (_track != null)
            {
                _track.color = hover ? new Color(1f, 1f, 1f, 1.15f) : Color.white;
            }
        }

        public void Activate()
        {
            _value = !_value;
            Apply();
            _onChanged?.Invoke(_value);
            QiyuGazeInteractor.HapticPulse();
        }

        private void Apply()
        {
            if (_track != null)
            {
                _track.sprite = _value
                    ? QiyuUI.RoundedSprite(18,
                        new Color(0.19f, 0.82f, 0.35f, 0.96f),
                        new Color(0.05f, 0.55f, 0.22f, 0.96f),
                        new Color(0.62f, 1f, 0.72f, 0.75f),
                        new Color(0.02f, 0.24f, 0.10f, 0.55f), 1.2f)
                    : QiyuUI.RoundedSprite(18,
                        new Color(1f, 1f, 1f, 0.10f), new Color(1f, 1f, 1f, 0.055f),
                        new Color(1f, 1f, 1f, 0.18f), new Color(1f, 1f, 1f, 0.06f), 1.2f);
                _track.type = Image.Type.Sliced;
            }
        }

        private void Update()
        {
            var dt = Mathf.Max(0.0001f, Time.unscaledDeltaTime);
            var target = _value ? 1f : 0f;
            _knobT = Mathf.SmoothDamp(_knobT, target, ref _knobVelocity, 0.09f,
                Mathf.Infinity, dt);
            if (_knob != null)
            {
                var x = Mathf.Lerp(4f, 52f, _knobT);
                _knob.anchoredPosition = new Vector2(x, _knob.anchoredPosition.y);
            }
            if (_knobImage != null)
            {
                _knobImage.color = Color.Lerp(Color.white, new Color(1f, 1f, 1f, 0.96f),
                    _knobT);
            }
        }

        public void OnPointerEnter(PointerEventData eventData)
        {
            SetHover(true);
        }

        public void OnPointerExit(PointerEventData eventData)
        {
            SetHover(false);
        }

        public void OnPointerClick(PointerEventData eventData)
        {
            Activate();
        }
    }

    /// <summary>液体玻璃滑杆，支持射线点击与拖动。</summary>
    public class QiyuUISlider : MonoBehaviour, IQiyuUIInteractable,
        IPointerEnterHandler, IPointerExitHandler, IPointerDownHandler,
        IDragHandler, IPointerUpHandler
    {
        private float _min;
        private float _max;
        private float _value;
        private Action<float> _onChanged;
        private string _suffix;
        private Image _track;
        private Image _fill;
        private RectTransform _knob;
        private TMP_Text _valueLabel;
        private float _displayT;
        private float _displayVelocity;
        private bool _hover;

        public RectTransform Rect => (RectTransform)transform;
        public float Value => _value;

        public void Configure(float min, float max, float initial,
                              Action<float> onChanged, string suffix, TMP_Text valueLabel)
        {
            _min = min;
            _max = max;
            _value = Mathf.Clamp(initial, min, max);
            _onChanged = onChanged;
            _suffix = suffix ?? "";
            _valueLabel = valueLabel;

            _track = gameObject.AddComponent<Image>();
            _track.sprite = QiyuUI.RoundedSprite(7,
                new Color(0.05f, 0.10f, 0.20f, 0.10f),
                new Color(0.05f, 0.10f, 0.20f, 0.05f),
                new Color(0.10f, 0.15f, 0.25f, 0.16f),
                new Color(0.10f, 0.15f, 0.25f, 0.05f), 1.2f);
            _track.type = Image.Type.Sliced;
            _track.raycastTarget = true;

            var fillRect = QiyuUI.CreateRect(transform, "Fill");
            QiyuUI.SetAnchored(fillRect, new Vector2(0f, 0f), new Vector2(0f, 1f),
                new Vector2(0f, 0f), new Vector2(0f, 0f));
            _fill = fillRect.gameObject.AddComponent<Image>();
            _fill.sprite = QiyuUI.RoundedSprite(7,
                new Color(0.20f, 0.55f, 1f, 0.95f),
                new Color(0.05f, 0.35f, 0.85f, 0.92f),
                new Color(0.65f, 0.85f, 1f, 0.75f),
                new Color(0.02f, 0.18f, 0.45f, 0.55f), 1.2f);
            _fill.type = Image.Type.Sliced;
            _fill.raycastTarget = false;

            var knobRect = QiyuUI.CreateRect(transform, "Knob");
            QiyuUI.SetAnchored(knobRect, new Vector2(0f, 0.5f), new Vector2(0f, 0.5f),
                new Vector2(-15f, -15f), new Vector2(15f, 15f));
            _knob = knobRect;
            var knobImage = knobRect.gameObject.AddComponent<Image>();
            knobImage.sprite = QiyuUI.RoundedSprite(15,
                Color.white, new Color(0.84f, 0.86f, 0.92f, 1f),
                new Color(1f, 1f, 1f, 0.95f), new Color(0.62f, 0.66f, 0.76f, 0.9f), 1.2f);
            knobImage.type = Image.Type.Sliced;
            knobImage.raycastTarget = false;

            _displayT = Mathf.InverseLerp(_min, _max, _value);
            Refresh();
            QiyuGazeInteractor.Register(this);
        }

        private void OnDestroy()
        {
            QiyuGazeInteractor.Unregister(this);
        }

        public void SetHover(bool hover)
        {
            _hover = hover;
            if (_track != null)
            {
                _track.color = hover ? new Color(1f, 1f, 1f, 1.15f) : Color.white;
            }
        }

        public void Activate()
        {
            SetValue(Mathf.Approximately(_value, _max) ? _min : _max);
        }

        public void SetFromLocalPoint(float localX, float width)
        {
            if (width <= 0f)
            {
                return;
            }
            var t = Mathf.Clamp01((localX + width * 0.5f) / width);
            SetValue(Mathf.Lerp(_min, _max, t));
        }

        public void SetValue(float value)
        {
            _value = Mathf.Clamp(value, _min, _max);
            Refresh();
            _onChanged?.Invoke(_value);
        }

        private void Refresh()
        {
            if (_valueLabel != null)
            {
                _valueLabel.text = $"{_value:0.##}{_suffix}";
            }
        }

        private void Update()
        {
            var target = Mathf.InverseLerp(_min, _max, _value);
            var dt = Mathf.Max(0.0001f, Time.unscaledDeltaTime);
            _displayT = Mathf.SmoothDamp(_displayT, target, ref _displayVelocity, 0.05f,
                Mathf.Infinity, dt);
            if (_fill != null)
            {
                _fill.rectTransform.anchorMax = new Vector2(_displayT, 1f);
            }
            if (_knob != null)
            {
                _knob.anchorMin = new Vector2(_displayT, 0.5f);
                _knob.anchorMax = new Vector2(_displayT, 0.5f);
            }
        }

        public void OnPointerEnter(PointerEventData eventData)
        {
            SetHover(true);
        }

        public void OnPointerExit(PointerEventData eventData)
        {
            SetHover(false);
        }

        public void OnPointerDown(PointerEventData eventData)
        {
            SetFromPointer(eventData);
        }

        public void OnDrag(PointerEventData eventData)
        {
            SetFromPointer(eventData);
        }

        public void OnPointerUp(PointerEventData eventData)
        {
        }

        public void SetFromPointer(PointerEventData eventData)
        {
            Vector3 world;
            if (eventData is OVRPointerEventData vrData &&
                vrData.worldSpaceRay.direction.sqrMagnitude > 0.0001f)
            {
                var plane = new Plane(Rect.forward, Rect.position);
                if (!plane.Raycast(vrData.worldSpaceRay, out var enter))
                {
                    return;
                }
                world = vrData.worldSpaceRay.GetPoint(enter);
            }
            else if (eventData.pointerCurrentRaycast.isValid)
            {
                world = eventData.pointerCurrentRaycast.worldPosition;
            }
            else
            {
                return;
            }
            var local = Rect.InverseTransformPoint(world);
            SetFromLocalPoint(local.x, Rect.rect.width);
        }
    }

    /// <summary>输入框包装：点击后弹出 Qiyu 自绘键盘（不依赖 Android 软键盘）。</summary>
    public class QiyuUIInputField : MonoBehaviour, IQiyuUIInteractable,
        IPointerEnterHandler, IPointerExitHandler, IPointerClickHandler
    {
        private TMP_InputField _input;
        private Image _background;
        private string _placeholder;

        public RectTransform Rect => (RectTransform)transform;
        public TMP_InputField Input => _input;

        public void Configure(TMP_InputField input, string placeholder)
        {
            _input = input;
            _placeholder = placeholder;
            _background = GetComponent<Image>();
            if (_input != null)
            {
                // 由 Qiyu 自绘键盘负责输入，避免 Quest 系统软键盘与 EventSystem 抢占。
                _input.interactable = false;
                _input.enabled = false;
                _input.shouldHideMobileInput = true;
                _input.restoreOriginalTextOnEscape = false;
            }
            QiyuGazeInteractor.Register(this);
        }

        private void OnDestroy()
        {
            QiyuGazeInteractor.Unregister(this);
        }

        public void SetHover(bool hover)
        {
            if (_background != null)
            {
                _background.color = hover ? new Color(1f, 1f, 1f, 1.10f) : Color.white;
            }
        }

        public void Activate()
        {
            if (_input == null)
            {
                return;
            }
            QiyuVirtualKeyboard.Show(_input, _placeholder);
            QiyuGazeInteractor.HapticPulse();
        }

        public void OnPointerEnter(PointerEventData eventData)
        {
            SetHover(true);
        }

        public void OnPointerExit(PointerEventData eventData)
        {
            SetHover(false);
        }

        public void OnPointerClick(PointerEventData eventData)
        {
            Activate();
        }
    }

    /// <summary>窗口顶部拖动条：6DoF 固定模式下把面板拖到空间中任意位置。</summary>
    public class QiyuPanelDragHandle : MonoBehaviour, IPointerEnterHandler,
        IPointerExitHandler, IBeginDragHandler, IDragHandler, IEndDragHandler
    {
        private QiyuMRApp _app;
        private Image _image;

        public void Initialize(QiyuMRApp app)
        {
            _app = app;
            _image = GetComponent<Image>();
            if (_image != null)
            {
                _image.raycastTarget = true;
                _image.color = new Color(1f, 1f, 1f, 0.88f);
            }
        }

        public void OnPointerEnter(PointerEventData eventData)
        {
            if (_image != null)
            {
                _image.color = Color.white;
            }
        }

        public void OnPointerExit(PointerEventData eventData)
        {
            if (_image != null)
            {
                _image.color = new Color(1f, 1f, 1f, 0.88f);
            }
        }

        public void OnBeginDrag(PointerEventData eventData)
        {
            _app?.BeginPanelDrag(eventData);
        }

        public void OnDrag(PointerEventData eventData)
        {
            _app?.DragPanel(eventData);
        }

        public void OnEndDrag(PointerEventData eventData)
        {
            _app?.EndPanelDrag(eventData);
        }
    }

    /// <summary>
    /// 手柄射线 / 手部捏合 / 头部视线交互。
    /// 不依赖 OVRRaycaster 或 EventSystem，直接对注册的世界空间 UI 做平面命中。
    /// </summary>
    public class QiyuGazeInteractor : MonoBehaviour
    {
        private static readonly List<IQiyuUIInteractable> Targets =
            new List<IQiyuUIInteractable>();

        /// <summary>模态根节点（例如自绘键盘）；非空时只允许命中该节点下的 UI。</summary>
        public static Transform ModalRoot;

        [SerializeField] private Transform head;
        [SerializeField] private Transform rightHand;
        [SerializeField] private Transform leftHand;
        [SerializeField] private float maxDistance = 10f;
        [SerializeField] private bool preferController = true;
        [SerializeField] private bool preferHands = true;
        [SerializeField] private Color rayColor = new Color(0.42f, 0.84f, 1f, 0.72f);

        private IQiyuUIInteractable _hovered;
        private LineRenderer _line;
        private Transform _dot;
        private Transform _dotGlow;
        private OVRHand[] _hands;
        private bool _wasPinching;

        public static void Register(IQiyuUIInteractable target)
        {
            if (target != null && !Targets.Contains(target))
            {
                Targets.Add(target);
            }
        }

        public static void Unregister(IQiyuUIInteractable target)
        {
            Targets.Remove(target);
        }

        public static void HapticPulse()
        {
            QiyuHaptics.Pulse();
        }

        private void Start()
        {
            if (head == null)
            {
                var centerEye = GameObject.Find("CenterEyeAnchor");
                head = centerEye != null ? centerEye.transform : Camera.main?.transform;
            }
            if (rightHand == null)
            {
                var right = GameObject.Find("RightHandAnchor") ??
                            GameObject.Find("RightControllerAnchor");
                rightHand = right != null ? right.transform : null;
            }
            if (leftHand == null)
            {
                var left = GameObject.Find("LeftHandAnchor") ??
                           GameObject.Find("LeftControllerAnchor");
                leftHand = left != null ? left.transform : null;
            }
            _hands = FindObjectsByType<OVRHand>(FindObjectsInactive.Include,
                FindObjectsSortMode.None);
            BuildPointer();
        }

        private void BuildPointer()
        {
            var shader = Shader.Find("Sprites/Default") ??
                         Shader.Find("UI/Default") ??
                         Shader.Find("Unlit/Color");

            var lineObject = new GameObject("QiyuRay");
            lineObject.transform.SetParent(null, false);
            _line = lineObject.AddComponent<LineRenderer>();
            _line.positionCount = 2;
            _line.startWidth = 0.0055f;
            _line.endWidth = 0.0022f;
            if (shader != null)
            {
                _line.material = new Material(shader) { color = rayColor };
            }
            _line.startColor = rayColor;
            _line.endColor = new Color(rayColor.r, rayColor.g, rayColor.b, 0.08f);
            _line.useWorldSpace = true;
            _line.numCapVertices = 4;
            _line.enabled = false;

            var dot = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            dot.name = "QiyuRayDot";
            dot.transform.SetParent(null, false);
            dot.transform.localScale = Vector3.one * 0.018f;
            Destroy(dot.GetComponent<Collider>());
            var renderer = dot.GetComponent<Renderer>();
            if (shader != null)
            {
                renderer.material = new Material(shader) { color = rayColor };
            }
            _dot = dot.transform;
            _dot.gameObject.SetActive(false);

            var glow = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            glow.name = "QiyuRayGlow";
            glow.transform.SetParent(_dot, false);
            glow.transform.localScale = Vector3.one * 2.6f;
            Destroy(glow.GetComponent<Collider>());
            var glowRenderer = glow.GetComponent<Renderer>();
            if (shader != null)
            {
                glowRenderer.material = new Material(shader)
                {
                    color = new Color(rayColor.r, rayColor.g, rayColor.b, 0.16f)
                };
            }
            _dotGlow = glow.transform;
        }

        private void OnDestroy()
        {
            if (_line != null)
            {
                Destroy(_line.gameObject);
            }
            if (_dot != null)
            {
                Destroy(_dot.gameObject);
            }
        }

        private void Update()
        {
            var origin = Vector3.zero;
            var direction = Vector3.forward;
            var hasRay = false;
            var clickPressed = false;
            OVRHand activeHand = null;

            if (preferHands && _hands != null)
            {
                foreach (var hand in _hands)
                {
                    if (hand != null && hand.IsTracked && hand.IsPointerPoseValid)
                    {
                        activeHand = hand;
                        break;
                    }
                }
            }

            if (activeHand != null)
            {
                origin = activeHand.PointerPose.position;
                direction = activeHand.PointerPose.forward;
                var pinching = activeHand.GetFingerIsPinching(OVRHand.HandFinger.Index);
                clickPressed = pinching && !_wasPinching;
                _wasPinching = pinching;
                hasRay = true;
            }
            else if (preferController && rightHand != null)
            {
                origin = rightHand.position;
                direction = rightHand.forward;
                clickPressed = ControllerClickPressed();
                hasRay = true;
            }
            else if (head != null)
            {
                origin = head.position;
                direction = head.forward;
                clickPressed = ControllerClickPressed();
                hasRay = true;
            }

            if (!hasRay)
            {
                return;
            }

            IQiyuUIInteractable hitTarget = null;
            var hitPoint = origin + direction * maxDistance;
            var bestDepth = float.MaxValue;
            foreach (var target in Targets)
            {
                if (target?.Rect == null || !target.Rect.gameObject.activeInHierarchy)
                {
                    continue;
                }
                if (ModalRoot != null && !target.Rect.IsChildOf(ModalRoot))
                {
                    continue;
                }
                var plane = new Plane(target.Rect.forward, target.Rect.position);
                if (!plane.Raycast(new Ray(origin, direction), out var enter) ||
                    enter < 0f || enter > maxDistance)
                {
                    continue;
                }
                var point = origin + direction * enter;
                var local = target.Rect.InverseTransformPoint(point);
                var rect = target.Rect.rect;
                if (local.x < rect.xMin || local.x > rect.xMax ||
                    local.y < rect.yMin || local.y > rect.yMax)
                {
                    continue;
                }
                if (enter < bestDepth)
                {
                    bestDepth = enter;
                    hitTarget = target;
                    hitPoint = point;
                }
            }

            if (_hovered != hitTarget)
            {
                _hovered?.SetHover(false);
                _hovered = hitTarget;
                _hovered?.SetHover(true);
            }

            if (_line != null)
            {
                _line.enabled = hitTarget != null;
                if (hitTarget != null)
                {
                    _line.SetPosition(0, origin);
                    _line.SetPosition(1, hitPoint);
                }
            }
            if (_dot != null)
            {
                _dot.gameObject.SetActive(hitTarget != null);
                if (hitTarget != null)
                {
                    _dot.position = hitPoint;
                }
            }

            if (hitTarget == null || !clickPressed)
            {
                return;
            }

            if (hitTarget is QiyuUISlider slider)
            {
                var local = slider.Rect.InverseTransformPoint(hitPoint);
                slider.SetFromLocalPoint(local.x, slider.Rect.rect.width);
                HapticPulse();
            }
            else
            {
                hitTarget.Activate();
            }
        }

        private static bool ControllerClickPressed()
        {
            return OVRInput.GetDown(OVRInput.Button.PrimaryIndexTrigger) ||
                   OVRInput.GetDown(OVRInput.Button.SecondaryIndexTrigger) ||
                   OVRInput.GetDown(OVRInput.Button.One) ||
                   OVRInput.GetDown(OVRInput.Button.Three);
        }
    }
}
