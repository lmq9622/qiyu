using System;
using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using Qiyu.Quest.Avatar;
using Qiyu.Quest.Networking;
using Qiyu.Quest.Perception;
using Qiyu.Quest.Voice;
using UnityEngine;
using UnityEngine.AI;

namespace Qiyu.Quest.Behavior
{
    /// <summary>
    /// Quest 本地 Character Behavior Runtime（5–10 Hz）。
    ///
    /// 输入：WorldState + CharacterState + AvatarIntent。
    /// 输出：高层 BehaviorDecision → 移动/注意力/动画执行层。
    ///
    /// 该层不是简单状态机：
    /// - 每 tick 生成行为 × 目标候选；
    /// - 学习型 TinyBehaviorPolicy + 确定性 Utility 共同打分；
    /// - 最小驻留、切换成本、重复惩罚、目标锁定；
    /// - Reflex Layer 可硬覆盖；
    /// - LLM 永远不直接控制骨骼/脚步/路径。
    /// </summary>
    [DefaultExecutionOrder(-80)]
    public class CharacterBehaviorRuntime : MonoBehaviour
    {
        [Header("依赖")]
        [SerializeField] private QiyuQuestWebSocketClient webSocketClient;
        [SerializeField] private MrukWorldStatePublisher worldStatePublisher;
        [SerializeField] private CharacterWorldModel worldModel;
        [SerializeField] private CharacterStateStore stateStore;
        [SerializeField] private TinyBehaviorPolicy behaviorPolicy;
        [Tooltip("可选：任何实现 ICharacterBehaviorPolicy 的 MonoBehaviour；留空则使用 BehaviorPolicyV1")]
        [SerializeField] private MonoBehaviour behaviorPolicyProvider;
        [SerializeField] private CharacterReflexLayer reflexLayer;
        [SerializeField] private CharacterLocomotionController locomotion;
        [SerializeField] private CharacterAttentionController attention;
        [SerializeField] private CharacterAnimationController animationController;
        [SerializeField] private QuestMicrophoneCapture microphone;
        [SerializeField] private QuestTtsPlayer ttsPlayer;
        [SerializeField] private HumanMotionCapture humanMotionCapture;
        [SerializeField] private MotionUnderstanding motionUnderstanding;
        [SerializeField] private SharedAttentionController sharedAttention;
        [SerializeField] private InteractionStateController interactionState;
        [SerializeField] private HumanAvatarInteractionController humanAvatarInteraction;

        [Header("角色引用")]
        [SerializeField] private Transform avatarRoot;
        [SerializeField] private Transform userHead;

        [Header("运行时")]
        [SerializeField] private float policyTickHz = 8f;
        [SerializeField] private float telemetryHz = 2f;
        [SerializeField] private float intentMaxAgeSeconds = 14f;
        [SerializeField] private float minBehaviorDwellSeconds = 0.75f;
        [SerializeField] private float switchScoreMargin = 0.08f;
        [SerializeField] private float autonomyCooldownSeconds = 75f;

        public BehaviorDecision CurrentDecision { get; private set; } = new BehaviorDecision();
        public AvatarIntentData CurrentIntent { get; private set; } = new AvatarIntentData();
        public WorldSnapshotData World => worldModel != null ? worldModel.Snapshot : new WorldSnapshotData();
        public CharacterStateData State => stateStore != null ? stateStore.State : new CharacterStateData();

        public event Action<BehaviorDecision> OnDecisionChanged;

        private readonly BehaviorCandidateGenerator _candidateGenerator =
            new BehaviorCandidateGenerator();
        private float _nextPolicyTickAt;
        private float _nextTelemetryAt;
        private float _lastAutonomyRequestAt = -999f;
        private ICharacterBehaviorPolicy _policy;
        private bool _initialized;

        private void Awake()
        {
            EnsureRuntimeComponents();
            ResolveDependencies();
            ResolvePolicy();
        }

        private void OnEnable()
        {
            if (webSocketClient != null)
            {
                webSocketClient.OnAvatarIntent += HandleAvatarIntent;
                webSocketClient.OnCharacterState += HandleCharacterState;
                webSocketClient.SessionEstablished += HandleSessionEstablished;
            }
            if (microphone != null)
            {
                microphone.OnSpeechStart += HandleUserSpeechStart;
                microphone.OnSpeechEnd += HandleUserSpeechEnd;
                microphone.OnBargeInDetected += HandleBargeIn;
            }
            if (ttsPlayer != null)
            {
                ttsPlayer.OnSpeechSegmentStart += HandleTtsStart;
                ttsPlayer.OnSpeechSegmentEnd += HandleTtsEnd;
            }
            if (humanAvatarInteraction != null)
            {
                humanAvatarInteraction.OnDirective += HandleHumanDirective;
            }
        }

