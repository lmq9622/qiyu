using System;
using UnityEngine;

namespace Qiyu.Quest.Behavior
{
    /// <summary>
    /// 人类与角色的共享注意力。
    ///
    /// 用户看物体 / 指向物体 / 看角色时，给出统一的 shared target 与置信度；
    /// 由 Behavior Runtime 决定 LookAt / Approach / Comment，而不是本层直接写骨骼。
    /// </summary>
    [DefaultExecutionOrder(-100)]
    public class SharedAttentionController : MonoBehaviour
    {
        [SerializeField] private CharacterWorldModel worldModel;
        [SerializeField] private Transform avatarRoot;
        [SerializeField] private float gazeAngleThreshold = 18f;
        [SerializeField] private float confidenceThreshold = 0.30f;

        public SharedAttentionData Current { get; private set; } = new SharedAttentionData();
        public event Action<SharedAttentionData> OnAttentionChanged;

        private string _lastSharedTarget = "";

        private void Awake()
        {
            if (worldModel == null)
            {
                worldModel = GetComponent<CharacterWorldModel>();
            }
            if (avatarRoot == null)
            {
                var found = GameObject.Find("QiyuAvatar");
                avatarRoot = found != null ? found.transform : transform;
            }
        }

        public void Tick(WorldSnapshotData world, CharacterStateData state,
                         BehaviorDecision decision)
        {
            if (world == null)
            {
                return;
            }
            var user = world.userState ?? new UserStateData();
            var humanFocus = ResolveHumanFocus(world, user);
            var avatarFocus = decision != null ? decision.targetId : "";
            var shared = humanFocus;
            if (humanFocus == "user" && avatarFocus != "user")
            {
                shared = "user";
            }
            else if (!string.IsNullOrEmpty(humanFocus) && humanFocus == avatarFocus)
            {
                shared = humanFocus;
            }
            var targetPosition = Vector3.zero;
            var targetEntity = world.FindEntity(shared);
            if (targetEntity != null)
            {
                targetPosition = targetEntity.position;
            }
            else if (shared == "user")
            {
                targetPosition = world.userPosition;
            }
            var alignment = ComputeAlignment(user, targetPosition);
            var confidence = Mathf.Clamp01(user.confidence *
                                           (string.IsNullOrEmpty(shared) ? 0.4f : 1f) *
                                           Mathf.Lerp(0.6f, 1f, alignment));
            Current = new SharedAttentionData
            {
                humanFocus = humanFocus,
                avatarFocus = avatarFocus,
                sharedTarget = confidence >= confidenceThreshold ? shared : "",
                sharedTargetPosition = targetPosition,
                gazeAlignment = alignment,
                attentionConfidence = confidence,
                updatedAtMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
            };
            world.sharedAttention = Current;
            worldModel?.SetSharedAttention(Current);
            if (Current.sharedTarget != _lastSharedTarget)
            {
                _lastSharedTarget = Current.sharedTarget;
                OnAttentionChanged?.Invoke(Current);
            }
        }

        private string ResolveHumanFocus(WorldSnapshotData world, UserStateData user)
        {
            if (avatarRoot != null)
            {
                var toAvatar = (avatarRoot.position - user.headPose.position).normalized;
                var angle = Vector3.Angle(user.gazeDirection, toAvatar);
                if (angle <= gazeAngleThreshold)
                {
                    return "user";
                }
            }
            if (!string.IsNullOrEmpty(user.gazeTargetId) &&
                world.FindEntity(user.gazeTargetId) != null)
            {
                return user.gazeTargetId;
            }
            if (!string.IsNullOrEmpty(user.interactionTarget) &&
                world.FindEntity(user.interactionTarget) != null)
            {
                return user.interactionTarget;
            }
            return "";
        }

        private static float ComputeAlignment(UserStateData user, Vector3 targetPosition)
        {
            if (targetPosition == Vector3.zero || user.gazeDirection.sqrMagnitude < 0.01f)
            {
                return 0.5f;
            }
            var direction = (targetPosition - user.headPose.position).normalized;
            var dot = Mathf.Clamp(Vector3.Dot(user.gazeDirection.normalized, direction), -1f, 1f);
            return Mathf.Clamp01((dot + 1f) * 0.5f);
        }
    }
}
