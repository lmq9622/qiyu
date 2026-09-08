using System;
using Newtonsoft.Json.Linq;
using Qiyu.Quest.Networking;
using Qiyu.Quest.Spatial;
using Qiyu.Quest.Voice;
using UnityEngine;

namespace Qiyu.Quest.Avatar
{
    /// <summary>
    /// 接收 avatar.intent / spatial.action，翻译成 Avatar 与空间执行层动作。
    ///
    /// 边界：LLM 只给高层意图，本层负责映射到表情/骨骼/导航，
    /// 绝不允许 LLM 直接指定骨骼坐标。
    /// </summary>
    public class AvatarIntentRouter : MonoBehaviour
    {
        [Header("依赖")]
        [SerializeField] private QiyuQuestWebSocketClient webSocketClient;
        [SerializeField] private BlendShapeAvatarDriver expressionDriver;
        [SerializeField] private AvatarLookController lookController;
        [SerializeField] private SpatialActionExecutor spatialExecutor;
        [SerializeField] private QuestTtsPlayer ttsPlayer;
        [SerializeField] private Animator animator;

        [Header("看向")]
        [SerializeField] private Transform userHead;
        [SerializeField] private bool autoFindUserHead = true;

        public string CurrentEmotion { get; private set; } = "neutral";
        public string CurrentAction { get; private set; } = "idle";
        public bool IsSpeaking { get; private set; }

        private void OnEnable()
        {
            if (webSocketClient == null)
            {
                return;
            }
            webSocketClient.OnAvatarIntent += HandleAvatarIntent;
            webSocketClient.OnSpatialAction += HandleSpatialAction;
        }

        private void OnDisable()
        {
            if (webSocketClient == null)
            {
                return;
            }
            webSocketClient.OnAvatarIntent -= HandleAvatarIntent;
            webSocketClient.OnSpatialAction -= HandleSpatialAction;
        }

        private void Start()
        {
            if (autoFindUserHead && userHead == null)
            {
                var found = GameObject.Find("CenterEyeAnchor");
                if (found != null)
                {
                    userHead = found.transform;
                }
            }
            if (spatialExecutor != null)
            {
                spatialExecutor.UserHead = userHead;
            }
            if (lookController != null)
            {
                lookController.UserHead = userHead;
            }
        }

        private void Update()
        {
            if (expressionDriver != null && ttsPlayer != null)
            {
                expressionDriver.SetMouthAmplitude(ttsPlayer.MouthAmplitude);
            }
        }

        private void HandleAvatarIntent(JObject payload)
        {
            var emotion = payload.Value<string>("emotion") ?? "neutral";
            var action = payload.Value<string>("action") ?? "idle";
            var intensity = payload.Value<float?>("intensity") ?? 0.5f;
            var speaking = payload.Value<bool?>("speaking") ?? false;
            var gesture = payload.Value<string>("gesture") ?? "";

            CurrentEmotion = emotion;
            CurrentAction = action;
            IsSpeaking = speaking;

            expressionDriver?.ApplyEmotion(emotion, intensity);
            if (animator != null && !string.IsNullOrEmpty(gesture))
            {
                animator.SetTrigger(gesture);
            }
            ApplyAction(action, payload);
        }

        private void ApplyAction(string action, JObject payload)
        {
            switch (action)
            {
                case "look_at_user":
                    lookController?.LookAtUser();
                    break;
                case "look_away":
                    lookController?.LookAway();
                    break;
                case "look_at_object":
                    if (spatialExecutor != null)
                    {
                        var targetId = payload.Value<string>("target_id") ?? "";
                        lookController?.LookAtPosition(spatialExecutor.ResolveTarget(targetId));
                    }
                    break;
                case "nod":
                case "shake":
                case "wave":
                case "lean_in":
                case "sigh":
                case "laugh":
                case "blush":
                    if (animator != null)
                    {
                        animator.SetTrigger(action);
                    }
                    break;
            }
        }

        private void HandleSpatialAction(JObject payload)
        {
            spatialExecutor?.Execute(payload);
        }
    }
}