        private void OnDisable()
        {
            if (webSocketClient != null)
            {
                webSocketClient.OnAvatarIntent -= HandleAvatarIntent;
                webSocketClient.OnCharacterState -= HandleCharacterState;
                webSocketClient.SessionEstablished -= HandleSessionEstablished;
            }
            if (microphone != null)
            {
                microphone.OnSpeechStart -= HandleUserSpeechStart;
                microphone.OnSpeechEnd -= HandleUserSpeechEnd;
                microphone.OnBargeInDetected -= HandleBargeIn;
            }
            if (ttsPlayer != null)
            {
                ttsPlayer.OnSpeechSegmentStart -= HandleTtsStart;
                ttsPlayer.OnSpeechSegmentEnd -= HandleTtsEnd;
            }
            if (humanAvatarInteraction != null)
            {
                humanAvatarInteraction.OnDirective -= HandleHumanDirective;
            }
        }

        private void Start()
        {
            ResolveDependencies();
            if (avatarRoot == null)
            {
                var found = GameObject.Find("QiyuAvatar");
                avatarRoot = found != null ? found.transform : transform;
            }
            if (userHead == null)
            {
                var found = GameObject.Find("CenterEyeAnchor");
                userHead = found != null ? found.transform : null;
            }
            if (worldModel != null)
            {
                worldModel.AvatarRoot = avatarRoot;
            }
            if (locomotion != null)
            {
                locomotion.UserHead = userHead;
            }
            if (attention != null)
            {
                attention.UserHead = userHead;
            }
            _initialized = true;
            _lastAutonomyRequestAt = Time.realtimeSinceStartup -
                                     Mathf.Max(0f, autonomyCooldownSeconds * 0.5f);
            CommitDecision(new BehaviorDecision
            {
                kind = BehaviorKind.Idle,
                targetId = "",
                confidence = 0.4f,
                policySource = "bootstrap",
                sinceMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                reason = "runtime_start",
            }, "bootstrap");
            Debug.Log("[QiyuBehavior] Character Behavior Runtime 启动");
        }

        private void Update()
        {
            if (!_initialized)
            {
                return;
            }
            worldModel?.TickAge();
            var world = World;
            reflexLayer?.Tick(world, State);
            sharedAttention?.Tick(world, State, CurrentDecision);
            interactionState?.Tick(world, State, CurrentDecision,
                humanAvatarInteraction != null ? humanAvatarInteraction.LastEvent : null);

            if (Time.realtimeSinceStartup >= _nextPolicyTickAt)
            {
                _nextPolicyTickAt = Time.realtimeSinceStartup + 1f / Mathf.Max(1f, policyTickHz);
                TickPolicy(world);
            }

            // 高频执行层：移动/注视/动画每帧消费同一个高层决策。
            attention?.Tick(world, State, CurrentDecision);
            animationController?.Apply(CurrentDecision, State, world);
            if (Time.realtimeSinceStartup >= _nextTelemetryAt)
            {
                _nextTelemetryAt = Time.realtimeSinceStartup + 1f / Mathf.Max(0.5f, telemetryHz);
                PublishTelemetry();
            }
        }

