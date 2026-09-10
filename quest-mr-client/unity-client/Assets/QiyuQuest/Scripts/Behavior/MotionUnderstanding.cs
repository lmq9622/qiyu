using System;
using System.Collections.Generic;
using UnityEngine;

namespace Qiyu.Quest.Behavior
{
    /// <summary>
    /// 连续 HumanMotionState → 高层 HumanInteractionEvent。
    ///
    /// 原始骨骼只在本层内存中使用，不送 LLM；输出手势/intent/target/direction。
    /// 所有识别器都是真实几何/时序启发式，置信度不足时不发事件。
    /// </summary>
    [DefaultExecutionOrder(-110)]
    public class MotionUnderstanding : MonoBehaviour
    {
        [SerializeField] private HumanMotionCapture capture;
        [SerializeField] private CharacterWorldModel worldModel;
        [SerializeField] private Transform avatarRoot;

        [Header("阈值")]
        [SerializeField] private float minConfidence = 0.35f;
        [SerializeField] private float waveMinAmplitude = 0.10f;
        [SerializeField] private float waveMinSignChanges = 2;
        [SerializeField] private float pointMaxAngleDegrees = 12f;
        [SerializeField] private float pointStableSeconds = 0.35f;
        [SerializeField] private float stopPalmDot = 0.45f;
        [SerializeField] private float stopStableSeconds = 0.45f;
        [SerializeField] private float highFiveDistance = 0.62f;
        [SerializeField] private float pushSpeed = 0.75f;

        public HumanInteractionEvent LastEvent { get; private set; }
        public event Action<HumanInteractionEvent> OnInteraction;

        private readonly List<MotionSample> _leftHistory = new List<MotionSample>();
        private readonly List<MotionSample> _rightHistory = new List<MotionSample>();
        private readonly List<MotionSample> _headHistory = new List<MotionSample>();
        private readonly Dictionary<HumanGesture, float> _cooldowns =
            new Dictionary<HumanGesture, float>();
        private HumanGesture _lastCandidate = HumanGesture.None;
        private float _candidateSince;
        private Vector3 _stablePointDirection;
        private string _stopCandidateHand = "";
        private float _stopCandidateSince;

        private struct MotionSample
        {
            public float time;
            public Vector3 position;
            public Quaternion rotation;
            public float confidence;
        }

        private void Awake()
        {
            if (capture == null)
            {
                capture = GetComponent<HumanMotionCapture>();
            }
            if (worldModel == null)
            {
                worldModel = GetComponent<CharacterWorldModel>();
            }
            if (avatarRoot == null)
            {
                var found = GameObject.Find("QiyuAvatar");
                avatarRoot = found != null ? found.transform : transform;
            }
        }

        private void Update()
        {
            if (capture == null)
            {
                capture = FindAnyObjectByType<HumanMotionCapture>();
            }
            if (capture == null || capture.CurrentState == null)
            {
                return;
            }
            var state = capture.CurrentState;
            var now = Time.realtimeSinceStartup;
            AddSample(_leftHistory, now, state.leftHand.wristPosition,
                state.leftHand.wristRotation, state.leftHand.confidence);
            AddSample(_rightHistory, now, state.rightHand.wristPosition,
                state.rightHand.wristRotation, state.rightHand.confidence);
            AddSample(_headHistory, now, state.headPose.position,
                state.headPose.rotation, 1f);

            HumanInteractionEvent evt = null;
            evt = DetectWave(state, _rightHistory, "right") ??
                  DetectWave(state, _leftHistory, "left") ??
                  DetectPoint(state, "right") ??
                  DetectPoint(state, "left") ??
                  DetectStop(state, _rightHistory, "right") ??
                  DetectStop(state, _leftHistory, "left") ??
                  DetectHighFive(state) ??
                  DetectPush(state) ??
                  DetectComeHere(state) ??
                  DetectSitStand(state) ??
                  DetectHeadGesture(state);
            if (evt != null && CanEmit(evt.gesture, now))
            {
                LastEvent = evt;
                capture.SetDominantGesture(evt.gesture);
                OnInteraction?.Invoke(evt);
            }
            else if (evt == null)
            {
                // 短暂保持手势状态，避免单帧抖动；超时后回到 None。
                if (now - _candidateSince > 0.6f)
                {
                    capture.SetDominantGesture(HumanGesture.None);
                }
            }
        }

