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
        private Transform _torso;
        private LineRenderer _spine;
        private LineRenderer _leftArm;
        private LineRenderer _rightArm;
        private LineRenderer _shoulders;
        private LineRenderer _hips;
        private JObject _latestJson = new JObject();
        private float _nextUploadAt;
        private bool _hasData;

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
            HeadPosition = head.position;
            var floorY = ResolveFloorY(HeadPosition.y);
            EstimatedHeight = Mathf.Clamp(HeadPosition.y - floorY + 0.18f, 1.2f, 2.1f);

            var headRight = head.right;
            headRight.y = 0f;
            if (headRight.sqrMagnitude < 0.0001f)
            {
                headRight = Vector3.right;
            }
            headRight.Normalize();

            ShoulderCenter = HeadPosition - Vector3.up * 0.20f;
            var hipDrop = Mathf.Clamp(EstimatedHeight * 0.52f, 0.65f, 1.05f);
            HipsPosition = HeadPosition - Vector3.up * hipDrop;
            var lean = HeadPosition - HipsPosition;
            LeanDegrees = Vector3.Angle(lean, Vector3.up);

            var left = ResolveHand(leftHand, leftController, leftHandAnchor,
                out var leftSource);
            var right = ResolveHand(rightHand, rightController, rightHandAnchor,
                out var rightSource);
            LeftHandPosition = left;
            RightHandPosition = right;
            LeftHandSource = leftSource;
            RightHandSource = rightSource;

            var trackedHands = 0;
            if (leftSource != "none") trackedHands++;
            if (rightSource != "none") trackedHands++;
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
                ["shoulder_left"] = VectorToJson(ShoulderCenter - headRight * 0.18f),
                ["shoulder_right"] = VectorToJson(ShoulderCenter + headRight * 0.18f),
                ["hips"] = VectorToJson(HipsPosition),
                ["body_height_m"] = EstimatedHeight,
                ["lean_deg"] = LeanDegrees,
                ["confidence"] = Confidence,
                ["model"] = "5point_head_hands",
                ["full_body"] = new JObject()
            };
            _hasData = true;
        }

        private Vector3 ResolveHand(OVRHand hand, OVRControllerHelper controller,
                                    Transform anchor, out string source)
        {
            if (hand != null && hand.IsDataValid && hand.IsPointerPoseValid)
            {
                source = "hand";
                return hand.PointerPose.position;
            }
            if (controller != null && controller.IsActive())
            {
                source = "controller";
                return controller.transform.position;
            }
            if (anchor != null)
            {
                source = "anchor";
                return anchor.position;
            }
            source = "none";
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
            _headSphere = CreateSphere("Head", 0.16f, new Color(0.95f, 0.95f, 1f, 0.9f));
            _leftSphere = CreateSphere("LeftHand", 0.075f, new Color(1f, 0.75f, 0.2f, 0.95f));
            _rightSphere = CreateSphere("RightHand", 0.075f, new Color(1f, 0.55f, 0.2f, 0.95f));
            _torso = CreateTorso();
            _spine = CreateLine("Spine", new Color(0.20f, 0.95f, 1f, 0.95f));
            _leftArm = CreateLine("LeftArm", new Color(1f, 0.75f, 0.2f, 0.95f));
            _rightArm = CreateLine("RightArm", new Color(1f, 0.55f, 0.2f, 0.95f));
            _shoulders = CreateLine("Shoulders", new Color(0.65f, 0.8f, 1f, 0.9f));
            _hips = CreateLine("Hips", new Color(0.65f, 0.8f, 1f, 0.9f));
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
            _headSphere.position = HeadPosition;
            _leftSphere.position = LeftHandPosition;
            _rightSphere.position = RightHandPosition;
            var shoulderLeft = ShoulderCenter - head.right * 0.18f;
            var shoulderRight = ShoulderCenter + head.right * 0.18f;
            _torso.position = (ShoulderCenter + HipsPosition) * 0.5f;
            _torso.rotation = Quaternion.LookRotation(head.forward, Vector3.up);
            _torso.localScale = new Vector3(0.36f, Mathf.Max(0.3f,
                Vector3.Distance(ShoulderCenter, HipsPosition) * 0.9f), 0.22f);

            _spine.SetPosition(0, HipsPosition);
            _spine.SetPosition(1, (ShoulderCenter + HipsPosition) * 0.5f);
            _spine.SetPosition(2, ShoulderCenter);
            _leftArm.SetPosition(0, shoulderLeft);
            _leftArm.SetPosition(1, Vector3.Lerp(shoulderLeft, LeftHandPosition, 0.5f));
            _leftArm.SetPosition(2, LeftHandPosition);
            _rightArm.SetPosition(0, shoulderRight);
            _rightArm.SetPosition(1, Vector3.Lerp(shoulderRight, RightHandPosition, 0.5f));
            _rightArm.SetPosition(2, RightHandPosition);
            _shoulders.SetPosition(0, shoulderLeft);
            _shoulders.SetPosition(1, ShoulderCenter);
            _shoulders.SetPosition(2, shoulderRight);
            _hips.SetPosition(0, HipsPosition - head.right * 0.12f);
            _hips.SetPosition(1, HipsPosition);
            _hips.SetPosition(2, HipsPosition + head.right * 0.12f);
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
