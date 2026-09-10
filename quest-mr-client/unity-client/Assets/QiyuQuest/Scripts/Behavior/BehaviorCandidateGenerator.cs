using System;
using System.Collections.Generic;
using UnityEngine;

namespace Qiyu.Quest.Behavior
{
    /// <summary>
    /// 行为候选生成器。
    ///
    /// 每 tick 生成“行为 × 目标 × 连续参数”候选，而不是直接 if/else 选动作。
    /// 候选同时包含正确行为和大量硬负样本，交由 TinyBehaviorPolicy + Utility 仲裁。
    /// </summary>
    public class BehaviorCandidateGenerator
    {
        private readonly List<BehaviorCandidate> _candidates = new List<BehaviorCandidate>(48);

        public IReadOnlyList<BehaviorCandidate> Generate(CharacterStateData state,
                                                          WorldSnapshotData world,
                                                          AvatarIntentData intent)
        {
            _candidates.Clear();
            state ??= new CharacterStateData();
            world ??= new WorldSnapshotData();
            intent ??= new AvatarIntentData();

            var goal = BehaviorCatalog.FromGoal(intent.goal);
            var userVisible = world.userVisible;
            var userDistance = world.userDistanceMeters;
            var desiredDistance = DesiredDistance(state, intent);
            var nearestObject = world.NearestInterestingObject();
            var target = world.FindEntity(intent.target) ?? nearestObject;
            var targetVisible = target != null && target.visible;
            var socialAvailable = state.drives.socialBattery > 0.15f &&
                                  state.drives.energy > 0.08f;

            Add(BehaviorKind.Idle, "", 0.28f + (1f - intent.urgency) * 0.12f,
                desiredDistance, 0f, 0.15f, 0.05f, 0.05f,
                energyCost: 0f, interruptibility: 1f);
            Add(BehaviorKind.ObserveUser, "user",
                0.22f + (userVisible ? 0.22f : -0.6f),
                desiredDistance, 0f, 0.72f, 0.08f, 0.08f,
                energyCost: 0f, interruptibility: 1f,
                hardNegative: !userVisible);
            Add(BehaviorKind.ListenUser, "user",
                0.25f + (world.userSpeaking ? 0.6f : 0f) +
                (goal == BehaviorKind.ListenUser ? 0.35f : 0f),
                desiredDistance, 0f, 0.85f, 0.04f, 0.03f,
                energyCost: 0.02f, interruptibility: 1f,
                hardNegative: !userVisible);
            Add(BehaviorKind.Speak, "user",
                0.18f + (intent.speaking ? 0.5f : 0f) +
                (state.speechState == "speaking" ? 0.25f : 0f),
                desiredDistance, 0f, 0.75f, 0.35f, 0.16f,
                energyCost: 0.08f, interruptibility: 0.8f,
                hardNegative: !userVisible || (world.userSpeaking && !intent.speaking));
            Add(BehaviorKind.Think, target != null ? target.id : "",
                0.2f + (goal == BehaviorKind.Think ? 0.45f : 0f) +
                state.drives.curiosity * 0.15f,
                desiredDistance, 0f, 0.45f, 0.08f, 0.22f,
                energyCost: 0.01f, interruptibility: 1f);

            AddObjectCandidates(state, world, intent, target, targetVisible, desiredDistance);
            AddUserMotionCandidates(state, world, intent, userVisible, userDistance,
                desiredDistance, socialAvailable);
            AddGestureCandidates(state, world, intent, userVisible, desiredDistance);
            AddAutonomyCandidates(state, world, intent, nearestObject, desiredDistance);
            AddHardNegatives(state, world, intent, target, targetVisible, desiredDistance);

            for (var i = 0; i < _candidates.Count; i++)
            {
                var candidate = _candidates[i];
                candidate.features = BehaviorFeatureEncoder.Encode(state, world, intent, candidate);
                candidate.utility = Mathf.Clamp01(candidate.utility);
            }
            return _candidates;
        }