        private static void AddSample(List<MotionSample> history, float time,
                                      Vector3 position, Quaternion rotation,
                                      float confidence)
        {
            history.Add(new MotionSample
            {
                time = time,
                position = position,
                rotation = rotation,
                confidence = confidence,
            });
            while (history.Count > 0 && time - history[0].time > 1.6f)
            {
                history.RemoveAt(0);
            }
        }

        private HumanInteractionEvent DetectWave(HumanMotionState state,
                                                  List<MotionSample> history,
                                                  string hand)
        {
            if (history.Count < 8)
            {
                return null;
            }
            var latest = history[history.Count - 1];
            if (latest.confidence < minConfidence)
            {
                return null;
            }
            var axis = Vector3.up;
            var min = float.MaxValue;
            var max = float.MinValue;
            var signs = 0;
            var lastSign = 0;
            for (var i = 1; i < history.Count; i++)
            {
                var p = Vector3.Dot(history[i].position - history[0].position, axis);
                min = Mathf.Min(min, p);
                max = Mathf.Max(max, p);
                var velocity = Vector3.Dot(history[i].position - history[i - 1].position, axis);
                var sign = velocity > 0.005f ? 1 : (velocity < -0.005f ? -1 : 0);
                if (sign != 0 && lastSign != 0 && sign != lastSign)
                {
                    signs++;
                }
                if (sign != 0)
                {
                    lastSign = sign;
                }
            }
            if (max - min < waveMinAmplitude || signs < waveMinSignChanges)
            {
                return null;
            }
            return BuildEvent(HumanGesture.Wave, "wave_response", "user",
                "手部左右摆动", latest.confidence);
        }

        private HumanInteractionEvent DetectPoint(HumanMotionState state, string hand)
        {
            var handState = hand == "left" ? state.leftHand : state.rightHand;
            if (!handState.tracked || handState.confidence < minConfidence ||
                !handState.indexPinching && handState.pinchStrength > 0.9f)
            {
                return null;
            }
            var direction = handState.pointerRotation * Vector3.forward;
            if (_stablePointDirection.sqrMagnitude < 0.1f)
            {
                _stablePointDirection = direction;
                _candidateSince = Time.realtimeSinceStartup;
                return null;
            }
            var angle = Vector3.Angle(_stablePointDirection, direction);
            if (angle > pointMaxAngleDegrees)
            {
                _stablePointDirection = direction;
                _candidateSince = Time.realtimeSinceStartup;
                return null;
            }
            if (Time.realtimeSinceStartup - _candidateSince < pointStableSeconds)
            {
                return null;
            }
            var target = ResolveRayTarget(handState.pointerPosition, direction);
            return BuildEvent(HumanGesture.Point,
                string.IsNullOrEmpty(target) ? "point_direction" : "attend_target",
                string.IsNullOrEmpty(target) ? "" : target,
                "指向目标", handState.confidence);
        }

        private HumanInteractionEvent DetectStop(HumanMotionState state,
                                                 List<MotionSample> history,
                                                 string hand)
        {
            if (history.Count < 6)
            {
                return null;
            }
            var handState = hand == "left" ? state.leftHand : state.rightHand;
            if (!handState.tracked || handState.confidence < minConfidence ||
                avatarRoot == null)
            {
                return null;
            }
            var toAvatar = (avatarRoot.position - handState.wristPosition).normalized;
            var palmForward = handState.wristRotation * Vector3.forward;
            var palmDot = Vector3.Dot(palmForward, toAvatar);
            if (palmDot < stopPalmDot)
            {
                _stopCandidateHand = "";
                return null;
            }
            if (HandMovement(history) > 0.12f)
            {
                _stopCandidateHand = "";
                return null;
            }
            if (_stopCandidateHand != hand)
            {
                _stopCandidateHand = hand;
                _stopCandidateSince = Time.realtimeSinceStartup;
            }
            if (Time.realtimeSinceStartup - _stopCandidateSince < stopStableSeconds)
            {
                return null;
            }
            return BuildEvent(HumanGesture.Stop, "stop", "avatar",
                "拒绝/停止", handState.confidence, priority: 5);
        }

