using Qiyu.Quest.Avatar;
using UnityEngine;

namespace Qiyu.Quest.Behavior
{
    /// <summary>
    /// 注意力与视线调度。
    /// 不固定盯住目标：说话/倾听时主要看用户，但会自然短暂移开；
    /// 看物体时偶尔回看用户确认；思考时看向环境。
    /// </summary>
    public class CharacterAttentionController : MonoBehaviour
    {
        [SerializeField] private AvatarLookController lookController;
        [SerializeField] private float glancePeriodMinSeconds = 2.2f;
        [SerializeField] private float glancePeriodMaxSeconds = 4.8f;
        [SerializeField] private float glanceDurationMinSeconds = 0.25f;
        [SerializeField] private float glanceDurationMaxSeconds = 0.8f;

        public Transform UserHead { get; set; }
        public string CurrentTargetId { get; private set; } = "";
        public float GazeWeight { get; private set; } = 0.7f;

        private float _nextGlanceAt;
        private float _glanceUntil;
        private bool _glancing;
        private float _phase;
        private string _lastAppliedTarget = "";
        private float _lookAwayRate = 0.15f;

        private void Awake()
        {
            if (lookController == null)
            {
                lookController = GetComponent<AvatarLookController>();
            }
            if (lookController == null)
            {
                lookController = GetComponentInChildren<AvatarLookController>();
            }
            _phase = Random.value * 10f;
            ScheduleNextGlance(Time.realtimeSinceStartup);
        }

        public void Tick(WorldSnapshotData world, CharacterStateData state,
                         BehaviorDecision decision)
        {
            if (lookController == null)
            {
                return;
            }
            if (UserHead != null)
            {
                lookController.UserHead = UserHead;
            }
            _lookAwayRate = Mathf.Clamp01(decision != null ? decision.lookAwayRate : 0.15f);
            var now = Time.realtimeSinceStartup;
            if (now >= _nextGlanceAt && !_glancing)
            {
                _glancing = true;
                _glanceUntil = now + Mathf.Lerp(glanceDurationMinSeconds,
                    glanceDurationMaxSeconds, Hash01(_phase + now));
                if (ShouldLookAtUser(decision.kind))
                {
                    var target = world.FindEntity(decision.targetId);
                    if (target != null && target.visible)
                    {
                        lookController.LookAtPosition(target.position);
                    }
                    else
                    {
                        lookController.LookAway();
                    }
                }
                else
                {
                    lookController.LookAtUser();
                }
            }
            if (_glancing && now >= _glanceUntil)
            {
                _glancing = false;
                ScheduleNextGlance(now);
                _lastAppliedTarget = "";
            }

            if (_glancing)
            {
                return;
            }
            ApplyPrimaryGaze(world, state, decision);
        }

        private void ApplyPrimaryGaze(WorldSnapshotData world, CharacterStateData state,
                                      BehaviorDecision decision)
        {
            var target = world.FindEntity(decision.targetId);
            var targetKey = decision.targetId ?? "";
            GazeWeight = Mathf.Clamp01(decision.gazeWeight);
            switch (decision.kind)
            {
                case BehaviorKind.ObserveObject:
                case BehaviorKind.GoToObject:
                case BehaviorKind.InspectObject:
                case BehaviorKind.PointAtObject:
                case BehaviorKind.InviteToObject:
                case BehaviorKind.Sit:
                    if (target != null && target.visible)
                    {
                        CurrentTargetId = target.id;
                        lookController.LookAtPosition(target.position);
                    }
                    else if (world.userVisible)
                    {
                        CurrentTargetId = "user";
                        lookController.LookAtUser();
                    }
                    break;
                case BehaviorKind.Think:
                case BehaviorKind.Sigh:
                    CurrentTargetId = "";
                    lookController.LookAway();
                    break;
                case BehaviorKind.Retreat:
                case BehaviorKind.ReflexStepBack:
                case BehaviorKind.ReflexDodge:
                    if (world.userVisible)
                    {
                        CurrentTargetId = "user";
                        lookController.LookAtUser();
                    }
                    break;
                case BehaviorKind.Idle:
                    if (!string.Equals(_lastAppliedTarget, "idle", System.StringComparison.Ordinal))
                    {
                        _lastAppliedTarget = "idle";
                        lookController.LookAway();
                        CurrentTargetId = "";
                    }
                    break;
                default:
                    if (world.userVisible)
                    {
                        CurrentTargetId = "user";
                        lookController.LookAtUser();
                    }
                    else if (target != null && target.visible)
                    {
                        CurrentTargetId = target.id;
                        lookController.LookAtPosition(target.position);
                    }
                    break;
            }
            if (!string.IsNullOrEmpty(targetKey))
            {
                _lastAppliedTarget = targetKey;
            }
        }

        private static bool ShouldLookAtUser(BehaviorKind kind)
        {
            return kind == BehaviorKind.Speak || kind == BehaviorKind.ListenUser ||
                   kind == BehaviorKind.ObserveUser || kind == BehaviorKind.ComfortUser ||
                   kind == BehaviorKind.Wave || kind == BehaviorKind.Nod ||
                   kind == BehaviorKind.Laugh;
        }

        private void ScheduleNextGlance(float now)
        {
            var rateScale = Mathf.Lerp(1.8f, 0.45f, _lookAwayRate);
            _nextGlanceAt = now + Mathf.Lerp(glancePeriodMinSeconds,
                glancePeriodMaxSeconds, Hash01(_phase + now * 0.37f)) * rateScale;
        }

        private static float Hash01(float value)
        {
            var v = Mathf.Sin(value * 12.9898f) * 43758.5453f;
            return v - Mathf.Floor(v);
        }
    }
}
