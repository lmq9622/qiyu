using System;
using Newtonsoft.Json.Linq;
using Qiyu.Quest.Networking;
using UnityEngine;

namespace Qiyu.Quest.Perception
{
    /// <summary>
    /// 用户自身建模（低阶动捕）。
    ///
    /// 输入：头显位姿 + 双手（OVRHand）或手柄（OVRControllerHelper）相对位置。
    /// 输出：头、双手、肩中心、髋部、身高、前倾角、置信度组成的用户身体骨架，
    /// 并生成可视化的线框/球体；通过 client.user_body 与 WorldState.user.body
    /// 上传给 Qiyu 后端，供后续 LLM 判断“用户在哪、面向哪、手在哪”。
    ///
    /// 这不是全身动捕，而是头显+双手的 5 点近似；接口预留 full_body 数据源，
    /// 未来接入 Meta Body Tracking 时只需替换 BuildFrame 中的躯干/腿部估计。
    /// </summary>
    public class QiyuUserBodyTracker : MonoBehaviour
    {
        [Header("输入")]
        [SerializeField] private Transform head;
        [SerializeField] private OVRHand leftHand;
        [SerializeField] private OVRHand rightHand;
        [SerializeField] private Transform leftHandAnchor;
        [SerializeField] private Transform rightHandAnchor;
        [SerializeField] private OVRControllerHelper leftController;
        [SerializeField] private OVRControllerHelper rightController;
        [SerializeField] private MrukSceneSummary sceneSummary;

        [Header("输出")]
        [SerializeField] private MrukWorldStatePublisher worldStatePublisher;
        [SerializeField] private QiyuQuestWebSocketClient webSocketClient;
        [SerializeField] private bool visualize = true;
        [SerializeField] private bool upload = true;
        [SerializeField] private float uploadHz = 5f;

        private GameObject _visualRoot;
        private Transform _headSphere;
        private Transform _leftSphere;
        private Transform _rightSphere;
        private Transform _leftElbowSphere;
        private Transform _rightElbowSphere;
        private Transform _leftFoot;
        private Transform _rightFoot;
        private Transform _torso;
        private LineRenderer _spine;
        private LineRenderer _leftArm;
        private LineRenderer _rightArm;
        private LineRenderer _shoulders;
        private LineRenderer _hips;
        private LineRenderer _leftLeg;
        private LineRenderer _rightLeg;
        private JObject _latestJson = new JObject();
        private float _nextUploadAt;
        private bool _hasData;

        // 关节平滑状态：动捕手部噪声大，直接画会抖成“抽筋”。
        private Vector3 _smoothHead;
        private Vector3 _smoothLeftHand;
        private Vector3 _smoothRightHand;
        private bool _smoothInit;
        private float _lastFrameTime;

        // 人体比例（相对身高 H），参考成人骨骼比例，避免“手长到离谱”。
        private const float EyeHeightRatio = 0.94f;
        private const float HipHeightRatio = 0.53f;
        private const float ShoulderWidthRatio = 0.245f;
        private const float UpperArmRatio = 0.186f;
        private const float ForearmRatio = 0.146f;
        private const float HipWidthRatio = 0.09f;

        public Vector3 LeftElbowPosition { get; private set; }
        public Vector3 RightElbowPosition { get; private set; }
        public Vector3 LeftKneePosition { get; private set; }
        public Vector3 RightKneePosition { get; private set; }
        public Vector3 LeftFootPosition { get; private set; }
        public Vector3 RightFootPosition { get; private set; }
        public bool LeftHandTracked { get; private set; }
        public bool RightHandTracked { get; private set; }

        public bool HasData => _hasData;
        public bool Visualize
        {
            get => visualize;
            set
            {
                visualize = value;
                if (_visualRoot != null)
                {
                    _visualRoot.SetActive(value);
                }
            }
        }

        public bool Upload
        {
            get => upload;
            set => upload = value;
        }

        public JObject LatestJson => _latestJson;
        public Vector3 HeadPosition { get; private set; }
        public Vector3 LeftHandPosition { get; private set; }
        public Vector3 RightHandPosition { get; private set; }
        public Vector3 ShoulderCenter { get; private set; }
        public Vector3 HipsPosition { get; private set; }
        public float EstimatedHeight { get; private set; }
        public float LeanDegrees { get; private set; }
        public float Confidence { get; private set; }
        public string LeftHandSource { get; private set; } = "none";
        public string RightHandSource { get; private set; } = "none";