        private void TickPolicy(WorldSnapshotData world)
        {
            worldModel?.UpdateSnapshot(worldStatePublisher != null
                ? worldStatePublisher.LatestPayload : null);
            world = World;
            if (!worldModel.IsWorldFresh)
            {
                CurrentIntent = new AvatarIntentData
                {
                    goal = "idle",
                    receivedAtMs = 0,
                    emotion = State.emotion.label,
                    emotionIntensity = State.emotion.intensity,
                };
            }
            else if (CurrentIntent.AgeSeconds > intentMaxAgeSeconds)
            {
                CurrentIntent = new AvatarIntentData
                {
                    goal = "idle",
                    receivedAtMs = 0,
                    emotion = State.emotion.label,
                    emotionIntensity = State.emotion.intensity,
                };
            }
            // Shared Attention：用户看/指向目标后，角色自然跟随注意力；
            // 只在低冲突状态下接管，不覆盖用户说话、危险或高优先级指令。
            var shared = sharedAttention != null ? sharedAttention.Current : null;
            if (shared != null && !string.IsNullOrEmpty(shared.sharedTarget) &&
                shared.attentionConfidence >= 0.55f &&
                !world.userSpeaking &&
                (CurrentIntent.goal == "idle" || CurrentIntent.goal == "observe_user"))
            {
                CurrentIntent = new AvatarIntentData
                {
                    goal = shared.sharedTarget == "user" ? "observe_user" : "observe_object",
                    target = shared.sharedTarget,
                    attention = shared.sharedTarget,
                    emotion = State.emotion.label,
                    emotionIntensity = State.emotion.intensity,
                    behaviorStyle = "casual",
                    urgency = 0.15f,
                    socialPriority = 0.6f,
                    priority = 2,
                    receivedAtMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                };
            }

            var reflex = reflexLayer != null ? reflexLayer.Current : null;
            if (reflex != null && reflex.active &&
                reflex.priority >= CurrentDecision.priority)
            {
                var forced = new BehaviorDecision
                {
                    kind = reflex.kind,
                    targetId = reflex.targetId,
                    confidence = 1f,
                    priority = reflex.priority,
                    speedScale = reflex.kind == BehaviorKind.ReflexStepBack ? 0.55f : 0.25f,
                    gazeWeight = 0.9f,
                    interruptible = false,
                    policySource = "reflex",
                    reason = reflex.reason,
                };
                CommitDecision(forced, "reflex");
                return;
            }

            var candidates = _candidateGenerator.Generate(State, world, CurrentIntent);
            if (candidates == null || candidates.Count == 0)
            {
                return;
            }
            BehaviorCandidate best = null;
            var policyReady = _policy != null && _policy.IsReady;
            for (var i = 0; i < candidates.Count; i++)
            {
                var candidate = candidates[i];
                if (policyReady && candidate.features != null)
                {
                    if (_policy.Score(candidate.features,
                            out var learned, out var parameters))
                    {
                        candidate.learnedScore = learned;
                        candidate.finalScore = _policy.Blend(candidate.utility, learned);
                        ApplyPolicyParameters(candidate, parameters);
                    }
                    else
                    {
                        candidate.finalScore = candidate.utility;
                    }
                }
                else
                {
                    candidate.finalScore = candidate.utility;
                }

                // 滞回与重复惩罚：相同行为有轻微优势，频繁切换会被压低。
                if (candidate.kind == CurrentDecision.kind)
                {
                    candidate.finalScore += 0.14f;
                }
                if (candidate.hardNegative)
                {
                    candidate.finalScore -= 0.35f;
                }
                candidate.finalScore -= Mathf.Clamp01(State.recentSwitchCount / 12f) * 0.08f;
                candidate.finalScore -= RepetitionPenalty(candidate);
                if (best == null || candidate.finalScore > best.finalScore)
                {
                    best = candidate;
                }
            }
            if (best == null)
            {
                return;
            }
            best = ApplyRuntimeConstraints(best, candidates, world);

            var decision = new BehaviorDecision
            {
                kind = best.kind,
                targetId = best.targetId,
                confidence = Mathf.Clamp01(best.finalScore),
                priority = PriorityFor(best.kind),
                desiredDistanceMeters = best.desiredDistanceMeters,
                speedScale = best.speedScale,
                gazeWeight = best.gazeWeight,
                gestureProbability = best.gestureProbability,
                lookAwayRate = best.lookAwayRate,
                speechUrge = best.speechUrge,
                interruptible = best.interruptibility > 0.45f,
                policySource = policyReady ? $"{_policy.SourceName}+utility" : "utility",
                reason = best.reason,
            };
            if (!ShouldSwitch(decision, best, candidates))
            {
                MaybeRequestAutonomy(world);
                return;
            }
            CommitDecision(decision, decision.policySource);
            MaybeRequestAutonomy(world);
        }

        private bool ShouldSwitch(BehaviorDecision next, BehaviorCandidate candidate,
                                  IReadOnlyList<BehaviorCandidate> candidates)
        {
            if (next.kind == CurrentDecision.kind &&
                string.Equals(next.targetId, CurrentDecision.targetId, StringComparison.Ordinal))
            {
                return true;
            }
            if (next.priority > CurrentDecision.priority + 0.5f)
            {
                return true;
            }
            if (!CurrentDecision.interruptible)
            {
                return false;
            }
            var age = (DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() -
                       CurrentDecision.sinceMs) / 1000f;
            if (age < minBehaviorDwellSeconds)
            {
                return false;
            }
            var currentScore = 0f;
            for (var i = 0; i < candidates.Count; i++)
            {
                if (candidates[i].kind == CurrentDecision.kind &&
                    string.Equals(candidates[i].targetId, CurrentDecision.targetId,
                        StringComparison.Ordinal))
                {
                    currentScore = candidates[i].finalScore;
                    break;
                }
            }
            return candidate.finalScore >= currentScore + switchScoreMargin;
        }