        private void AddObjectCandidates(CharacterStateData state, WorldSnapshotData world,
                                         AvatarIntentData intent, WorldEntityData target,
                                         bool targetVisible, float desiredDistance)
        {
            var goal = BehaviorCatalog.FromGoal(intent.goal);
            if (target == null)
            {
                Add(BehaviorKind.GoToObject, "", -0.5f, desiredDistance, 0f,
                    0f, 0f, 0f, 0.8f, 0.2f, hardNegative: true);
                Add(BehaviorKind.ObserveObject, "", -0.5f, desiredDistance, 0f,
                    0f, 0f, 0f, 0.05f, 1f, hardNegative: true);
                return;
            }

            var targetDistance = Vector3.Distance(world.userPosition, target.position);
            var targetGoal = goal == BehaviorKind.GoToObject ||
                             goal == BehaviorKind.ObserveObject ||
                             goal == BehaviorKind.InspectObject ||
                             goal == BehaviorKind.PointAtObject ||
                             goal == BehaviorKind.InviteToObject ||
                             goal == BehaviorKind.Sit;
            Add(BehaviorKind.ObserveObject, target.id,
                0.24f + (targetGoal ? 0.35f : 0f) + target.interest * 0.15f,
                desiredDistance, 0f, 0.78f, 0.08f, 0.1f,
                energyCost: 0.01f, interruptibility: 1f,
                hardNegative: !targetVisible);
            Add(BehaviorKind.GoToObject, target.id,
                0.16f + (goal == BehaviorKind.GoToObject ? 0.55f : 0f) +
                (targetDistance > 1.1f ? 0.08f : -0.1f),
                Mathf.Max(0.45f, desiredDistance), 0.72f, 0.6f, 0.12f, 0.12f,
                energyCost: 0.8f, interruptibility: 0.65f,
                hardNegative: !targetVisible || !world.navmeshReachable ||
                              state.drives.energy < 0.12f);
            Add(BehaviorKind.InspectObject, target.id,
                0.16f + (goal == BehaviorKind.InspectObject ? 0.55f : 0f),
                Mathf.Max(0.45f, desiredDistance * 0.75f), 0.55f, 0.9f, 0.3f, 0.08f,
                energyCost: 0.45f, interruptibility: 0.7f,
                hardNegative: !targetVisible || !target.isSmallObject);
            Add(BehaviorKind.PointAtObject, target.id,
                0.12f + (goal == BehaviorKind.PointAtObject ? 0.6f : 0f),
                desiredDistance, 0f, 0.65f, 0.65f, 0.08f,
                energyCost: 0.25f, interruptibility: 0.85f,
                hardNegative: !targetVisible);
            Add(BehaviorKind.InviteToObject, target.id,
                0.1f + (goal == BehaviorKind.InviteToObject ? 0.6f : 0f),
                Mathf.Max(0.55f, desiredDistance), 0.4f, 0.7f, 0.5f, 0.12f,
                energyCost: 0.55f, interruptibility: 0.65f,
                hardNegative: !targetVisible || !world.userVisible);
            Add(BehaviorKind.Sit, target.id,
                0.08f + (goal == BehaviorKind.Sit ? 0.7f : 0f),
                0.35f, 0f, 0.4f, 0.05f, 0.12f,
                energyCost: 0.55f, interruptibility: 0.6f,
                hardNegative: !target.isSeat || !targetVisible);
        }

        private void AddUserMotionCandidates(CharacterStateData state, WorldSnapshotData world,
                                             AvatarIntentData intent, bool userVisible,
                                             float userDistance, float desiredDistance,
                                             bool socialAvailable)
        {
            var goal = BehaviorCatalog.FromGoal(intent.goal);
            Add(BehaviorKind.ApproachUser, "user",
                0.12f + (goal == BehaviorKind.ApproachUser ? 0.6f : 0f) +
                (userDistance > desiredDistance + 0.3f ? 0.18f : -0.2f) +
                state.relationship.affinity / 500f,
                desiredDistance, 0.62f, 0.7f, 0.08f, 0.08f,
                energyCost: 0.7f, interruptibility: 0.7f,
                hardNegative: !userVisible || !socialAvailable ||
                              userDistance <= desiredDistance);
            Add(BehaviorKind.MaintainDistance, "user",
                0.18f + (goal == BehaviorKind.MaintainDistance ? 0.55f : 0f) +
                (Mathf.Abs(userDistance - desiredDistance) < 0.35f ? 0.18f : 0f),
                desiredDistance, 0.25f, 0.55f, 0.04f, 0.08f,
                energyCost: 0.18f, interruptibility: 1f,
                hardNegative: !userVisible);
            Add(BehaviorKind.Retreat, "user",
                0.08f + (goal == BehaviorKind.Retreat ? 0.6f : 0f) +
                (userDistance < 0.6f ? 0.45f : 0f),
                Mathf.Max(0.8f, desiredDistance), 0.5f, 0.5f, 0.02f, 0.06f,
                energyCost: 0.45f, interruptibility: 0.9f,
                hardNegative: !userVisible || userDistance > 1.0f);
            Add(BehaviorKind.FollowUser, "user",
                0.06f + (goal == BehaviorKind.FollowUser ? 0.65f : 0f) +
                (world.userRetreatSpeedMps > 0.2f ? 0.2f : 0f),
                desiredDistance, 0.68f, 0.72f, 0.05f, 0.08f,
                energyCost: 0.85f, interruptibility: 0.55f,
                hardNegative: !userVisible || !socialAvailable ||
                              state.relationship.affinity < 45f);
        }

