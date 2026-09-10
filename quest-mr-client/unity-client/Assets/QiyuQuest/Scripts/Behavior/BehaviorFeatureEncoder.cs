using System;
using UnityEngine;

namespace Qiyu.Quest.Behavior
{
    /// <summary>
    /// Behavior Policy 固定特征编码器。
    /// 特征顺序必须与 Python 训练/导出脚本完全一致。
    /// </summary>
    public static class BehaviorFeatureEncoder
    {
        public const int StateFeatureCount = 52;
        public const int GoalFeatureCount = 8;
        public const int BehaviorFeatureCount = 29;
        public const int TargetTypeFeatureCount = 6;
        public const int CandidateFeatureCount = 9;
        public const int InputDimension =
            StateFeatureCount + GoalFeatureCount + BehaviorFeatureCount +
            TargetTypeFeatureCount + CandidateFeatureCount;

        public static readonly string[] FeatureNames = BuildFeatureNames();

        public static float[] Encode(CharacterStateData state, WorldSnapshotData world,
                                     AvatarIntentData intent, BehaviorCandidate candidate)
        {
            var features = new float[InputDimension];
            var i = 0;
            state ??= new CharacterStateData();
            world ??= new WorldSnapshotData();
            intent ??= new AvatarIntentData();
            candidate ??= new BehaviorCandidate();

            Add(features, ref i, state.drives.energy);
            Add(features, ref i, state.drives.patience);
            Add(features, ref i, state.drives.curiosity);
            Add(features, ref i, state.drives.socialBattery);
            Add(features, ref i, state.drives.stress);
            Add(features, ref i, (state.emotion.valence + 1f) * 0.5f);
            Add(features, ref i, state.emotion.arousal);
            Add(features, ref i, state.emotion.intensity);
            Add(features, ref i, state.relationship.affinity / 100f);
            Add(features, ref i, state.relationship.trust / 100f);
            Add(features, ref i, state.relationship.familiarity / 100f);
            Add(features, ref i, intent.urgency);
            Add(features, ref i, intent.socialPriority);
            Add(features, ref i, Clamp01(intent.AgeSeconds / 10f));
            Add(features, ref i, world.userVisible ? 1f : 0f);
            Add(features, ref i, Clamp01(world.userDistanceMeters / 5f));
            Add(features, ref i, ClampSigned(world.userRelativeAngleDegrees / 180f));
            Add(features, ref i, Clamp01(world.userApproachSpeedMps / 2f));
            Add(features, ref i, Clamp01(world.userRetreatSpeedMps / 2f));
            Add(features, ref i, world.userSpeaking ? 1f : 0f);
            Add(features, ref i, world.userLookingAtAvatar ? 1f : 0f);
            Add(features, ref i, string.IsNullOrEmpty(world.userPointingTargetId) ? 0f : 1f);
            Add(features, ref i, Clamp01(world.userIdleSeconds / 30f));
            Add(features, ref i, state.speechState == "speaking" ? 1f : 0f);
            Add(features, ref i, state.speechState == "listening" ? 1f : 0f);
            Add(features, ref i, state.speechState == "thinking" ? 1f : 0f);
            Add(features, ref i, Clamp01(state.currentBehaviorAgeSeconds / 10f));
            Add(features, ref i, Clamp01(state.recentSwitchCount / 10f));
            Add(features, ref i, Clamp01(world.collisionRisk));
            Add(features, ref i, Clamp01(world.nearestObstacleMeters / 2f));
            Add(features, ref i, world.navmeshGenerated && world.navmeshReachable ? 1f : 0f);

            var target = world.FindEntity(candidate.targetId);
            Add(features, ref i, target != null ? 1f : 0f);
            Add(features, ref i, target != null
                ? Clamp01(Vector3.Distance(world.userPosition, target.position) / 6f)
                : 1f);
            Add(features, ref i, target != null ? TargetAngleNorm(world, target) : 1f);
            Add(features, ref i, target != null && target.visible ? 1f : 0f);
            Add(features, ref i, target != null ? Clamp01(target.lastSeenAgeSeconds / 30f) : 1f);
            Add(features, ref i, target != null && target.isSeat ? 1f : 0f);
            Add(features, ref i, target != null && target.isSurface ? 1f : 0f);
            Add(features, ref i, target != null && target.isSmallObject ? 1f : 0f);
            Add(features, ref i, target != null ? target.interest : 0f);
            Add(features, ref i, Clamp01(world.entities.Count / 12f));
            Add(features, ref i, NearestObjectDistanceNorm(world));
            Add(features, ref i, world.sceneStable ? 1f : 0f);
            Add(features, ref i, Clamp01(world.worldAgeSeconds / 10f));
            Add(features, ref i, intent.AgeSeconds > 12f ? 1f : 0f);
            Add(features, ref i, Clamp01(state.salientMemoryCount / 6f));
            Add(features, ref i, RelationshipTierNorm(state.relationship.tier));
            Add(features, ref i, Clamp01(state.lastInteractionAgeSeconds / 60f));
            Add(features, ref i, state.lastAutonomyRequestAgeSeconds > 45f ? 1f : 0f);
            Add(features, ref i, RepetitionPenalty(state));
            Add(features, ref i, DistancePreferenceError(world, candidate));
            Add(features, ref i, candidate.energyCost);

            SetOneHot(features, StateFeatureCount, GoalFeatureCount, GoalGroup(intent.goal));
            SetOneHot(features, StateFeatureCount + GoalFeatureCount,
                BehaviorFeatureCount, (int)candidate.kind);
            SetOneHot(features, StateFeatureCount + GoalFeatureCount + BehaviorFeatureCount,
                TargetTypeFeatureCount, TargetType(candidate.targetId, target, world));

            var candidateOffset = StateFeatureCount + GoalFeatureCount +
                                   BehaviorFeatureCount + TargetTypeFeatureCount;
            Add(features, ref candidateOffset, AffordanceMatch(candidate.kind, target));
            Add(features, ref candidateOffset, DistanceFit(candidate.kind, world, candidate));
            Add(features, ref candidateOffset, SocialFit(candidate.kind, state, world));
            Add(features, ref candidateOffset, candidate.energyCost);
            Add(features, ref candidateOffset, candidate.interruptibility);
            Add(features, ref candidateOffset, MotionCost(candidate.kind));
            Add(features, ref candidateOffset, candidate.novelty);
            Add(features, ref candidateOffset, EmotionMatch(candidate.kind, state));
            Add(features, ref candidateOffset, GoalMatch(candidate.kind, intent.goal));
            return features;
        }

