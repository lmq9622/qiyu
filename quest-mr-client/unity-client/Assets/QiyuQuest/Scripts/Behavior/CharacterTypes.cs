using System;
using System.Collections.Generic;
using UnityEngine;

namespace Qiyu.Quest.Behavior
{
    /// <summary>
    /// 高层行为枚举。顺序必须与训练数据的 behavior_names 保持一致。
    /// </summary>
    public enum BehaviorKind
    {
        Idle = 0,
        ListenUser = 1,
        Think = 2,
        Speak = 3,
        ObserveUser = 4,
        ObserveObject = 5,
        ApproachUser = 6,
        MaintainDistance = 7,
        Retreat = 8,
        FollowUser = 9,
        GoToObject = 10,
        PointAtObject = 11,
        InspectObject = 12,
        InviteToObject = 13,
        Sit = 14,
        Stand = 15,
        Reposition = 16,
        Wave = 17,
        Nod = 18,
        ShakeHead = 19,
        Laugh = 20,
        Sigh = 21,
        Surprised = 22,
        ComfortUser = 23,
        ReflexStop = 24,
        ReflexStepBack = 25,
        ReflexDodge = 26,
        ReflexFreeze = 27,
        ReflexLookAtThreat = 28
    }

    public enum BehaviorPriority
    {
        Idle = 0,
        Social = 1,
        Task = 2,
        Urgent = 3,
        Reflex = 4,
        Safety = 5
    }

    public static class BehaviorCatalog
    {
        public static readonly string[] Names =
        {
            "idle",
            "listen_user",
            "think",
            "speak",
            "observe_user",
            "observe_object",
            "approach_user",
            "maintain_distance",
            "retreat",
            "follow_user",
            "go_to_object",
            "point_at_object",
            "inspect_object",
            "invite_to_object",
            "sit",
            "stand",
            "reposition",
            "wave",
            "nod",
            "shake_head",
            "laugh",
            "sigh",
            "surprised",
            "comfort_user",
            "reflex_stop",
            "reflex_step_back",
            "reflex_dodge",
            "reflex_freeze",
            "reflex_look_at_threat"
        };

        public static string ToName(BehaviorKind kind)
        {
            var index = (int)kind;
            return index >= 0 && index < Names.Length ? Names[index] : "idle";
        }

        public static BehaviorKind FromGoal(string goal)
        {
            switch ((goal ?? "").Trim().ToLowerInvariant())
            {
                case "listen_user": return BehaviorKind.ListenUser;
                case "think": return BehaviorKind.Think;
                case "speak": return BehaviorKind.Speak;
                case "observe_user": return BehaviorKind.ObserveUser;
                case "observe_object": return BehaviorKind.ObserveObject;
                case "approach_user": return BehaviorKind.ApproachUser;
                case "maintain_distance": return BehaviorKind.MaintainDistance;
                case "retreat": return BehaviorKind.Retreat;
                case "follow_user": return BehaviorKind.FollowUser;
                case "go_to_object": return BehaviorKind.GoToObject;
                case "point_at_object": return BehaviorKind.PointAtObject;
                case "inspect_object": return BehaviorKind.InspectObject;
                case "invite_to_object": return BehaviorKind.InviteToObject;
                case "sit": return BehaviorKind.Sit;
                case "stand": return BehaviorKind.Stand;
                case "reposition": return BehaviorKind.Reposition;
                case "wave": return BehaviorKind.Wave;
                case "nod": return BehaviorKind.Nod;
                case "shake_head": return BehaviorKind.ShakeHead;
                case "laugh": return BehaviorKind.Laugh;
                case "sigh": return BehaviorKind.Sigh;
                case "surprised": return BehaviorKind.Surprised;
                case "comfort_user": return BehaviorKind.ComfortUser;
                default: return BehaviorKind.Idle;
            }
        }
    }

    [Serializable]
    public sealed class CharacterDrivesData
    {
        public float patience = 0.7f;
        public float energy = 0.8f;
        public float curiosity = 0.6f;
        public float socialBattery = 0.75f;
        public float stress = 0.1f;
    }

    [Serializable]
    public sealed class CharacterEmotionData
    {
        public string label = "neutral";
        public float intensity;
        public float valence;
        public float arousal;
    }

    [Serializable]
    public sealed class CharacterRelationshipData
    {
        public string tier = "acquaintance";
        public float affinity = 50f;
        public float trust = 50f;
        public float familiarity;
    }

    [Serializable]
    public sealed class CharacterStateData
    {
        public string characterId = "qiyu";
        public CharacterEmotionData emotion = new CharacterEmotionData();
        public CharacterRelationshipData relationship = new CharacterRelationshipData();
        public CharacterDrivesData drives = new CharacterDrivesData();
        public string speechState = "idle";
        public string activeBehavior = "idle";
        public string activeGoal = "idle";
        public string activeTargetId = "";
        public string attentionTargetId = "";
        public float attentionFocus = 0.5f;
        public float lastInteractionAgeSeconds = 0f;
        public int salientMemoryCount;
        public bool hasUnfinishedTopic;
        public float currentBehaviorAgeSeconds;
        public int recentSwitchCount;
        public float lastAutonomyRequestAgeSeconds = 999f;
    }

