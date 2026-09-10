using System;
using UnityEngine;

namespace Qiyu.Quest.Behavior
{
    /// <summary>
    /// 双向 InteractionState。不是单向 START→END：
    /// interrupt / cancel / resume / replan 都是显式状态迁移。
    /// </summary>
    public class InteractionStateController : MonoBehaviour
    {
        public InteractionStateData Current { get; private set; } = new InteractionStateData();
        public event Action<InteractionStateData> OnStateChanged;

        public void Tick(WorldSnapshotData world, CharacterStateData state,
                         BehaviorDecision decision, HumanInteractionEvent evt)
        {
            var next = ResolveState(world, state, decision, evt);
            if (next == Current.state &&
                decision != null &&
                string.Equals(Current.target, decision.targetId, StringComparison.Ordinal))
            {
                Current.confidence = Mathf.Lerp(Current.confidence,
                    decision != null ? decision.confidence : 0.5f, 0.25f);
                return;
            }
            Current.state = next;
            Current.goal = decision != null ? BehaviorCatalog.ToName(decision.kind) : "";
            Current.target = decision != null ? decision.targetId : "";
            Current.sinceMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            Current.confidence = decision != null ? decision.confidence : 0.5f;
            Current.interruptible = decision == null || decision.interruptible;
            OnStateChanged?.Invoke(Current);
        }

        public void Interrupt(string reason)
        {
            if (Current.state != InteractionActivity.Interrupted)
            {
                Current.resumeGoal = Current.goal;
                Current.resumeTarget = Current.target;
            }
            Current.interrupted = true;
            Current.state = InteractionActivity.Interrupted;
            Current.sinceMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            OnStateChanged?.Invoke(Current);
            Debug.Log($"[QiyuInteraction] interrupt: {reason}");
        }

        public void Cancel(string reason)
        {
            Current.cancelled = true;
            Current.state = InteractionActivity.Idle;
            Current.goal = "";
            Current.target = "";
            Current.sinceMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            OnStateChanged?.Invoke(Current);
            Debug.Log($"[QiyuInteraction] cancel: {reason}");
        }

        public void Resume()
        {
            if (string.IsNullOrEmpty(Current.resumeGoal))
            {
                return;
            }
            Current.goal = Current.resumeGoal;
            Current.target = Current.resumeTarget;
            Current.resumeGoal = "";
            Current.resumeTarget = "";
            Current.interrupted = false;
            Current.cancelled = false;
            Current.state = MapGoalToState(Current.goal);
            Current.sinceMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            OnStateChanged?.Invoke(Current);
            Debug.Log("[QiyuInteraction] resume");
        }

        public void Replan(string goal, string target, float confidence)
        {
            Current.goal = goal ?? "";
            Current.target = target ?? "";
            Current.interrupted = false;
            Current.cancelled = false;
            Current.state = MapGoalToState(Current.goal);
            Current.confidence = Mathf.Clamp01(confidence);
            Current.sinceMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            OnStateChanged?.Invoke(Current);
            Debug.Log($"[QiyuInteraction] replan {Current.goal} -> {Current.target}");
        }

        private static InteractionActivity ResolveState(WorldSnapshotData world,
                                                        CharacterStateData state,
                                                        BehaviorDecision decision,
                                                        HumanInteractionEvent evt)
        {
            if (evt != null)
            {
                if (evt.gesture == HumanGesture.Stop || evt.gesture == HumanGesture.Push)
                {
                    return InteractionActivity.Interrupted;
                }
                if (evt.gesture == HumanGesture.HighFive || evt.gesture == HumanGesture.Give)
                {
                    return InteractionActivity.Cooperating;
                }
                if (evt.gesture == HumanGesture.Wave || evt.gesture == HumanGesture.ComeHere)
                {
                    return InteractionActivity.Responding;
                }
            }
            if (decision == null)
            {
                return InteractionActivity.Idle;
            }
            switch (decision.kind)
            {
                case BehaviorKind.ApproachUser:
                    return InteractionActivity.Approaching;
                case BehaviorKind.FollowUser:
                    return InteractionActivity.Following;
                case BehaviorKind.ObserveUser:
                case BehaviorKind.ObserveObject:
                case BehaviorKind.ListenUser:
                    return InteractionActivity.Watching;
                case BehaviorKind.Speak:
                case BehaviorKind.Wave:
                case BehaviorKind.Nod:
                case BehaviorKind.ComfortUser:
                    return InteractionActivity.Responding;
                case BehaviorKind.Laugh:
                case BehaviorKind.Surprised:
                    return InteractionActivity.Playing;
                case BehaviorKind.InviteToObject:
                case BehaviorKind.InspectObject:
                case BehaviorKind.PointAtObject:
                    return InteractionActivity.Cooperating;
                case BehaviorKind.MaintainDistance:
                case BehaviorKind.Idle:
                case BehaviorKind.Think:
                    return InteractionActivity.Waiting;
                case BehaviorKind.Retreat:
                case BehaviorKind.ReflexStepBack:
                case BehaviorKind.ReflexDodge:
                    return InteractionActivity.Avoiding;
                default:
                    return InteractionActivity.Idle;
            }
        }

        private static InteractionActivity MapGoalToState(string goal)
        {
            switch (goal)
            {
                case "approach_user": return InteractionActivity.Approaching;
                case "follow_user": return InteractionActivity.Following;
                case "observe_user":
                case "observe_object":
                case "listen_user": return InteractionActivity.Watching;
                case "speak":
                case "wave":
                case "nod":
                case "comfort_user": return InteractionActivity.Responding;
                case "invite_to_object":
                case "inspect_object":
                case "point_at_object": return InteractionActivity.Cooperating;
                case "retreat": return InteractionActivity.Avoiding;
                case "maintain_distance":
                case "idle":
                case "think": return InteractionActivity.Waiting;
                default: return InteractionActivity.Idle;
            }
        }
    }
}
