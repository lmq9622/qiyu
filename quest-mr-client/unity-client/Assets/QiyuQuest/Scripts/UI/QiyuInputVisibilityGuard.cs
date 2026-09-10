using System.Collections.Generic;
using System.Reflection;
using System.Text;
using UnityEngine;

namespace Qiyu.Quest.UI
{
    /// <summary>
    /// 输入可见性守卫（手 + 手柄）。
    ///
    /// 真机日志实测的两个 Meta 默认行为会让用户“什么都看不见”：
    ///
    /// 1) 手柄模型：
    ///    OVRControllerHelper 默认在
    ///    <c>IsControllerDrivenHandPosesEnabled() &amp;&amp; AreControllerDrivenHandPosesNatural()</c>
    ///    成立时把手柄模型关掉（Meta 认为此时应该显示“由手柄驱动的手”）。
    ///    但 OVRHand 在“手柄在手里”时同样不会渲染手 —— 两边都不显示。
    ///
    /// 2) 手部网格：
    ///    OVRMeshRenderer / OVRSkeletonRenderer 只有在
    ///    <c>IsDataValid &amp;&amp; IsDataHighConfidence</c> 时才渲染，
    ///    而 Quest 真机常态是 <c>tracked=False / conf=Low</c>（日志可复现：
    ///    data=True bones=26 但 conf=Low），于是手网格永远不出现。
    ///
    /// 这里做三件事：
    ///   - 强制手柄模型在连接且获得输入焦点时可见；
    ///   - 把手部网格/骨架的置信度门槛降为“数据有效即可见”；
    ///   - 每 2 秒打一条精简诊断日志，便于真机核对。
    /// </summary>
    public class QiyuInputVisibilityGuard : MonoBehaviour
    {
        [SerializeField] private OVRHand leftHand;
        [SerializeField] private OVRHand rightHand;
        [SerializeField] private OVRControllerHelper leftController;
        [SerializeField] private OVRControllerHelper rightController;
        [SerializeField] private bool logDiagnostics = true;

        private sealed class HandRig
        {
            public OVRHand Hand;
            public OVRMeshRenderer MeshRenderer;
            public OVRSkeletonRenderer SkeletonRenderer;
            public OVRSkeleton Skeleton;
            public SkinnedMeshRenderer Skin;
            public readonly List<Renderer> SkeletonRenderers = new List<Renderer>();
            public bool Visible;
            public bool Wired;
            public bool Applied;
        }

        private readonly List<HandRig> _hands = new List<HandRig>();
        private readonly List<OVRControllerHelper> _controllers = new List<OVRControllerHelper>();
        private float _nextLogAt;
        private float _nextShowStateAt;

        private void Start()
        {
            Collect();
            Debug.Log($"[QiyuInput] 可见性守卫启动 hands={_hands.Count} " +
                      $"controllers={_controllers.Count}");
        }

        private void Update()
        {
            Apply();
            if (logDiagnostics && Time.unscaledTime >= _nextLogAt)
            {
                _nextLogAt = Time.unscaledTime + 2f;
                LogDiagnostics();
            }
        }

        /// <summary>收集手/手柄引用并完成一次性配置。</summary>
        public void Collect()
        {
            if (leftHand == null || rightHand == null)
            {
                var hands = FindObjectsByType<OVRHand>(FindObjectsInactive.Include);
                foreach (var hand in hands)
                {
                    if (hand == null)
                    {
                        continue;
                    }
                    // HandType 是 internal，官方提供了公开的 GetHand()。
                    if (hand.GetHand() == OVRPlugin.Hand.HandLeft && leftHand == null)
                    {
                        leftHand = hand;
                    }
                    else if (hand.GetHand() == OVRPlugin.Hand.HandRight && rightHand == null)
                    {
                        rightHand = hand;
                    }
                }
            }
            if (leftController == null || rightController == null)
            {
                var helpers = FindObjectsByType<OVRControllerHelper>(FindObjectsInactive.Include);
                foreach (var helper in helpers)
                {
                    if (helper == null)
                    {
                        continue;
                    }
                    switch (helper.m_controller)
                    {
                        case OVRInput.Controller.LTouch:
                            leftController ??= helper;
                            break;
                        case OVRInput.Controller.RTouch:
                            rightController ??= helper;
                            break;
                    }
                }
            }

            foreach (var hand in new[] { leftHand, rightHand })
            {
                if (hand != null)
                {
                    _hands.Add(CreateRig(hand));
                }
            }
            foreach (var helper in new[] { leftController, rightController })
            {
                if (helper != null && !_controllers.Contains(helper))
                {
                    _controllers.Add(helper);
                    ConfigureController(helper);
                }
            }
        }