        private BehaviorCandidate ApplyRuntimeConstraints(
            BehaviorCandidate best, IReadOnlyList<BehaviorCandidate> candidates,
            WorldSnapshotData world)
        {
            if (world != null && world.userSpeaking)
            {
                BehaviorCandidate listening = null;
                for (var i = 0; i < candidates.Count; i++)
                {
                    var candidate = candidates[i];
                    if (candidate.hardNegative)
                    {
                        continue;
                    }
                    if (candidate.kind != BehaviorKind.ListenUser &&
                        candidate.kind != BehaviorKind.Nod &&
                        candidate.kind != BehaviorKind.ObserveUser &&
                        candidate.kind != BehaviorKind.Think)
                    {
                        continue;
                    }
                    if (listening == null || candidate.finalScore > listening.finalScore)
                    {
                        listening = candidate;
                    }
                }
                if (listening != null)
                {
                    best = listening;
                }
            }
            // 指令目标仍有效时，避免无理由放弃；只在分数接近时保留目标。
            var desired = BehaviorCatalog.FromGoal(CurrentIntent.goal);
            if (desired != BehaviorKind.Idle)
            {
                BehaviorCandidate goalCandidate = null;
                for (var i = 0; i < candidates.Count; i++)
                {
                    var candidate = candidates[i];
                    if (candidate.kind == desired && !candidate.hardNegative)
                    {
                        if (goalCandidate == null ||
                            candidate.finalScore > goalCandidate.finalScore)
                        {
                            goalCandidate = candidate;
                        }
                    }
                }
                if (goalCandidate != null &&
                    goalCandidate.finalScore >= best.finalScore - 0.18f)
                {
                    best = goalCandidate;
                }
            }
            if (best.hardNegative)
            {
                BehaviorCandidate safe = null;
                for (var i = 0; i < candidates.Count; i++)
                {
                    var candidate = candidates[i];
                    if (!candidate.hardNegative &&
                        (safe == null || candidate.finalScore > safe.finalScore))
                    {
                        safe = candidate;
                    }
                }
                if (safe != null)
                {
                    best = safe;
                }
            }
            return best;
        }

        private void CommitDecision(BehaviorDecision decision, string source)
        {
            decision.policySource = source ?? decision.policySource;
            if (decision.sinceMs <= 0)
            {
                decision.sinceMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            }
            CurrentDecision = decision;
            stateStore?.SetBehavior(decision);
            stateStore?.SetAttention(decision.targetId, decision.gazeWeight);
            ExecuteDecision(decision);
            OnDecisionChanged?.Invoke(decision);
        }

        private void ExecuteDecision(BehaviorDecision decision)
        {
            var world = World;
            switch (decision.kind)
            {
                case BehaviorKind.ApproachUser:
                case BehaviorKind.FollowUser:
                    locomotion?.MoveNearUser(decision.desiredDistanceMeters,
                        decision.speedScale, decision.kind.ToString());
                    break;
                case BehaviorKind.MaintainDistance:
                    locomotion?.KeepDistanceFromUser(decision.desiredDistanceMeters,
                        decision.speedScale);
                    break;
                case BehaviorKind.Retreat:
                    MoveAwayFromUser(decision, 1.0f);
                    break;
                case BehaviorKind.ReflexStepBack:
                    MoveAwayFromUser(decision, 0.65f);
                    break;
                case BehaviorKind.ReflexDodge:
                    MoveSideways(decision, 0.8f);
                    break;
                case BehaviorKind.GoToObject:
                case BehaviorKind.InspectObject:
                case BehaviorKind.InviteToObject:
                case BehaviorKind.Sit:
                {
                    var entity = world.FindEntity(decision.targetId);
                    if (entity != null && entity.visible && locomotion != null)
                    {
                        var distance = decision.kind == BehaviorKind.InspectObject
                            ? 0.55f : decision.desiredDistanceMeters;
                        locomotion.MoveTo(entity.position, distance, decision.speedScale,
                            entity.id, true);
                    }
                    else
                    {
                        locomotion?.Stop("target_missing");
                    }
                    break;
                }
                case BehaviorKind.Reposition:
                    MoveToRepositionPoint(decision);
                    break;
                case BehaviorKind.ReflexStop:
                case BehaviorKind.ReflexFreeze:
                    locomotion?.Stop("reflex");
                    break;
                default:
                    locomotion?.Stop();
                    if (decision.kind == BehaviorKind.ObserveUser ||
                        decision.kind == BehaviorKind.ListenUser ||
                        decision.kind == BehaviorKind.Speak ||
                        decision.kind == BehaviorKind.ComfortUser)
                    {
                        locomotion?.FaceUser();
                    }
                    break;
            }
        }

        private void MoveAwayFromUser(BehaviorDecision decision, float distance)
        {
            if (locomotion == null || userHead == null)
            {
                return;
            }
            var away = locomotion.transform.position - userHead.position;
            away.y = 0f;
            if (away.sqrMagnitude < 0.001f)
            {
                away = -locomotion.transform.forward;
            }
            var target = locomotion.transform.position + away.normalized * distance;
            locomotion.MoveTo(target, 0.05f, decision.speedScale,
                "user", false);
        }

