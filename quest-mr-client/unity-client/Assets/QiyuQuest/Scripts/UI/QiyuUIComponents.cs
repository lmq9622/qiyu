using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;

namespace Qiyu.Quest.UI
{
    public interface IQiyuUIInteractable
    {
        RectTransform Rect { get; }
        void SetHover(bool hover);
        void Activate();
    }

    /// <summary>液态玻璃按钮：由 QiyuGazeInteractor 统一做命中/hover/点击。</summary>
    public class QiyuUIButton : MonoBehaviour, IQiyuUIInteractable
    {
        private Image _image;
        private Action _onClick;
        private Color _normal;
        private Color _hover;
        private float _targetScale = 1f;

        public RectTransform Rect => (RectTransform)transform;

        public void Configure(Image image, Action onClick)
        {
            _image = image;
            _onClick = onClick;
            _normal = image.color;
            _hover = new Color(1f, 1f, 1f, 0.92f);
            QiyuGazeInteractor.Register(this);
        }

        private void OnDestroy()
        {
            QiyuGazeInteractor.Unregister(this);
        }

        public void SetHover(bool hover)
        {
            if (_image != null)
            {
                _image.color = hover ? _hover : _normal;
            }
            _targetScale = hover ? 1.06f : 1f;
        }

        private void Update()
        {
            transform.localScale = Vector3.Lerp(transform.localScale,
                Vector3.one * _targetScale, Time.unscaledDeltaTime * 12f);
        }

        public void Activate()
        {
            _onClick?.Invoke();
        }
    }

    public class QiyuUIToggle : MonoBehaviour, IQiyuUIInteractable
    {
        private Image _knob;
        private Action<bool> _onChanged;
        private bool _value;
        private RectTransform _knobRect;

        public RectTransform Rect => (RectTransform)transform;
        public bool Value => _value;

        public void Configure(Image knob, bool initial, Action<bool> onChanged)
        {
            _knob = knob;
            _knobRect = knob.rectTransform;
            _onChanged = onChanged;
            _value = initial;
            Apply();
            QiyuGazeInteractor.Register(this);
        }

        private void OnDestroy()
        {
            QiyuGazeInteractor.Unregister(this);
        }

        public void SetHover(bool hover)
        {
            if (_knob != null)
            {
                _knob.color = hover
                    ? new Color(1f, 1f, 1f, 1f)
                    : Color.white;
            }
        }

        public void Activate()
        {
            _value = !_value;
            Apply();
            _onChanged?.Invoke(_value);
        }

        private void Apply()
        {
            if (_knob == null)
            {
                return;
            }
            _knob.sprite = QiyuUI.RoundedSprite(16,
                _value ? new Color(0.02f, 0.59f, 0.41f, 0.95f)
                       : new Color(1f, 1f, 1f, 0.10f),
                _value ? new Color(0.3f, 0.9f, 0.7f, 0.7f)
                       : QiyuUI.Border, 2);
            if (_knobRect != null)
            {
                var anchored = _knobRect.anchoredPosition;
                anchored.x = _value ? -30f : -54f;
                _knobRect.anchoredPosition = anchored;
            }
        }
    }

    public class QiyuUISlider : MonoBehaviour, IQiyuUIInteractable
    {
        private float _min;
        private float _max;
        private float _value;
        private Action<float> _onChanged;
        private string _suffix;
        private Image _track;
        private Image _fill;
        private RectTransform _knob;
        private Text _valueLabel;

        public RectTransform Rect => (RectTransform)transform;
        public float Value => _value;

        public void Configure(float min, float max, float initial,
                              Action<float> onChanged, string suffix)
        {
            _min = min;
            _max = max;
            _value = Mathf.Clamp(initial, min, max);
            _onChanged = onChanged;
            _suffix = suffix ?? "";

            _track = gameObject.AddComponent<Image>();
            _track.sprite = QiyuUI.RoundedSprite(8, new Color(1f, 1f, 1f, 0.08f),
                new Color(1f, 1f, 1f, 0.10f), 1);
            _track.type = Image.Type.Sliced;
            _track.raycastTarget = false;

            var fillRect = QiyuUI.CreateRect(transform, "Fill");
            QiyuUI.SetAnchored(fillRect, new Vector2(0, 0), new Vector2(0, 1),
                new Vector2(0, 0), new Vector2(0, 0));
            _fill = fillRect.gameObject.AddComponent<Image>();
            _fill.sprite = QiyuUI.RoundedSprite(8, new Color(0.9f, 0.9f, 0.94f, 0.85f),
                new Color(1f, 1f, 1f, 0.4f), 1);
            _fill.type = Image.Type.Sliced;
            _fill.raycastTarget = false;

            var knobRect = QiyuUI.CreateRect(transform, "Knob");
            QiyuUI.SetAnchored(knobRect, new Vector2(0, 0.5f), new Vector2(0, 0.5f),
                new Vector2(-12, -12), new Vector2(12, 12));
            _knob = knobRect;
            var knobImage = knobRect.gameObject.AddComponent<Image>();
            knobImage.sprite = QiyuUI.RoundedSprite(12, Color.white,
                new Color(1f, 1f, 1f, 0.6f), 2);
            knobImage.type = Image.Type.Sliced;
            knobImage.raycastTarget = false;

            var valueText = QiyuUI.Label(transform, "Value", "", 18, QiyuUI.TextSecondary,
                TextAnchor.MiddleRight);
            QiyuUI.SetAnchored(valueText.rectTransform, new Vector2(1, 0.5f),
                new Vector2(1, 1f), new Vector2(-90, 0), new Vector2(0, 0));
            _valueLabel = valueText;
            Refresh();
            QiyuGazeInteractor.Register(this);
        }