        private HandRig CreateRig(OVRHand hand)
        {
            // 手在手柄里时不渲染手（Meta 语义），手柄模型负责显示；
            // 放下手柄后手部数据有效，手就会出现。
            hand.m_showState = OVRInput.InputDeviceShowState.ControllerNotInHand;

            var rig = new HandRig
            {
                Hand = hand,
                MeshRenderer = hand.GetComponentInChildren<OVRMeshRenderer>(true),
                SkeletonRenderer = hand.GetComponentInChildren<OVRSkeletonRenderer>(true),
                Skeleton = hand.GetComponentInChildren<OVRSkeleton>(true)
            };
            if (rig.MeshRenderer != null)
            {
                rig.MeshRenderer.enabled = true;
                // 0 = ConfidenceBehavior.None：不再让官方组件按 IsDataHighConfidence 开关网格，
                // 改由本组件按 IsDataValid 控制，Low 置信度也能看到手。
                SetPrivateField(rig.MeshRenderer, "_confidenceBehavior", 0);
            }
            if (rig.SkeletonRenderer != null)
            {
                rig.SkeletonRenderer.enabled = true;
                SetPrivateField(rig.SkeletonRenderer, "_confidenceBehavior", 0);
            }
            // 真机实测：OVRSkeleton 默认 _updateRootPose=false，骨骼链会留在世界原点
            // （日志里食指尖的世界坐标是 (0,0,0)，而 PointerPose 是 (-0.60,0.49,0.42)）。
            // 打开后骨架/手网格/激光才会跟着真实手位走。
            return rig;
        }

        private void ConfigureController(OVRControllerHelper helper)
        {
            OVRInput.ControllerInHandState inHand =
                OVRInput.GetControllerIsInHandState(
                    helper.m_controller == OVRInput.Controller.LTouch
                        ? OVRInput.Hand.HandLeft
                        : OVRInput.Hand.HandRight);
            Debug.Log($"[QiyuInput] 手柄 {helper.name} 配置前 " +
                      $"showState={helper.m_showState} " +
                      $"showWhenNatural={helper.showWhenHandsArePoweredByNaturalControllerPoses} " +
                      $"inHand={inHand}");

            // 只要手柄连着并且这个应用有输入焦点就显示模型。
            // 手柄放桌上会自动断开连接（连接状态为 Hands），不会留下悬空模型。
            helper.m_showState = OVRInput.InputDeviceShowState.Always;
            helper.showWhenHandsArePoweredByNaturalControllerPoses = true;
        }