        private void AddGestureCandidates(CharacterStateData state, WorldSnapshotData world,
                                          AvatarIntentData intent, bool userVisible,
                                          float desiredDistance)
        {
            var goal = BehaviorCatalog.FromGoal(intent.goal);
            Add(BehaviorKind.Wave, "user",
                0.06f + (goal == BehaviorKind.Wave ? 0.75f : 0f) +
                (state.emotion.valence > 0.35f ? 0.08f : 0f),
                desiredDistance, 0f, 0.7f, 0.85f, 0.1f,
                energyCost: 0.2f, interruptibility: 0.8f,
                hardNegative: !userVisible);
            Add(BehaviorKind.Nod, "user",
                0.08f + (goal == BehaviorKind.Nod ? 0.7f : 0f) +
                (world.userSpeaking ? 0.12f : 0f),
                desiredDistance, 0f, 0.75f, 0.8f, 0.08f,
                energyCost: 0.08f, interruptibility: 0.95f,
                hardNegative: !userVisible);
            Add(BehaviorKind.ShakeHead, "user",
                0.05f + (goal == BehaviorKind.ShakeHead ? 0.75f : 0f),
                desiredDistance, 0f, 0.6f, 0.7f, 0.1f,
                energyCost: 0.08f, interruptibility: 0.9f,
                hardNegative: !userVisible);
            Add(BehaviorKind.Laugh, "user",
                0.04f + (goal == BehaviorKind.Laugh ? 0.75f : 0f) +
                Mathf.Max(0f, state.emotion.valence) * 0.15f,
                desiredDistance, 0f, 0.55f, 0.6f, 0.14f,
                energyCost: 0.12f, interruptibility: 0.85f,
                hardNegative: !userVisible);
            Add(BehaviorKind.Sigh, "",
                0.04f + (goal == BehaviorKind.Sigh ? 0.7f : 0f) +
                Mathf.Max(0f, -state.emotion.valence) * 0.15f,
                desiredDistance, 0f, 0.25f, 0.35f, 0.22f,
                energyCost: 0.05f, interruptibility: 1f);
            Add(BehaviorKind.Surprised, "user",
                0.03f + (goal == BehaviorKind.Surprised ? 0.8f : 0f) +
                state.emotion.arousal * 0.12f,
                desiredDistance, 0f, 0.65f, 0.55f, 0.1f,
                energyCost: 0.05f, interruptibility: 0.95f,
                hardNegative: !userVisible);
            Add(BehaviorKind.ComfortUser, "user",
                0.05f + (goal == BehaviorKind.ComfortUser ? 0.75f : 0f) +
                state.relationship.trust / 400f,
                Mathf.Max(0.55f, desiredDistance), 0.2f, 0.8f, 0.35f, 0.12f,
                energyCost: 0.3f, interruptibility: 0.75f,
                hardNegative: !userVisible || state.drives.patience < 0.2f);
        }

        private void AddAutonomyCandidates(CharacterStateData state, WorldSnapshotData world,
                                           AvatarIntentData intent, WorldEntityData nearestObject,
                                           float desiredDistance)
        {
            if (intent.AgeSeconds < 8f)
            {
                return;
            }
            var curiosity = state.drives.curiosity;
            var social = state.drives.socialBattery;
            Add(BehaviorKind.ObserveObject, nearestObject != null ? nearestObject.id : "",
                0.1f + curiosity * 0.35f,
                desiredDistance, 0f, 0.65f, 0.08f, 0.2f,
                energyCost: 0.01f, interruptibility: 1f,
                hardNegative: nearestObject == null);
            Add(BehaviorKind.Reposition, "",
                0.04f + curiosity * 0.18f + (1f - state.drives.energy) * -0.1f,
                desiredDistance, 0.35f, 0.4f, 0.08f, 0.22f,
                energyCost: 0.6f, interruptibility: 0.8f,
                hardNegative: state.drives.energy < 0.25f || !world.navmeshReachable);
            Add(BehaviorKind.ObserveUser, "user",
                0.08f + social * 0.28f + state.relationship.affinity / 600f,
                desiredDistance, 0f, 0.7f, 0.06f, 0.12f,
                energyCost: 0f, interruptibility: 1f,
                hardNegative: !world.userVisible);
        }

