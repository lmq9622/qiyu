using System;
using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.AI;

namespace Qiyu.Quest.Behavior
{
    /// <summary>
    /// 把 Quest 的 WorldState v1/v1.1 JObject 转成行为层快照。
    /// 只消费真实 MRUK/视觉数据；WorldState 缺失或过期时进入保守状态。
    /// </summary>
    public class CharacterWorldModel : MonoBehaviour
    {
        [SerializeField] private float staleAfterSeconds = 6f;
        [SerializeField] private float lostUserAfterSeconds = 3f;
        [SerializeField] private float occlusionRayHeight = 1.55f;

        public WorldSnapshotData Snapshot { get; private set; } = new WorldSnapshotData();
        public Transform AvatarRoot { get; set; }
        public bool IsWorldFresh => Snapshot.worldAgeSeconds <= staleAfterSeconds;

        private readonly Dictionary<string, TrackedPose> _tracked =
            new Dictionary<string, TrackedPose>(StringComparer.Ordinal);
        private JObject _lastPayload;
        private float _lastWorldReceivedAt = -999f;
        private float _lastUserSeenAt = -999f;
        private Vector3 _lastUserPosition;
        private float _lastUserSampleAt = -999f;
        private Vector3 _userVelocity;
        private UserStateData _userState = new UserStateData();

        private sealed class TrackedPose
        {
            public Vector3 position;
            public float sampledAt;
        }

        public void UpdateSnapshot(JObject payload)
        {
            if (payload == null)
            {
                Snapshot.worldAgeSeconds = Time.realtimeSinceStartup - _lastWorldReceivedAt;
                Snapshot.status = "lost";
                Snapshot.userVisible = false;
                return;
            }
            _lastPayload = payload;
            _lastWorldReceivedAt = Time.realtimeSinceStartup;

            var snapshot = new WorldSnapshotData
            {
                ts = payload.Value<long?>("ts") ?? 0,
                sceneVersion = payload.Value<int?>("scene_version") ?? 0,
                status = payload.Value<string>("status") ?? "scanning",
                worldAgeSeconds = 0f,
                navmeshGenerated = payload["navmesh"]?.Value<bool?>("generated") ?? false,
                navmeshReachable = true,
            };

            var interaction = payload["interaction"] as JObject;
            if (interaction != null)
            {
                snapshot.userDistanceMeters =
                    interaction.Value<float?>("user_distance_m") ?? snapshot.userDistanceMeters;
                snapshot.userApproachSpeedMps =
                    interaction.Value<float?>("user_approach_speed_mps") ?? 0f;
                snapshot.userRelativeAngleDegrees =
                    interaction.Value<float?>("user_relative_angle_deg") ?? 0f;
                snapshot.occluded = interaction.Value<bool?>("occluded") ?? false;
                snapshot.collisionRisk =
                    interaction.Value<float?>("collision_risk") ?? 0f;
                snapshot.nearestObstacleMeters =
                    interaction.Value<float?>("nearest_obstacle_m") ?? 99f;
                snapshot.navmeshReachable =
                    interaction.Value<bool?>("navmesh_reachable") ?? true;
            }

            var user = payload["user"] as JObject;
            if (user != null && user["head"] is JObject head)
            {
                var userPosition = ReadPosition(head);
                var now = Time.realtimeSinceStartup;
                if (_lastUserSampleAt > 0f)
                {
                    var dt = Mathf.Max(0.001f, now - _lastUserSampleAt);
                    var measured = (userPosition - _lastUserPosition) / dt;
                    _userVelocity = Vector3.Lerp(_userVelocity, measured, 0.35f);
                }
                _lastUserPosition = userPosition;
                _lastUserSampleAt = now;
                _lastUserSeenAt = now;
                snapshot.userVisible = true;
                snapshot.userPosition = userPosition;
                snapshot.userForward = ReadForward(head, Quaternion.identity) * Vector3.forward;
                snapshot.userVelocity = ReadVector(user["velocity"] as JObject, _userVelocity);
                snapshot.userSpeaking = user.Value<bool?>("is_speaking") ?? false;
                snapshot.userGazeTargetId = user.Value<string>("gaze_target_id") ?? "";
                snapshot.userPointingTargetId = user.Value<string>("pointing_target_id") ?? "";
                var lastSpokeMs = user.Value<long?>("last_spoke_at_ms") ?? 0;
                snapshot.userIdleSeconds = lastSpokeMs > 0
                    ? Mathf.Max(0f, (DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - lastSpokeMs) / 1000f)
                    : 999f;
            }
            else
            {
                snapshot.userVisible = Time.realtimeSinceStartup - _lastUserSeenAt < lostUserAfterSeconds;
                snapshot.userPosition = _lastUserPosition;
            }

            AddAnchors(snapshot, payload["anchors"] as JArray);
            AddDetectedObjects(snapshot, payload["objects"] as JArray);
            ComputeAvatarRelative(snapshot);
            ComputeOcclusion(snapshot);
            snapshot.userState = _userState;
            ResolveGazeTarget(snapshot);
            Snapshot = snapshot;
        }