        private void Apply()
        {
            RefreshHandShowState();
            foreach (var rig in _hands)
            {
                if (rig?.Hand == null)
                {
                    continue;
                }
                if (!rig.Wired)
                {
                    Wire(rig);
                }
                if (rig.Skin == null && rig.MeshRenderer != null)
                {
                    rig.Skin = rig.MeshRenderer.GetComponent<SkinnedMeshRenderer>();
                }
                if (rig.SkeletonRenderers.Count == 0 && rig.SkeletonRenderer != null &&
                    Time.frameCount % 30 == 0)
                {
                    CollectSkeletonRenderers(rig);
                }

                // 关节链退化时（真机实测整条链塌在原点上）不要显示 OVR 手网格，
                // 否则手会退化成一个点；这种机器上由 QiyuHandRig 的 XR Hands 骨架顶上。
                var visible = rig.Hand.IsDataValid &&
                              rig.Hand.gameObject.activeInHierarchy &&
                              !IsChainCollapsed(rig);
                if (rig.Applied && visible == rig.Visible)
                {
                    continue;
                }
                rig.Applied = true;
                rig.Visible = visible;
                if (rig.Skin != null)
                {
                    rig.Skin.enabled = visible;
                }
                for (var i = 0; i < rig.SkeletonRenderers.Count; i++)
                {
                    rig.SkeletonRenderers[i].enabled = visible;
                }
            }
        }

        /// <summary>
        /// 动态修正 OVRHand.m_showState。
        ///
        /// Meta 默认值是 ControllerNotInHand，而 OVRInput.GetControllerIsInHandState
        /// 在“没有连接手柄”时会返回 NoHand，于是 OVRHand 会把 IsDataValid 直接置 false ——
        /// 裸手模式下反而什么都拿不到（手网格、激光、捏合全部失效）。
        /// 因此：没连手柄就用 Always，连了手柄再用 ControllerNotInHand。
        /// </summary>
        private void RefreshHandShowState()
        {
            if (Time.unscaledTime < _nextShowStateAt)
            {
                return;
            }
            _nextShowStateAt = Time.unscaledTime + 0.5f;
            var connected = OVRInput.GetConnectedControllers();
            // 注意：只判断 Touch 手柄。LHand/RHand 位在开启手部追踪时也会置位，
            // 用它判断会把“纯裸手”误判成“有手柄”。
            var anyController =
                (connected & (OVRInput.Controller.LTouch | OVRInput.Controller.RTouch)) != 0;
            var state = anyController
                ? OVRInput.InputDeviceShowState.ControllerNotInHand
                : OVRInput.InputDeviceShowState.Always;
            foreach (var rig in _hands)
            {
                if (rig?.Hand == null)
                {
                    continue;
                }
                rig.Hand.m_showState = state;
                // OVRCameraRig 只在“手柄激活”时驱动 hand anchor；
                // 裸手模式下 anchor 停在原点，必须让骨架自己跟根位姿，
                // 否则整条骨骼链（以及指尖激光）会留在世界原点。
                if (rig.Skeleton != null)
                {
                    SetPrivateField(rig.Skeleton, "_updateRootPose", !anyController);
                }
            }
        }

        /// <summary>网格渲染器由 OVRMeshRenderer 在 Start 里动态创建，需要延迟接线。</summary>
        private void Wire(HandRig rig)
        {
            rig.Skin = rig.MeshRenderer != null
                ? rig.MeshRenderer.GetComponent<SkinnedMeshRenderer>()
                : null;
            CollectSkeletonRenderers(rig);
            rig.Wired = true;
        }

        private static void CollectSkeletonRenderers(HandRig rig)
        {
            if (rig.SkeletonRenderer == null)
            {
                return;
            }
            rig.SkeletonRenderers.Clear();
            foreach (var line in rig.SkeletonRenderer
                         .GetComponentsInChildren<Renderer>(true))
            {
                if (line != null && line != rig.Skin)
                {
                    rig.SkeletonRenderers.Add(line);
                }
            }
        }

