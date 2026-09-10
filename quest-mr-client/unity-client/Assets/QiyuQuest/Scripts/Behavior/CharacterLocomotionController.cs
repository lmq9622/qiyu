using System;
using Qiyu.Quest.Spatial;
using UnityEngine;
using UnityEngine.AI;

namespace Qiyu.Quest.Behavior
{
    /// <summary>
    /// 角色移动执行器：NavMesh 路径、避障、到达、距离控制、卡住恢复。
    /// Behavior Runtime 只给目标与期望距离；本层不接收 LLM 坐标序列。
    /// </summary>
    [RequireComponent(typeof(NavMeshAgent))]
    public class CharacterLocomotionController : MonoBehaviour
    {
        [SerializeField] private float baseSpeedMps = 1.15f;
        [SerializeField] private float acceleration = 8f;
        [SerializeField] private float angularSpeed = 240f;
        [SerializeField] private float arriveTolerance = 0.12f;
        [SerializeField] private float stuckTimeoutSeconds = 1.4f;
        [SerializeField] private float stuckDistanceThreshold = 0.04f;
        [SerializeField] private bool disableLegacySpatialExecutor = true;

        public bool IsMoving { get; private set; }
        public bool IsStuck { get; private set; }
        public float CurrentSpeedMps => _agent != null ? _agent.velocity.magnitude : 0f;
        public Vector3 Destination { get; private set; }
        public float DistanceToUser { get; private set; }
        public Transform UserHead { get; set; }
        public event Action<string> OnArrived;
        public event Action<string> OnMoveFailed;

        private NavMeshAgent _agent;
        private Vector3 _lastStuckSample;
        private float _lastStuckAt;
        private float _destinationTolerance;
        private bool _faceAfterArrival;
        private Vector3? _faceTarget;
        private string _currentTargetId = "";
        private int _repathAttempts;

        private void Awake()
        {
            _agent = GetComponent<NavMeshAgent>();
            _agent.updateRotation = false;
            _agent.acceleration = acceleration;
            _agent.angularSpeed = angularSpeed;
            _agent.stoppingDistance = 0.05f;
            // 与 RoomNavMeshBuilder 的烘焙半径保持一致：0.25 太保守，
            // 小房间里会直接判定“无处可走”。
            _agent.radius = 0.18f;
            _agent.height = 1.6f;
            if (disableLegacySpatialExecutor)
            {
                var legacy = GetComponent<SpatialActionExecutor>();
                if (legacy != null)
                {
                    legacy.enabled = false;
                    Debug.Log("[QiyuLocomotion] 已停用旧 SpatialActionExecutor，避免重复控制 NavMeshAgent");
                }
            }
            _lastStuckSample = transform.position;
            _lastStuckAt = Time.realtimeSinceStartup;
        }

        private void Update()
        {
            if (_agent == null || !_agent.enabled || !_agent.isOnNavMesh)
            {
                IsMoving = false;
                return;
            }
            if (UserHead != null)
            {
                DistanceToUser = Vector3.Distance(transform.position, UserHead.position);
            }
            if (_faceTarget.HasValue)
            {
                FaceWorldPositionInternal(_faceTarget.Value);
            }

            if (!IsMoving)
            {
                return;
            }
            if (_agent.pathPending)
            {
                return;
            }

            var remaining = _agent.remainingDistance;
            if (!float.IsInfinity(remaining) && remaining <= _destinationTolerance)
            {
                StopInternal();
                OnArrived?.Invoke(_currentTargetId);
                return;
            }

            if (Time.realtimeSinceStartup - _lastStuckAt >= stuckTimeoutSeconds)
            {
                var moved = Vector3.Distance(transform.position, _lastStuckSample);
                if (moved < stuckDistanceThreshold)
                {
                    IsStuck = true;
                    _repathAttempts++;
                    if (_repathAttempts <= 2 &&
                        NavMesh.SamplePosition(Destination, out var hit, 1.0f, NavMesh.AllAreas))
                    {
                        _agent.ResetPath();
                        _agent.SetDestination(hit.position);
                        Debug.LogWarning($"[QiyuLocomotion] 检测到卡住，重新寻路 attempt={_repathAttempts}");
                    }
                    else
                    {
                        StopInternal();
                        OnMoveFailed?.Invoke("stuck");
                    }
                }
                _lastStuckSample = transform.position;
                _lastStuckAt = Time.realtimeSinceStartup;
            }
        }

