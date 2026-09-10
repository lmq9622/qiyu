using System;
using Qiyu.Quest.Perception;
using UnityEngine;

namespace Qiyu.Quest.Behavior
{
    /// <summary>
    /// Quest 本地 Human Motion Capture。
    ///
    /// 真实使用 Meta XR SDK 205：
    /// - OVRHand：手部是否追踪、pinch、pointer pose、置信度；
    /// - OVRBody.BodyState：Body Tracking 关节位置/旋转/置信度（设备支持时）；
    /// - OVREyeGaze：眼动方向（设备支持且授权时，否则回退头部朝向）。
    ///
    /// 原始骨骼不会持续上传云端；本组件只产出本地 HumanMotionState。
    /// </summary>
    [DefaultExecutionOrder(-120)]
    public class HumanMotionCapture : MonoBehaviour
    {
        [Header("Meta XR 引用")]
        [SerializeField] private Transform head;
        [SerializeField] private OVRHand leftHand;
        [SerializeField] private OVRHand rightHand;
        [SerializeField] private OVRBody body;
        [SerializeField] private OVREyeGaze leftEye;
        [SerializeField] private OVREyeGaze rightEye;

        [Header("采集")]
        [SerializeField] private bool autoFindMetaRig = true;
        [SerializeField] private bool enableEyeTracking = true;
        [SerializeField] private bool enableBodyTracking = true;
        [SerializeField] private float bodyJointConfidenceThreshold = 0.35f;

        public HumanMotionState CurrentState { get; private set; } = new HumanMotionState();
        public bool EyeTrackingActive => leftEye != null && rightEye != null &&
                                         leftEye.isActiveAndEnabled && rightEye.isActiveAndEnabled;
        public bool BodyTrackingActive => body != null && body.isActiveAndEnabled &&
                                          body.BodyState.HasValue;

        public event Action<HumanMotionState> OnMotionUpdated;

        public void SetDominantGesture(HumanGesture gesture)
        {
            if (CurrentState != null)
            {
                CurrentState.dominantGesture = gesture;
            }
        }

        private CharacterWorldModel _worldModel;
        private Vector3 _lastHeadPosition;
        private float _lastHeadSampleAt = -1f;
        private Vector3 _headVelocity;
        private int _sequence;
        private GameObject _bodyRig;
        private GameObject _leftEyeRig;
        private GameObject _rightEyeRig;

        private void Awake()
        {
            if (autoFindMetaRig)
            {
                ResolveMetaRig();
            }
        }

        private void Start()
        {
            if (autoFindMetaRig)
            {
                ResolveMetaRig();
            }
            EnsureOptionalTracking();
            _worldModel = FindAnyObjectByType<CharacterWorldModel>();
            if (_lastHeadSampleAt < 0f && head != null)
            {
                _lastHeadPosition = head.position;
                _lastHeadSampleAt = Time.realtimeSinceStartup;
            }
            Debug.Log($"[QiyuMotionCapture] head={(head != null)} " +
                      $"leftHand={(leftHand != null)} rightHand={(rightHand != null)} " +
                      $"eyeSupported={OVRPlugin.eyeTrackingSupported} " +
                      $"bodySupported={OVRPlugin.bodyTrackingSupported}");
        }

        private void Update()
        {
            if (head == null)
            {
                return;
            }
            var state = new HumanMotionState
            {
                timestampMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                sequence = ++_sequence,
                headPose = new Pose(head.position, head.rotation),
                facingDirection = head.forward,
                eyeTrackingSupported = OVRPlugin.eyeTrackingSupported,
                bodyTrackingSupported = OVRPlugin.bodyTrackingSupported,
                source = "meta_xr",
            };
            UpdateHeadVelocity(state);
            state.leftHand = ReadHand(leftHand);
            state.rightHand = ReadHand(rightHand);
            state.body = ReadBody();
            UpdateGaze(state);
            state.dominantGesture = HumanGesture.None;
            state.confidence = AverageConfidence(state);
            CurrentState = state;
            _worldModel?.SetHumanMotion(state);
            OnMotionUpdated?.Invoke(state);
        }