        /// <summary>腕到食指尖的距离应该在 3cm~25cm，超出视为关节数据退化。</summary>
        private static bool IsChainCollapsed(HandRig rig)
        {
            var bones = rig.Skeleton?.Bones;
            if (bones == null || bones.Count == 0)
            {
                return false;
            }
            Transform wrist = null;
            Transform tip = null;
            foreach (var bone in bones)
            {
                if (bone?.Transform == null)
                {
                    continue;
                }
                if (bone.Id == OVRSkeleton.BoneId.Hand_WristRoot ||
                    bone.Id == OVRSkeleton.BoneId.XRHand_Wrist)
                {
                    wrist = bone.Transform;
                }
                else if (bone.Id == OVRSkeleton.BoneId.Hand_IndexTip ||
                         bone.Id == OVRSkeleton.BoneId.XRHand_IndexTip)
                {
                    tip = bone.Transform;
                }
            }
            if (wrist == null || tip == null)
            {
                return false;
            }
            var distance = Vector3.Distance(wrist.position, tip.position);
            return distance < 0.03f || distance > 0.25f;
        }

        private void LogDiagnostics()
        {
            var builder = new StringBuilder();
            builder.Append("[QiyuInput] connected=")
                .Append(OVRInput.GetConnectedControllers())
                .Append(" active=").Append(OVRInput.GetActiveController())
                .Append(" ctrlDriven=").Append(OVRPlugin.IsControllerDrivenHandPosesEnabled())
                .Append(" natural=").Append(OVRPlugin.AreControllerDrivenHandPosesNatural())
                .Append(" hasFocus=").Append(OVRManager.hasInputFocus);

            foreach (var hand in _hands)
            {
                if (hand?.Hand == null)
                {
                    continue;
                }
                var skeleton = hand.Hand.GetComponentInChildren<OVRSkeleton>(true);
                builder.Append(" | ").Append(hand.Hand.name)
                    .Append(" valid=").Append(hand.Hand.IsDataValid)
                    .Append(" tracked=").Append(hand.Hand.IsTracked)
                    .Append(" conf=").Append(hand.Hand.HandConfidence)
                    .Append(" inferred=").Append(hand.Hand.PoseSourceInferred)
                    .Append(" bones=").Append(skeleton?.Bones?.Count ?? -1)
                    .Append(" skelPos=").Append(Format(hand.Skeleton != null
                        ? hand.Skeleton.transform.position
                        : Vector3.zero))
                    .Append(" tipPos=").Append(Format(FindTip(hand.Skeleton)))
                    .Append(" meshRenderer=").Append(hand.MeshRenderer != null)
                    .Append(" meshInit=").Append(hand.MeshRenderer?.IsInitialized)
                    .Append(" skin=").Append(hand.Skin != null && hand.Skin.enabled)
                    .Append(" skel=").Append(hand.SkeletonRenderer != null &&
                                              hand.SkeletonRenderer.enabled);
            }
            foreach (var helper in _controllers)
            {
                if (helper == null)
                {
                    continue;
                }
                builder.Append(" | ctrl ").Append(helper.name)
                    .Append(" active=").Append(helper.IsActive())
                    .Append(" connected=")
                    .Append(OVRInput.IsControllerConnected(helper.m_controller));
            }
            Debug.Log(builder.ToString());
        }

        private static Vector3 FindTip(OVRSkeleton skeleton)
        {
            if (skeleton?.Bones == null)
            {
                return Vector3.zero;
            }
            foreach (var bone in skeleton.Bones)
            {
                if (bone?.Transform == null)
                {
                    continue;
                }
                if (bone.Id == OVRSkeleton.BoneId.Hand_IndexTip ||
                    bone.Id == OVRSkeleton.BoneId.XRHand_IndexTip)
                {
                    return bone.Transform.position;
                }
            }
            return Vector3.zero;
        }

        private static string Format(Vector3 value)
        {
            return $"({value.x:F2},{value.y:F2},{value.z:F2})";
        }

        private static void SetPrivateField(object target, string field, object value)
        {
            if (target == null)
            {
                return;
            }
            var info = target.GetType().GetField(field,
                BindingFlags.Instance | BindingFlags.NonPublic);
            if (info == null)
            {
                return;
            }
            var converted = info.FieldType.IsEnum
                ? System.Enum.ToObject(info.FieldType, value)
                : System.Convert.ChangeType(value, info.FieldType);
            info.SetValue(target, converted);
        }
    }
}