        private HumanInteractionEvent DetectHighFive(HumanMotionState state)
        {
            if (avatarRoot == null || !state.rightHand.tracked)
            {
                return null;
            }
            var hand = state.rightHand;
            var distance = Vector3.Distance(hand.wristPosition, avatarRoot.position);
            var handHeight = hand.wristPosition.y;
            var avatarHeight = avatarRoot.position.y;
            if (distance > highFiveDistance || handHeight < avatarHeight + 0.9f ||
                hand.indexPinching)
            {
                return null;
            }
            var towardAvatar = Vector3.Dot(state.velocity, -Vector3.forward) > 0f;
            if (!towardAvatar && distance > highFiveDistance * 0.75f)
            {
                return null;
            }
            return BuildEvent(HumanGesture.HighFive, "high_five", "avatar",
                "击掌", hand.confidence, priority: 4);
        }

        private HumanInteractionEvent DetectPush(HumanMotionState state)
        {
            var hand = state.rightHand.tracked ? state.rightHand : state.leftHand;
            if (!hand.tracked || avatarRoot == null)
            {
                return null;
            }
            var toAvatar = (avatarRoot.position - hand.wristPosition);
            var speed = state.velocity.magnitude;
            if (speed < pushSpeed || toAvatar.magnitude > 1.2f)
            {
                return null;
            }
            var palm = hand.wristRotation * Vector3.forward;
            if (Vector3.Dot(palm, toAvatar.normalized) < 0.4f)
            {
                return null;
            }
            return BuildEvent(HumanGesture.Push, "avoid", "avatar",
                "推开/危险动作", Mathf.Clamp01(hand.confidence), priority: 5);
        }

        private HumanInteractionEvent DetectComeHere(HumanMotionState state)
        {
            if (_rightHistory.Count < 10 && _leftHistory.Count < 10)
            {
                return null;
            }
            var hand = state.rightHand.tracked ? state.rightHand : state.leftHand;
            if (!hand.tracked || hand.indexPinching)
            {
                return null;
            }
            var history = state.rightHand.tracked ? _rightHistory : _leftHistory;
            var minDistance = float.MaxValue;
            var maxDistance = float.MinValue;
            foreach (var sample in history)
            {
                var distance = Vector3.Distance(sample.position, state.headPose.position);
                minDistance = Mathf.Min(minDistance, distance);
                maxDistance = Mathf.Max(maxDistance, distance);
            }
            if (maxDistance - minDistance < 0.12f ||
                state.headPose.position.y - hand.wristPosition.y < 0.15f)
            {
                return null;
            }
            return BuildEvent(HumanGesture.ComeHere, "come_here", "user",
                "招手", hand.confidence);
        }

        private HumanInteractionEvent DetectSitStand(HumanMotionState state)
        {
            if (_headHistory.Count < 10)
            {
                return null;
            }
            var first = _headHistory[0].position.y;
            var last = _headHistory[_headHistory.Count - 1].position.y;
            var delta = last - first;
            if (Mathf.Abs(delta) < 0.22f)
            {
                return null;
            }
            var gesture = delta < 0f ? HumanGesture.Sit : HumanGesture.Stand;
            return BuildEvent(gesture, gesture == HumanGesture.Sit ? "sit_down" : "stand_up",
                "user", gesture == HumanGesture.Sit ? "用户坐下" : "用户站起",
                state.confidence);
        }

