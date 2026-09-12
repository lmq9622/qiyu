using UnityEngine;

namespace Qiyu.Quest.Behavior
{
    /// <summary>
    /// 把用户的实时动捕套到 Avatar 上（镜像 Avatar）。
    ///
    /// 输入：HumanMotionCapture 的实时状态（头 + 双手；设备支持时含躯干）。
    /// 输出：Avatar 的 Hips/Chest/Head 旋转 + 双臂双骨 IK 到双手目标。
    ///
    /// 空间约定：
    /// - 用户位姿在 tracking 空间（相对 userOrigin）；
    /// - 映射到 Avatar 时可选左右镜像（mirrorX），让 Avatar 成为"镜子里的你"；
    /// - 全程指数平滑，不做瞬时跳变。
    ///
    /// 说明：Quest 3S 无全身追踪，因此腿部由 Avatar 自身的 Idle/Walk 层负责，
    /// 本组件只驱动上半身，避免"腿乱甩"。
    /// </summary>
    [DefaultExecutionOrder(300)]
    public class MocapAvatarDriver : MonoBehaviour
    {
        [Header("数据源")]
        [SerializeField] private HumanMotionCapture motionCapture;
        [SerializeField] private Transform userOrigin;

        [Header("目标 Avatar")]
        [SerializeField] private Transform avatarRoot;
        [SerializeField] private Animator avatarAnimator;

        [Header("映射")]
        [SerializeField] private bool enableMocap = true;
        [SerializeField] private bool mirrorX = true;
        [SerializeField] private float smoothSpeed = 14f;
        [SerializeField] private float headYawFollowOnChest = 0.35f;
        [SerializeField] private float armReachScale = 1f;

        private Transform _head;
        private Transform _chest;
        private Transform _hips;
        private Transform _leftShoulder;
        private Transform _rightShoulder;
        private Transform _leftUpperArm;
        private Transform _rightUpperArm;
        private Transform _leftLowerArm;
        private Transform _rightLowerArm;

        private Vector3 _headTarget;
        private Quaternion _headRotationTarget = Quaternion.identity;
        private float _hipsYawTarget;
        private Vector3 _leftHandTarget;
        private Vector3 _rightHandTarget;
        private bool _initialized;
        private bool _hasUser;

        public bool MocapActive => enableMocap && _initialized && _hasUser;
        public int AppliedFrames { get; private set; }

        private void Awake()
        {
            if (motionCapture == null)
            {
                motionCapture = FindAnyObjectByType<HumanMotionCapture>();
            }
            if (avatarAnimator == null && avatarRoot != null)
            {
                avatarAnimator = avatarRoot.GetComponentInChildren<Animator>();
            }
            Initialize();
        }

        private void Initialize()
        {
            if (avatarAnimator == null || !avatarAnimator.isHuman)
            {
                return;
            }
            _head = avatarAnimator.GetBoneTransform(HumanBodyBones.Head);
            _chest = avatarAnimator.GetBoneTransform(HumanBodyBones.Chest)
                     ?? avatarAnimator.GetBoneTransform(HumanBodyBones.Spine);
            _hips = avatarAnimator.GetBoneTransform(HumanBodyBones.Hips);
            _leftShoulder = avatarAnimator.GetBoneTransform(HumanBodyBones.LeftShoulder)
                            ?? avatarAnimator.GetBoneTransform(HumanBodyBones.LeftUpperArm);
            _rightShoulder = avatarAnimator.GetBoneTransform(HumanBodyBones.RightShoulder)
                             ?? avatarAnimator.GetBoneTransform(HumanBodyBones.RightUpperArm);
            _leftUpperArm = avatarAnimator.GetBoneTransform(HumanBodyBones.LeftUpperArm);
            _rightUpperArm = avatarAnimator.GetBoneTransform(HumanBodyBones.RightUpperArm);
            _leftLowerArm = avatarAnimator.GetBoneTransform(HumanBodyBones.LeftLowerArm);
            _rightLowerArm = avatarAnimator.GetBoneTransform(HumanBodyBones.RightLowerArm);
            _initialized = _head != null;
            if (_initialized)
            {
                Debug.Log($"[MocapAvatar] 已绑定镜像 Avatar 骨骼 " +
                          $"head={_head != null} chest={_chest != null} " +
                          $"hips={_hips != null} arms=" +
                          $"{_leftUpperArm != null && _rightUpperArm != null}");
            }
            else
            {
                Debug.LogWarning("[MocapAvatar] Avatar 不是 Humanoid，动捕无法套用");
            }
        }

        private void LateUpdate()
        {
            if (!enableMocap || !_initialized || motionCapture == null)
            {
                return;
            }
            var state = motionCapture.CurrentState;
            _hasUser = state != null && state.headPose != null &&
                       state.confidence > 0.1f;
            if (!_hasUser)
            {
                return;
            }
            var dt = Mathf.Max(0.001f, Time.deltaTime);
            var blend = 1f - Mathf.Exp(-smoothSpeed * dt);

            // 头：位置 + 旋转（镜像后映射到 Avatar 空间）
            _headTarget = MapToAvatar(state.headPose.position);
            _headRotationTarget = MapRotation(state.headPose.rotation);
            _hipsYawTarget = NormalizeYaw(_headRotationTarget.eulerAngles.y);

            if (_hips != null)
            {
                var hipsEuler = _hips.rotation.eulerAngles;
                var yaw = Mathf.LerpAngle(hipsEuler.y, _hipsYawTarget, blend);
                _hips.rotation = Quaternion.Euler(hipsEuler.x, yaw, hipsEuler.z);
            }
            if (_chest != null)
            {
                var target = Mathf.LerpAngle(_hipsYawTarget, _headRotationTarget.eulerAngles.y,
                                             headYawFollowOnChest);
                var chestEuler = _chest.rotation.eulerAngles;
                _chest.rotation = Quaternion.Euler(
                    chestEuler.x,
                    Mathf.LerpAngle(chestEuler.y, target, blend),
                    chestEuler.z);
            }
            if (_head != null)
            {
                _head.rotation = Quaternion.Slerp(_head.rotation, _headRotationTarget, blend);
            }

            ApplyArm(true, state.leftHand, blend);
            ApplyArm(false, state.rightHand, blend);
            AppliedFrames++;
        }

