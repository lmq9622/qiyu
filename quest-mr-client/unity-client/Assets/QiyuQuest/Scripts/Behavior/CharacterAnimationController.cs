using System;
using System.Collections.Generic;
using Qiyu.Quest.Avatar;
using UnityEngine;

namespace Qiyu.Quest.Behavior
{
    /// <summary>
    /// 行为 → 动作库 → Animator 的选择与过渡层。
    ///
    /// 模型/行为层永远不直接写 Animator 参数；只有本层根据 MotionLibrary 执行。
    /// 没有真实动画资产时启用程序化低精度兜底，并明确记录缺失。
    /// </summary>
    public class CharacterAnimationController : MonoBehaviour
    {
        [SerializeField] private Animator animator;
        [SerializeField] private MotionLibrary motionLibrary;
        [SerializeField] private ProceduralMotionFallback proceduralFallback;
        [SerializeField] private BlendShapeAvatarDriver expressionDriver;

        public string CurrentMotionId { get; private set; } = "";
        public string LastMissingClip { get; private set; } = "";

        private readonly HashSet<string> _missingLogged = new HashSet<string>();
        private string _lastEmotion = "";
        private float _lastEmotionIntensity = -1f;

        private static readonly int SpeedHash = Animator.StringToHash("Speed");
        private static readonly int TalkingHash = Animator.StringToHash("Talking");
        private static readonly int ListeningHash = Animator.StringToHash("Listening");
        private static readonly int ThinkingHash = Animator.StringToHash("Thinking");
        private static readonly int EmotionHash = Animator.StringToHash("EmotionIntensity");
        private static readonly int MovingHash = Animator.StringToHash("Moving");

        private void Awake()
        {
            if (animator == null)
            {
                animator = GetComponentInChildren<Animator>();
            }
            if (motionLibrary == null)
            {
                motionLibrary = GetComponent<MotionLibrary>();
            }
            if (proceduralFallback == null)
            {
                proceduralFallback = GetComponent<ProceduralMotionFallback>();
            }
            if (expressionDriver == null)
            {
                expressionDriver = GetComponentInChildren<BlendShapeAvatarDriver>();
            }
        }

        public void Apply(BehaviorDecision decision, CharacterStateData state,
                          WorldSnapshotData world)
        {
            if (decision == null || state == null)
            {
                return;
            }
            var motionId = SelectMotionId(decision, state, world);
            ApplyEmotion(state);
            ApplyParameters(decision, state);
            if (string.Equals(CurrentMotionId, motionId, StringComparison.Ordinal))
            {
                return;
            }
            CurrentMotionId = motionId;
            var motion = motionLibrary != null ? motionLibrary.GetById(motionId) : null;
            var hasClip = motion != null && !string.IsNullOrEmpty(motion.clip) &&
                          animator != null && animator.runtimeAnimatorController != null;
            if (!hasClip)
            {
                LastMissingClip = motion != null ? motion.clip : motionId;
                if (_missingLogged.Add(LastMissingClip))
                {
                    Debug.LogWarning(
                        $"[QiyuAnimation] 缺少动作资产 {LastMissingClip}；" +
                        "启用程序化低精度兜底（真机最终效果需要导入授权动作）");
                }
                if (proceduralFallback != null)
                {
                    proceduralFallback.SetBehavior(decision.kind,
                        Mathf.Lerp(0.35f, 1f, decision.confidence));
                }
                return;
            }
            proceduralFallback?.Disable();
            var stateHash = Animator.StringToHash(motion.layer + "." + motion.clip);
            if (!animator.HasState(0, stateHash))
            {
                // 大多数工程把状态名放在 Base Layer，先尝试无层名前缀。
                stateHash = Animator.StringToHash(motion.clip);
            }
            if (!animator.HasState(0, stateHash))
            {
                if (_missingLogged.Add(motion.clip))
                {
                    Debug.LogWarning(
                        $"[QiyuAnimation] Animator 中找不到状态 {motion.clip}；" +
                        "Motion Library 槽位已就绪，但资产尚未导入");
                }
                proceduralFallback?.SetBehavior(decision.kind,
                    Mathf.Lerp(0.35f, 1f, decision.confidence));
                return;
            }
            var blend = Mathf.Clamp(motion.blend_s, 0.05f, 1.2f);
            animator.CrossFadeInFixedTime(stateHash, blend, 0, 0f);
        }

        private void ApplyParameters(BehaviorDecision decision, CharacterStateData state)
        {
            if (animator == null || animator.runtimeAnimatorController == null)
            {
                return;
            }
            SafeSetFloat(SpeedHash, decision.speedScale);
            SafeSetBool(MovingHash, IsMovingBehavior(decision.kind));
            SafeSetBool(TalkingHash, decision.kind == BehaviorKind.Speak ||
                                     state.speechState == "speaking");
            SafeSetBool(ListeningHash, decision.kind == BehaviorKind.ListenUser ||
                                       state.speechState == "listening");
            SafeSetBool(ThinkingHash, decision.kind == BehaviorKind.Think ||
                                      state.speechState == "thinking");
            SafeSetFloat(EmotionHash, state.emotion.intensity);
        }