        private void ResolveMetaRig()
        {
            if (head == null)
            {
                var centerEye = GameObject.Find("CenterEyeAnchor");
                head = centerEye != null ? centerEye.transform : null;
            }
            if (leftHand == null)
            {
                leftHand = FindHand("LeftHand");
            }
            if (rightHand == null)
            {
                rightHand = FindHand("RightHand");
            }
            if (body == null)
            {
                body = FindAnyObjectByType<OVRBody>();
            }
        }

        private static OVRHand FindHand(string name)
        {
            var all = FindObjectsByType<OVRHand>(FindObjectsInactive.Include,
                FindObjectsSortMode.None);
            foreach (var hand in all)
            {
                if (hand == null)
                {
                    continue;
                }
                if (hand.name == name || hand.name.StartsWith(name, StringComparison.Ordinal))
                {
                    return hand;
                }
            }
            return null;
        }

        private void EnsureOptionalTracking()
        {
            if (enableEyeTracking && OVRPlugin.eyeTrackingSupported &&
                head != null && (leftEye == null || rightEye == null))
            {
                _leftEyeRig = CreateEyeRig("QiyuLeftEyeGaze", OVREyeGaze.EyeId.Left);
                _rightEyeRig = CreateEyeRig("QiyuRightEyeGaze", OVREyeGaze.EyeId.Right);
                leftEye = _leftEyeRig.GetComponent<OVREyeGaze>();
                rightEye = _rightEyeRig.GetComponent<OVREyeGaze>();
            }
            if (!enableBodyTracking || !OVRPlugin.bodyTrackingSupported || body != null)
            {
                return;
            }
            _bodyRig = new GameObject("QiyuHumanBodyTracking");
            _bodyRig.transform.SetParent(transform, false);
            body = _bodyRig.AddComponent<OVRBody>();
            var jointSet = OVRPlugin.BodyJointSet.FullBody;
            if (!OVRBody.SetRequestedJointSet(jointSet))
            {
                jointSet = OVRPlugin.BodyJointSet.UpperBody;
                OVRBody.SetRequestedJointSet(jointSet);
            }
            body.ProvidedSkeletonType = jointSet;
            Debug.Log($"[QiyuMotionCapture] 启用 Body Tracking jointSet={jointSet}");
        }

        private GameObject CreateEyeRig(string name, OVREyeGaze.EyeId eye)
        {
            var go = new GameObject(name);
            go.transform.SetParent(head, false);
            var gaze = go.AddComponent<OVREyeGaze>();
            gaze.Eye = eye;
            gaze.TrackingMode = OVREyeGaze.EyeTrackingMode.HeadSpace;
            gaze.ReferenceFrame = head;
            gaze.ApplyPosition = false;
            gaze.ApplyRotation = true;
            gaze.ConfidenceThreshold = 0.25f;
            return go;
        }

        private void UpdateHeadVelocity(HumanMotionState state)
        {
            var now = Time.realtimeSinceStartup;
            if (_lastHeadSampleAt > 0f)
            {
                var dt = Mathf.Max(0.001f, now - _lastHeadSampleAt);
                var measured = (head.position - _lastHeadPosition) / dt;
                _headVelocity = Vector3.Lerp(_headVelocity, measured, 0.4f);
            }
            _lastHeadPosition = head.position;
            _lastHeadSampleAt = now;
            state.velocity = _headVelocity;
        }