        private void AddHardNegatives(CharacterStateData state, WorldSnapshotData world,
                                      AvatarIntentData intent, WorldEntityData target,
                                      bool targetVisible, float desiredDistance)
        {
            // 这些候选故意保留在列表中，让学习模型和仲裁器学会拒绝。
            Add(BehaviorKind.ApproachUser, "user", 0.25f,
                desiredDistance, 0.7f, 0.6f, 0.05f, 0.05f,
                energyCost: 0.8f, interruptibility: 0.5f,
                hardNegative: true, reason: "unnecessary_movement");
            Add(BehaviorKind.GoToObject, target != null ? target.id : "missing",
                0.25f, desiredDistance, 0.7f, 0.5f, 0.05f, 0.05f,
                energyCost: 0.9f, interruptibility: 0.4f,
                hardNegative: true, reason: "unnecessary_movement");
            Add(BehaviorKind.Speak, "user", 0.2f,
                desiredDistance, 0f, 0.6f, 0.5f, 0.1f,
                energyCost: 0.1f, interruptibility: 0.4f,
                hardNegative: world.userSpeaking,
                reason: "speak_while_user_speaks");
            Add(BehaviorKind.ObserveObject, target != null ? target.id : "missing",
                0.2f, desiredDistance, 0f, 0.9f, 0.02f, 0.02f,
                energyCost: 0f, interruptibility: 1f,
                hardNegative: true, reason: "target_missing_or_invisible");
            Add(BehaviorKind.Reposition, "", 0.18f,
                desiredDistance, 0.4f, 0.35f, 0.05f, 0.05f,
                energyCost: 0.7f, interruptibility: 0.4f,
                hardNegative: state.recentSwitchCount > 2,
                reason: "high_frequency_switching");
        }

        private void Add(BehaviorKind kind, string targetId, float baseUtility,
                         float desiredDistance, float speedScale, float gazeWeight,
                         float gestureProbability, float lookAwayRate,
                         float energyCost, float interruptibility,
                         bool hardNegative = false, string reason = "")
        {
            var utility = baseUtility;
            if (hardNegative)
            {
                utility -= 0.85f;
            }
            _candidates.Add(new BehaviorCandidate
            {
                kind = kind,
                targetId = targetId ?? "",
                utility = utility,
                desiredDistanceMeters = Mathf.Clamp(desiredDistance, 0.35f, 3f),
                speedScale = Mathf.Clamp01(speedScale),
                gazeWeight = Mathf.Clamp01(gazeWeight),
                gestureProbability = Mathf.Clamp01(gestureProbability),
                lookAwayRate = Mathf.Clamp01(lookAwayRate),
                speechUrge = kind == BehaviorKind.Speak ? 0.8f :
                    (kind == BehaviorKind.ComfortUser ? 0.55f : 0.05f),
                energyCost = Mathf.Clamp01(energyCost),
                interruptibility = Mathf.Clamp01(interruptibility),
                hardNegative = hardNegative,
                reason = reason ?? "",
                novelty = NoveltyFor(kind),
            });
        }

        private static float DesiredDistance(CharacterStateData state, AvatarIntentData intent)
        {
            var baseDistance = 1.1f;
            baseDistance -= (state.relationship.affinity - 50f) / 200f;
            baseDistance -= Mathf.Max(0f, state.emotion.valence) * 0.15f;
            if (string.Equals(intent.behaviorStyle, "shy", StringComparison.Ordinal))
            {
                baseDistance += 0.35f;
            }
            if (string.Equals(intent.behaviorStyle, "warm", StringComparison.Ordinal))
            {
                baseDistance -= 0.2f;
            }
            if (intent.spatialTargetId == "user")
            {
                baseDistance = intent.desiredDistanceMeters;
            }
            return Mathf.Clamp(baseDistance, 0.55f, 2.2f);
        }

        private static float NoveltyFor(BehaviorKind kind)
        {
            switch (kind)
            {
                case BehaviorKind.Idle:
                case BehaviorKind.ObserveUser:
                case BehaviorKind.ObserveObject:
                    return 0.15f;
                case BehaviorKind.Wave:
                case BehaviorKind.Laugh:
                case BehaviorKind.Surprised:
                    return 0.8f;
                default:
                    return 0.45f;
            }
        }
    }
}