        private void ApplyEmotion(CharacterStateData state)
        {
            if (expressionDriver == null)
            {
                return;
            }
            if (string.Equals(_lastEmotion, state.emotion.label, StringComparison.Ordinal) &&
                Mathf.Abs(_lastEmotionIntensity - state.emotion.intensity) < 0.03f)
            {
                return;
            }
            _lastEmotion = state.emotion.label;
            _lastEmotionIntensity = state.emotion.intensity;
            expressionDriver.ApplyEmotion(state.emotion.label, state.emotion.intensity);
        }

        private void SafeSetFloat(int hash, float value)
        {
            foreach (var parameter in animator.parameters)
            {
                if (parameter.nameHash == hash && parameter.type == AnimatorControllerParameterType.Float)
                {
                    animator.SetFloat(hash, value);
                    return;
                }
            }
        }

        private void SafeSetBool(int hash, bool value)
        {
            foreach (var parameter in animator.parameters)
            {
                if (parameter.nameHash == hash && parameter.type == AnimatorControllerParameterType.Bool)
                {
                    animator.SetBool(hash, value);
                    return;
                }
            }
        }

        private static string SelectMotionId(BehaviorDecision decision,
                                             CharacterStateData state,
                                             WorldSnapshotData world)
        {
            switch (decision.kind)
            {
                case BehaviorKind.Idle:
                    if (state.emotion.label == "embarrassed") return "emotion_embarrassed";
                    if (state.emotion.label == "curious") return "emotion_curious";
                    if (state.drives.energy < 0.25f) return "idle_tired";
                    if (state.drives.curiosity > 0.7f) return "idle_curious";
                    return "idle_relaxed";
                case BehaviorKind.ListenUser:
                    return world != null && world.userSpeaking ? "listen_nod" : "listen";
                case BehaviorKind.Think:
                    return state.emotion.label == "confused" ? "emotion_confused" : "think";
                case BehaviorKind.Speak:
                    return decision.gestureProbability > 0.45f ? "talk_gesture" : "talk";
                case BehaviorKind.ObserveUser:
                    return "look_at_user";
                case BehaviorKind.ObserveObject:
                    return "look_at_object";
                case BehaviorKind.ApproachUser:
                    return decision.speedScale > 0.9f ? "run" : "approach";
                case BehaviorKind.FollowUser:
                    return decision.speedScale > 0.85f ? "run" : "walk_fast";
                case BehaviorKind.GoToObject:
                case BehaviorKind.Reposition:
                    return decision.speedScale > 0.85f ? "walk_fast" : "walk";
                case BehaviorKind.MaintainDistance:
                    return "idle_alert";
                case BehaviorKind.Retreat:
                case BehaviorKind.ReflexStepBack:
                    return "leave";
                case BehaviorKind.PointAtObject:
                case BehaviorKind.InviteToObject:
                    return "point";
                case BehaviorKind.InspectObject:
                    return "inspect";
                case BehaviorKind.Sit:
                    return "sit";
                case BehaviorKind.Stand:
                    return "stand";
                case BehaviorKind.Wave:
                    return "wave";
                case BehaviorKind.Nod:
                    return "nod";
                case BehaviorKind.ShakeHead:
                    return state.emotion.label == "annoyed" ? "emotion_annoyed" : "shake_head";
                case BehaviorKind.Laugh:
                    return state.emotion.label == "happy" ? "emotion_happy" : "laugh";
                case BehaviorKind.Sigh:
                    return state.emotion.label == "sad" ? "emotion_sad" : "sigh";
                case BehaviorKind.Surprised:
                    return "surprised";
                case BehaviorKind.ComfortUser:
                    return "comfort";
                case BehaviorKind.ReflexStop:
                case BehaviorKind.ReflexFreeze:
                    return "reflex_freeze";
                case BehaviorKind.ReflexDodge:
                    return "reflex_dodge";
                case BehaviorKind.ReflexLookAtThreat:
                    return "look_at_threat";
                default:
                    return "idle_relaxed";
            }
        }

        private static bool IsMovingBehavior(BehaviorKind kind)
        {
            return kind == BehaviorKind.ApproachUser || kind == BehaviorKind.FollowUser ||
                   kind == BehaviorKind.GoToObject || kind == BehaviorKind.Reposition ||
                   kind == BehaviorKind.Retreat || kind == BehaviorKind.ReflexStepBack ||
                   kind == BehaviorKind.ReflexDodge;
        }
    }
}