        public static int GoalGroup(string goal)
        {
            switch ((goal ?? "").ToLowerInvariant())
            {
                case "idle": return 0;
                case "observe_user":
                case "observe_object": return 1;
                case "listen_user":
                case "speak":
                case "think": return 2;
                case "approach_user":
                case "maintain_distance":
                case "retreat":
                case "follow_user": return 3;
                case "go_to_object":
                case "inspect_object":
                case "invite_to_object":
                case "sit":
                case "stand":
                case "reposition": return 4;
                case "wave":
                case "nod":
                case "shake_head":
                case "laugh":
                case "sigh":
                case "surprised": return 5;
                case "point_at_object": return 6;
                case "comfort_user": return 7;
                default: return 0;
            }
        }

        private static int TargetType(string targetId, WorldEntityData target, WorldSnapshotData world)
        {
            if (string.Equals(targetId, "user", StringComparison.Ordinal))
            {
                return 1;
            }
            if (target == null)
            {
                return 0;
            }
            if (target.isSeat)
            {
                return 4;
            }
            if (target.isSurface)
            {
                return 5;
            }
            return target.kind == "object" ? 3 : 2;
        }

        private static float TargetAngleNorm(WorldSnapshotData world, WorldEntityData target)
        {
            var direction = target.position - world.userPosition;
            direction.y = 0f;
            if (direction.sqrMagnitude < 0.0001f)
            {
                return 0f;
            }
            return ClampSigned(Vector3.SignedAngle(world.userForward, direction, Vector3.up) / 180f);
        }

        private static float NearestObjectDistanceNorm(WorldSnapshotData world)
        {
            var best = 99f;
            for (var i = 0; i < world.entities.Count; i++)
            {
                var entity = world.entities[i];
                if (entity == null || !entity.visible || entity.kind != "object")
                {
                    continue;
                }
                best = Mathf.Min(best, Vector3.Distance(world.userPosition, entity.position));
            }
            return Clamp01(best / 6f);
        }

        private static float RelationshipTierNorm(string tier)
        {
            switch ((tier ?? "").ToLowerInvariant())
            {
                case "stranger": return 0f;
                case "acquaintance": return 0.25f;
                case "friend": return 0.5f;
                case "close_friend": return 0.75f;
                case "intimate": return 1f;
                default: return 0.4f;
            }
        }

