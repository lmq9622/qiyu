using Qiyu.Quest.Avatar;
using UnityEngine;

namespace Qiyu.Quest.Behavior
{
    /// <summary>
    /// Ambient Life 执行层：把 AmbientLifeCore 的策略输出叠加到 Avatar 骨骼与表情上。
    ///
    /// 关键点：
    /// - 策略在 Core 里（纯 C#，可离线测试），这里只做"读取上下文 + 落骨骼"；
    /// - 以**叠加**方式写入骨骼（乘法叠加增量四元数），不覆盖 Behavior/行走层的姿态；
    /// - 策略 10~30Hz 更新，骨骼叠加每帧更新，保证平滑；
    /// - 显式行为期间让位（由 CharacterBehaviorRuntime 的决策驱动）。
    ///
    /// 执行顺序必须晚于 ProceduralMotionFallback，否则会被它覆盖。
    /// </summary>
    [DefaultExecutionOrder(200)]
    public class AmbientLife : MonoBehaviour
    {
        [Header("配置")]
        [SerializeField] private bool enableAmbientLife = true;
        [SerializeField] private string personality = "balanced";
        [SerializeField] private int randomSeed = 20260912;
        [SerializeField] private float strategyHz = 20f;
        [SerializeField] private bool debugOverlay;

        [Header("强度（整体缩放，用于现场微调）")]
        [SerializeField] private float breathingScale = 1f;
        [SerializeField] private float microMotionScale = 1f;
        [SerializeField] private float gazeScale = 1f;

        [Header("引用（留空自动查找）")]
        [SerializeField] private Animator animator;
        [SerializeField] private CharacterWorldModel worldModel;
        [SerializeField] private CharacterBehaviorRuntime behaviorRuntime;
        [SerializeField] private CharacterLocomotionController locomotion;
        [SerializeField] private CharacterAttentionController attention;
        [SerializeField] private BlendShapeAvatarDriver expressionDriver;

        private AmbientLifeCore _core;
        private Transform _head;
        private Transform _chest;
        private Transform _spine;
        private Transform _hips;
        private Transform _leftShoulder;
        private Transform _rightShoulder;
        private Transform _leftUpperArm;
        private Transform _rightUpperArm;
        private Transform _leftEye;
        private Transform _rightEye;

        private float _nextStrategyAt;
        private AmbientFrame _frame;
        private bool _initialized;
        private string _lastExplicitBehavior = "";
        private float _lastStateLogAt;
        private float _lastLoggedActivity = -1f;

        private void Awake()
        {
            if (animator == null)
            {
                animator = GetComponentInChildren<Animator>();
            }
            if (worldModel == null)
            {
                worldModel = GetComponent<CharacterWorldModel>();
            }
            if (behaviorRuntime == null)
            {
                behaviorRuntime = GetComponent<CharacterBehaviorRuntime>();
            }
            if (locomotion == null)
            {
                locomotion = GetComponentInChildren<CharacterLocomotionController>();
            }
            if (attention == null)
            {
                attention = GetComponent<CharacterAttentionController>();
            }
            if (expressionDriver == null)
            {
                expressionDriver = GetComponentInChildren<BlendShapeAvatarDriver>();
            }
            var profile = personality == "calm" ? PersonalityMotionProfile.Calm()
                        : personality == "lively" ? PersonalityMotionProfile.Lively()
                        : PersonalityMotionProfile.Balanced();
            _core = new AmbientLifeCore(profile, randomSeed);
            Initialize();
        }

        private void Initialize()
        {
            if (animator == null || !animator.isHuman)
            {
                return;
            }
            _head = animator.GetBoneTransform(HumanBodyBones.Head);
            _chest = animator.GetBoneTransform(HumanBodyBones.Chest)
                     ?? animator.GetBoneTransform(HumanBodyBones.Spine);
            _spine = animator.GetBoneTransform(HumanBodyBones.Spine);
            _hips = animator.GetBoneTransform(HumanBodyBones.Hips);
            _leftShoulder = animator.GetBoneTransform(HumanBodyBones.LeftShoulder);
            _rightShoulder = animator.GetBoneTransform(HumanBodyBones.RightShoulder);
            _leftUpperArm = animator.GetBoneTransform(HumanBodyBones.LeftUpperArm);
            _rightUpperArm = animator.GetBoneTransform(HumanBodyBones.RightUpperArm);
            _leftEye = animator.GetBoneTransform(HumanBodyBones.LeftEye);
            _rightEye = animator.GetBoneTransform(HumanBodyBones.RightEye);
            _initialized = _head != null || _chest != null;
            if (_initialized)
            {
                if (expressionDriver != null)
                {
                    expressionDriver.ExternalBlinkControl = true;
                }
                Debug.Log($"[AmbientLife] 启动 profile={_core.Profile.name} " +
                          $"seed={randomSeed} 骨骼={( _head != null ? "head" : "")}" +
                          $"{(_chest != null ? "+chest" : "")}" +
                          $"{(_hips != null ? "+hips" : "")}" +
                          $"{(_leftEye != null ? "+eyes" : "")}");
            }
            else
            {
                Debug.LogWarning("[AmbientLife] 没有可用的 Humanoid 骨骼，Ambient 未启用");
            }
        }

