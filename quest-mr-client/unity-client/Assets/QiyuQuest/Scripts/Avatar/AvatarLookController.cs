using UnityEngine;

namespace Qiyu.Quest.Avatar
{
    /// <summary>
    /// 头部/上身看向控制。LLM 只给 look_at_user / look_at_object 高层意图，
    /// 本层在骨骼层做限幅平滑，避免瞬移和反关节。
    /// </summary>
    public class AvatarLookController : MonoBehaviour
    {
        [Header("骨骼")]
        [SerializeField] private Transform headBone;
        [SerializeField] private Transform chestBone;
        [SerializeField] private bool autoFindHeadBone = true;

        [Header("参数")]
        [SerializeField] private float lookSpeed = 6f;
        [SerializeField] private float yawLimit = 70f;
        [SerializeField] private float pitchLimit = 35f;
        [SerializeField] private float chestWeight = 0.3f;
        [SerializeField] private Vector3 headRotationOffset = Vector3.zero;
        [SerializeField] private float lookAwayDurationSeconds = 1.2f;

        public Transform UserHead { get; set; }

        private enum Mode { Idle, User, Point, Away }

        private Mode _mode = Mode.Idle;
        private Vector3 _targetPosition;
        private float _awayUntil;
        private Quaternion _headRestRotation;
        private Quaternion _chestRestRotation;
        private bool _initialized;

        private void Start()
        {
            Initialize();
        }

        private void Initialize()
        {
            if (_initialized)
            {
                return;
            }
            if (headBone == null && autoFindHeadBone)
            {
                var animator = GetComponentInChildren<Animator>();
                if (animator != null && animator.isHuman)
                {
                    headBone = animator.GetBoneTransform(HumanBodyBones.Head);
                    if (chestBone == null)
                    {
                        chestBone = animator.GetBoneTransform(HumanBodyBones.Chest);
                    }
                }
            }
            if (headBone != null)
            {
                _headRestRotation = headBone.localRotation;
            }
            if (chestBone != null)
            {
                _chestRestRotation = chestBone.localRotation;
            }
            _initialized = true;
        }

        public void LookAtUser()
        {
            if (UserHead == null)
            {
                _mode = Mode.Idle;
                return;
            }
            _targetPosition = UserHead.position;
            _mode = Mode.User;
        }

        public void LookAtPosition(Vector3 worldPosition)
        {
            _targetPosition = worldPosition;
            _mode = Mode.Point;
        }

        public void LookAway()
        {
            _awayUntil = Time.time + lookAwayDurationSeconds;
            _mode = Mode.Away;
        }

        private void LateUpdate()
        {
            Initialize();
            if (headBone == null)
            {
                return;
            }
            if (_mode == Mode.Away && Time.time >= _awayUntil)
            {
                _mode = Mode.Idle;
            }
            if (_mode == Mode.User && UserHead != null)
            {
                _targetPosition = UserHead.position;
            }

            if (_mode == Mode.Idle)
            {
                headBone.localRotation = Quaternion.Slerp(
                    headBone.localRotation, _headRestRotation, Time.deltaTime * lookSpeed);
                if (chestBone != null)
                {
                    chestBone.localRotation = Quaternion.Slerp(
                        chestBone.localRotation, _chestRestRotation, Time.deltaTime * lookSpeed);
                }
                return;
            }

            var lookPoint = _mode == Mode.Away
                ? headBone.position + headBone.forward * 3f + headBone.right * 2f
                : _targetPosition;
            var direction = lookPoint - headBone.position;
            if (direction.sqrMagnitude < 0.0001f)
            {
                return;
            }
            var parentRotation = headBone.parent != null
                ? headBone.parent.rotation : Quaternion.identity;
            var worldRotation = Quaternion.LookRotation(direction.normalized, Vector3.up) *
                                Quaternion.Euler(headRotationOffset);
            var localTarget = Quaternion.Inverse(parentRotation) * worldRotation;
            var euler = NormalizeEuler(localTarget.eulerAngles);
            var clamped = Quaternion.Euler(
                Mathf.Clamp(euler.x, -pitchLimit, pitchLimit),
                Mathf.Clamp(euler.y, -yawLimit, yawLimit),
                0f);
            headBone.localRotation = Quaternion.Slerp(
                headBone.localRotation, clamped, Time.deltaTime * lookSpeed);

            if (chestBone != null)
            {
                var chestTarget = Quaternion.Slerp(
                    _chestRestRotation, clamped, chestWeight);
                chestBone.localRotation = Quaternion.Slerp(
                    chestBone.localRotation, chestTarget, Time.deltaTime * lookSpeed * 0.6f);
            }
        }

        private static Vector3 NormalizeEuler(Vector3 euler)
        {
            if (euler.x > 180f) euler.x -= 360f;
            if (euler.y > 180f) euler.y -= 360f;
            if (euler.z > 180f) euler.z -= 360f;
            return euler;
        }
    }
}