        private HumanInteractionEvent DetectHeadGesture(HumanMotionState state)
        {
            if (_headHistory.Count < 10)
            {
                return null;
            }
            var yawChanges = 0;
            var pitchChanges = 0;
            var lastYawSign = 0;
            var lastPitchSign = 0;
            for (var i = 1; i < _headHistory.Count; i++)
            {
                var delta = _headHistory[i].rotation * Quaternion.Inverse(_headHistory[i - 1].rotation);
                var euler = delta.eulerAngles;
                var yaw = Mathf.DeltaAngle(0f, euler.y);
                var pitch = Mathf.DeltaAngle(0f, euler.x);
                var yawSign = yaw > 1.5f ? 1 : (yaw < -1.5f ? -1 : 0);
                var pitchSign = pitch > 1.5f ? 1 : (pitch < -1.5f ? -1 : 0);
                if (yawSign != 0 && lastYawSign != 0 && yawSign != lastYawSign) yawChanges++;
                if (pitchSign != 0 && lastPitchSign != 0 && pitchSign != lastPitchSign) pitchChanges++;
                if (yawSign != 0) lastYawSign = yawSign;
                if (pitchSign != 0) lastPitchSign = pitchSign;
            }
            if (pitchChanges >= 2 && pitchChanges > yawChanges)
            {
                return BuildEvent(HumanGesture.Nod, "acknowledge", "user",
                    "点头", state.confidence);
            }
            if (yawChanges >= 2)
            {
                return BuildEvent(HumanGesture.ShakeHead, "deny", "user",
                    "摇头", state.confidence);
            }
            return null;
        }

        private static float HandMovement(List<MotionSample> history)
        {
            var sum = 0f;
            for (var i = 1; i < history.Count; i++)
            {
                sum += Vector3.Distance(history[i].position, history[i - 1].position);
            }
            return sum;
        }

        private string ResolveRayTarget(Vector3 origin, Vector3 direction)
        {
            if (worldModel != null)
            {
                var snapshot = worldModel.Snapshot;
                var bestId = "";
                var bestScore = float.MaxValue;
                foreach (var entity in snapshot.entities)
                {
                    if (entity == null || !entity.visible)
                    {
                        continue;
                    }
                    var toEntity = entity.position - origin;
                    var angle = Vector3.Angle(direction, toEntity.normalized);
                    if (angle > pointMaxAngleDegrees * 1.8f)
                    {
                        continue;
                    }
                    var score = angle + toEntity.magnitude * 0.04f;
                    if (score < bestScore)
                    {
                        bestScore = score;
                        bestId = entity.id;
                    }
                }
                if (!string.IsNullOrEmpty(bestId))
                {
                    return bestId;
                }
            }
            var hits = Physics.RaycastAll(origin, direction, 8f, ~0,
                QueryTriggerInteraction.Ignore);
            if (hits.Length == 0)
            {
                return "";
            }
            Array.Sort(hits, (a, b) => a.distance.CompareTo(b.distance));
            return hits[0].collider != null
                ? hits[0].collider.gameObject.name
                : "";
        }

        private HumanInteractionEvent BuildEvent(HumanGesture gesture, string intent,
                                                  string target, string emotion,
                                                  float confidence,
                                                  int priority = 2)
        {
            var state = capture.CurrentState;
            var hand = state.rightHand.tracked ? state.rightHand : state.leftHand;
            var direction = hand.wristPosition - state.headPose.position;
            _candidateSince = Time.realtimeSinceStartup;
            _lastCandidate = gesture;
            var distance = avatarRoot != null
                ? Vector3.Distance(state.headPose.position, avatarRoot.position)
                : 0f;
            return new HumanInteractionEvent
            {
                timestampMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                gesture = gesture,
                intent = intent,
                target = target,
                direction = direction,
                distance = distance,
                confidence = Mathf.Clamp01(confidence),
                emotionHint = emotion,
                source = "local_motion_understanding",
                priority = priority,
            };
        }

        private bool CanEmit(HumanGesture gesture, float now)
        {
            var cooldown = gesture == HumanGesture.Point ? 0.45f : 1.2f;
            if (_cooldowns.TryGetValue(gesture, out var next) && now < next)
            {
                return false;
            }
            _cooldowns[gesture] = now + cooldown;
            return true;
        }
    }
}
