using UnityEngine;

namespace Qiyu.Quest.Behavior
{
    /// <summary>
    /// 无动画资产时的低精度程序化兜底。
    ///
    /// 只驱动少量 Humanoid 骨骼做呼吸、点头、倾听、思考、挥手等；
    /// 它不能替代专业 Walk/Run/Idle 动作资产，也不会伪装成完整动作库。
    /// </summary>
    public class ProceduralMotionFallback : MonoBehaviour
    {
        [SerializeField] private Animator animator;
        [SerializeField] private float blendSpeed = 5f;

        public bool Active { get; private set; }

        private Transform _hips;
        private Transform _chest;
        private Transform _head;
        private Transform _leftUpperArm;
        private Transform _rightUpperArm;
        private Transform _leftLowerArm;
        private Transform _rightLowerArm;
        private Quaternion _hipsRest;
        private Quaternion _chestRest;
        private Quaternion _headRest;
        private Quaternion _leftUpperRest;
        private Quaternion _rightUpperRest;
        private Quaternion _leftLowerRest;
        private Quaternion _rightLowerRest;
        private bool _initialized;
        private BehaviorKind _kind = BehaviorKind.Idle;
        private float _intensity = 0.4f;
        private float _startedAt;
        private Vector3 _currentHips;
        private Vector3 _currentChest;
        private Vector3 _currentHead;
        private Vector3 _currentLeftUpper;
        private Vector3 _currentRightUpper;
        private Vector3 _currentLeftLower;
        private Vector3 _currentRightLower;

        private void Awake()
        {
            if (animator == null)
            {
                animator = GetComponentInChildren<Animator>();
            }
            Initialize();
        }

        public void SetBehavior(BehaviorKind kind, float intensity)
        {
            if (!_initialized)
            {
                Initialize();
            }
            if (!_initialized)
            {
                return;
            }
            if (_kind != kind)
            {
                _startedAt = Time.time;
            }
            _kind = kind;
            _intensity = Mathf.Clamp01(intensity);
            Active = true;
        }

        public void Disable()
        {
            Active = false;
            _currentHips = Vector3.zero;
            _currentChest = Vector3.zero;
            _currentHead = Vector3.zero;
            _currentLeftUpper = Vector3.zero;
            _currentRightUpper = Vector3.zero;
            _currentLeftLower = Vector3.zero;
            _currentRightLower = Vector3.zero;
        }

