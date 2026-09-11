using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using Qiyu.Quest.Avatar;
using Qiyu.Quest.Networking;
using UnityEngine;

namespace Qiyu.Quest.Behavior
{
    /// <summary>
    /// 接收后端 Behavior 层的计划/动作，并落到既有的本地执行能力上。
    ///
    /// 边界：
    /// - 后端只下发"动作语义 + 强度 + 目标"，不下发骨骼/Animator/坐标；
    /// - 表情走 BlendShapeAvatarDriver；移动走 CharacterLocomotionController；
    ///   其余（视线/头部/手势/身体）统一转成高层指令交给 CharacterBehaviorRuntime，
    ///   由本地行为运行时决定具体怎么动；
    /// - 现有执行层覆盖不到的动作明确记录"暂未接入"，不假装执行成功。
    /// </summary>
    public class BehaviorActionBridge : MonoBehaviour
    {
        [SerializeField] private QiyuQuestWebSocketClient webSocketClient;
        [SerializeField] private CharacterBehaviorRuntime behaviorRuntime;
        [SerializeField] private CharacterLocomotionController locomotion;
        [SerializeField] private BlendShapeAvatarDriver expressionDriver;
        [SerializeField] private bool logVerbose = true;

        private readonly Dictionary<string, string> _running = new Dictionary<string, string>();
        private readonly HashSet<string> _unsupportedLogged = new HashSet<string>();
        private int _plansReceived;
        private int _actionsStarted;
        private int _actionsUnsupported;

        public string CurrentIntent { get; private set; } = "";
        public int PlansReceived => _plansReceived;
        public int ActionsStarted => _actionsStarted;
        public int ActionsUnsupported => _actionsUnsupported;

        private void OnEnable()
        {
            if (webSocketClient == null)
            {
                webSocketClient = FindAnyObjectByType<QiyuQuestWebSocketClient>();
            }
            if (behaviorRuntime == null)
            {
                behaviorRuntime = GetComponent<CharacterBehaviorRuntime>();
            }
            if (locomotion == null)
            {
                locomotion = GetComponentInChildren<CharacterLocomotionController>();
            }
            if (expressionDriver == null)
            {
                expressionDriver = GetComponentInChildren<BlendShapeAvatarDriver>();
            }
            if (webSocketClient != null)
            {
                webSocketClient.OnBehaviorPlan += HandlePlan;
                webSocketClient.OnBehaviorAction += HandleAction;
                webSocketClient.OnBehaviorEvent += HandleEvent;
            }
        }

        private void OnDisable()
        {
            if (webSocketClient != null)
            {
                webSocketClient.OnBehaviorPlan -= HandlePlan;
                webSocketClient.OnBehaviorAction -= HandleAction;
                webSocketClient.OnBehaviorEvent -= HandleEvent;
            }
        }

        private void HandlePlan(JObject payload)
        {
            _plansReceived++;
            CurrentIntent = payload.Value<string>("intent") ?? "";
            var describe = payload.Value<string>("describe") ?? "";
            Debug.Log($"[QiyuBehaviorBridge] 行为计划 #{_plansReceived} " +
                      $"intent={CurrentIntent} describe:\n{describe}");
        }

        private void HandleEvent(JObject payload)
        {
            var action = payload.Value<string>("action") ?? "";
            var state = payload.Value<string>("state") ?? "";
            var channel = payload.Value<string>("channel") ?? "";
            if (state == "completed" || state == "cancelled" || state == "failed")
            {
                _running.Remove(action);
                if (action == "approach_user" || action == "move_away")
                {
                    locomotion?.Stop($"behavior:{action}:{state}");
                }
            }
            if (logVerbose)
            {
                var reason = payload.Value<string>("reason");
                Debug.Log($"[QiyuBehaviorBridge] 事件 {action} {state} channel={channel}" +
                          (string.IsNullOrEmpty(reason) ? "" : $" reason={reason}"));
            }
        }

        private void HandleAction(JObject payload)
        {
            var action = payload.Value<string>("action") ?? "";
            var channel = payload.Value<string>("channel") ?? "";
            var state = payload.Value<string>("state") ?? "start";
            var intensity = payload.Value<float?>("intensity") ?? 0.6f;
            var target = payload.Value<string>("target") ?? "";
            if (string.IsNullOrEmpty(action))
            {
                return;
            }
            if (state == "stop")
            {
                _running.Remove(action);
                return;
            }
            _running[action] = channel;
            _actionsStarted++;
            if (logVerbose)
            {
                Debug.Log($"[QiyuBehaviorBridge] 执行 {action} channel={channel} " +
                          $"intensity={intensity:F2} target={target}");
            }
            Dispatch(action, channel, intensity, target);
        }