        /// <summary>
        /// 唯一的用户实时状态入口：HumanMotionCapture → WorldModel。
        /// 行为层不再各自读取 OVRHand/OVRBody/OVREyeGaze。
        /// </summary>
        public void SetHumanMotion(HumanMotionState motion)
        {
            if (motion == null)
            {
                return;
            }
            _userState.position = motion.headPose.position;
            _userState.rotation = motion.headPose.rotation;
            _userState.headPose = motion.headPose;
            _userState.leftHand = motion.leftHand ?? new HumanHandState();
            _userState.rightHand = motion.rightHand ?? new HumanHandState();
            _userState.body = motion.body ?? new HumanBodyState();
            _userState.gazeDirection = motion.gazeDirection;
            _userState.gazeTargetId = motion.gazeTargetId;
            _userState.gesture = motion.dominantGesture;
            _userState.velocity = motion.velocity;
            _userState.confidence = motion.confidence;
            _userState.activity = ClassifyActivity(motion);
        }

        public void SetSharedAttention(SharedAttentionData attention)
        {
            if (attention != null && Snapshot != null)
            {
                Snapshot.sharedAttention = attention;
            }
        }

        private static InteractionActivity ClassifyActivity(HumanMotionState motion)
        {
            if (motion == null)
            {
                return InteractionActivity.Idle;
            }
            if (motion.dominantGesture == HumanGesture.Stop ||
                motion.dominantGesture == HumanGesture.Push)
            {
                return InteractionActivity.Avoiding;
            }
            if (motion.dominantGesture == HumanGesture.HighFive ||
                motion.dominantGesture == HumanGesture.Give)
            {
                return InteractionActivity.Cooperating;
            }
            if (motion.dominantGesture == HumanGesture.Wave ||
                motion.dominantGesture == HumanGesture.ComeHere)
            {
                return InteractionActivity.Responding;
            }
            if (motion.velocity.magnitude > 0.45f)
            {
                return InteractionActivity.Approaching;
            }
            if (motion.body.tracked)
            {
                return InteractionActivity.Watching;
            }
            return InteractionActivity.Idle;
        }

        public void TickAge()
        {
            Snapshot.worldAgeSeconds = Time.realtimeSinceStartup - _lastWorldReceivedAt;
            if (Snapshot.worldAgeSeconds > staleAfterSeconds)
            {
                Snapshot.status = "stale";
                Snapshot.userVisible = false;
                Snapshot.navmeshReachable = false;
            }
        }

