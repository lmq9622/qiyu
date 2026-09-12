using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using UnityEngine;

namespace Qiyu.Quest.Behavior
{
    /// <summary>单个关节/节点的动作采样。</summary>
    [Serializable]
    public struct MotionJointSample
    {
        public string id;            // head / left_hand / right_hand / hips / chest / gaze / ...
        public bool tracked;
        public float confidence;
        public Vector3 position;     // 世界坐标（Unity 右手系，Y 上）
        public Quaternion rotation;

        public MotionJointSample(string id, bool tracked, float confidence,
                                 Vector3 position, Quaternion rotation)
        {
            this.id = id;
            this.tracked = tracked;
            this.confidence = confidence;
            this.position = position;
            this.rotation = rotation;
        }
    }

    /// <summary>
    /// 实时动作状态快照：这是对外输出接口的**唯一数据结构**。
    ///
    /// 约定：
    /// - 坐标是世界坐标（米），旋转是四元数；不传骨骼索引/内部实现；
    /// - 版本号在接口里，方便下游兼容升级；
    /// - JSON 由本类自己序列化，不依赖第三方库。
    /// </summary>
    [Serializable]
    public sealed class MotionStateSnapshot
    {
        public string version = "1.0";
        public long timestampMs;
        public int sequence;
        public string source = "meta_xr";
        public bool eyeTracking;
        public bool bodyTracking;
        public float confidence;
        public string dominantGesture = "none";
        public string activity = "idle";
        public List<MotionJointSample> joints = new List<MotionJointSample>();

        public MotionJointSample? Find(string id)
        {
            for (var i = 0; i < joints.Count; i++)
            {
                if (string.Equals(joints[i].id, id, StringComparison.Ordinal))
                {
                    return joints[i];
                }
            }
            return null;
        }

        public string ToJson()
        {
            var sb = new StringBuilder(512);
            sb.Append('{');
            sb.Append("\"version\":\"").Append(version).Append("\",");
            sb.Append("\"timestamp_ms\":").Append(timestampMs).Append(',');
            sb.Append("\"sequence\":").Append(sequence).Append(',');
            sb.Append("\"source\":\"").Append(source).Append("\",");
            sb.Append("\"eye_tracking\":").Append(eyeTracking ? "true" : "false").Append(',');
            sb.Append("\"body_tracking\":").Append(bodyTracking ? "true" : "false").Append(',');
            sb.Append("\"confidence\":").Append(confidence.ToString("F3",
                System.Globalization.CultureInfo.InvariantCulture)).Append(',');
            sb.Append("\"gesture\":\"").Append(dominantGesture).Append("\",");
            sb.Append("\"activity\":\"").Append(activity).Append("\",");
            sb.Append("\"joints\":[");
            for (var i = 0; i < joints.Count; i++)
            {
                var j = joints[i];
                if (i > 0)
                {
                    sb.Append(',');
                }
                sb.Append('{');
                sb.Append("\"id\":\"").Append(j.id).Append("\",");
                sb.Append("\"tracked\":").Append(j.tracked ? "true" : "false").Append(',');
                sb.Append("\"confidence\":").Append(j.confidence.ToString("F3",
                    System.Globalization.CultureInfo.InvariantCulture)).Append(',');
                sb.Append("\"position\":[")
                  .Append(F(j.position.x)).Append(',').Append(F(j.position.y))
                  .Append(',').Append(F(j.position.z)).Append("],");
                sb.Append("\"rotation\":[")
                  .Append(F(j.rotation.x)).Append(',').Append(F(j.rotation.y))
                  .Append(',').Append(F(j.rotation.z)).Append(',').Append(F(j.rotation.w))
                  .Append(']');
                sb.Append('}');
            }
            sb.Append("]}");
            return sb.ToString();
        }

        private static string F(float value)
        {
            return value.ToString("F4", System.Globalization.CultureInfo.InvariantCulture);
        }
    }

    /// <summary>动作状态数据源：任何能提供实时动作状态的组件都实现它。</summary>
    public interface IMotionStateSource
    {
        MotionStateSnapshot GetMotionState();
    }

    /// <summary>动作状态消费者：注册后按广播频率收到快照。</summary>
    public interface IMotionStateConsumer
    {
        void OnMotionState(MotionStateSnapshot snapshot);
    }

    /// <summary>
    /// 实时动作状态输出接口（对外唯一入口）。
    ///
    /// 四种消费方式，按需取用：
    /// 1) C# 事件：`OnSnapshot += handler`；
    /// 2) 接口注册：`AddConsumer(IMotionStateConsumer)`；
    /// 3) 本地 JSONL 文件：`recordToFile = true` → persistentDataPath/qiyu/motion_state.jsonl
    ///    （外部工具、Python 分析脚本可直接 tail）；
    /// 4) 网络：既有 `HumanMotionSync` 已按 10Hz 走 `client.human_motion_state`，
    ///    本组件不重复发送，避免同一份数据两条链路。
    ///
    /// 频率默认 15Hz，刻意不每帧广播。
    /// </summary>
    [DefaultExecutionOrder(-50)]
    public class MotionStateBroadcaster : MonoBehaviour, IMotionStateSource
    {
        [Header("数据源")]
        [SerializeField] private HumanMotionCapture motionCapture;

        [Header("输出")]
        [SerializeField] private float broadcastHz = 15f;
        [SerializeField] private bool recordToFile;
        [SerializeField] private string recordFileName = "motion_state.jsonl";
        [SerializeField] private int maxRecordLinesHint = 200000;

        private readonly List<IMotionStateConsumer> _consumers = new List<IMotionStateConsumer>();
        private MotionStateSnapshot _snapshot = new MotionStateSnapshot();
        private float _nextBroadcastAt;
        private int _sequence;
        private StreamWriter _writer;
        private long _linesWritten;