        public bool MoveTo(Vector3 worldPosition, float stopDistanceMeters,
                           float speedScale, string targetId, bool faceTarget)
        {
            if (_agent == null || !_agent.enabled)
            {
                return false;
            }
            if (!_agent.isOnNavMesh)
            {
                if (!NavMesh.SamplePosition(transform.position, out var selfHit, 1.5f,
                        NavMesh.AllAreas))
                {
                    OnMoveFailed?.Invoke("not_on_navmesh");
                    return false;
                }
                _agent.Warp(selfHit.position);
            }
            if (!NavMesh.SamplePosition(worldPosition, out var destination, 1.2f,
                    NavMesh.AllAreas))
            {
                OnMoveFailed?.Invoke("destination_unreachable");
                return false;
            }

            var direction = destination.position - transform.position;
            direction.y = 0f;
            var distance = direction.magnitude;
            var stop = Mathf.Clamp(stopDistanceMeters, 0.25f, 2.5f);
            var finalDestination = distance > stop
                ? destination.position - direction.normalized * stop
                : transform.position;
            if (Vector3.Distance(transform.position, finalDestination) < 0.08f)
            {
                StopInternal();
                if (faceTarget)
                {
                    _faceTarget = destination.position;
                }
                OnArrived?.Invoke(targetId ?? "");
                return true;
            }

            _agent.speed = Mathf.Clamp(baseSpeedMps * Mathf.Clamp(speedScale, 0.25f, 1.5f),
                0.35f, 2.0f);
            _agent.isStopped = false;
            _agent.ResetPath();
            if (!_agent.SetDestination(finalDestination))
            {
                OnMoveFailed?.Invoke("set_destination_failed");
                return false;
            }
            Destination = finalDestination;
            _destinationTolerance = arriveTolerance;
            _faceAfterArrival = faceTarget;
            _faceTarget = faceTarget ? destination.position : (Vector3?)null;
            _currentTargetId = targetId ?? "";
            IsMoving = true;
            IsStuck = false;
            _repathAttempts = 0;
            _lastStuckSample = transform.position;
            _lastStuckAt = Time.realtimeSinceStartup;
            return true;
        }

        public bool MoveNearUser(float desiredDistanceMeters, float speedScale, string reason)
        {
            if (UserHead == null)
            {
                OnMoveFailed?.Invoke("user_unavailable");
                return false;
            }
            return MoveTo(UserHead.position, desiredDistanceMeters, speedScale,
                "user", true);
        }

        public bool KeepDistanceFromUser(float desiredDistanceMeters, float speedScale)
        {
            if (UserHead == null)
            {
                return false;
            }
            var current = Vector3.Distance(transform.position, UserHead.position);
            var error = current - desiredDistanceMeters;
            if (Mathf.Abs(error) < 0.18f)
            {
                StopInternal();
                return true;
            }
            var direction = error > 0f
                ? (UserHead.position - transform.position).normalized
                : (transform.position - UserHead.position).normalized;
            var target = UserHead.position - direction * desiredDistanceMeters;
            return MoveTo(target, 0.05f, speedScale, "user", true);
        }

        public void Stop(string reason = "")
        {
            StopInternal();
            if (!string.IsNullOrEmpty(reason))
            {
                OnMoveFailed?.Invoke(reason);
            }
        }

        public void FaceUser()
        {
            if (UserHead != null)
            {
                _faceTarget = UserHead.position;
            }
        }

        public void FaceWorldPosition(Vector3 position)
        {
            _faceTarget = position;
        }

        public void ClearFacing()
        {
            _faceTarget = null;
        }

        private void StopInternal()
        {
            IsMoving = false;
            if (_agent != null && _agent.enabled && _agent.isOnNavMesh)
            {
                if (!_agent.isStopped)
                {
                    _agent.ResetPath();
                }
                _agent.isStopped = true;
            }
        }

        private void FaceWorldPositionInternal(Vector3 position)
        {
            var direction = position - transform.position;
            direction.y = 0f;
            if (direction.sqrMagnitude < 0.001f)
            {
                return;
            }
            var targetRotation = Quaternion.LookRotation(direction.normalized, Vector3.up);
            transform.rotation = Quaternion.RotateTowards(
                transform.rotation, targetRotation, angularSpeed * Time.deltaTime);
        }
    }
}