        private void Update()
        {
            if (!enableAmbientLife || !_initialized || _core == null)
            {
                return;
            }
            var now = Time.unscaledTime;
            if (now < _nextStrategyAt)
            {
                return;
            }
            var interval = 1f / Mathf.Clamp(strategyHz, 5f, 30f);
            _nextStrategyAt = now + interval;
            var context = BuildContext();
            _frame = _core.Tick(interval, context);
            SyncExplicitBehaviorState(context);
            ApplyExpression();
            LogStateIfNeeded(context);
        }

        /// <summary>从既有运行时读取上下文，不复制状态源。</summary>
        private AmbientContext BuildContext()
        {
            var context = new AmbientContext();
            var world = worldModel != null ? worldModel.Snapshot : null;
            if (world != null)
            {
                context.userPresent = world.userVisible;
                context.userDistance = world.userDistanceMeters;
                context.userSpeaking = world.userSpeaking;
                context.userLookingAtAvatar = world.userLookingAtAvatar;
                context.userApproaching = world.userApproachSpeedMps > 0.15f;
                context.userIdleSeconds = Mathf.Max(0f, world.userIdleSeconds);
                context.occluded = world.occluded;
            }
            if (locomotion != null)
            {
                context.locomotionSpeed = locomotion.CurrentSpeedMps;
                context.locomotionActive = context.locomotionSpeed > 0.05f;
            }
            if (behaviorRuntime != null)
            {
                var decision = behaviorRuntime.CurrentDecision;
                if (decision != null)
                {
                    var interactive = decision.kind != BehaviorKind.Idle &&
                                      decision.kind != BehaviorKind.Reposition;
                    context.explicitBehaviorActive = interactive;
                    context.explicitBehaviorPriority = interactive
                        ? Mathf.Max(70f, decision.priority) : 10f;
                }
            }
            return context;
        }

        /// <summary>显式行为开始/结束 → 通知 Core 让位/恢复（第十四/二十节）。</summary>
        private void SyncExplicitBehaviorState(AmbientContext context)
        {
            var decision = behaviorRuntime != null ? behaviorRuntime.CurrentDecision : null;
            var current = decision != null ? decision.kind.ToString() : "";
            var meaningful = decision != null && decision.kind != BehaviorKind.Idle
                             && decision.kind != BehaviorKind.Reposition;
            if (meaningful && current != _lastExplicitBehavior)
            {
                _core.NotifyExplicitBehavior(string.IsNullOrEmpty(current) ? "behavior" : current,
                    context.explicitBehaviorPriority, 2.0f);
                Debug.Log($"[AmbientLife] 行为覆盖 Ambient: {current}（Ambient 让位）");
            }
            else if (!meaningful && !string.IsNullOrEmpty(_lastExplicitBehavior))
            {
                _core.NotifyBehaviorComplete(_lastExplicitBehavior);
                Debug.Log($"[AmbientLife] 行为结束: {_lastExplicitBehavior} → 进入恢复阶段");
            }
            _lastExplicitBehavior = meaningful ? current : "";
        }

        private void ApplyExpression()
        {
            if (expressionDriver == null)
            {
                return;
            }
            // 眨眼由 Ambient 统一驱动（生理表现独立于行为）
            expressionDriver.SetBlink(_frame.blinkWeight);
        }