        public WorldEntityData NearestInterestingObject(float maxDistance = 6f)
        {
            WorldEntityData best = null;
            var bestScore = float.MinValue;
            foreach (var entity in Snapshot.entities)
            {
                if (entity == null || !entity.visible || entity.kind != "object")
                {
                    continue;
                }
                var distance = Vector3.Distance(AvatarRoot != null
                    ? AvatarRoot.position : Vector3.zero, entity.position);
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

        public JObject LastPayload => _lastPayload;

        private void AddAnchors(WorldSnapshotData snapshot, JArray anchors)
        {
            if (anchors == null)
            {
                return;
            }
            foreach (var raw in anchors)
            {
                if (!(raw is JObject anchor))
                {
                    continue;
                }
                var label = (anchor.Value<string>("label") ?? "unknown").ToLowerInvariant();
                if (label == "floor" || label == "ceiling" || label == "wall" || label == "room")
                {
                    continue;
                }
                var id = anchor.Value<string>("id") ?? "";
                if (string.IsNullOrEmpty(id))
                {
                    continue;
                }
                var pose = anchor["pose"] as JObject;
                var position = pose != null ? ReadPosition(pose) : Vector3.zero;
                var entity = new WorldEntityData
                {
                    id = id,
                    label = label,
                    kind = "anchor",
                    position = position,
                    confidence = 1f,
                    visible = true,
                    lastSeenAgeSeconds = 0f,
                    isSeat = label == "chair" || label == "sofa",
                    isSurface = label == "table",
                    isSmallObject = false,
                    interest = LabelInterest(label),
                    affordances = AffordancesFor(label),
                };
                UpdateVelocity(entity);
                snapshot.entities.Add(entity);
            }
        }

        private void AddDetectedObjects(WorldSnapshotData snapshot, JArray objects)
        {
            if (objects == null)
            {
                return;
            }
            foreach (var raw in objects)
            {
                if (!(raw is JObject item))
                {
                    continue;
                }
                var id = item.Value<string>("id") ?? "";
                if (string.IsNullOrEmpty(id))
                {
                    continue;
                }
                var label = (item.Value<string>("label") ?? "object").ToLowerInvariant();
                var entity = new WorldEntityData
                {
                    id = id,
                    label = label,
                    kind = "object",
                    position = ReadVector(item["position"] as JObject, Vector3.zero),
                    velocity = ReadVector(item["velocity"] as JObject, Vector3.zero),
                    confidence = Mathf.Clamp01(item.Value<float?>("confidence") ?? 0.5f),
                    visible = string.Equals(item.Value<string>("state") ?? "visible",
                        "visible", StringComparison.OrdinalIgnoreCase),
                    lastSeenAgeSeconds = AgeFromMs(item.Value<long?>("last_seen_at_ms") ?? 0),
                    isSmallObject = !IsLargeObjectLabel(label),
                    interest = LabelInterest(label) + 0.25f,
                    affordances = ReadStringArray(item["affordances"] as JArray),
                };
                UpdateVelocity(entity);
                snapshot.entities.Add(entity);
            }
        }

        private void UpdateVelocity(WorldEntityData entity)
        {
            var now = Time.realtimeSinceStartup;
            if (_tracked.TryGetValue(entity.id, out var previous))
            {
                var dt = Mathf.Max(0.001f, now - previous.sampledAt);
                if (entity.velocity.sqrMagnitude < 0.0001f)
                {
                    entity.velocity = (entity.position - previous.position) / dt;
                }
            }
            _tracked[entity.id] = new TrackedPose
            {
                position = entity.position,
                sampledAt = now,
            };
        }

        private void ComputeAvatarRelative(WorldSnapshotData snapshot)
        {
            if (!snapshot.userVisible || AvatarRoot == null)
            {
                return;
            }
            var toUser = snapshot.userPosition - AvatarRoot.position;
            toUser.y = 0f;
            snapshot.userDistanceMeters = toUser.magnitude;
            if (toUser.sqrMagnitude < 0.0001f)
            {
                snapshot.userRelativeAngleDegrees = 0f;
                return;
            }
            var forward = AvatarRoot.forward;
            forward.y = 0f;
            if (forward.sqrMagnitude < 0.0001f)
            {
                forward = Vector3.forward;
            }
            snapshot.userRelativeAngleDegrees =
                Vector3.SignedAngle(forward.normalized, toUser.normalized, Vector3.up);
            var approach = Vector3.Dot(snapshot.userVelocity, toUser.normalized);
            snapshot.userApproachSpeedMps = Mathf.Max(0f, approach);
            snapshot.userRetreatSpeedMps = Mathf.Max(0f, -approach);

            if (NavMesh.SamplePosition(snapshot.userPosition, out _, 1.2f,
                    NavMesh.AllAreas))
            {
                snapshot.navmeshReachable = true;
            }
        }

        private void ComputeOcclusion(WorldSnapshotData snapshot)
        {
            if (!snapshot.userVisible || AvatarRoot == null)
            {
                snapshot.occluded = false;
                return;
            }
            var origin = AvatarRoot.position + Vector3.up * occlusionRayHeight;
            var target = snapshot.userPosition + Vector3.up * 0.1f;
            var direction = target - origin;
            var distance = direction.magnitude;
            if (distance < 0.2f)
            {
                snapshot.occluded = false;
                return;
            }
            var hits = Physics.RaycastAll(origin, direction.normalized, distance,
                ~0, QueryTriggerInteraction.Ignore);
            for (var i = 0; i < hits.Length; i++)
            {
                var hit = hits[i];
                if (hit.collider == null)
                {
                    continue;
                }
                if (hit.collider.transform.root == AvatarRoot.root)
                {
                    continue;
                }
                // 用户头部附近命中视为没有遮挡。
                if (hit.distance < distance - 0.18f)
                {
                    snapshot.occluded = true;
                    return;
                }
            }
            snapshot.occluded = false;
        }

        private void ResolveGazeTarget(WorldSnapshotData snapshot)
        {
            var gaze = snapshot.userState.gazeDirection;
            if (gaze.sqrMagnitude < 0.001f)
            {
                return;
            }
            var origin = snapshot.userState.position;
            WorldEntityData best = null;
            var bestScore = float.MaxValue;
            foreach (var entity in snapshot.entities)
            {
                if (entity == null || !entity.visible)
                {
                    continue;
                }
                var toEntity = entity.position - origin;
                if (toEntity.sqrMagnitude < 0.05f)
                {
                    continue;
                }
                var angle = Vector3.Angle(gaze, toEntity.normalized);
                if (angle > 18f)
                {
                    continue;
                }
                var score = angle + toEntity.magnitude * 0.05f;
                if (score < bestScore)
                {
                    bestScore = score;
                    best = entity;
                }
            }
            if (best != null)
            {
                snapshot.userState.gazeTargetId = best.id;
                _userState.gazeTargetId = best.id;
            }
        }

        private static Vector3 ReadPosition(JObject pose)
        {
            return ReadVector(pose?["position"] as JObject, Vector3.zero);
        }

        private static Vector3 ReadVector(JObject value, Vector3 fallback)
        {
            if (value == null)
            {
                return fallback;
            }
            return new Vector3(
                value.Value<float?>("x") ?? fallback.x,
                value.Value<float?>("y") ?? fallback.y,
                value.Value<float?>("z") ?? fallback.z);
        }

        private static Quaternion ReadForward(JObject pose, Quaternion fallback)
        {
            var rotation = pose?["rotation"] as JObject;
            if (rotation == null)
            {
                return fallback;
            }
            return new Quaternion(
                rotation.Value<float?>("x") ?? 0f,
                rotation.Value<float?>("y") ?? 0f,
                rotation.Value<float?>("z") ?? 0f,
                rotation.Value<float?>("w") ?? 1f);
        }

        private static float AgeFromMs(long timestampMs)
        {
            if (timestampMs <= 0)
            {
                return 999f;
            }
            return Mathf.Max(0f,
                (float)(DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - timestampMs) / 1000f);
        }

        private static string[] ReadStringArray(JArray array)
        {
            if (array == null)
            {
                return Array.Empty<string>();
            }
            var result = new string[array.Count];
            for (var i = 0; i < array.Count; i++)
            {
                result[i] = array[i]?.ToString() ?? "";
            }
            return result;
        }

        private static string[] AffordancesFor(string label)
        {
            switch (label)
            {
                case "table": return new[] { "surface", "reachable" };
                case "chair":
                case "sofa": return new[] { "seat", "rest" };
                case "door": return new[] { "passage" };
                case "screen": return new[] { "display" };
                case "plant": return new[] { "decor" };
                default: return Array.Empty<string>();
            }
        }

        private static bool IsLargeObjectLabel(string label)
        {
            return label == "table" || label == "chair" || label == "sofa" ||
                   label == "door" || label == "window" || label == "storage" ||
                   label == "screen";
        }

        private static float LabelInterest(string label)
        {
            switch (label)
            {
                case "plant": return 0.55f;
                case "screen": return 0.5f;
                case "table": return 0.35f;
                case "chair":
                case "sofa": return 0.3f;
                case "cup":
                case "phone":
                case "book": return 0.7f;
                default: return 0.25f;
            }
        }
    }
}
