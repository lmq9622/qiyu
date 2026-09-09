using System.Collections.Generic;
using System.Reflection;
using System.Text;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.UI;

namespace Qiyu.Quest.UI
{
    /// <summary>
    /// 手部/手柄可见激光与指针点。
    ///
    /// 点击链路仍然走 Meta 官方 OVRInputModule + OVRRaycaster；
    /// 这个组件只负责“看得见的激光 + 命中点 + 诊断日志”，
    /// 避免官方 OVRRayHelper 在输入源切换时留下卡死的蓝色网格。
    /// </summary>
    public class QiyuPointerVisuals : MonoBehaviour
    {
        private sealed class PointerVisual
        {
            public OVRHand Hand;
            public OVRControllerHelper Controller;
            public Transform Source;
            public LineRenderer Line;
            public Transform Dot;
            public Renderer DotRenderer;
        }

        [SerializeField] private float maxDistance = 6f;
        [SerializeField] private Color rayColor = new Color(0.42f, 0.84f, 1f, 0.85f);
        [SerializeField] private Color activeColor = new Color(1f, 1f, 1f, 0.95f);
        [SerializeField] private bool logDiagnostics = true;

        private readonly List<PointerVisual> _visuals = new List<PointerVisual>();
        private readonly List<RaycastResult> _raycastResults = new List<RaycastResult>();
        private Canvas _canvas;
        private OVRPointerEventData _eventData;
        private PointerEventData _handEventData;
        private GameObject _hoveredHandObject;
        private bool _wasHandPinching;
        private Material _rayMaterial;
        private Material _activeMaterial;
        private Material _dotMaterial;
        private float _nextDiagnosticsAt;

        private void Start()
        {
            _canvas = FindFirstObjectByType<Canvas>();
            CreateMaterials();
            foreach (var hand in FindObjectsByType<OVRHand>(FindObjectsInactive.Include))
            {
                if (hand != null)
                {
                    _visuals.Add(CreateVisual(hand.transform, hand, null));
                }
            }
            foreach (var controller in FindObjectsByType<OVRControllerHelper>(
                         FindObjectsInactive.Include))
            {
                if (controller != null)
                {
                    _visuals.Add(CreateVisual(controller.transform, null, controller));
                }
            }
            Debug.Log($"[QiyuPointer] 初始化完成 hands/controllers={_visuals.Count}");
        }

        private void Update()
        {
            if (EventSystem.current == null)
            {
                return;
            }
            if (_eventData == null)
            {
                _eventData = new OVRPointerEventData(EventSystem.current);
            }
            if (_handEventData == null)
            {
                _handEventData = new PointerEventData(EventSystem.current);
            }

            foreach (var visual in _visuals)
            {
                UpdateVisual(visual);
            }

            if (logDiagnostics && Time.unscaledTime >= _nextDiagnosticsAt)
            {
                _nextDiagnosticsAt = Time.unscaledTime + 2f;
                LogDiagnostics();
            }
        }

        private PointerVisual CreateVisual(Transform source, OVRHand hand,
                                           OVRControllerHelper controller)
        {
            var visual = new PointerVisual
            {
                Hand = hand,
                Controller = controller,
                Source = source
            };

            var lineObject = new GameObject(source.name + "QiyuLaser");
            lineObject.transform.SetParent(transform, false);
            visual.Line = lineObject.AddComponent<LineRenderer>();
            visual.Line.positionCount = 2;
            visual.Line.startWidth = 0.0075f;
            visual.Line.endWidth = 0.0025f;
            visual.Line.numCapVertices = 4;
            visual.Line.useWorldSpace = true;
            visual.Line.sharedMaterial = _rayMaterial;
            visual.Line.startColor = rayColor;
            visual.Line.endColor = new Color(rayColor.r, rayColor.g, rayColor.b, 0.10f);
            visual.Line.enabled = false;

            var dot = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            dot.name = source.name + "QiyuDot";
            dot.transform.SetParent(transform, false);
            dot.transform.localScale = Vector3.one * 0.014f;
            Destroy(dot.GetComponent<Collider>());
            visual.Dot = dot.transform;
            visual.DotRenderer = dot.GetComponent<Renderer>();
            if (visual.DotRenderer != null)
            {
                visual.DotRenderer.sharedMaterial = _dotMaterial;
            }
            visual.Dot.gameObject.SetActive(false);
            return visual;
        }

