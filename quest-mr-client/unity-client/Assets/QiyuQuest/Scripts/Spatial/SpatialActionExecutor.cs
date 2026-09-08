using System;
using Meta.XR.MRUtilityKit;
using Newtonsoft.Json.Linq;
using Qiyu.Quest.Perception;
using UnityEngine;
using UnityEngine.AI;

namespace Qiyu.Quest.Spatial
{
    /// <summary>
    /// 执行后端下发的 SpatialAction（高层意图）。
    ///
    /// 路径/避障全部交给 Unity NavMeshAgent；本层只做：
    /// target_id → 真实世界坐标解析、stop_distance 计算、朝向与动画触发。
    /// </summary>
    [RequireComponent(typeof(NavMeshAgent))]
    public class SpatialActionExecutor : MonoBehaviour
    {
        [SerializeField] private MrukSceneSummary sceneSummary;
        [SerializeField] private Animator animator;
        [SerializeField] private float defaultStopDistance = 0.6f;
        [SerializeField] private float rotationSpeed = 6f;
        [SerializeField] private float arriveTolerance = 0.15f;

        public Transform UserHead { get; set; }
        public string CurrentAction { get; private set; } = "idle";
        public string CurrentTargetId { get; private set; } = "";
        public bool IsMoving => _agent != null && _agent.enabled &&
                                !_agent.pathPending &&
                                _agent.remainingDistance > arriveTolerance;

        public event Action<string> OnActionStarted;
        public event Action<string> OnActionCompleted;
        public event Action<string, string> OnActionFailed;

        private NavMeshAgent _agent;
        private Vector3? _faceTarget;
        private float _stopDistance;

        private void Awake()
        {
            _agent = GetComponent<NavMeshAgent>();
            if (animator == null)
            {
                animator = GetComponentInChildren<Animator>();
            }
        }

        private void Update()
        {
            QuestObjectRegistry.Prune(120f);
            if (_faceTarget.HasValue)
            {
                var direction = _faceTarget.Value - transform.position;
                direction.y = 0f;
                if (direction.sqrMagnitude > 0.001f)
                {
                    var targetRotation = Quaternion.LookRotation(direction.normalized, Vector3.up);
                    transform.rotation = Quaternion.Slerp(
                        transform.rotation, targetRotation, Time.deltaTime * rotationSpeed);
                }
            }
            if (!IsMoving && !string.IsNullOrEmpty(CurrentAction) &&
                CurrentAction != "idle" && _agent.enabled && !_agent.pathPending)
            {
                if (CurrentAction == "move_to" || CurrentAction == "approach" ||
                    CurrentAction == "move_away")
                {
                    OnActionCompleted?.Invoke(CurrentAction);
                    CurrentAction = "idle";
                }
            }
            if (animator != null && _agent.enabled)
            {
                animator.SetFloat("Speed", _agent.velocity.magnitude);
            }
        }

        public Vector3 ResolveTarget(string targetId)
        {
            if (string.IsNullOrEmpty(targetId))
            {
                return transform.position;
            }
            if (QuestObjectRegistry.TryGet(targetId, out var position, out _))
            {
                return position;
            }
            var room = sceneSummary != null ? sceneSummary.CurrentRoom : null;
            if (room != null)
            {
                foreach (var anchor in room.Anchors)
                {
                    if (anchor != null && anchor.gameObject.name == targetId)
                    {
                        return anchor.transform.position;
                    }
                }
            }
            return transform.position;
        }

        public void Execute(JObject payload)
        {
            if (payload == null || _agent == null)
            {
                return;
            }
            var action = payload.Value<string>("action") ?? "stop";
            CurrentTargetId = payload.Value<string>("target_id") ?? "";
            _stopDistance = payload.Value<float?>("stop_distance_m") ?? defaultStopDistance;
            var speed = payload.Value<float?>("speed") ?? 1f;
            var avoid = payload.Value<bool?>("avoid_obstacles") ?? true;
            var faceTarget = payload.Value<bool?>("face_target") ?? true;
            _agent.speed = Mathf.Clamp(speed, 0.1f, 2f) * 1.2f;
            _agent.obstacleAvoidanceType = avoid
                ? ObstacleAvoidanceType.HighQualityObstacleAvoidance
                : ObstacleAvoidanceType.NoObstacleAvoidance;

            if (!_agent.isOnNavMesh)
            {
                OnActionFailed?.Invoke(action, "agent_not_on_navmesh");
                Debug.LogWarning("[SpatialAction] NavMeshAgent 不在 NavMesh 上，无法执行");
                return;
            }

            Vector3 targetPosition;
            switch (action)
            {
                case "stop":
                    _agent.ResetPath();
                    _faceTarget = null;
                    CurrentAction = "idle";
                    OnActionCompleted?.Invoke("stop");
                    return;
                case "face_user":
                    if (UserHead != null)
                    {
                        _faceTarget = UserHead.position;
                        CurrentAction = "face_user";
                        OnActionStarted?.Invoke(action);
                    }
                    return;
                case "move_to":
                case "approach":
                case "move_away":
                case "face_object":
                case "look_at":
                case "interact":
                    targetPosition = ResolveTargetPosition(payload);
                    break;
                case "play_animation":
                    if (animator != null)
                    {
                        var animation = payload.Value<string>("animation") ?? "";
                        if (!string.IsNullOrEmpty(animation))
                        {
                            animator.SetTrigger(animation);
                        }
                    }
                    CurrentAction = "idle";
                    OnActionStarted?.Invoke(action);
                    return;
                default:
                    OnActionFailed?.Invoke(action, "unsupported_action");
                    return;
            }

            if (action == "look_at" || action == "face_object" || action == "interact")
            {
                if (faceTarget)
                {
                    _faceTarget = targetPosition;
                }
                CurrentAction = action;
                OnActionStarted?.Invoke(action);
                if (action == "interact" && animator != null)
                {
                    animator.SetTrigger("interact");
                }
                return;
            }

            var destination = ComputeDestination(action, targetPosition);
            _agent.SetDestination(destination);
            if (faceTarget)
            {
                _faceTarget = targetPosition;
            }
            CurrentAction = action;
            OnActionStarted?.Invoke(action);
            Debug.Log($"[SpatialAction] {action} -> {destination} (target={CurrentTargetId})");
        }

        private Vector3 ResolveTargetPosition(JObject payload)
        {
            var targetId = payload.Value<string>("target_id") ?? "";
            if (!string.IsNullOrEmpty(targetId))
            {
                return ResolveTarget(targetId);
            }
            var pos = payload["target_position"];
            if (pos != null)
            {
                return new Vector3(
                    pos.Value<float?>("x") ?? 0f,
                    pos.Value<float?>("y") ?? 0f,
                    pos.Value<float?>("z") ?? 0f);
            }
            return transform.position;
        }

        private Vector3 ComputeDestination(string action, Vector3 targetPosition)
        {
            var toTarget = targetPosition - transform.position;
            toTarget.y = 0f;
            var distance = toTarget.magnitude;
            if (action == "move_away")
            {
                var away = distance > 0.001f ? -toTarget.normalized : transform.forward;
                return transform.position + away * Mathf.Max(_stopDistance, 1f);
            }
            if (distance <= _stopDistance)
            {
                return transform.position;
            }
            return targetPosition - toTarget.normalized * _stopDistance;
        }
    }
}
