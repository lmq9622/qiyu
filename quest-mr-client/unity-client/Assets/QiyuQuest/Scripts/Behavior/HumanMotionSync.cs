using System;
using Newtonsoft.Json.Linq;
using Qiyu.Quest.Networking;
using UnityEngine;

namespace Qiyu.Quest.Behavior
{
    /// <summary>
    /// 压缩 Human Motion 同步：
    /// - 5–15Hz：只发 head/hands/body/gaze/gesture 的低维状态；
    /// - 事件发生：立即发 client.interaction_event；
    /// - 原始骨骼持续上传被禁止。
    /// </summary>
    [DefaultExecutionOrder(-90)]
    public class HumanMotionSync : MonoBehaviour
    {
        [SerializeField] private HumanMotionCapture capture;
        [SerializeField] private MotionUnderstanding understanding;
        [SerializeField] private QiyuQuestWebSocketClient webSocketClient;
        [SerializeField] private float syncHz = 10f;

        private float _nextSyncAt;

        private void Awake()
        {
            if (capture == null) capture = GetComponent<HumanMotionCapture>();
            if (understanding == null) understanding = GetComponent<MotionUnderstanding>();
            if (webSocketClient == null)
                webSocketClient = FindAnyObjectByType<QiyuQuestWebSocketClient>();
        }

        private void OnEnable()
        {
            if (understanding != null)
            {
                understanding.OnInteraction += HandleInteraction;
            }
        }

        private void OnDisable()
        {
            if (understanding != null)
            {
                understanding.OnInteraction -= HandleInteraction;
            }
        }

        private void Update()
        {
            if (capture == null || webSocketClient == null ||
                !webSocketClient.HandshakeDone)
            {
                return;
            }
            if (Time.realtimeSinceStartup < _nextSyncAt)
            {
                return;
            }
            _nextSyncAt = Time.realtimeSinceStartup + 1f / Mathf.Max(1f, syncHz);
            var state = capture.CurrentState;
            var payload = new JObject
            {
                ["schema_version"] = "1.1",
                ["ts"] = state.timestampMs,
                ["sequence"] = state.sequence,
                ["head_pose"] = PoseToJson(state.headPose),
                ["left_hand_position"] = VectorToJson(state.leftHand.wristPosition),
                ["right_hand_position"] = VectorToJson(state.rightHand.wristPosition),
                ["left_hand_tracked"] = state.leftHand.tracked,
                ["right_hand_tracked"] = state.rightHand.tracked,
                ["body_tracked"] = state.body.tracked,
                ["body_confidence"] = state.body.confidence,
                ["gaze_direction"] = VectorToJson(state.gazeDirection),
                ["gaze_target_id"] = state.gazeTargetId,
                ["gesture"] = state.dominantGesture.ToString().ToLowerInvariant(),
                ["facing_direction"] = VectorToJson(state.facingDirection),
                ["velocity"] = VectorToJson(state.velocity),
                ["confidence"] = state.confidence,
                ["source"] = state.source,
            };
            _ = webSocketClient.SendHumanMotionStateAsync(payload);
        }

        private void HandleInteraction(HumanInteractionEvent evt)
        {
            if (evt == null || webSocketClient == null || !webSocketClient.HandshakeDone)
            {
                return;
            }
            _ = webSocketClient.SendGestureEventAsync(
                evt.gesture.ToString().ToLowerInvariant(),
                evt.intent,
                evt.target,
                evt.confidence,
                evt.direction,
                evt.distance,
                evt.emotionHint);
        }

        private static JObject PoseToJson(Pose pose)
        {
            return new JObject
            {
                ["position"] = VectorToJson(pose.position),
                ["rotation"] = new JObject
                {
                    ["x"] = pose.rotation.x,
                    ["y"] = pose.rotation.y,
                    ["z"] = pose.rotation.z,
                    ["w"] = pose.rotation.w
                }
            };
        }

        private static JObject VectorToJson(Vector3 v)
        {
            return new JObject { ["x"] = v.x, ["y"] = v.y, ["z"] = v.z };
        }
    }
}
