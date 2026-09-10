using System;
using UnityEngine;

namespace Qiyu.Quest.Behavior
{
    /// <summary>
    /// HumanInteractionEvent → 本地 AvatarIntent / Reflex / InteractionState。
    ///
    /// 这是用户动作到角色响应的桥：
    /// wave → look + wave 回应
    /// come_here → approach / follow
    /// point → look / approach target
    /// high_five → approach + gesture
    /// sit/stand → UserState + 上下文行为
    /// stop/push → 高优先级 interrupt + reflex
    /// </summary>
    [DefaultExecutionOrder(-95)]
    public class HumanAvatarInteractionController : MonoBehaviour
    {
        [SerializeField] private MotionUnderstanding motionUnderstanding;
        [SerializeField] private CharacterReflexLayer reflexLayer;
        [SerializeField] private InteractionStateController interactionState;
        [SerializeField] private CharacterWorldModel worldModel;
        [SerializeField] private Transform avatarRoot;
        [SerializeField] private float highFiveApproachMeters = 0.75f;

        public event Action<AvatarIntentData> OnDirective;
        public AvatarIntentData PendingDirective { get; private set; }
        public HumanInteractionEvent LastEvent { get; private set; }

        private void Awake()
        {
            if (motionUnderstanding == null)
                motionUnderstanding = GetComponent<MotionUnderstanding>();
            if (reflexLayer == null) reflexLayer = GetComponent<CharacterReflexLayer>();
            if (interactionState == null)
                interactionState = GetComponent<InteractionStateController>();
            if (worldModel == null) worldModel = GetComponent<CharacterWorldModel>();
            if (avatarRoot == null)
            {
                var found = GameObject.Find("QiyuAvatar");
                avatarRoot = found != null ? found.transform : transform;
            }
        }

        private void OnEnable()
        {
            if (motionUnderstanding != null)
            {
                motionUnderstanding.OnInteraction += HandleInteraction;
            }
        }

        private void OnDisable()
        {
            if (motionUnderstanding != null)
            {
                motionUnderstanding.OnInteraction -= HandleInteraction;
            }
        }

        public bool ConsumeDirective(out AvatarIntentData directive)
        {
            directive = PendingDirective;
            PendingDirective = null;
            return directive != null;
        }

        private void HandleInteraction(HumanInteractionEvent evt)
        {
            if (evt == null || evt.confidence < 0.35f)
            {
                return;
            }
            LastEvent = evt;
            var intent = new AvatarIntentData
            {
                schemaVersion = "1.1",
                intentId = evt.eventId,
                goal = "observe_user",
                target = "user",
                attention = "user",
                emotion = "curious",
                emotionIntensity = Mathf.Clamp01(evt.confidence),
                behaviorStyle = "casual",
                urgency = Mathf.Clamp01(evt.priority / 5f),
                socialPriority = 0.8f,
                priority = evt.priority,
                speaking = false,
                receivedAtMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
            };
            switch (evt.gesture)
            {
                case HumanGesture.Wave:
                    intent.goal = "wave";
                    intent.target = "user";
                    intent.attention = "user";
                    intent.emotion = "happy";
                    intent.speaking = true;
                    break;
                case HumanGesture.ComeHere:
                    intent.goal = "follow_user";
                    intent.target = "user";
                    intent.attention = "user";
                    intent.urgency = 0.7f;
                    break;
                case HumanGesture.Point:
                    intent.goal = ResolvePointGoal(evt);
                    intent.target = evt.target;
                    intent.attention = evt.target;
                    intent.emotion = "curious";
                    break;
                case HumanGesture.HighFive:
                    intent.goal = "approach_user";
                    intent.target = "user";
                    intent.emotion = "happy";
                    intent.gestureHint = "high_five";
                    intent.urgency = 0.6f;
                    intent.desiredDistanceMeters = highFiveApproachMeters;
                    break;
                case HumanGesture.Stop:
                case HumanGesture.Push:
                    reflexLayer?.TriggerDanger(evt.gesture == HumanGesture.Stop
                        ? "user_stop_gesture" : "user_push_gesture");
                    interactionState?.Interrupt(evt.gesture.ToString());
                    intent.goal = "maintain_distance";
                    intent.target = "user";
                    intent.attention = "user";
                    intent.emotion = "surprised";
                    intent.priority = 5;
                    intent.urgency = 1f;
                    break;
                case HumanGesture.Sit:
                    intent.goal = "observe_user";
                    intent.attention = "user";
                    break;
                case HumanGesture.Stand:
                    intent.goal = "observe_user";
                    intent.attention = "user";
                    break;
                case HumanGesture.Nod:
                    intent.goal = "nod";
                    intent.target = "user";
                    intent.emotion = "happy";
                    break;
                case HumanGesture.ShakeHead:
                    intent.goal = "shake_head";
                    intent.target = "user";
                    intent.emotion = "confused";
                    break;
                case HumanGesture.Look:
                    intent.goal = "observe_user";
                    intent.attention = "user";
                    break;
            }
            PendingDirective = intent;
            interactionState?.Replan(intent.goal, intent.target, evt.confidence);
            OnDirective?.Invoke(intent);
            Debug.Log($"[QiyuHumanAvatar] {evt.gesture} -> {intent.goal} " +
                      $"target={intent.target} conf={evt.confidence:F2}");
        }

        private string ResolvePointGoal(HumanInteractionEvent evt)
        {
            if (string.IsNullOrEmpty(evt.target) || worldModel == null)
            {
                return "observe_user";
            }
            var entity = worldModel.Snapshot.FindEntity(evt.target);
            if (entity == null)
            {
                return "observe_user";
            }
            var distance = avatarRoot != null
                ? Vector3.Distance(avatarRoot.position, entity.position)
                : 0f;
            if (distance > 1.8f && worldModel.Snapshot.navmeshReachable)
            {
                return "go_to_object";
            }
            return distance > 0.8f ? "point_at_object" : "observe_object";
        }
    }
}