        private static float RepetitionPenalty(CharacterStateData state)
        {
            return Clamp01(state.recentSwitchCount / 8f) * 0.5f +
                   (1f - Clamp01(state.currentBehaviorAgeSeconds / 8f)) * 0.5f;
        }

        private static float DistancePreferenceError(WorldSnapshotData world, BehaviorCandidate candidate)
        {
            if (!world.userVisible)
            {
                return 0f;
            }
            return Clamp01(Mathf.Abs(world.userDistanceMeters - candidate.desiredDistanceMeters) / 3f);
        }

        private static float AffordanceMatch(BehaviorKind kind, WorldEntityData target)
        {
            if (kind == BehaviorKind.Sit)
            {
                return target != null && target.isSeat ? 1f : 0f;
            }
            if (kind == BehaviorKind.InspectObject || kind == BehaviorKind.ObserveObject ||
                kind == BehaviorKind.PointAtObject)
            {
                return target != null && target.isSmallObject ? 1f : 0.2f;
            }
            if (kind == BehaviorKind.GoToObject)
            {
                return target != null ? 0.8f : 0f;
            }
            return 0.5f;
        }

        private static float DistanceFit(BehaviorKind kind, WorldSnapshotData world,
                                         BehaviorCandidate candidate)
        {
            if (!world.userVisible)
            {
                return 0.5f;
            }
            if (kind == BehaviorKind.ApproachUser || kind == BehaviorKind.FollowUser)
            {
                return world.userDistanceMeters > candidate.desiredDistanceMeters + 0.2f ? 1f : 0f;
            }
            if (kind == BehaviorKind.Retreat)
            {
                return world.userDistanceMeters < 0.9f ? 1f : 0.1f;
            }
            if (kind == BehaviorKind.MaintainDistance)
            {
                return Mathf.Abs(world.userDistanceMeters - candidate.desiredDistanceMeters) < 0.35f
                    ? 1f : 0.2f;
            }
            return 0.6f;
        }

        private static float SocialFit(BehaviorKind kind, CharacterStateData state,
                                       WorldSnapshotData world)
        {
            var social = kind == BehaviorKind.ObserveUser || kind == BehaviorKind.ListenUser ||
                         kind == BehaviorKind.Speak || kind == BehaviorKind.ComfortUser ||
                         kind == BehaviorKind.Wave || kind == BehaviorKind.Nod;
            if (!social)
            {
                return 0.5f;
            }
            return Clamp01(state.drives.socialBattery * 0.5f +
                           state.relationship.affinity / 200f +
                           (world.userSpeaking ? 0.25f : 0f));
        }

        private static float MotionCost(BehaviorKind kind)
        {
            switch (kind)
            {
                case BehaviorKind.ApproachUser:
                case BehaviorKind.FollowUser:
                case BehaviorKind.GoToObject:
                case BehaviorKind.Reposition:
                    return 0.8f;
                case BehaviorKind.Retreat:
                case BehaviorKind.Sit:
                case BehaviorKind.Stand:
                    return 0.6f;
                case BehaviorKind.Wave:
                case BehaviorKind.PointAtObject:
                    return 0.35f;
                default:
                    return 0.05f;
            }
        }

        private static float EmotionMatch(BehaviorKind kind, CharacterStateData state)
        {
            var valence = state.emotion.valence;
            var arousal = state.emotion.arousal;
            switch (kind)
            {
                case BehaviorKind.Laugh:
                case BehaviorKind.Wave:
                    return Clamp01(valence * 0.7f + arousal * 0.3f);
                case BehaviorKind.ComfortUser:
                case BehaviorKind.ListenUser:
                    return Clamp01((1f - valence) * 0.3f + state.drives.patience * 0.7f);
                case BehaviorKind.Sigh:
                    return Clamp01((1f - valence) * 0.6f + (1f - arousal) * 0.4f);
                case BehaviorKind.Surprised:
                    return Clamp01(arousal);
                case BehaviorKind.Think:
                    return Clamp01(state.drives.curiosity);
                default:
                    return 0.5f;
            }
        }

        private static float GoalMatch(BehaviorKind kind, string goal)
        {
            return kind == BehaviorCatalog.FromGoal(goal) ? 1f : 0f;
        }