    [Serializable]
    public sealed class WorldEntityData
    {
        public string id = "";
        public string label = "";
        public string kind = "object";
        public Vector3 position;
        public Vector3 velocity;
        public float confidence = 0.5f;
        public float lastSeenAgeSeconds = 999f;
        public bool visible = true;
        public bool reachable = true;
        public bool isSeat;
        public bool isSurface;
        public bool isSmallObject;
        public float interest;
        public string[] affordances = Array.Empty<string>();
    }

    [Serializable]
    public sealed class WorldSnapshotData
    {
        public long ts;
        public int sceneVersion;
        public string status = "scanning";
        public float worldAgeSeconds = 999f;
        public bool userVisible;
        public Vector3 userPosition;
        public Vector3 userVelocity;
        public Vector3 userForward = Vector3.forward;
        public bool userSpeaking;
        public bool userLookingAtAvatar;
        public string userGazeTargetId = "";
        public string userPointingTargetId = "";
        public float userDistanceMeters = 10f;
        public float userRelativeAngleDegrees;
        public float userApproachSpeedMps;
        public float userRetreatSpeedMps;
        public float userIdleSeconds;
        public bool navmeshGenerated;
        public bool navmeshReachable = true;
        public float collisionRisk;
        public float nearestObstacleMeters = 99f;
        public bool occluded;
        public bool sceneStable = true;
        public UserStateData userState = new UserStateData();
        public SharedAttentionData sharedAttention = new SharedAttentionData();
        public List<WorldEntityData> entities = new List<WorldEntityData>();

        public WorldEntityData FindEntity(string id)
        {
            if (string.IsNullOrEmpty(id))
            {
                return null;
            }
            for (var i = 0; i < entities.Count; i++)
            {
                if (string.Equals(entities[i].id, id, StringComparison.Ordinal))
                {
                    return entities[i];
                }
            }
            return null;
        }

        public WorldEntityData NearestInterestingObject(float maxDistance = 6f)
        {
            WorldEntityData best = null;
            var bestScore = float.MinValue;
            for (var i = 0; i < entities.Count; i++)
            {
                var entity = entities[i];
                if (entity == null || !entity.visible || entity.kind != "object")
                {
                    continue;
                }
                var distance = Vector3.Distance(userPosition, entity.position);
                if (distance > maxDistance)
                {
                    continue;
                }
                var score = entity.interest * 2f - distance * 0.25f +
                            entity.confidence * 0.5f;
                if (score > bestScore)
                {
                    bestScore = score;
                    best = entity;
                }
            }
            return best;
        }
    }

    [Serializable]
    public sealed class AvatarIntentData
    {
        public string schemaVersion = "1.1";
        public string intentId = "";
        public string goal = "idle";
        public string target = "";
        public string attention = "";
        public string emotion = "neutral";
        public float emotionIntensity;
        public string behaviorStyle = "neutral";
        public float urgency;
        public float socialPriority = 0.5f;
        public int durationHintMs;
        public string speechAct = "";
        public bool speaking;
        public string responseId = "";
        public bool cancelOnBargeIn = true;
        public int priority = 1;
        public string interruptPolicy = "on_higher_priority";
        public string expressionHint = "";
        public string gestureHint = "";
        public string spatialTargetId = "";
        public float desiredDistanceMeters = 0.9f;
        public bool spatialFaceTarget = true;
        public long receivedAtMs;

        public float AgeSeconds => receivedAtMs <= 0
            ? 999f
            : Mathf.Max(0f, (float)(DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - receivedAtMs) / 1000f);
    }

    [Serializable]
    public sealed class BehaviorCandidate
    {
        public BehaviorKind kind;
        public string targetId = "";
        public float utility;
        public float learnedScore;
        public float finalScore;
        public float desiredDistanceMeters = 0.9f;
        public float speedScale = 0.7f;
        public float gazeWeight = 0.7f;
        public float gestureProbability = 0.2f;
        public float lookAwayRate = 0.15f;
        public float speechUrge;
        public float novelty;
        public float energyCost;
        public float interruptibility = 1f;
        public bool hardNegative;
        public string reason = "";
        public float[] features;
    }

    [Serializable]
    public sealed class BehaviorDecision
    {
        public BehaviorKind kind = BehaviorKind.Idle;
        public string targetId = "";
        public float confidence;
        public float priority;
        public float desiredDistanceMeters = 0.9f;
        public float speedScale = 0.7f;
        public float gazeWeight = 0.7f;
        public float gestureProbability = 0.2f;
        public float lookAwayRate = 0.15f;
        public float speechUrge;
        public bool interruptible = true;
        public string policySource = "utility";
        public string reason = "";
        public long sinceMs;
        public float policyLatencyMs;
    }
}