        private void UpdateVisual(PointerVisual visual)
        {
            if (visual?.Source == null)
            {
                return;
            }
            var active = IsSourceActive(visual);
            if (!active)
            {
                visual.Line.enabled = false;
                visual.Dot.gameObject.SetActive(false);
                return;
            }

            GetPointerRay(visual, out var origin, out var direction);
            var end = origin + direction * maxDistance;
            var hit = false;
            RaycastResult hitResult = default;

            _eventData.Reset();
            _eventData.worldSpaceRay = new Ray(origin, direction);
            _eventData.button = PointerEventData.InputButton.Left;
            _raycastResults.Clear();
            EventSystem.current.RaycastAll(_eventData, _raycastResults);
            for (var i = 0; i < _raycastResults.Count; i++)
            {
                var result = _raycastResults[i];
                if (!result.isValid || result.gameObject == null)
                {
                    continue;
                }
                end = result.worldPosition;
                hit = true;
                hitResult = result;
                break;
            }

            visual.Line.enabled = true;
            visual.Line.sharedMaterial = hit ? _activeMaterial : _rayMaterial;
            visual.Line.SetPosition(0, origin);
            visual.Line.SetPosition(1, end);
            visual.Dot.gameObject.SetActive(true);
            visual.Dot.position = end;
            if (visual.DotRenderer != null)
            {
                visual.DotRenderer.sharedMaterial = hit ? _activeMaterial : _dotMaterial;
            }
            if (visual.Hand != null)
            {
                UpdateHandInteraction(visual, hit ? hitResult : default, hit);
            }
        }

        private static bool IsSourceActive(PointerVisual visual)
        {
            if (visual.Hand != null)
            {
                // tracked=False 但 pointer/data 有效时也要给用户反馈；
                // 否则低置信度裸手会完全消失。
                return visual.Hand.IsPointerPoseValid || visual.Hand.IsDataValid;
            }
            return visual.Controller != null && visual.Controller.IsActive();
        }

        private static void GetPointerRay(PointerVisual visual, out Vector3 origin,
                                          out Vector3 direction)
        {
            if (visual.Hand != null && TryGetHandRay(visual.Hand, out origin, out direction))
            {
                return;
            }
            origin = visual.Source.position;
            direction = visual.Source.forward;
        }

        /// <summary>
        /// 裸手射线不再用 OVRHand.PointerPose（捏合时会斜向上），
        /// 改成食指指节 → 食指指尖的方向，激光顺着手指走。
        /// </summary>
        private static bool TryGetHandRay(OVRHand hand, out Vector3 origin,
                                          out Vector3 direction)
        {
            origin = hand.PointerPose.position;
            direction = hand.PointerPose.forward;
            var skeleton = hand.GetComponentInChildren<OVRSkeleton>(true);
            if (skeleton == null || skeleton.Bones == null || skeleton.Bones.Count == 0)
            {
                return false;
            }
            Transform distal = null;
            Transform tip = null;
            foreach (var bone in skeleton.Bones)
            {
                if (bone?.Transform == null)
                {
                    continue;
                }
                if (bone.Id == OVRSkeleton.BoneId.Hand_Index1 ||
                    bone.Id == OVRSkeleton.BoneId.XRHand_IndexProximal)
                {
                    distal = bone.Transform;
                }
                else if (bone.Id == OVRSkeleton.BoneId.Hand_IndexTip ||
                         bone.Id == OVRSkeleton.BoneId.XRHand_IndexTip)
                {
                    tip = bone.Transform;
                }
            }
            if (tip == null)
            {
                return false;
            }
            origin = tip.position;
            if (distal != null)
            {
                var fingerDirection = tip.position - distal.position;
                if (fingerDirection.sqrMagnitude > 0.000001f)
                {
                    direction = fingerDirection.normalized;
                    return true;
                }
            }
            return false;
        }

        private void UpdateHandInteraction(PointerVisual visual, RaycastResult hitResult,
                                           bool hit)
        {
            var hovered = hit && hitResult.gameObject != null
                ? hitResult.gameObject
                : null;
            if (_hoveredHandObject != hovered)
            {
                if (_hoveredHandObject != null)
                {
                    ExecuteEvents.ExecuteHierarchy(_hoveredHandObject, _handEventData,
                        ExecuteEvents.pointerExitHandler);
                }
                _hoveredHandObject = hovered;
                if (_hoveredHandObject != null)
                {
                    ExecuteEvents.ExecuteHierarchy(_hoveredHandObject, _handEventData,
                        ExecuteEvents.pointerEnterHandler);
                }
            }

            var pinchStrength = visual.Hand.GetFingerPinchStrength(
                OVRHand.HandFinger.Index);
            var pinching = pinchStrength > 0.65f ||
                           visual.Hand.GetFingerIsPinching(OVRHand.HandFinger.Index);
            if (hovered != null)
            {
                _handEventData.pointerCurrentRaycast = hitResult;
                var slider = hovered.GetComponentInParent<QiyuUISlider>();
                if (slider != null && pinching)
                {
                    slider.SetFromPointer(_handEventData);
                }
                else if (pinching && !_wasHandPinching)
                {
                    ExecuteEvents.ExecuteHierarchy(hovered, _handEventData,
                        ExecuteEvents.pointerClickHandler);
                }
            }
            _wasHandPinching = pinching;
        }