        private void OnDestroy()
        {
            QiyuGazeInteractor.Unregister(this);
        }

        public void SetHover(bool hover)
        {
            if (_track != null)
            {
                _track.color = hover ? new Color(1f, 1f, 1f, 0.16f) : Color.white;
            }
        }

        public void Activate()
        {
            // 单击在中间位置切换一次；精确拖动由 QiyuGazeInteractor 的 SetFromLocalPoint 处理
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
            var t = Mathf.InverseLerp(_min, _max, _value);
            var rect = (RectTransform)transform;
            var width = rect.rect.width;
            if (_fill != null)
            {
                _fill.rectTransform.anchorMax = new Vector2(t, 1f);
            }
            if (_knob != null)
            {
                _knob.anchorMin = new Vector2(t, 0.5f);
                _knob.anchorMax = new Vector2(t, 0.5f);
            }
            if (_valueLabel != null)
            {
                _valueLabel.text = $"{_value:0.##}{_suffix}";
            }
        }
    }

    /// <summary>
    /// 手柄射线 / 视线交互：不依赖 OVRRaycaster/EventSystem，命中注册的世界空间 UI 元素。
    /// 右手控制器可用时优先用手柄射线，否则用头部视线。
    /// </summary>
    public class QiyuGazeInteractor : MonoBehaviour
    {
        private static readonly List<IQiyuUIInteractable> Targets =
            new List<IQiyuUIInteractable>();

        [SerializeField] private Transform head;
        [SerializeField] private Transform rightHand;
        [SerializeField] private float maxDistance = 8f;
        [SerializeField] private bool preferController = true;
        [SerializeField] private bool preferHands = true;
        [SerializeField] private Color rayColor = new Color(1f, 1f, 1f, 0.55f);

        private IQiyuUIInteractable _hovered;
        private LineRenderer _line;
        private Transform _dot;
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

        private void Start()
        {
            if (head == null)
            {
                var centerEye = GameObject.Find("CenterEyeAnchor");
                if (centerEye != null)
                {
                    head = centerEye.transform;
                }
                else if (Camera.main != null)
                {
                    head = Camera.main.transform;
                }
            }
            if (rightHand == null)
            {
                var right = GameObject.Find("RightHandAnchor") ??
                            GameObject.Find("RightControllerAnchor");
                if (right != null)
                {
                    rightHand = right.transform;
                }
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
            _line.startWidth = 0.006f;
            _line.endWidth = 0.003f;
            if (shader != null)
            {
                _line.material = new Material(shader) { color = rayColor };
            }
            _line.startColor = rayColor;
            _line.endColor = new Color(rayColor.r, rayColor.g, rayColor.b, 0.1f);
            _line.useWorldSpace = true;
            _line.enabled = false;

            var dot = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            dot.name = "QiyuRayDot";
            dot.transform.SetParent(null, false);
            dot.transform.localScale = Vector3.one * 0.02f;
            Destroy(dot.GetComponent<Collider>());
            var renderer = dot.GetComponent<Renderer>();
            if (shader != null)
            {
                renderer.material = new Material(shader) { color = rayColor };
            }
            _dot = dot.transform;
            _dot.gameObject.SetActive(false);
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

            if (hitTarget != null && clickPressed)
            {
                if (hitTarget is QiyuUISlider slider)
                {
                    var local = slider.Rect.InverseTransformPoint(hitPoint);
                    slider.SetFromLocalPoint(local.x, slider.Rect.rect.width);
                }
                else
                {
                    hitTarget.Activate();
                }
            }
        }

        private static bool ControllerClickPressed()
        {
            return OVRInput.GetDown(OVRInput.Button.PrimaryIndexTrigger) ||
                   OVRInput.GetDown(OVRInput.Button.SecondaryIndexTrigger) ||
                   OVRInput.GetDown(OVRInput.Button.One);
        }
    }
}