        private void Awake()
        {
            CreateVisuals();
        }

        private void OnEnable()
        {
            if (webSocketClient != null)
            {
                webSocketClient.SessionEstablished += OnSessionEstablished;
            }
        }

        private void OnDisable()
        {
            if (webSocketClient != null)
            {
                webSocketClient.SessionEstablished -= OnSessionEstablished;
            }
        }

        private void OnSessionEstablished()
        {
            _nextUploadAt = 0f;
        }

        private void Update()
        {
            if (head == null)
            {
                return;
            }
            BuildFrame();
            UpdateVisuals();
            if (upload && Time.unscaledTime >= _nextUploadAt)
            {
                var interval = uploadHz > 0.1f ? 1f / uploadHz : 0.2f;
                _nextUploadAt = Time.unscaledTime + interval;
                Publish();
            }
        }

        private void BuildFrame()
        {
            var now = Time.unscaledTime;
            var dt = _lastFrameTime <= 0f ? 0.016f : Mathf.Clamp(now - _lastFrameTime, 0.001f, 0.1f);
            _lastFrameTime = now;

            HeadPosition = Smooth(ref _smoothHead, head.position, dt, 22f, 0.10f);
            var floorY = ResolveFloorY(HeadPosition.y);
            // 眼高约 0.94×身高，比“眼高+固定值”更稳。
            EstimatedHeight = Mathf.Clamp(
                (HeadPosition.y - floorY) / EyeHeightRatio, 1.2f, 2.1f);
            var h = EstimatedHeight;

            var headRight = head.right;
            headRight.y = 0f;
            if (headRight.sqrMagnitude < 0.0001f)
            {
                headRight = Vector3.right;
            }
            headRight.Normalize();

            var headForward = head.forward;
            headForward.y = 0f;
            if (headForward.sqrMagnitude < 0.0001f)
            {
                headForward = Vector3.forward;
            }
            headForward.Normalize();

            // 肩/髋用身高比例定位，并且髋部必须落在真实地面上，
            // 否则整个人会“飘”在半空。
            var shoulderHalf = ShoulderWidthRatio * 0.5f * h;
            ShoulderCenter = HeadPosition - Vector3.up * 0.16f * h;
            HipsPosition = new Vector3(HeadPosition.x, floorY + HipHeightRatio * h,
                HeadPosition.z);
            var lean = HeadPosition - HipsPosition;
            LeanDegrees = Vector3.Angle(lean, Vector3.up);

            var shoulderLeft = ShoulderCenter - headRight * shoulderHalf;
            var shoulderRight = ShoulderCenter + headRight * shoulderHalf;

            var left = ResolveHand(leftHand, leftController, leftHandAnchor,
                out var leftSource, out var leftTracked);
            var right = ResolveHand(rightHand, rightController, rightHandAnchor,
                out var rightSource, out var rightTracked);
            leftTracked &= IsPlausibleHand(left, HeadPosition);
            rightTracked &= IsPlausibleHand(right, HeadPosition);
            if (!leftTracked)
            {
                leftSource = "none";
            }
            if (!rightTracked)
            {
                rightSource = "none";
            }
            LeftHandTracked = leftTracked;
            RightHandTracked = rightTracked;
            LeftHandSource = leftSource;
            RightHandSource = rightSource;

            if (leftTracked)
            {
                LeftHandPosition = Smooth(ref _smoothLeftHand, left, dt, 18f, 0.15f);
            }
            if (rightTracked)
            {
                RightHandPosition = Smooth(ref _smoothRightHand, right, dt, 18f, 0.15f);
            }

            // 双骨 IK：肩→肘→手。肘部朝向（pole）取“向下 + 略微外扩 + 略向后”，
            // 这是 VRChat/SteamVR 那套三点动捕的标准做法，避免手臂穿进躯干。
            var upperArm = UpperArmRatio * h;
            var forearm = ForearmRatio * h;
            if (leftTracked)
            {
                var pole = (-headRight * 0.55f + Vector3.down + headForward * -0.18f).normalized;
                LeftElbowPosition = SolveElbow(shoulderLeft, LeftHandPosition,
                    upperArm, forearm, pole, out var reachLeft);
                LeftHandPosition = ClampReach(shoulderLeft, LeftHandPosition,
                    upperArm + forearm, reachLeft);
            }
            if (rightTracked)
            {
                var pole = (headRight * 0.55f + Vector3.down + headForward * -0.18f).normalized;
                RightElbowPosition = SolveElbow(shoulderRight, RightHandPosition,
                    upperArm, forearm, pole, out var reachRight);
                RightHandPosition = ClampReach(shoulderRight, RightHandPosition,
                    upperArm + forearm, reachRight);
            }

            // 腿：髋→膝→踝，脚踩在地面上，让骨架“站住”。
            var hipHalf = HipWidthRatio * h;
            var hipLeft = HipsPosition - headRight * hipHalf;
            var hipRight = HipsPosition + headRight * hipHalf;
            var ankleY = floorY + 0.07f;
            LeftFootPosition = new Vector3(hipLeft.x, ankleY, hipLeft.z)
                               + headForward * 0.03f * h;
            RightFootPosition = new Vector3(hipRight.x, ankleY, hipRight.z)
                                + headForward * 0.03f * h;
            LeftKneePosition = (hipLeft + LeftFootPosition) * 0.5f
                               + headForward * 0.035f * h;
            RightKneePosition = (hipRight + RightFootPosition) * 0.5f
                                + headForward * 0.035f * h;

            var trackedHands = (leftTracked ? 1 : 0) + (rightTracked ? 1 : 0);
            Confidence = trackedHands switch
            {
                2 => 0.95f,
                1 => 0.65f,
                _ => 0.35f
            };

            _latestJson = new JObject
            {
                ["ts"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                ["source"] = "headset_hands_controllers",
                ["head"] = PoseToJson(HeadPosition, head.rotation),
                ["gaze_direction"] = VectorToJson(head.forward),
                ["left_hand"] = PoseToJson(LeftHandPosition, head.rotation),
                ["right_hand"] = PoseToJson(RightHandPosition, head.rotation),
                ["left_hand_source"] = LeftHandSource,
                ["right_hand_source"] = RightHandSource,
                ["shoulder_center"] = VectorToJson(ShoulderCenter),
                ["shoulder_left"] = VectorToJson(ShoulderCenter - headRight * shoulderHalf),
                ["shoulder_right"] = VectorToJson(ShoulderCenter + headRight * shoulderHalf),
                ["elbow_left"] = VectorToJson(LeftElbowPosition),
                ["elbow_right"] = VectorToJson(RightElbowPosition),
                ["hips"] = VectorToJson(HipsPosition),
                ["knee_left"] = VectorToJson(LeftKneePosition),
                ["knee_right"] = VectorToJson(RightKneePosition),
                ["foot_left"] = VectorToJson(LeftFootPosition),
                ["foot_right"] = VectorToJson(RightFootPosition),
                ["floor_y"] = floorY,
                ["left_hand_tracked"] = LeftHandTracked,
                ["right_hand_tracked"] = RightHandTracked,
                ["body_height_m"] = EstimatedHeight,
                ["lean_deg"] = LeanDegrees,
                ["confidence"] = Confidence,
                ["model"] = "5point_head_hands_ik_legs",
                ["full_body"] = new JObject()
            };
            _hasData = true;
            _smoothInit = true;
        }

        /// <summary>
        /// 指数平滑，减少手部追踪抖动；差值过大（刚开始追踪/瞬移）时直接吸附。
        /// </summary>
        private Vector3 Smooth(ref Vector3 state, Vector3 target, float dt,
                               float speed, float snapDistance)
        {
            if (!_smoothInit || Vector3.Distance(state, target) > snapDistance * 3f)
            {
                state = target;
                return state;
            }
            var alpha = 1f - Mathf.Exp(-speed * dt);
            state = Vector3.Lerp(state, target, alpha);
            return state;
        }

        /// <summary>
        /// 三点动捕的手部有效性判定：世界原点或离头过远/过近都不可信。
        /// </summary>
        private static bool IsPlausibleHand(Vector3 p, Vector3 headPosition)
        {
            if (p.sqrMagnitude < 1e-6f)
            {
                return false;
            }
            var distance = Vector3.Distance(p, headPosition);
            return distance > 0.12f && distance < 1.25f;
        }

        /// <summary>
        /// 双骨解析 IK：求肘关节位置。reach 返回肩到手的目标距离（未夹取）。
        /// </summary>
        private static Vector3 SolveElbow(Vector3 shoulder, Vector3 hand,
                                          float upperLength, float foreLength,
                                          Vector3 poleDirection, out float reach)
        {
            var axis = hand - shoulder;
            reach = axis.magnitude;
            if (reach < 1e-4f)
            {
                return shoulder + poleDirection * upperLength;
            }
            var dir = axis / reach;
            var minReach = Mathf.Abs(upperLength - foreLength) + 1e-3f;
            var maxReach = upperLength + foreLength - 1e-3f;
            var d = Mathf.Clamp(reach, minReach, maxReach);
            var along = (d * d + upperLength * upperLength - foreLength * foreLength) /
                        (2f * d);
            var heightSquared = upperLength * upperLength - along * along;
            var height = heightSquared > 0f ? Mathf.Sqrt(heightSquared) : 0f;
            var pole = poleDirection - dir * Vector3.Dot(poleDirection, dir);
            if (pole.sqrMagnitude < 1e-6f)
            {
                pole = Vector3.Cross(dir, Vector3.right);
                if (pole.sqrMagnitude < 1e-6f)
                {
                    pole = Vector3.Cross(dir, Vector3.forward);
                }
            }
            pole.Normalize();
            return shoulder + dir * along + pole * height;
        }

        /// <summary>
        /// 手超出臂长时把手拉回可达范围，否则会画出一条“橡皮手臂”。
        /// </summary>
        private static Vector3 ClampReach(Vector3 shoulder, Vector3 hand,
                                          float maxLength, float reach)
        {
            var limit = maxLength * 0.99f;
            if (reach <= limit || reach < 1e-4f)
            {
                return hand;
            }
            return shoulder + (hand - shoulder) / reach * limit;
        }

        private Vector3 ResolveHand(OVRHand hand, OVRControllerHelper controller,
                                    Transform anchor, out string source,
                                    out bool tracked)
        {
            if (hand != null && hand.IsDataValid && hand.IsPointerPoseValid)
            {
                source = "hand";
                tracked = true;
                return hand.PointerPose.position;
            }
            if (controller != null && controller.IsActive())
            {
                source = "controller";
                tracked = true;
                return controller.transform.position;
            }
            if (anchor != null)
            {
                source = "anchor";
                tracked = true;
                return anchor.position;
            }
            source = "none";
            tracked = false;
            return HeadPosition;
        }

        private float ResolveFloorY(float fallback)
        {
            var room = sceneSummary != null ? sceneSummary.CurrentRoom : null;
            if (room != null && room.FloorAnchors != null && room.FloorAnchors.Count > 0)
            {
                var floor = room.FloorAnchors[0];
                if (floor != null)
                {
                    return floor.transform.position.y;
                }
            }
            return fallback - 1.6f;
        }

        private void Publish()
        {
            if (worldStatePublisher != null)
            {
                worldStatePublisher.SetUserBody(_latestJson);
            }
            if (webSocketClient != null && webSocketClient.HandshakeDone &&
                !string.IsNullOrEmpty(webSocketClient.SessionId))
            {
                _ = webSocketClient.SendAsync(new QuestEnvelope("client.user_body",
                    _latestJson, webSocketClient.SessionId));
            }
        }

        private void CreateVisuals()
        {
            _visualRoot = new GameObject("QiyuUserBodyModel");
            _visualRoot.transform.SetParent(transform, false);
            _headSphere = CreateSphere("Head", 0.15f, new Color(0.95f, 0.95f, 1f, 0.9f));
            _leftSphere = CreateSphere("LeftHand", 0.055f, new Color(1f, 0.75f, 0.2f, 0.95f));
            _rightSphere = CreateSphere("RightHand", 0.055f, new Color(1f, 0.55f, 0.2f, 0.95f));
            _leftElbowSphere = CreateSphere("LeftElbow", 0.045f,
                new Color(1f, 0.78f, 0.32f, 0.9f));
            _rightElbowSphere = CreateSphere("RightElbow", 0.045f,
                new Color(1f, 0.62f, 0.32f, 0.9f));
            _leftFoot = CreateSphere("LeftFoot", 0.06f, new Color(0.6f, 0.85f, 1f, 0.85f));
            _rightFoot = CreateSphere("RightFoot", 0.06f, new Color(0.6f, 0.85f, 1f, 0.85f));
            _torso = CreateTorso();
            _spine = CreateLine("Spine", new Color(0.20f, 0.95f, 1f, 0.95f));
            _leftArm = CreateLine("LeftArm", new Color(1f, 0.75f, 0.2f, 0.95f));
            _rightArm = CreateLine("RightArm", new Color(1f, 0.55f, 0.2f, 0.95f));
            _shoulders = CreateLine("Shoulders", new Color(0.65f, 0.8f, 1f, 0.9f));
            _hips = CreateLine("Hips", new Color(0.65f, 0.8f, 1f, 0.9f));
            _leftLeg = CreateLine("LeftLeg", new Color(0.55f, 0.85f, 1f, 0.9f));
            _rightLeg = CreateLine("RightLeg", new Color(0.55f, 0.85f, 1f, 0.9f));
        }

        private Transform CreateSphere(string name, float size, Color color)
        {
            var go = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            go.name = name;
            go.transform.SetParent(_visualRoot.transform, false);
            go.transform.localScale = Vector3.one * size;
            Destroy(go.GetComponent<Collider>());
            var renderer = go.GetComponent<Renderer>();
            renderer.sharedMaterial = CreateMaterial(
                Shader.Find("Universal Render Pipeline/Unlit") ??
                Shader.Find("Unlit/Color") ?? Shader.Find("Sprites/Default"),
                "QiyuBody_" + name, color);
            return go.transform;
        }

        private Transform CreateTorso()
        {
            var go = GameObject.CreatePrimitive(PrimitiveType.Cube);
            go.name = "Torso";
            go.transform.SetParent(_visualRoot.transform, false);
            Destroy(go.GetComponent<Collider>());
            var renderer = go.GetComponent<Renderer>();
            renderer.sharedMaterial = CreateMaterial(
                Shader.Find("Universal Render Pipeline/Unlit") ??
                Shader.Find("Unlit/Color") ?? Shader.Find("Sprites/Default"),
                "QiyuBodyTorso", new Color(0.35f, 0.75f, 1f, 0.22f));
            return go.transform;
        }

        private LineRenderer CreateLine(string name, Color color)
        {
            var go = new GameObject(name);
            go.transform.SetParent(_visualRoot.transform, false);
            var line = go.AddComponent<LineRenderer>();
            line.useWorldSpace = true;
            line.positionCount = 3;
            line.startWidth = 0.018f;
            line.endWidth = 0.012f;
            line.numCapVertices = 4;
            line.sharedMaterial = CreateMaterial(
                Shader.Find("Universal Render Pipeline/Unlit") ??
                Shader.Find("Sprites/Default") ?? Shader.Find("Unlit/Color"),
                "QiyuBodyLine_" + name, color);
            return line;
        }

        private void UpdateVisuals()
        {
            if (_visualRoot == null)
            {
                return;
            }
            _visualRoot.SetActive(visualize);
            if (!visualize)
            {
                return;
            }
            var h = EstimatedHeight;
            var headRight = head.right;
            headRight.y = 0f;
            if (headRight.sqrMagnitude < 0.0001f)
            {
                headRight = Vector3.right;
            }
            headRight.Normalize();

            var shoulderHalf = ShoulderWidthRatio * 0.5f * h;
            var shoulderLeft = ShoulderCenter - headRight * shoulderHalf;
            var shoulderRight = ShoulderCenter + headRight * shoulderHalf;
            var hipHalf = HipWidthRatio * h;
            var hipLeft = HipsPosition - headRight * hipHalf;
            var hipRight = HipsPosition + headRight * hipHalf;

            _headSphere.position = HeadPosition;
            // 没跟到手就把整条手臂藏起来：老实现会把球画在头的位置，
            // 看起来就像“手直接连在身体上”。
            _leftSphere.gameObject.SetActive(LeftHandTracked);
            _leftElbowSphere.gameObject.SetActive(LeftHandTracked);
            _leftArm.gameObject.SetActive(LeftHandTracked);
            _rightSphere.gameObject.SetActive(RightHandTracked);
            _rightElbowSphere.gameObject.SetActive(RightHandTracked);
            _rightArm.gameObject.SetActive(RightHandTracked);
            if (LeftHandTracked)
            {
                _leftSphere.position = LeftHandPosition;
                _leftElbowSphere.position = LeftElbowPosition;
                _leftArm.SetPosition(0, shoulderLeft);
                _leftArm.SetPosition(1, LeftElbowPosition);
                _leftArm.SetPosition(2, LeftHandPosition);
            }
            if (RightHandTracked)
            {
                _rightSphere.position = RightHandPosition;
                _rightElbowSphere.position = RightElbowPosition;
                _rightArm.SetPosition(0, shoulderRight);
                _rightArm.SetPosition(1, RightElbowPosition);
                _rightArm.SetPosition(2, RightHandPosition);
            }

            _torso.position = (ShoulderCenter + HipsPosition) * 0.5f;
            _torso.rotation = Quaternion.LookRotation(head.forward, Vector3.up);
            _torso.localScale = new Vector3(0.36f, Mathf.Max(0.3f,
                Vector3.Distance(ShoulderCenter, HipsPosition) * 0.9f), 0.22f);

            _spine.SetPosition(0, HipsPosition);
            _spine.SetPosition(1, (ShoulderCenter + HipsPosition) * 0.5f);
            _spine.SetPosition(2, ShoulderCenter);
            _shoulders.SetPosition(0, shoulderLeft);
            _shoulders.SetPosition(1, ShoulderCenter);
            _shoulders.SetPosition(2, shoulderRight);
            _hips.SetPosition(0, hipLeft);
            _hips.SetPosition(1, HipsPosition);
            _hips.SetPosition(2, hipRight);

            _leftLeg.SetPosition(0, hipLeft);
            _leftLeg.SetPosition(1, LeftKneePosition);
            _leftLeg.SetPosition(2, LeftFootPosition);
            _rightLeg.SetPosition(0, hipRight);
            _rightLeg.SetPosition(1, RightKneePosition);
            _rightLeg.SetPosition(2, RightFootPosition);
            _leftFoot.position = LeftFootPosition;
            _rightFoot.position = RightFootPosition;
        }

        private static Material CreateMaterial(Shader shader, string name, Color color)
        {
            if (shader == null)
            {
                return null;
            }
            var material = new Material(shader) { name = name };
            if (material.HasProperty("_BaseColor"))
            {
                material.SetColor("_BaseColor", color);
            }
            if (material.HasProperty("_Color"))
            {
                material.SetColor("_Color", color);
            }
            material.EnableKeyword("_SURFACE_TYPE_TRANSPARENT");
            material.EnableKeyword("_ALPHAPREMULTIPLY_ON");
            material.SetOverrideTag("RenderType", "Transparent");
            material.SetInt("_SrcBlend",
                (int)UnityEngine.Rendering.BlendMode.SrcAlpha);
            material.SetInt("_DstBlend",
                (int)UnityEngine.Rendering.BlendMode.OneMinusSrcAlpha);
            if (material.HasProperty("_ZWrite"))
            {
                material.SetInt("_ZWrite", 0);
            }
            material.renderQueue = (int)UnityEngine.Rendering.RenderQueue.Transparent;
            return material;
        }

        private static JObject PoseToJson(Vector3 position, Quaternion rotation)
        {
            return new JObject
            {
                ["position"] = VectorToJson(position),
                ["rotation"] = new JObject
                {
                    ["x"] = rotation.x,
                    ["y"] = rotation.y,
                    ["z"] = rotation.z,
                    ["w"] = rotation.w
                }
            };
        }

        private static JObject VectorToJson(Vector3 v)
        {
            return new JObject { ["x"] = v.x, ["y"] = v.y, ["z"] = v.z };
        }
    }
}