        private static HumanHandState ReadHand(OVRHand hand)
        {
            var state = new HumanHandState();
            if (hand == null)
            {
                return state;
            }
            state.tracked = hand.IsDataValid && hand.IsTracked;
            state.confidence = hand.HandConfidence == OVRHand.TrackingConfidence.High
                ? 0.95f : (state.tracked ? 0.45f : 0f);
            state.wristPosition = hand.transform.position;
            state.wristRotation = hand.transform.rotation;
            if (hand.IsPointerPoseValid)
            {
                state.pointerPosition = hand.PointerPose.position;
                state.pointerRotation = hand.PointerPose.rotation;
            }
            else
            {
                state.pointerPosition = state.wristPosition;
                state.pointerRotation = state.wristRotation;
            }
            state.indexPinching = hand.GetFingerIsPinching(OVRHand.HandFinger.Index);
            state.pinchStrength = hand.GetFingerPinchStrength(OVRHand.HandFinger.Index);
            return state;
        }

        private HumanBodyState ReadBody()
        {
            var state = new HumanBodyState();
            if (body == null || !body.BodyState.HasValue)
            {
                return state;
            }
            var bodyState = body.BodyState.Value;
            var joints = bodyState.JointLocations;
            if (joints == null || joints.Length == 0)
            {
                return state;
            }
            state.tracked = bodyState.Confidence >= bodyJointConfidenceThreshold;
            state.fullBodySupported = body.ProvidedSkeletonType == OVRPlugin.BodyJointSet.FullBody;
            state.confidence = bodyState.Confidence;
            state.validJointCount = 0;
            for (var i = 0; i < joints.Length; i++)
            {
                if (joints[i].PositionValid && joints[i].OrientationValid)
                {
                    state.validJointCount++;
                }
            }
            ReadJoint(joints, OVRPlugin.BoneId.Body_Hips,
                out state.hipsPosition, out state.hipsRotation);
            ReadJoint(joints, OVRPlugin.BoneId.Body_Chest,
                out state.chestPosition, out state.chestRotation);
            ReadJoint(joints, OVRPlugin.BoneId.Body_Head,
                out state.headPosition, out state.headRotation);
            ReadJoint(joints, OVRPlugin.BoneId.Body_LeftHandWrist,
                out state.leftHandPosition, out _);
            ReadJoint(joints, OVRPlugin.BoneId.Body_RightHandWrist,
                out state.rightHandPosition, out _);
            return state;
        }

        private static void ReadJoint(OVRPlugin.BodyJointLocation[] joints,
                                      OVRPlugin.BoneId bone,
                                      out Vector3 position,
                                      out Quaternion rotation)
        {
            position = Vector3.zero;
            rotation = Quaternion.identity;
            var index = (int)bone;
            if (joints == null || index < 0 || index >= joints.Length)
            {
                return;
            }
            var joint = joints[index];
            if (joint.PositionValid)
            {
                position = joint.Pose.Position.FromFlippedZVector3f();
            }
            if (joint.OrientationValid)
            {
                rotation = joint.Pose.Orientation.FromFlippedZQuatf();
            }
        }

        private void UpdateGaze(HumanMotionState state)
        {
            var available = leftEye != null && rightEye != null &&
                            leftEye.isActiveAndEnabled && rightEye.isActiveAndEnabled &&
                            leftEye.Confidence > 0.15f && rightEye.Confidence > 0.15f;
            if (available)
            {
                var direction = (leftEye.transform.forward + rightEye.transform.forward).normalized;
                state.gazeDirection = direction;
                state.confidence = Mathf.Max(state.confidence,
                    Mathf.Min(leftEye.Confidence, rightEye.Confidence));
            }
            else
            {
                state.gazeDirection = head.forward;
            }
            // gaze target 由 MotionUnderstanding/WorldModel 射线决定，避免两处各算一套。
        }

        private static float AverageConfidence(HumanMotionState state)
        {
            var values = new[]
            {
                1f,
                state.leftHand.confidence,
                state.rightHand.confidence,
                state.body.confidence,
            };
            var sum = 0f;
            foreach (var value in values)
            {
                sum += value;
            }
            return sum / values.Length;
        }
    }
}