        // ------------------------------------------------------------------ 映射
        private void Dispatch(string action, string channel, float intensity,
                              string target)
        {
            switch (channel)
            {
                case "facial":
                    if (expressionDriver != null)
                    {
                        expressionDriver.ApplyEmotion(action, intensity);
                    }
                    else
                    {
                        LogUnsupportedOnce(action, "场景里没有 BlendShapeAvatarDriver");
                    }
                    break;
                case "locomotion":
                    DispatchLocomotion(action, intensity, target);
                    break;
                case "gaze":
                case "head":
                case "gesture":
                case "upper_body":
                case "lower_body":
                    // 交给本地行为运行时：它决定视线/动画/程序化动作怎么落到骨骼
                    DispatchAsIntent(action, channel, intensity);
                    break;
                case "interaction":
                    LogUnsupportedOnce(action, "interaction 需要 IK/手部判定，尚未接入");
                    break;
                case "audio":
                    // 说话由 TTS 链路负责，这里不重复驱动
                    break;
                default:
                    LogUnsupportedOnce(action, $"未知 channel={channel}");
                    break;
            }
        }

        private void DispatchLocomotion(string action, float intensity, string target)
        {
            if (locomotion == null)
            {
                LogUnsupportedOnce(action, "缺少 CharacterLocomotionController");
                return;
            }
            switch (action)
            {
                case "approach_user":
                    locomotion.MoveNearUser(0.9f,
                        Mathf.Clamp(intensity, 0.4f, 1.2f), "behavior:approach_user");
                    break;
                case "move_away":
                    locomotion.KeepDistanceFromUser(1.6f,
                        Mathf.Clamp(intensity, 0.4f, 1.2f));
                    break;
                case "stop":
                    locomotion.Stop("behavior:stop");
                    break;
                case "turn":
                case "walk":
                case "run":
                    DispatchAsIntent(action, "locomotion", intensity);
                    break;
                case "sit_down":
                case "stand_up":
                    LogUnsupportedOnce(action, "缺少坐/站动作资产与座位判定");
                    break;
                default:
                    LogUnsupportedOnce(action, "未接入的移动动作");
                    break;
            }
        }

        private void DispatchAsIntent(string action, string channel, float intensity)
        {
            if (behaviorRuntime == null)
            {
                LogUnsupportedOnce(action, "缺少 CharacterBehaviorRuntime");
                return;
            }
            var goal = GoalFor(action);
            if (string.IsNullOrEmpty(goal))
            {
                LogUnsupportedOnce(action, "本地行为运行时没有对应 goal");
                return;
            }
            behaviorRuntime.ApplyExternalIntent(new AvatarIntentData
            {
                goal = goal,
                target = "",
                attention = channel == "gaze" ? "user" : "",
                emotion = EmotionFor(action),
                urgency = Mathf.Clamp01(intensity),
                priority = 2,
            });
        }

        /// <summary>
        /// 动作 → 本地行为运行时支持的 goal。
        /// 只返回 BehaviorCatalog.FromGoal 真正认识的字符串；
        /// 没有对应 goal 的动作返回空串，由调用方明确记为"暂未接入"。
        /// </summary>
        private static string GoalFor(string action)
        {
            switch (action)
            {
                case "look_at_user":
                case "look_up":
                    return "observe_user";
                case "nod":
                    return "nod";
                case "shake_head":
                    return "shake_head";
                case "wave":
                    return "wave";
                case "point":
                    return "point_at_object";
                case "laugh":
                    return "laugh";
                case "surprised":
                    return "surprised";
                case "sad":
                case "comfort_touch":
                    return "comfort_user";
                case "think":
                case "head_tilt":
                case "confused":
                    return "think";
                case "walk":
                case "approach_user":
                    return "approach_user";
                case "turn":
                    return "reposition";
                case "sit_down":
                    return "sit";
                case "stand_up":
                    return "stand";
                case "idle":
                case "relaxed_idle":
                    return "listen_user";
                default:
                    return "";
            }
        }
        private static string EmotionFor(string action)
        {
            switch (action)
            {
                case "smile":
                case "laugh":
                    return "happy";
                case "sad":
                    return "sad";
                case "angry":
                    return "angry";
                case "surprised":
                    return "surprised";
                case "shy":
                case "embarrassed":
                case "blush":
                    return "shy";
                default:
                    return "neutral";
            }
        }

        private void LogUnsupportedOnce(string action, string reason)
        {
            _actionsUnsupported++;
            if (_unsupportedLogged.Add(action + "|" + reason))
            {
                Debug.LogWarning(
                    $"[QiyuBehaviorBridge] {action} 暂未接入本地执行：{reason}");
            }
        }
    }
}