        /// <summary>
        /// 每帧叠加到骨骼：读当前姿态 × 增量四元数，不覆盖其它层。
        /// 必须在 ProceduralMotionFallback 之后执行（DefaultExecutionOrder=200）。
        /// </summary>
        private void LateUpdate()
        {
            if (!enableAmbientLife || !_initialized)
            {
                return;
            }
            var smooth = 1f - Mathf.Exp(-12f * Time.deltaTime);

            // 呼吸：胸腔 + 腹部 + 头微幅
            ApplyDelta(_chest, new Vector3(
                _frame.breathChestPitchDeg * breathingScale * smooth, 0f, 0f));
            ApplyDelta(_spine, new Vector3(
                _frame.breathBellyPitchDeg * breathingScale * smooth, 0f, 0f));
            ApplyDelta(_head, new Vector3(
                (_frame.breathHeadBobDeg + _frame.microHeadPitchDeg * microMotionScale)
                * breathingScale * smooth, 0f, 0f));

            // 姿态/重心：只用旋转表达，不改 localPosition。
            // 原因：位置是绝对量，叠加会逐帧累积（人会漂走），
            // 而且会和程序化行走的上下起伏互相打架。
            ApplyDelta(_hips, new Vector3(0f, 0f, _frame.hipsRollDeg * microMotionScale * smooth));
            ApplyDelta(_chest, new Vector3(0f, 0f, _frame.chestRollDeg * microMotionScale * smooth));
            // 侧向重心用脊椎微旋 + 头反向偏移近似
            ApplyDelta(_spine, new Vector3(0f, _frame.hipsSideMeters * 60f * microMotionScale * smooth, 0f));
            ApplyDelta(_head, new Vector3(0f, -_frame.hipsSideMeters * 30f * microMotionScale * smooth, 0f));

            // 微动作：头/肩/手臂/身体
            ApplyDelta(_head, new Vector3(
                0f,
                _frame.microHeadYawDeg * microMotionScale * smooth,
                _frame.microHeadRollDeg * microMotionScale * smooth));
            ApplyDelta(_chest, new Vector3(
                0f, 0f, _frame.microBodyDeg * microMotionScale * smooth));
            ApplyDelta(_leftShoulder, new Vector3(
                0f, 0f, _frame.microShoulderDeg * microMotionScale * smooth));
            ApplyDelta(_rightShoulder, new Vector3(
                0f, 0f, -_frame.microShoulderDeg * microMotionScale * smooth));
            ApplyDelta(_leftUpperArm, new Vector3(
                0f, 0f, _frame.microArmDeg * microMotionScale * smooth));
            ApplyDelta(_rightUpperArm, new Vector3(
                0f, 0f, -_frame.microArmDeg * microMotionScale * smooth));

            // 视线：眼睛优先，头部按比例跟随；行为要求看用户时由 Core 归零
            var gazeYaw = _frame.gazeYawDeg * gazeScale;
            var gazePitch = _frame.gazePitchDeg * gazeScale;
            if (_leftEye != null || _rightEye != null)
            {
                ApplyDelta(_leftEye, new Vector3(gazePitch, gazeYaw, 0f));
                ApplyDelta(_rightEye, new Vector3(gazePitch, gazeYaw, 0f));
            }
            ApplyDelta(_head, new Vector3(
                _frame.headPitchDeg * gazeScale * smooth,
                _frame.headYawDeg * gazeScale * smooth,
                0f));
        }

        private static void ApplyDelta(Transform bone, Vector3 eulerDelta)
        {
            if (bone == null || eulerDelta.sqrMagnitude < 1e-8f)
            {
                return;
            }
            bone.localRotation = bone.localRotation * Quaternion.Euler(eulerDelta);
        }

        /// <summary>Release 不打日志；状态明显变化或开了 debugOverlay 才输出。</summary>
        private void LogStateIfNeeded(AmbientContext context)
        {
            var now = Time.unscaledTime;
            var activityChanged = Mathf.Abs(_core.Activity - _lastLoggedActivity) > 0.15f;
            if (debugOverlay)
            {
                if (now - _lastStateLogAt >= 1f)
                {
                    _lastStateLogAt = now;
                    Debug.Log(_core.DebugLine() +
                              $" userPresent={context.userPresent}" +
                              $" userSpeaking={context.userSpeaking}");
                }
                return;
            }
            if (activityChanged)
            {
                _lastLoggedActivity = _core.Activity;
                if (now - _lastStateLogAt >= 5f)
                {
                    _lastStateLogAt = now;
                    Debug.Log($"[AmbientLife] activity={_core.Activity:F2} " +
                              $"attention={_core.Attention:F2} " +
                              $"gaze={_core.GazeTarget} posture={_core.PostureState} " +
                              $"ambient={_core.ActiveAmbientAction}");
                }
            }
        }

        /// <summary>供外部（如调试 HUD）读取的一行状态。</summary>
        public string StatusLine()
        {
            if (_core == null)
            {
                return "[AmbientLife] 未初始化";
            }
            return _core.DebugLine();
        }

        public AmbientFrame CurrentFrame => _frame;
        public float Activity => _core != null ? _core.Activity : 0f;
        public float Attention => _core != null ? _core.Attention : 0f;
    }
}


