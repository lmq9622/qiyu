using System;
using UnityEngine;

namespace Qiyu.Quest.Behavior
{
    public enum HumanGesture
    {
        None = 0,
        Wave,
        Point,
        ComeHere,
        Stop,
        Reach,
        Give,
        Sit,
        Stand,
        Turn,
        Look,
        Nod,
        ShakeHead,
        HighFive,
        Push
    }

    public enum InteractionActivity
    {
        Idle = 0,
        Approaching,
        Following,
        Watching,
        Responding,
        Playing,
        Cooperating,
        Waiting,
        Avoiding,
        Interrupted
    }

    [Serializable]
    public sealed class HumanHandState
    {
        public bool tracked;
        public float confidence;
        public Vector3 wristPosition;
        public Quaternion wristRotation = Quaternion.identity;
        public Vector3 pointerPosition;
        public Quaternion pointerRotation = Quaternion.identity;
        public float pinchStrength;
        public bool indexPinching;
        public HumanGesture gesture = HumanGesture.None;
    }

    [Serializable]
    public sealed class HumanBodyState
    {
        public bool tracked;
        public bool fullBodySupported;
        public float confidence;
        public Vector3 hipsPosition;
        public Quaternion hipsRotation = Quaternion.identity;
        public Vector3 chestPosition;
        public Quaternion chestRotation = Quaternion.identity;
        public Vector3 headPosition;
        public Quaternion headRotation = Quaternion.identity;
        public Vector3 leftHandPosition;
        public Vector3 rightHandPosition;
        public int validJointCount;
    }

    [Serializable]
    public sealed class HumanMotionState
    {
        public long timestampMs;
        public int sequence;
        public Pose headPose;
        public HumanHandState leftHand = new HumanHandState();
        public HumanHandState rightHand = new HumanHandState();
        public HumanBodyState body = new HumanBodyState();
        public Vector3 gazeDirection = Vector3.forward;
        public string gazeTargetId = "";
        public Vector3 facingDirection = Vector3.forward;
        public HumanGesture dominantGesture = HumanGesture.None;
        public Vector3 velocity;
        public float confidence;
        public string source = "meta_xr";
        public bool eyeTrackingSupported;
        public bool bodyTrackingSupported;
    }

    [Serializable]
    public sealed class HumanInteractionEvent
    {
        public string eventId = Guid.NewGuid().ToString("N");
        public long timestampMs;
        public HumanGesture gesture = HumanGesture.None;
        public string intent = "";
        public string target = "";
        public Vector3 direction;
        public float distance;
        public float confidence;
        public string emotionHint = "";
        public string source = "local_motion_understanding";
        public int priority;
    }

    [Serializable]
    public sealed class UserStateData
    {
        public Vector3 position;
        public Quaternion rotation = Quaternion.identity;
        public Pose headPose;
        public HumanHandState leftHand = new HumanHandState();
        public HumanHandState rightHand = new HumanHandState();
        public HumanBodyState body = new HumanBodyState();
        public Vector3 gazeDirection = Vector3.forward;
        public string gazeTargetId = "";
        public HumanGesture gesture = HumanGesture.None;
        public InteractionActivity activity = InteractionActivity.Idle;
        public string interactionTarget = "";
        public float confidence;
        public Vector3 velocity;
    }

    [Serializable]
    public sealed class SharedAttentionData
    {
        public string humanFocus = "";
        public string avatarFocus = "";
        public string sharedTarget = "";
        public float gazeAlignment;
        public float attentionConfidence;
        public Vector3 sharedTargetPosition;
        public long updatedAtMs;
    }

    [Serializable]
    public sealed class InteractionStateData
    {
        public InteractionActivity state = InteractionActivity.Idle;
        public string goal = "";
        public string target = "";
        public long sinceMs;
        public float confidence;
        public bool interruptible = true;
        public bool cancelled;
        public bool interrupted;
        public string resumeGoal = "";
        public string resumeTarget = "";
    }
}