        private static void Add(float[] array, ref int index, float value)
        {
            if (index >= 0 && index < array.Length)
            {
                array[index] = float.IsNaN(value) || float.IsInfinity(value)
                    ? 0f : value;
            }
            index++;
        }

        private static void SetOneHot(float[] array, int offset, int count, int index)
        {
            if (index < 0 || index >= count)
            {
                return;
            }
            array[offset + index] = 1f;
        }

        private static float Clamp01(float value)
        {
            return Mathf.Clamp01(value);
        }

        private static float ClampSigned(float value)
        {
            return Mathf.Clamp(value, -1f, 1f);
        }

        private static string[] BuildFeatureNames()
        {
            var names = new string[InputDimension];
            var i = 0;
            AddName(names, ref i, "energy");
            AddName(names, ref i, "patience");
            AddName(names, ref i, "curiosity");
            AddName(names, ref i, "social_battery");
            AddName(names, ref i, "stress");
            AddName(names, ref i, "emotion_valence");
            AddName(names, ref i, "emotion_arousal");
            AddName(names, ref i, "emotion_intensity");
            AddName(names, ref i, "affinity_norm");
            AddName(names, ref i, "trust_norm");
            AddName(names, ref i, "familiarity_norm");
            AddName(names, ref i, "intent_urgency");
            AddName(names, ref i, "intent_social_priority");
            AddName(names, ref i, "intent_age_norm");
            AddName(names, ref i, "user_visible");
            AddName(names, ref i, "user_distance_norm");
            AddName(names, ref i, "user_angle_norm");
            AddName(names, ref i, "user_approach_norm");
            AddName(names, ref i, "user_retreat_norm");
            AddName(names, ref i, "user_speaking");
            AddName(names, ref i, "user_looking_at_avatar");
            AddName(names, ref i, "user_pointing");
            AddName(names, ref i, "user_idle_norm");
            AddName(names, ref i, "avatar_speaking");
            AddName(names, ref i, "avatar_listening");
            AddName(names, ref i, "avatar_thinking");
            AddName(names, ref i, "current_behavior_age_norm");
            AddName(names, ref i, "recent_switch_norm");
            AddName(names, ref i, "collision_risk");
            AddName(names, ref i, "obstacle_distance_norm");
            AddName(names, ref i, "navmesh_ok");
            AddName(names, ref i, "target_present");
            AddName(names, ref i, "target_distance_norm");
            AddName(names, ref i, "target_angle_norm");
            AddName(names, ref i, "target_visible");
            AddName(names, ref i, "target_age_norm");
            AddName(names, ref i, "target_is_seat");
            AddName(names, ref i, "target_is_surface");
            AddName(names, ref i, "target_is_small");
            AddName(names, ref i, "target_interest");
            AddName(names, ref i, "object_count_norm");
            AddName(names, ref i, "nearest_interest_distance_norm");
            AddName(names, ref i, "scene_stable");
            AddName(names, ref i, "world_age_norm");
            AddName(names, ref i, "intent_stale");
            AddName(names, ref i, "memory_salient_norm");
            AddName(names, ref i, "relationship_tier_norm");
            AddName(names, ref i, "last_interaction_age_norm");
            AddName(names, ref i, "autonomy_available");
            AddName(names, ref i, "repetition_penalty");
            AddName(names, ref i, "distance_pref_error");
            AddName(names, ref i, "candidate_energy_cost_state");

            for (var g = 0; g < GoalFeatureCount; g++)
            {
                AddName(names, ref i, $"goal_{g}");
            }
            for (var b = 0; b < BehaviorFeatureCount; b++)
            {
                AddName(names, ref i, $"behavior_{b}");
            }
            for (var t = 0; t < TargetTypeFeatureCount; t++)
            {
                AddName(names, ref i, $"target_type_{t}");
            }
            AddName(names, ref i, "candidate_affordance_match");
            AddName(names, ref i, "candidate_distance_fit");
            AddName(names, ref i, "candidate_social_fit");
            AddName(names, ref i, "candidate_energy_cost");
            AddName(names, ref i, "candidate_interruptibility");
            AddName(names, ref i, "candidate_motion_cost");
            AddName(names, ref i, "candidate_novelty");
            AddName(names, ref i, "candidate_emotion_match");
            AddName(names, ref i, "candidate_goal_match");
            return names;
        }

        private static void AddName(string[] names, ref int index, string name)
        {
            if (index >= 0 && index < names.Length)
            {
                names[index] = name;
            }
            index++;
        }
    }
}