        private void MoveSideways(BehaviorDecision decision, float distance)
        {
            if (locomotion == null)
            {
                return;
            }
            var side = Vector3.Cross(Vector3.up, locomotion.transform.forward).normalized;
            var sign = ((int)(Time.realtimeSinceStartup * 0.5f) & 1) == 0 ? 1f : -1f;
            locomotion.MoveTo(locomotion.transform.position + side * distance * sign,
                0.05f, decision.speedScale, "", false);
        }

        private void MoveToRepositionPoint(BehaviorDecision decision)
        {
            if (locomotion == null)
            {
                return;
            }
            var origin = locomotion.transform.position;
            var user = userHead != null ? userHead.position : origin + locomotion.transform.forward;
            var side = Vector3.Cross(Vector3.up, (user - origin).normalized).normalized;
            var offset = side * (0.7f + 0.2f * Mathf.Sin(Time.realtimeSinceStartup * 0.37f));
            var candidate = origin + offset;
            if (NavMesh.SamplePosition(candidate, out var hit, 0.8f, NavMesh.AllAreas))
            {
                locomotion.MoveTo(hit.position, 0.1f, decision.speedScale,
                    "reposition", false);
            }
        }

        private void ApplyPolicyParameters(BehaviorCandidate candidate, float[] parameters)
        {
            if (parameters == null || parameters.Length < 6)
            {
                return;
            }
            candidate.desiredDistanceMeters = Mathf.Lerp(0.55f, 2.2f, parameters[0]);
            candidate.speedScale = Mathf.Clamp01(parameters[1]);
            candidate.gazeWeight = Mathf.Clamp01(parameters[2]);
            candidate.gestureProbability = Mathf.Clamp01(parameters[3]);
            candidate.lookAwayRate = Mathf.Clamp01(parameters[4]);
            candidate.speechUrge = Mathf.Clamp01(parameters[5]);
        }

        private float RepetitionPenalty(BehaviorCandidate candidate)
        {
            if (candidate.kind == BehaviorKind.Idle)
            {
                return 0f;
            }
            if (candidate.kind == CurrentDecision.kind)
            {
                return 0f;
            }
            var age = (DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() -
                       CurrentDecision.sinceMs) / 1000f;
            if (age < 1.5f)
            {
                return 0.08f;
            }
            if (candidate.kind == BehaviorKind.ApproachUser ||
                candidate.kind == BehaviorKind.Retreat ||
                candidate.kind == BehaviorKind.Reposition)
            {
                return Mathf.Clamp01(State.recentSwitchCount / 6f) * 0.12f;
            }
            return 0f;
        }

        private void MaybeRequestAutonomy(WorldSnapshotData world)
        {
            if (webSocketClient == null || !webSocketClient.HandshakeDone)
            {
                return;
            }
            if (CurrentIntent.AgeSeconds < intentMaxAgeSeconds || !world.userVisible)
            {
                return;
            }
            if (CurrentDecision.kind != BehaviorKind.Idle &&
                CurrentDecision.kind != BehaviorKind.ObserveUser &&
                CurrentDecision.kind != BehaviorKind.ObserveObject)
            {
                return;
            }
            if (Time.realtimeSinceStartup - _lastAutonomyRequestAt < autonomyCooldownSeconds)
            {
                return;
            }
            if (State.relationship.affinity < 58f || State.drives.energy < 0.25f ||
                State.drives.socialBattery < 0.2f)
            {
                return;
            }
            _lastAutonomyRequestAt = Time.realtimeSinceStartup;
            stateStore?.NoteAutonomyRequest();
            var speechUrge = CurrentDecision != null ? CurrentDecision.speechUrge : 0.2f;
            var reason = speechUrge > 0.55f
                ? "high_speech_urge"
                : (world.userIdleSeconds > 90f
                    ? "long_silence_high_affinity"
                    : "autonomous_check_in");
            _ = webSocketClient.SendAutonomyRequestAsync(
                reason,
                Mathf.Clamp01(0.2f + speechUrge * 0.5f +
                              (State.relationship.affinity - 58f) / 200f),
                Mathf.Clamp01(0.45f + State.relationship.affinity / 250f),
                Mathf.RoundToInt(autonomyCooldownSeconds),
                world.sceneVersion);
            Debug.Log($"[QiyuBehavior] 请求低频自主表达: {reason}");
        }