        private void LateUpdate()
        {
            if (!Active || !_initialized)
            {
                return;
            }
            var t = Time.time - _startedAt;
            var targetHips = Vector3.zero;
            var targetChest = Vector3.zero;
            var targetHead = Vector3.zero;
            var targetLeftUpper = Vector3.zero;
            var targetRightUpper = Vector3.zero;
            var targetLeftLower = Vector3.zero;
            var targetRightLower = Vector3.zero;

            switch (_kind)
            {
                case BehaviorKind.ListenUser:
                    targetHead = new Vector3(
                        2f * Mathf.Sin(t * 1.7f),
                        2.5f,
                        4f * Mathf.Sin(t * 0.8f));
                    targetChest = new Vector3(0f, 0f, 1.5f * Mathf.Sin(t * 0.7f));
                    break;
                case BehaviorKind.Think:
                    targetHead = new Vector3(-5f, 9f, -6f) * _intensity;
                    targetRightUpper = new Vector3(-35f, 0f, -55f) * _intensity;
                    targetRightLower = new Vector3(-70f, 0f, 20f) * _intensity;
                    targetChest = new Vector3(2f, -3f, 0f) * _intensity;
                    break;
                case BehaviorKind.Speak:
                    targetHead = new Vector3(
                        1.5f * Mathf.Sin(t * 3.4f),
                        2f * Mathf.Sin(t * 1.3f),
                        1.2f * Mathf.Sin(t * 2.1f));
                    targetChest = new Vector3(0f, 1.2f * Mathf.Sin(t * 1.1f), 0f);
                    targetRightUpper = new Vector3(
                        0f, 0f, -8f * Mathf.Max(0f, Mathf.Sin(t * 1.8f)));
                    break;
                case BehaviorKind.Wave:
                    targetRightUpper = new Vector3(-20f, 0f, -110f) * _intensity;
                    targetRightLower = new Vector3(
                        0f, 18f * Mathf.Sin(t * 8f), -30f) * _intensity;
                    targetHead = new Vector3(0f, -4f, 2f) * _intensity;
                    break;
                case BehaviorKind.Nod:
                    targetHead = new Vector3(8f * Mathf.Sin(t * 7f), 0f, 0f);
                    break;
                case BehaviorKind.ShakeHead:
                    targetHead = new Vector3(0f, 12f * Mathf.Sin(t * 7f), 0f);
                    break;
                case BehaviorKind.Laugh:
                    targetChest = new Vector3(5f * Mathf.Sin(t * 6f), 0f, 0f);
                    targetHead = new Vector3(-4f, 0f, 0f);
                    targetLeftUpper = new Vector3(-10f, 0f, 18f) * _intensity;
                    targetRightUpper = new Vector3(-10f, 0f, -18f) * _intensity;
                    break;
                case BehaviorKind.Sigh:
                    targetChest = new Vector3(6f, 0f, 0f);
                    targetHead = new Vector3(7f, 0f, 0f);
                    break;
                case BehaviorKind.Surprised:
                    targetChest = new Vector3(-5f, 0f, 0f);
                    targetHead = new Vector3(-8f, 0f, 0f);
                    break;
                case BehaviorKind.ComfortUser:
                    targetChest = new Vector3(4f, 0f, 0f);
                    targetRightUpper = new Vector3(-25f, 0f, -35f) * _intensity;
                    targetHead = new Vector3(3f, -5f, 2f) * _intensity;
                    break;
                case BehaviorKind.Retreat:
                case BehaviorKind.ReflexStepBack:
                    targetChest = new Vector3(-4f, 0f, 0f);
                    targetHead = new Vector3(-2f, 0f, 0f);
                    break;
                default:
                    targetChest = new Vector3(0f, 0f, 1.2f * Mathf.Sin(t * 0.9f));
                    targetHead = new Vector3(
                        0.8f * Mathf.Sin(t * 0.7f),
                        1.4f * Mathf.Sin(t * 0.43f),
                        0.8f * Mathf.Sin(t * 0.61f));
                    targetHips = new Vector3(0f, 0.8f * Mathf.Sin(t * 0.37f), 0f);
                    break;
            }

            var blend = 1f - Mathf.Exp(-blendSpeed * Time.deltaTime);
            _currentHips = Vector3.Lerp(_currentHips, targetHips, blend);
            _currentChest = Vector3.Lerp(_currentChest, targetChest, blend);
            _currentHead = Vector3.Lerp(_currentHead, targetHead, blend);
            _currentLeftUpper = Vector3.Lerp(_currentLeftUpper, targetLeftUpper, blend);
            _currentRightUpper = Vector3.Lerp(_currentRightUpper, targetRightUpper, blend);
            _currentLeftLower = Vector3.Lerp(_currentLeftLower, targetLeftLower, blend);
            _currentRightLower = Vector3.Lerp(_currentRightLower, targetRightLower, blend);

            Apply(_hips, _hipsRest, _currentHips);
            Apply(_chest, _chestRest, _currentChest);
            Apply(_head, _headRest, _currentHead);
            Apply(_leftUpperArm, _leftUpperRest, _currentLeftUpper);
            Apply(_rightUpperArm, _rightUpperRest, _currentRightUpper);
            Apply(_leftLowerArm, _leftLowerRest, _currentLeftLower);
            Apply(_rightLowerArm, _rightLowerRest, _currentRightLower);
        }

        private void Initialize()
        {
            if (_initialized || animator == null || !animator.isHuman)
            {
                return;
            }
            _hips = animator.GetBoneTransform(HumanBodyBones.Hips);
            _chest = animator.GetBoneTransform(HumanBodyBones.Chest);
            _head = animator.GetBoneTransform(HumanBodyBones.Head);
            _leftUpperArm = animator.GetBoneTransform(HumanBodyBones.LeftUpperArm);
            _rightUpperArm = animator.GetBoneTransform(HumanBodyBones.RightUpperArm);
            _leftLowerArm = animator.GetBoneTransform(HumanBodyBones.LeftLowerArm);
            _rightLowerArm = animator.GetBoneTransform(HumanBodyBones.RightLowerArm);
            _hipsRest = RestOf(_hips);
            _chestRest = RestOf(_chest);
            _headRest = RestOf(_head);
            _leftUpperRest = RestOf(_leftUpperArm);
            _rightUpperRest = RestOf(_rightUpperArm);
            _leftLowerRest = RestOf(_leftLowerArm);
            _rightLowerRest = RestOf(_rightLowerArm);
            _initialized = _head != null || _chest != null;
            if (_initialized)
            {
                Debug.Log("[QiyuProceduralFallback] 无动作资产，启用低精度程序化兜底");
            }
        }

        private static Quaternion RestOf(Transform bone)
        {
            return bone != null ? bone.localRotation : Quaternion.identity;
        }

        private static void Apply(Transform bone, Quaternion rest, Vector3 additiveEuler)
        {
            if (bone == null)
            {
                return;
            }
            bone.localRotation = rest * Quaternion.Euler(additiveEuler);
        }
    }
}
