using System;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace Qiyu.Quest.Behavior
{
    /// <summary>
    /// Quest 本地 CharacterState。所有值都做限幅和平滑，避免情绪/耐心瞬变。
    /// 后端仍保留长期 Memory/Emotion/Relationship；本组件负责实时状态估计。
    /// </summary>
    public class CharacterStateStore : MonoBehaviour
    {
        [Header("驱动衰减/恢复")]
        [SerializeField] private float energyDrainPerMinute = 1.5f;
        [SerializeField] private float patienceRecoveryPerMinute = 8f;
        [SerializeField] private float socialRecoveryPerMinute = 4f;
        [SerializeField] private float stressDecayPerMinute = 6f;
        [SerializeField] private float emotionBlendSpeed = 2.5f;

        public CharacterStateData State { get; private set; } = new CharacterStateData();
        public AvatarIntentData ActiveIntent { get; private set; } = new AvatarIntentData();

        private float _lastInteractionAt = -999f;
        private float _lastAutonomyRequestAt = -999f;
        private float _behaviorChangedAt;
        private int _recentSwitchCount;
        private float _switchWindowStartedAt;

        public event Action<string> OnSpeechStateChanged;

        private void Awake()
        {
            _behaviorChangedAt = Time.realtimeSinceStartup;
            _switchWindowStartedAt = Time.realtimeSinceStartup;
        }

        private void Update()
        {
            Tick(Time.unscaledDeltaTime);
        }

        public void Tick(float dt)
        {
            if (dt <= 0f)
            {
                return;
            }
            var minutes = dt / 60f;
            var speech = State.speechState;
            var behavior = State.activeBehavior;

            // 精力：移动/说话消耗更高，静止缓慢恢复。
            var drain = energyDrainPerMinute;
            if (behavior == "go_to_object" || behavior == "approach_user" ||
                behavior == "follow_user" || behavior == "reposition")
            {
                drain *= 2.2f;
            }
            if (speech == "speaking")
            {
                drain *= 1.4f;
            }
            State.drives.energy = Mathf.Clamp01(
                State.drives.energy - drain * minutes + (drain < 1.7f ? 0.35f * minutes : 0f));

            // 耐心：倾听/对话中恢复更快；被频繁打断/高压力时下降。
            var patienceDelta = patienceRecoveryPerMinute;
            if (speech == "listening" || speech == "speaking")
            {
                patienceDelta *= 1.3f;
            }
            State.drives.patience = Mathf.Clamp01(
                State.drives.patience + patienceDelta * minutes - State.drives.stress * 2f * minutes);

            State.drives.socialBattery = Mathf.Clamp01(
                State.drives.socialBattery + socialRecoveryPerMinute * minutes -
                (speech == "speaking" ? 1.2f * minutes : 0f));
            State.drives.stress = Mathf.Clamp01(
                State.drives.stress - stressDecayPerMinute * minutes);

            State.currentBehaviorAgeSeconds = Mathf.Max(
                0f, Time.realtimeSinceStartup - _behaviorChangedAt);
            State.lastInteractionAgeSeconds = Time.realtimeSinceStartup - _lastInteractionAt;
            State.lastAutonomyRequestAgeSeconds = Time.realtimeSinceStartup - _lastAutonomyRequestAt;
            if (Time.realtimeSinceStartup - _switchWindowStartedAt > 20f)
            {
                _switchWindowStartedAt = Time.realtimeSinceStartup;
                _recentSwitchCount = 0;
            }
            State.recentSwitchCount = _recentSwitchCount;

            // 情绪向目标值缓慢靠近，避免表情抽动。
            var t = 1f - Mathf.Exp(-emotionBlendSpeed * dt);
            State.emotion.valence = Mathf.Lerp(State.emotion.valence, _targetValence, t);
            State.emotion.arousal = Mathf.Lerp(State.emotion.arousal, _targetArousal, t);
            State.emotion.intensity = Mathf.Lerp(State.emotion.intensity, _targetIntensity, t);
            if (t > 0.08f && !string.IsNullOrEmpty(_targetEmotion))
            {
                State.emotion.label = _targetEmotion;
            }
        }

        private string _targetEmotion = "neutral";
        private float _targetIntensity;
        private float _targetValence;
        private float _targetArousal;

        public void ApplyIntent(AvatarIntentData intent)
        {
            if (intent == null)
            {
                return;
            }
            ActiveIntent = intent;
            _lastInteractionAt = Time.realtimeSinceStartup;
            _targetEmotion = string.IsNullOrEmpty(intent.emotion) ? "neutral" : intent.emotion;
            _targetIntensity = Mathf.Clamp01(intent.emotionIntensity);
            ApplyEmotionAffect(_targetEmotion, _targetIntensity);
            State.drives.stress = Mathf.Clamp01(
                State.drives.stress + Mathf.Max(0f, intent.urgency - 0.6f) * 0.25f);
            if (string.Equals(intent.goal, "listen_user", StringComparison.Ordinal))
            {
                SetSpeechState("listening");
            }
            else if (string.Equals(intent.goal, "think", StringComparison.Ordinal))
            {
                SetSpeechState("thinking");
            }
            else if (intent.speaking)
            {
                SetSpeechState("speaking");
            }
        }

        public void ApplyServerState(JObject payload)
        {
            if (payload == null)
            {
                return;
            }
            var drives = payload["drives"] as JObject;
            if (drives != null)
            {
                State.drives.patience = drives.Value<float?>("patience") ?? State.drives.patience;
                State.drives.energy = drives.Value<float?>("energy") ?? State.drives.energy;
                State.drives.curiosity = drives.Value<float?>("curiosity") ?? State.drives.curiosity;
                State.drives.socialBattery =
                    drives.Value<float?>("social_battery") ?? State.drives.socialBattery;
                State.drives.stress = drives.Value<float?>("stress") ?? State.drives.stress;
            }
            var relationship = payload["relationship"] as JObject;
            if (relationship != null)
            {
                State.relationship.tier =
                    relationship.Value<string>("tier") ?? State.relationship.tier;
                State.relationship.affinity =
                    relationship.Value<float?>("affinity") ?? State.relationship.affinity;
                State.relationship.trust =
                    relationship.Value<float?>("trust") ?? State.relationship.trust;
                State.relationship.familiarity =
                    relationship.Value<float?>("familiarity") ?? State.relationship.familiarity;
            }
            var memory = payload["memory_context"] as JObject;
            if (memory != null)
            {
                State.salientMemoryCount =
                    memory.Value<int?>("salient_count") ?? State.salientMemoryCount;
                State.hasUnfinishedTopic =
                    memory.Value<bool?>("has_unfinished_topic") ?? State.hasUnfinishedTopic;
            }
            ClampAll();
        }

        public void SetBehavior(BehaviorDecision decision)
        {
            if (decision == null)
            {
                return;
            }
            var name = BehaviorCatalog.ToName(decision.kind);
            if (!string.Equals(State.activeBehavior, name, StringComparison.Ordinal))
            {
                _recentSwitchCount++;
            }
            State.activeBehavior = name;
            State.activeGoal = name;
            State.activeTargetId = decision.targetId ?? "";
            _behaviorChangedAt = Time.realtimeSinceStartup;
        }

        public void SetAttention(string targetId, float focus)
        {
            State.attentionTargetId = targetId ?? "";
            State.attentionFocus = Mathf.Clamp01(focus);
        }

        public void SetSpeechState(string state)
        {
            if (string.Equals(State.speechState, state, StringComparison.Ordinal))
            {
                return;
            }
            State.speechState = state ?? "idle";
            OnSpeechStateChanged?.Invoke(State.speechState);
        }

        public void NoteInteraction()
        {
            _lastInteractionAt = Time.realtimeSinceStartup;
        }

        public void NoteAutonomyRequest()
        {
            _lastAutonomyRequestAt = Time.realtimeSinceStartup;
        }

        public void ApplyEmotionDelta(string emotion, float intensity)
        {
            if (string.IsNullOrEmpty(emotion))
            {
                return;
            }
            _targetEmotion = emotion;
            _targetIntensity = Mathf.Clamp01(intensity);
            ApplyEmotionAffect(emotion, _targetIntensity);
        }

        public JObject ToJObject()
        {
            return new JObject
            {
                ["schema_version"] = "1.1",
                ["character_id"] = State.characterId,
                ["ts"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                ["emotion"] = new JObject
                {
                    ["label"] = State.emotion.label,
                    ["intensity"] = State.emotion.intensity,
                    ["valence"] = State.emotion.valence,
                    ["arousal"] = State.emotion.arousal
                },
                ["relationship"] = new JObject
                {
                    ["tier"] = State.relationship.tier,
                    ["affinity"] = State.relationship.affinity,
                    ["trust"] = State.relationship.trust,
                    ["familiarity"] = State.relationship.familiarity
                },
                ["drives"] = new JObject
                {
                    ["patience"] = State.drives.patience,
                    ["energy"] = State.drives.energy,
                    ["curiosity"] = State.drives.curiosity,
                    ["social_battery"] = State.drives.socialBattery,
                    ["stress"] = State.drives.stress
                },
                ["memory_context"] = new JObject
                {
                    ["salient_count"] = State.salientMemoryCount,
                    ["last_interaction_age_s"] = State.lastInteractionAgeSeconds,
                    ["has_unfinished_topic"] = State.hasUnfinishedTopic
                },
                ["attention"] = new JObject
                {
                    ["target_id"] = State.attentionTargetId,
                    ["focus"] = State.attentionFocus
                },
                ["speech"] = new JObject
                {
                    ["state"] = State.speechState
                },
                ["active_behavior"] = State.activeBehavior,
                ["active_goal"] = State.activeGoal,
                ["active_target_id"] = State.activeTargetId
            };
        }

        private void ApplyEmotionAffect(string emotion, float intensity)
        {
            switch ((emotion ?? "neutral").ToLowerInvariant())
            {
                case "happy":
                case "excited":
                    _targetValence = 0.8f * intensity;
                    _targetArousal = 0.75f * intensity;
                    break;
                case "calm":
                    _targetValence = 0.35f * intensity;
                    _targetArousal = 0.25f * intensity;
                    break;
                case "curious":
                    _targetValence = 0.25f * intensity;
                    _targetArousal = 0.55f * intensity;
                    break;
                case "sad":
                case "tired":
                    _targetValence = -0.6f * intensity;
                    _targetArousal = 0.2f * intensity;
                    break;
                case "annoyed":
                case "angry":
                    _targetValence = -0.7f * intensity;
                    _targetArousal = 0.7f * intensity;
                    break;
                case "surprised":
                    _targetValence = 0.1f * intensity;
                    _targetArousal = 0.9f * intensity;
                    break;
                case "shy":
                case "embarrassed":
                    _targetValence = -0.15f * intensity;
                    _targetArousal = 0.45f * intensity;
                    break;
                case "confused":
                    _targetValence = -0.25f * intensity;
                    _targetArousal = 0.5f * intensity;
                    break;
                default:
                    _targetValence = 0f;
                    _targetArousal = 0.2f * intensity;
                    break;
            }
        }

        private void ClampAll()
        {
            State.drives.patience = Mathf.Clamp01(State.drives.patience);
            State.drives.energy = Mathf.Clamp01(State.drives.energy);
            State.drives.curiosity = Mathf.Clamp01(State.drives.curiosity);
            State.drives.socialBattery = Mathf.Clamp01(State.drives.socialBattery);
            State.drives.stress = Mathf.Clamp01(State.drives.stress);
            State.relationship.affinity = Mathf.Clamp(State.relationship.affinity, 0f, 100f);
            State.relationship.trust = Mathf.Clamp(State.relationship.trust, 0f, 100f);
            State.relationship.familiarity = Mathf.Clamp(State.relationship.familiarity, 0f, 100f);
            State.emotion.intensity = Mathf.Clamp01(State.emotion.intensity);
            State.emotion.valence = Mathf.Clamp(State.emotion.valence, -1f, 1f);
            State.emotion.arousal = Mathf.Clamp01(State.emotion.arousal);
        }
    }
}