        private void CreateMaterials()
        {
            var shader = Shader.Find("Universal Render Pipeline/Unlit")
                         ?? Shader.Find("Sprites/Default")
                         ?? Shader.Find("Unlit/Color");
            _rayMaterial = CreateMaterial(shader, "QiyuLaserRay", rayColor);
            _activeMaterial = CreateMaterial(shader, "QiyuLaserActive", activeColor);
            _dotMaterial = CreateMaterial(shader, "QiyuLaserDot",
                new Color(0.55f, 0.90f, 1f, 0.95f));
        }

        private static Material CreateMaterial(Shader shader, string name, Color color)
        {
            var material = new Material(shader) { name = name };
            if (material.HasProperty("_BaseColor"))
            {
                material.SetColor("_BaseColor", color);
            }
            if (material.HasProperty("_Color"))
            {
                material.SetColor("_Color", color);
            }
            if (material.HasProperty("_Surface"))
            {
                material.SetFloat("_Surface", 1f);
            }
            if (material.HasProperty("_Blend"))
            {
                material.SetFloat("_Blend", 0f);
            }
            if (material.HasProperty("_ZWrite"))
            {
                material.SetFloat("_ZWrite", 0f);
            }
            material.renderQueue = 3000;
            return material;
        }

        private void LogDiagnostics()
        {
            try
            {
                LogDiagnosticsInternal();
            }
            catch (System.Exception e)
            {
                Debug.LogWarning("[QiyuPointer] 诊断日志异常: " + e.Message);
            }
        }

        private void LogDiagnosticsInternal()
        {
            var builder = new StringBuilder();
            builder.Append("[QiyuPointer] ");
            builder.Append("eventSystem=").Append(EventSystem.current != null);
            builder.Append(" module=").Append(OVRInputModule.instance != null);
            builder.Append(" handTracking=").Append(OVRPlugin.GetHandTrackingEnabled());
            builder.Append(" connected=").Append(OVRInput.GetConnectedControllers());
            builder.Append(" activeCtrl=").Append(OVRInput.GetActiveController());
            if (OVRInputModule.instance != null)
            {
                var field = typeof(OVRInputModule).GetField("_trackedInputSources",
                    BindingFlags.NonPublic | BindingFlags.Instance);
                var list = field?.GetValue(OVRInputModule.instance) as System.Collections.IList;
                builder.Append(" trackedSources=").Append(list?.Count ?? -1);
            }
            builder.Append(" hands=");
            var hands = FindObjectsByType<OVRHand>(FindObjectsInactive.Include);
            foreach (var hand in hands)
            {
                if (hand == null)
                {
                    continue;
                }
                builder.Append('[').Append(hand.name)
                    .Append(" tracked=").Append(hand.IsTracked)
                    .Append(" pointer=").Append(hand.IsPointerPoseValid)
                    .Append(" data=").Append(hand.IsDataValid)
                    .Append(" conf=").Append(hand.HandConfidence)
                    .Append(" pinch=").Append(hand.GetFingerPinchStrength(
                        OVRHand.HandFinger.Index).ToString("F2"))
                    .Append(" pinching=").Append(hand.GetFingerIsPinching(
                        OVRHand.HandFinger.Index))
                    .Append(" pos=").Append(hand.PointerPose.position.ToString("F2"))
                    .Append(" ray=").Append(hand.RayHelper != null)
                    .Append(']');
            }
            builder.Append(" controllers=");
            var controllers = FindObjectsByType<OVRControllerHelper>(
                FindObjectsInactive.Include);
            foreach (var controller in controllers)
            {
                if (controller == null)
                {
                    continue;
                }
                builder.Append('[').Append(controller.name)
                    .Append(' ').Append(controller.m_controller)
                    .Append(" active=").Append(controller.IsActive())
                    .Append(" ray=").Append(controller.RayHelper != null)
                    .Append(']');
            }
            if (_canvas != null)
            {
                builder.Append(" raycastables=")
                    .Append(GraphicRegistry.GetRaycastableGraphicsForCanvas(_canvas).Count);
            }
            Debug.Log(builder.ToString());
        }
    }
}