        /// <summary>每次广播时触发（先于 consumers）。</summary>
        public event Action<MotionStateSnapshot> OnSnapshot;

        public int BroadcastCount { get; private set; }
        public string RecordPath { get; private set; } = "";

        private void Awake()
        {
            if (motionCapture == null)
            {
                motionCapture = GetComponent<HumanMotionCapture>();
            }
            if (motionCapture == null)
            {
                motionCapture = FindAnyObjectByType<HumanMotionCapture>();
            }
            if (recordToFile)
            {
                StartRecording();
            }
        }

        private void OnDestroy()
        {
            StopRecording();
        }

        public void AddConsumer(IMotionStateConsumer consumer)
        {
            if (consumer != null && !_consumers.Contains(consumer))
            {
                _consumers.Add(consumer);
            }
        }

        public void RemoveConsumer(IMotionStateConsumer consumer)
        {
            _consumers.Remove(consumer);
        }

        public void StartRecording()
        {
            if (_writer != null)
            {
                return;
            }
            var dir = Path.Combine(Application.persistentDataPath, "qiyu");
            Directory.CreateDirectory(dir);
            RecordPath = Path.Combine(dir, recordFileName);
            _writer = new StreamWriter(RecordPath, append: true, Encoding.UTF8);
            _writer.AutoFlush = true;
            Debug.Log($"[MotionState] 开始记录动作状态 → {RecordPath}");
        }

        public void StopRecording()
        {
            if (_writer == null)
            {
                return;
            }
            _writer.Flush();
            _writer.Dispose();
            _writer = null;
            Debug.Log($"[MotionState] 停止记录（共 {_linesWritten} 行）");
        }

        private void Update()
        {
            if (motionCapture == null)
            {
                return;
            }
            if (Time.unscaledTime < _nextBroadcastAt)
            {
                return;
            }
            var interval = 1f / Mathf.Clamp(broadcastHz, 1f, 30f);
            _nextBroadcastAt = Time.unscaledTime + interval;
            var snapshot = BuildSnapshot();
            _snapshot = snapshot;
            BroadcastCount++;
            OnSnapshot?.Invoke(snapshot);
            for (var i = 0; i < _consumers.Count; i++)
            {
                var consumer = _consumers[i];
                if (consumer == null)
                {
                    continue;
                }
                try
                {
                    consumer.OnMotionState(snapshot);
                }
                catch (Exception e)
                {
                    Debug.LogWarning($"[MotionState] consumer 异常: {e.Message}");
                }
            }
            if (_writer != null)
            {
                _writer.WriteLine(snapshot.ToJson());
                _linesWritten++;
                if (maxRecordLinesHint > 0 && _linesWritten == maxRecordLinesHint)
                {
                    Debug.LogWarning(
                        $"[MotionState] 记录行数已达 {_linesWritten}，建议关闭录制或清理文件");
                }
            }
        }

        public MotionStateSnapshot GetMotionState()
        {
            return _snapshot;
        }

        /// <summary>把既有 HumanMotionState 转成对外接口结构。</summary>
        private MotionStateSnapshot BuildSnapshot()
        {
            var state = motionCapture.CurrentState;
            var snapshot = new MotionStateSnapshot
            {
                timestampMs = state.timestampMs,
                sequence = ++_sequence,
                source = string.IsNullOrEmpty(state.source) ? "meta_xr" : state.source,
                eyeTracking = state.eyeTrackingSupported,
                bodyTracking = state.bodyTrackingSupported,
                confidence = state.confidence,
                dominantGesture = state.dominantGesture.ToString().ToLowerInvariant(),
                activity = state.body != null && state.body.tracked ? "tracked" : "upper_body",
            };

            if (state.headPose != null)
            {
                snapshot.joints.Add(new MotionJointSample(
                    "head", true, state.confidence,
                    state.headPose.position, state.headPose.rotation));
            }
            snapshot.joints.Add(new MotionJointSample(
                "gaze", true, state.confidence,
                state.headPose != null ? state.headPose.position : Vector3.zero,
                Quaternion.LookRotation(
                    state.gazeDirection.sqrMagnitude > 1e-6f
                        ? state.gazeDirection.normalized : Vector3.forward)));

            AddHand(snapshot, "left_hand", state.leftHand);
            AddHand(snapshot, "right_hand", state.rightHand);

            if (state.body != null)
            {
                snapshot.joints.Add(new MotionJointSample(
                    "hips", state.body.tracked, state.body.confidence,
                    state.body.hipsPosition, state.body.hipsRotation));
                snapshot.joints.Add(new MotionJointSample(
                    "chest", state.body.tracked, state.body.confidence,
                    state.body.chestPosition, state.body.chestRotation));
                if (state.body.tracked)
                {
                    snapshot.joints.Add(new MotionJointSample(
                        "left_hand_body", true, state.body.confidence,
                        state.body.leftHandPosition, Quaternion.identity));
                    snapshot.joints.Add(new MotionJointSample(
                        "right_hand_body", true, state.body.confidence,
                        state.body.rightHandPosition, Quaternion.identity));
                }
            }
            return snapshot;
        }

        private static void AddHand(MotionStateSnapshot snapshot, string id,
                                    HumanHandState hand)
        {
            if (hand == null)
            {
                return;
            }
            snapshot.joints.Add(new MotionJointSample(
                id, hand.tracked, hand.confidence,
                hand.tracked ? hand.wristPosition : hand.pointerPosition,
                hand.wristRotation));
            snapshot.joints.Add(new MotionJointSample(
                id + "_pointer", hand.tracked, hand.confidence,
                hand.pointerPosition, hand.pointerRotation));
        }
    }
}