        private void PublishTelemetry()
        {
            if (webSocketClient == null || !webSocketClient.HandshakeDone)
            {
                return;
            }
            var world = World;
            var decision = CurrentDecision;
            var payload = new JObject
            {
                ["schema_version"] = "1.1",
                ["ts"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                ["active_behavior"] = BehaviorCatalog.ToName(decision.kind),
                ["goal"] = CurrentIntent.goal,
                ["target_id"] = decision.targetId,
                ["priority"] = decision.priority,
                ["confidence"] = decision.confidence,
                ["policy_source"] = decision.policySource,
                ["since_ms"] = decision.sinceMs,
                ["interruptible"] = decision.interruptible,
                ["locomotion"] = new JObject
                {
                    ["moving"] = locomotion != null && locomotion.IsMoving,
                    ["speed_mps"] = locomotion != null && locomotion.IsMoving
                        ? locomotion.CurrentSpeedMps : 0f,
                    ["distance_to_user_m"] = world.userDistanceMeters,
                    ["stuck"] = locomotion != null && locomotion.IsStuck
                },
                ["attention"] = new JObject
                {
                    ["target_id"] = attention != null ? attention.CurrentTargetId : decision.targetId,
                    ["gaze_weight"] = attention != null ? attention.GazeWeight : decision.gazeWeight
                },
                ["motion"] = new JObject
                {
                    ["motion_id"] = animationController != null
                        ? animationController.CurrentMotionId : "",
                    ["blend"] = 0.2f
                },
                ["reflex"] = new JObject
                {
                    ["active"] = reflexLayer != null && reflexLayer.HasActiveOverride,
                    ["kind"] = reflexLayer != null && reflexLayer.HasActiveOverride
                        ? BehaviorCatalog.ToName(reflexLayer.Current.kind) : ""
                },
                ["latency_ms"] = new JObject
                {
                    ["policy"] = decision.policyLatencyMs,
                    ["intent_age"] = CurrentIntent.AgeSeconds * 1000f
                }
            };
            _ = webSocketClient.SendBehaviorStateAsync(payload);
        }

        private void HandleAvatarIntent(JObject payload)
        {
            if (payload == null)
            {
                return;
            }
            var intent = new AvatarIntentData
            {
                schemaVersion = payload.Value<string>("schema_version") ?? "1.1",
                intentId = payload.Value<string>("intent_id") ?? payload.Value<string>("id") ?? "",
                goal = payload.Value<string>("goal") ?? "idle",
                target = payload.Value<string>("target") ?? "",
                attention = payload.Value<string>("attention") ?? "",
                emotion = payload.Value<string>("emotion") ?? "neutral",
                emotionIntensity = payload.Value<float?>("emotion_intensity") ??
                                   payload.Value<float?>("intensity") ?? 0f,
                behaviorStyle = payload.Value<string>("behavior_style") ?? "neutral",
                urgency = payload.Value<float?>("urgency") ?? 0f,
                socialPriority = payload.Value<float?>("social_priority") ?? 0.5f,
                durationHintMs = payload.Value<int?>("duration_hint_ms") ?? 0,
                speechAct = payload.Value<string>("speech_act") ?? "",
                speaking = payload.Value<bool?>("speaking") ?? false,
                responseId = payload.Value<string>("response_id") ?? "",
                cancelOnBargeIn = payload.Value<bool?>("cancel_on_barge_in") ?? true,
                priority = payload.Value<int?>("priority") ?? 1,
                interruptPolicy = payload.Value<string>("interrupt_policy") ?? "on_higher_priority",
                expressionHint = payload.Value<string>("expression") ?? "",
                gestureHint = payload.Value<string>("gesture") ?? "",
                receivedAtMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
            };
            var spatialHint = payload["spatial_hint"] as JObject;
            if (spatialHint != null)
            {
                intent.spatialTargetId = spatialHint.Value<string>("target_id") ?? "";
                intent.desiredDistanceMeters =
                    spatialHint.Value<float?>("desired_distance_m") ?? 0.9f;
                intent.spatialFaceTarget = spatialHint.Value<bool?>("face_target") ?? true;
            }
            CurrentIntent = intent;
            stateStore?.ApplyIntent(intent);
            if (intent.speaking)
            {
                stateStore?.SetSpeechState("speaking");
            }
            else if (intent.goal == "listen_user")
            {
                stateStore?.SetSpeechState("listening");
            }
            else if (intent.goal == "think")
            {
                stateStore?.SetSpeechState("thinking");
            }
            Debug.Log($"[QiyuBehavior] AvatarIntent goal={intent.goal} " +
                      $"target={intent.target} urgency={intent.urgency:F2}");
        }

        private void HandleCharacterState(JObject payload)
        {
            stateStore?.ApplyServerState(payload);
        }

        private void HandleSessionEstablished()
        {
            if (webSocketClient == null)
            {
                return;
            }
            _ = webSocketClient.SendCharacterStateAsync(stateStore?.ToJObject() ?? new JObject());
            PublishTelemetry();
        }

        private void HandleUserSpeechStart()
        {
            stateStore?.NoteInteraction();
            stateStore?.SetSpeechState("listening");
            if (webSocketClient != null)
            {
                _ = webSocketClient.SendInteractionEventAsync("user_speech_start", "user");
            }
        }

        private void HandleUserSpeechEnd()
        {
            stateStore?.NoteInteraction();
            stateStore?.SetSpeechState("thinking");
            if (webSocketClient != null)
            {
                _ = webSocketClient.SendInteractionEventAsync("user_speech_end", "user");
            }
        }

        private void HandleBargeIn()
        {
            reflexLayer?.TriggerBargeIn();
            stateStore?.SetSpeechState("interrupted");
            stateStore?.NoteInteraction();
            if (webSocketClient != null)
            {
                _ = webSocketClient.SendInteractionEventAsync("barge_in", "user");
            }
        }

        private void HandleTtsStart(string text)
        {
            stateStore?.SetSpeechState("speaking");
        }

        private void HandleTtsEnd(string responseId, bool interrupted)
        {
            stateStore?.SetSpeechState(interrupted ? "listening" : "idle");
        }

        private void ResolveDependencies()
        {
            if (worldModel == null) worldModel = GetComponent<CharacterWorldModel>();
            if (stateStore == null) stateStore = GetComponent<CharacterStateStore>();
            if (behaviorPolicy == null) behaviorPolicy = GetComponent<TinyBehaviorPolicy>();
            if (humanMotionCapture == null) humanMotionCapture = GetComponent<HumanMotionCapture>();
            if (motionUnderstanding == null) motionUnderstanding = GetComponent<MotionUnderstanding>();
            if (sharedAttention == null) sharedAttention = GetComponent<SharedAttentionController>();
            if (interactionState == null) interactionState = GetComponent<InteractionStateController>();
            if (humanAvatarInteraction == null)
                humanAvatarInteraction = GetComponent<HumanAvatarInteractionController>();
            if (reflexLayer == null) reflexLayer = GetComponent<CharacterReflexLayer>();
            if (locomotion == null) locomotion = GetComponent<CharacterLocomotionController>();
            if (attention == null) attention = GetComponent<CharacterAttentionController>();
            if (animationController == null)
                animationController = GetComponent<CharacterAnimationController>();
            if (microphone == null) microphone = FindFirstObjectByType<QuestMicrophoneCapture>();
            if (ttsPlayer == null) ttsPlayer = FindFirstObjectByType<QuestTtsPlayer>();
            if (worldStatePublisher == null)
                worldStatePublisher = FindFirstObjectByType<MrukWorldStatePublisher>();
            if (webSocketClient == null)
                webSocketClient = FindFirstObjectByType<QiyuQuestWebSocketClient>();
        }

        private void ResolvePolicy()
        {
            var providerPolicy = behaviorPolicyProvider as ICharacterBehaviorPolicy;
            if (providerPolicy != null && !providerPolicy.IsReady)
            {
                providerPolicy.Load();
            }
            _policy = providerPolicy != null && providerPolicy.IsReady
                ? providerPolicy : null;
            if (_policy == null)
            {
                _policy = behaviorPolicy as ICharacterBehaviorPolicy;
            }
            if (_policy == null)
            {
                _policy = GetComponent<TinyBehaviorPolicy>() as ICharacterBehaviorPolicy;
            }
            if (_policy != null && !_policy.IsReady)
            {
                _policy.Load();
            }
        }

        private void HandleHumanDirective(AvatarIntentData directive)
        {
            if (directive == null)
            {
                return;
            }
            directive.receivedAtMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            CurrentIntent = directive;
            stateStore?.ApplyIntent(directive);
            if (directive.priority >= 4)
            {
                interactionState?.Interrupt(directive.goal);
            }
            Debug.Log($"[QiyuBehavior] Human→Avatar directive goal={directive.goal} " +
                      $"target={directive.target} priority={directive.priority}");
        }

        /// <summary>
        /// 兼容旧场景：即使场景尚未重新执行 QiyuP0Setup，也能补齐行为运行时组件。
        /// 这是装配兜底，不改变任何模型/协议语义。
        /// </summary>
        public void EnsureRuntimeComponents()
        {
            if (worldModel == null) worldModel = GetComponent<CharacterWorldModel>();
            if (worldModel == null) worldModel = gameObject.AddComponent<CharacterWorldModel>();
            if (stateStore == null) stateStore = GetComponent<CharacterStateStore>();
            if (stateStore == null) stateStore = gameObject.AddComponent<CharacterStateStore>();
            if (behaviorPolicy == null) behaviorPolicy = GetComponent<TinyBehaviorPolicy>();
            if (behaviorPolicy == null) behaviorPolicy = gameObject.AddComponent<TinyBehaviorPolicy>();
            if (reflexLayer == null) reflexLayer = GetComponent<CharacterReflexLayer>();
            if (reflexLayer == null) reflexLayer = gameObject.AddComponent<CharacterReflexLayer>();
            if (humanMotionCapture == null)
                humanMotionCapture = GetComponent<HumanMotionCapture>();
            if (humanMotionCapture == null)
                humanMotionCapture = gameObject.AddComponent<HumanMotionCapture>();
            if (motionUnderstanding == null)
                motionUnderstanding = GetComponent<MotionUnderstanding>();
            if (motionUnderstanding == null)
                motionUnderstanding = gameObject.AddComponent<MotionUnderstanding>();
            if (sharedAttention == null)
                sharedAttention = GetComponent<SharedAttentionController>();
            if (sharedAttention == null)
                sharedAttention = gameObject.AddComponent<SharedAttentionController>();
            if (interactionState == null)
                interactionState = GetComponent<InteractionStateController>();
            if (interactionState == null)
                interactionState = gameObject.AddComponent<InteractionStateController>();
            if (humanAvatarInteraction == null)
                humanAvatarInteraction = GetComponent<HumanAvatarInteractionController>();
            if (humanAvatarInteraction == null)
                humanAvatarInteraction = gameObject.AddComponent<HumanAvatarInteractionController>();
            if (GetComponent<HumanMotionSync>() == null)
                gameObject.AddComponent<HumanMotionSync>();

            if (avatarRoot == null)
            {
                var found = GameObject.Find("QiyuAvatar");
                if (found == null)
                {
                    found = new GameObject("QiyuAvatar");
                    found.transform.SetParent(transform, false);
                    found.transform.localPosition = Vector3.zero;
                    found.transform.localRotation = Quaternion.identity;
                }
                avatarRoot = found.transform;
            }
            if (avatarRoot.GetComponent<NavMeshAgent>() == null)
            {
                avatarRoot.gameObject.AddComponent<NavMeshAgent>();
            }
            if (avatarRoot.GetComponent<CapsuleCollider>() == null)
            {
                var capsule = avatarRoot.gameObject.AddComponent<CapsuleCollider>();
                capsule.height = 1.7f;
                capsule.radius = 0.25f;
                capsule.center = new Vector3(0f, 0.85f, 0f);
            }
            if (avatarRoot.GetComponent<Rigidbody>() == null)
            {
                var body = avatarRoot.gameObject.AddComponent<Rigidbody>();
                body.isKinematic = true;
                body.useGravity = false;
            }
            if (avatarRoot.GetComponent<CharacterLocomotionController>() == null)
            {
                avatarRoot.gameObject.AddComponent<CharacterLocomotionController>();
            }
            if (avatarRoot.GetComponent<AvatarLookController>() == null)
            {
                avatarRoot.gameObject.AddComponent<AvatarLookController>();
            }
            if (avatarRoot.GetComponent<MotionLibrary>() == null)
            {
                avatarRoot.gameObject.AddComponent<MotionLibrary>();
            }
            if (avatarRoot.GetComponent<ProceduralMotionFallback>() == null)
            {
                avatarRoot.gameObject.AddComponent<ProceduralMotionFallback>();
            }
            if (avatarRoot.GetComponent<BlendShapeAvatarDriver>() == null)
            {
                avatarRoot.gameObject.AddComponent<BlendShapeAvatarDriver>();
            }
            if (avatarRoot.GetComponent<CharacterAnimationController>() == null)
            {
                avatarRoot.gameObject.AddComponent<CharacterAnimationController>();
            }
            if (avatarRoot.GetComponent<CharacterAttentionController>() == null)
            {
                avatarRoot.gameObject.AddComponent<CharacterAttentionController>();
            }
            locomotion = avatarRoot.GetComponent<CharacterLocomotionController>();
            attention = avatarRoot.GetComponent<CharacterAttentionController>();
            animationController = avatarRoot.GetComponent<CharacterAnimationController>();
            if (worldModel != null)
            {
                worldModel.AvatarRoot = avatarRoot;
            }
        }

        private static float PriorityFor(BehaviorKind kind)
        {
            switch (kind)
            {
                case BehaviorKind.ReflexStop:
                case BehaviorKind.ReflexFreeze:
                case BehaviorKind.ReflexStepBack:
                case BehaviorKind.ReflexDodge:
                    return (float)BehaviorPriority.Safety;
                case BehaviorKind.ListenUser:
                    return (float)BehaviorPriority.Reflex;
                case BehaviorKind.Speak:
                case BehaviorKind.ComfortUser:
                case BehaviorKind.ApproachUser:
                case BehaviorKind.FollowUser:
                case BehaviorKind.GoToObject:
                case BehaviorKind.InspectObject:
                case BehaviorKind.Sit:
                    return (float)BehaviorPriority.Task;
                case BehaviorKind.Idle:
                    return (float)BehaviorPriority.Idle;
                default:
                    return (float)BehaviorPriority.Social;
            }
        }
    }
}
