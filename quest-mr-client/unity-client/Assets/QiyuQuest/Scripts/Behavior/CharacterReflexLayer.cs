using UnityEngine;

namespace Qiyu.Quest.Behavior
{
    [System.Serializable]
    public sealed class ReflexOverride
    {
        public bool active;
        public BehaviorKind kind = BehaviorKind.ReflexStop;
        public string targetId = "";
        public float priority = (float)BehaviorPriority.Safety;
        public float until;
        public string reason = "";
    }

    /// <summary>
    /// 60 Hz 反射层：碰撞、突然靠近、危险、遮挡、打断、距离控制。
    /// 它只做短时硬覆盖，不替代 Behavior Runtime 的长期行为选择。
    /// </summary>
    public class CharacterReflexLayer : MonoBehaviour
    {
        [SerializeField] private float personalSpaceMeters = 0.55f;
        [SerializeField] private float fastApproachMps = 0.55f;
        [SerializeField] private float collisionRiskThreshold = 0.55f;
        [SerializeField] private float obstacleStopMeters = 0.35f;
        [SerializeField] private float obstacleProbeMeters = 0.85f;
        [SerializeField] private float obstacleProbeRadius = 0.22f;
        [SerializeField] private float bargeInHoldSeconds = 1.6f;
        [SerializeField] private float occlusionHoldSeconds = 2.2f;

        public bool HasActiveOverride => _current.active;
        public ReflexOverride Current => _current;

        private ReflexOverride _current = new ReflexOverride();
        private float _bargeInUntil;
        private float _collisionUntil;
        private float _occlusionUntil;
        private string _occlusionReason = "";
        private int _collisionContacts;

        public void Tick(WorldSnapshotData world, CharacterStateData state)
        {
            var now = Time.realtimeSinceStartup;
            if (_current.active && now >= _current.until)
            {
                _current.active = false;
                _current.reason = "";
            }
            if (world == null || state == null)
            {
                return;
            }

            if (now < _collisionUntil || _collisionContacts > 0)
            {
                Set(BehaviorKind.ReflexStop, "", (float)BehaviorPriority.Safety,
                    Mathf.Max(_collisionUntil, now + 0.35f), "collision");
                return;
            }
            if (world.collisionRisk >= collisionRiskThreshold ||
                world.nearestObstacleMeters <= obstacleStopMeters)
            {
                Set(BehaviorKind.ReflexDodge, "", (float)BehaviorPriority.Safety,
                    now + 0.9f, "obstacle_too_close");
                return;
            }
            if (ProbeObstacleAhead(out var hit))
            {
                Set(BehaviorKind.ReflexDodge, "", (float)BehaviorPriority.Safety,
                    now + 0.7f, $"obstacle_ahead:{hit.distance:F2}m");
                return;
            }
            if (world.userVisible &&
                world.userDistanceMeters < personalSpaceMeters &&
                world.userApproachSpeedMps > fastApproachMps)
            {
                Set(BehaviorKind.ReflexStepBack, "user", (float)BehaviorPriority.Safety,
                    now + 0.8f, "user_fast_approach");
                return;
            }
            if (now < _bargeInUntil)
            {
                Set(BehaviorKind.ListenUser, "user", (float)BehaviorPriority.Reflex,
                    _bargeInUntil, "barge_in");
                return;
            }
            if (now < _occlusionUntil)
            {
                Set(BehaviorKind.Reposition, "user", (float)BehaviorPriority.Reflex,
                    _occlusionUntil, _occlusionReason);
                return;
            }
            if (world.occluded && world.userVisible)
            {
                _occlusionUntil = now + occlusionHoldSeconds;
                _occlusionReason = "user_occluded";
                Set(BehaviorKind.Reposition, "user", (float)BehaviorPriority.Reflex,
                    _occlusionUntil, _occlusionReason);
            }
        }

        public void TriggerBargeIn()
        {
            _bargeInUntil = Time.realtimeSinceStartup + bargeInHoldSeconds;
        }

        public void TriggerDanger(string reason)
        {
            _collisionUntil = Time.realtimeSinceStartup + 1.2f;
            Set(BehaviorKind.ReflexFreeze, "", (float)BehaviorPriority.Safety,
                _collisionUntil, string.IsNullOrEmpty(reason) ? "danger" : reason);
        }

        private void OnCollisionEnter(Collision collision)
        {
            if (collision == null || collision.collider == null)
            {
                return;
            }
            _collisionContacts++;
            _collisionUntil = Time.realtimeSinceStartup + 0.45f;
        }

        private void OnCollisionExit(Collision collision)
        {
            _collisionContacts = Mathf.Max(0, _collisionContacts - 1);
        }

        private void Set(BehaviorKind kind, string targetId, float priority,
                         float until, string reason)
        {
            _current.active = true;
            _current.kind = kind;
            _current.targetId = targetId ?? "";
            _current.priority = priority;
            _current.until = until;
            _current.reason = reason ?? "";
        }

        private bool ProbeObstacleAhead(out RaycastHit hit)
        {
            hit = default;
            var origin = transform.position + Vector3.up * 0.9f;
            var direction = transform.forward;
            direction.y = 0f;
            if (direction.sqrMagnitude < 0.001f)
            {
                return false;
            }
            var hits = Physics.SphereCastAll(origin, obstacleProbeRadius,
                direction.normalized, obstacleProbeMeters,
                ~0, QueryTriggerInteraction.Ignore);
            var best = float.MaxValue;
            foreach (var candidate in hits)
            {
                if (candidate.collider == null ||
                    candidate.collider.transform.root == transform.root)
                {
                    continue;
                }
                if (candidate.distance < best)
                {
                    best = candidate.distance;
                    hit = candidate;
                }
            }
            return best < float.MaxValue;
        }
    }
}