        /// <summary>把一只手的目标位置做双骨 IK，驱动上臂/前臂。</summary>
        private void ApplyArm(bool isLeft, HumanHandState hand, float blend)
        {
            var upper = isLeft ? _leftUpperArm : _rightUpperArm;
            var lower = isLeft ? _leftLowerArm : _rightLowerArm;
            var shoulder = isLeft ? _leftShoulder : _rightShoulder;
            if (upper == null || lower == null || hand == null || !hand.tracked)
            {
                return;
            }
            var target = MapToAvatar(hand.tracked ? hand.wristPosition : hand.pointerPosition);
            var root = shoulder != null ? shoulder.position : upper.position;
            var upperLength = Vector3.Distance(upper.position, lower.position);
            var forearmLength = lower.childCount > 0
                ? Vector3.Distance(lower.position, lower.GetChild(0).position)
                : upperLength;
            if (upperLength < 1e-4f)
            {
                return;
            }
            forearmLength = Mathf.Max(forearmLength, upperLength * 0.6f);
            var reach = Vector3.Distance(root, target) * armReachScale;
            var maxReach = (upperLength + forearmLength) * 0.98f;
            var direction = (target - root);
            if (direction.sqrMagnitude < 1e-6f)
            {
                return;
            }
            direction.Normalize();
            if (reach > maxReach)
            {
                target = root + direction * maxReach;
                reach = maxReach;
            }
            // 肘部朝向：向下 + 向外（与用户骨架一致的偏好方向）
            var pole = (Vector3.down + avatarRoot.right * (isLeft ? -0.35f : 0.35f)
                        - avatarRoot.forward * 0.25f).normalized;
            var elbow = SolveElbow(root, target, upperLength, forearmLength, pole);
            var upperDir = (elbow - root).normalized;
            var lowerDir = (target - elbow).normalized;

            // 用增量方式施加，避免破坏 Avatar 的绑定姿态轴
            var currentUpperDir = (lower.position - upper.position).normalized;
            upper.rotation = Quaternion.FromToRotation(currentUpperDir, upperDir) * upper.rotation;
            var child = lower.childCount > 0 ? lower.GetChild(0) : null;
            if (child != null)
            {
                var currentLowerDir = (child.position - lower.position).normalized;
                lower.rotation = Quaternion.FromToRotation(currentLowerDir, lowerDir) *
                                 lower.rotation;
            }
        }

        private static Vector3 SolveElbow(Vector3 root, Vector3 target,
                                          float upperLength, float foreLength,
                                          Vector3 pole)
        {
            var axis = target - root;
            var distance = axis.magnitude;
            if (distance < 1e-4f)
            {
                return root + pole * upperLength;
            }
            var direction = axis / distance;
            var minReach = Mathf.Abs(upperLength - foreLength) + 1e-3f;
            var maxReach = upperLength + foreLength - 1e-3f;
            var clamped = Mathf.Clamp(distance, minReach, maxReach);
            var along = (clamped * clamped + upperLength * upperLength -
                         foreLength * foreLength) / (2f * clamped);
            var heightSquared = upperLength * upperLength - along * along;
            var height = heightSquared > 0f ? Mathf.Sqrt(heightSquared) : 0f;
            var projected = pole - direction * Vector3.Dot(pole, direction);
            if (projected.sqrMagnitude < 1e-6f)
            {
                projected = Vector3.Cross(direction, Vector3.right);
            }
            projected.Normalize();
            return root + direction * along + projected * height;
        }

        /// <summary>用户 tracking 坐标 → Avatar 世界坐标（可选左右镜像）。</summary>
        private Vector3 MapToAvatar(Vector3 userWorldPosition)
        {
            if (avatarRoot == null)
            {
                return userWorldPosition;
            }
            var origin = userOrigin != null ? userOrigin : avatarRoot;
            var local = origin.InverseTransformPoint(userWorldPosition);
            if (mirrorX)
            {
                local.x = -local.x;
            }
            return avatarRoot.TransformPoint(local);
        }

        /// <summary>用户头部旋转 → Avatar 头部世界旋转（镜像时反转偏航/翻滚）。</summary>
        private Quaternion MapRotation(Quaternion userWorldRotation)
        {
            var origin = userOrigin != null ? userOrigin : avatarRoot;
            var local = Quaternion.Inverse(origin.rotation) * userWorldRotation;
            if (mirrorX)
            {
                var euler = local.eulerAngles;
                local = Quaternion.Euler(euler.x, -euler.y, -euler.z);
            }
            return (avatarRoot != null ? avatarRoot.rotation : Quaternion.identity) * local;
        }

        private static float NormalizeYaw(float yaw)
        {
            return yaw > 180f ? yaw - 360f : yaw;
        }

        public void SetMocapEnabled(bool value)
        {
            enableMocap = value;
            Debug.Log($"[MocapAvatar] 动捕套用 {(value ? "开启" : "关闭")}");
        }
    }
}

