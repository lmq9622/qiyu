using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.XR.Hands;

namespace Qiyu.Quest.UI
{
    /// <summary>
    /// 基于 Unity XR Hands（OpenXR 手部追踪）的手部骨架可视化与关节数据源。
    ///
    /// 为什么要另起一条路：
    /// Quest 真机日志显示，Meta 旧接口 OVRHand/OVRSkeleton 在当前 OpenXR 运行时下
    /// 只给出 PointerPose（position 有效），26 个关节的位置全是 0，手部网格因此
    /// 退化成一个点，指尖激光也无从谈起。
    /// 而 XRHandSubsystem（OpenXR 原生手部追踪，项目里 HandTracking 子系统特性已启用）
    /// 能拿到真实关节 —— 运行时既然能算出 pinch strength=0.70，就说明关节数据是有的。
    ///
    /// 这里提供两件事：
    ///  1) 可见手部骨架（关节球 + 骨链线），保证“看得见手”；
    ///  2) 指尖位置/朝向/捏合距离，供激光与点击使用。
    /// </summary>
    public class QiyuHandRig : MonoBehaviour
    {
        public enum HandSide
        {
            Left,
            Right,
        }

        [SerializeField] private bool visualize = true;
        [SerializeField] private Color leftColor = new Color(0.48f, 0.88f, 1f, 0.95f);
        [SerializeField] private Color rightColor = new Color(1f, 0.82f, 0.45f, 0.95f);
        [SerializeField] private float jointSize = 0.013f;
        [SerializeField] private float lineWidth = 0.0055f;
        [SerializeField] private bool logDiagnostics = true;

        /// <summary>骨链：按 OpenXR 关节层级连线，画出来就是一只手的骨架。</summary>
        private static readonly XRHandJointID[][] Chains =
        {
            new[]
            {
                XRHandJointID.Wrist, XRHandJointID.Palm,
            },
            new[]
            {
                XRHandJointID.Wrist, XRHandJointID.ThumbMetacarpal,
                XRHandJointID.ThumbProximal, XRHandJointID.ThumbDistal,
                XRHandJointID.ThumbTip,
            },
            new[]
            {
                XRHandJointID.Palm, XRHandJointID.IndexMetacarpal,
                XRHandJointID.IndexProximal, XRHandJointID.IndexIntermediate,
                XRHandJointID.IndexDistal, XRHandJointID.IndexTip,
            },
            new[]
            {
                XRHandJointID.Palm, XRHandJointID.MiddleMetacarpal,
                XRHandJointID.MiddleProximal, XRHandJointID.MiddleIntermediate,
                XRHandJointID.MiddleDistal, XRHandJointID.MiddleTip,
            },
            new[]
            {
                XRHandJointID.Palm, XRHandJointID.RingMetacarpal,
                XRHandJointID.RingProximal, XRHandJointID.RingIntermediate,
                XRHandJointID.RingDistal, XRHandJointID.RingTip,
            },
            new[]
            {
                XRHandJointID.Palm, XRHandJointID.LittleMetacarpal,
                XRHandJointID.LittleProximal, XRHandJointID.LittleIntermediate,
                XRHandJointID.LittleDistal, XRHandJointID.LittleTip,
            },
        };

        private sealed class HandVisual
        {
            public HandSide Side;
            public Material JointMaterial;
            public readonly List<LineRenderer> Lines = new List<LineRenderer>();
            public readonly List<Matrix4x4> Matrices = new List<Matrix4x4>(32);
            public Transform FallbackMarker;
            public Renderer FallbackRenderer;
            public bool Visible;
        }

        private readonly List<HandVisual> _visuals = new List<HandVisual>();
        private readonly List<XRHandSubsystem> _subsystems = new List<XRHandSubsystem>();
        private XRHandSubsystem _subsystem;
        private Mesh _sphere;
        private float _nextLogAt;
        private float _nextSubsystemCheckAt;
        private bool _warnedAboutSubsystem;
        private OVRHand _leftOvrHand;
        private OVRHand _rightOvrHand;
        private int _lastSubsystemId = -1;

        public bool IsReady => _subsystem != null && _subsystem.running;

        /// <summary>调试面板用：当前是否拿得到左手/右手关节。</summary>
        public bool IsTracked(HandSide side)
        {
            var hand = GetHand(side);
            if (hand.isTracked)
            {
                return true;
            }
            // 子系统把 isTracked 置 false、但关节仍然可用（推断/上一帧姿态）时也要算可用，
            // 否则手部骨架会在中途整条消失。
            return CountValidJoints(side) >= 4;
        }

        private void Awake()
        {
            CreateVisuals();
        }

        private void Start()
        {
            var hands = FindObjectsByType<OVRHand>(FindObjectsInactive.Include);
            foreach (var candidate in hands)
            {
                if (candidate == null)
                {
                    continue;
                }
                if (candidate.GetHand() == OVRPlugin.Hand.HandLeft)
                {
                    _leftOvrHand = candidate;
                }
                else if (candidate.GetHand() == OVRPlugin.Hand.HandRight)
                {
                    _rightOvrHand = candidate;
                }
            }
        }

        private void Update()
        {
            EnsureSubsystem();
            UpdateVisuals();
            if (logDiagnostics && Time.unscaledTime >= _nextLogAt)
            {
                _nextLogAt = Time.unscaledTime + 5f;
                LogDiagnostics();
            }
        }

        /// <summary>拿某只手的某个关节位姿（追踪空间）。</summary>
        public bool TryGetJoint(HandSide side, XRHandJointID id, out Pose pose)
        {
            pose = default;
            var hand = GetHand(side);
            var joint = hand.GetJoint(id);
            return joint.TryGetPose(out pose);
        }

        /// <summary>统计当前有效的关节数，用于判断手是否可用。</summary>
        private int CountValidJoints(HandSide side)
        {
            var count = 0;
            var hand = GetHand(side);
            for (var id = XRHandJointID.BeginMarker;
                 id < XRHandJointID.EndMarker; id++)
            {
                if (hand.GetJoint(id).TryGetPose(out _))
                {
                    count++;
                }
            }
            return count;
        }

        /// <summary>
        /// 食指射线：指尖为起点，指尖减去中节指骨得到方向，激光顺着手指出。
        /// </summary>
        public bool TryGetIndexRay(HandSide side, out Vector3 origin, out Vector3 direction)
        {
            origin = Vector3.zero;
            direction = Vector3.forward;
            if (!TryGetJoint(side, XRHandJointID.IndexTip, out var tip))
            {
                return false;
            }
            origin = tip.position;
            if (TryGetJoint(side, XRHandJointID.IndexDistal, out var distal))
            {
                var forward = tip.position - distal.position;
                if (forward.sqrMagnitude > 1e-8f)
                {
                    direction = forward.normalized;
                    return true;
                }
            }
            direction = tip.rotation * Vector3.up;
            return true;
        }

        /// <summary>拇指尖到食指尖的距离；拿不到关节时返回 -1。</summary>
        public float PinchDistance(HandSide side)
        {
            if (!TryGetJoint(side, XRHandJointID.IndexTip, out var index) ||
                !TryGetJoint(side, XRHandJointID.ThumbTip, out var thumb))
            {
                return -1f;
            }
            return Vector3.Distance(index.position, thumb.position);
        }

        private XRHand GetHand(HandSide side)
        {
            if (_subsystem == null)
            {
                return default;
            }
            return side == HandSide.Left ? _subsystem.leftHand : _subsystem.rightHand;
        }

        private void EnsureSubsystem()
        {
            if (Time.unscaledTime < _nextSubsystemCheckAt)
            {
                return;
            }
            // 每秒回查一次：手柄/裸手切换、会话重启都可能换掉子系统实例，
            // 只认引用一次会导致“开始有手、切一次模式后再也不出现”。
            _nextSubsystemCheckAt = Time.unscaledTime + 1f;
            _subsystems.Clear();
            SubsystemManager.GetSubsystems(_subsystems);
            XRHandSubsystem running = null;
            XRHandSubsystem fallback = null;
            foreach (var candidate in _subsystems)
            {
                if (candidate == null)
                {
                    continue;
                }
                fallback ??= candidate;
                if (candidate.running)
                {
                    running = candidate;
                    break;
                }
            }
            var best = running ?? fallback;
            if (best != null && !best.running)
            {
                // 手柄/裸手来回切换时子系统可能被停下；这里主动拉起来，
                // 否则会表现成“手出现一次之后再也不回来”。
                try
                {
                    best.Start();
                    Debug.Log("[QiyuHand] 手部子系统未运行，已尝试重新启动");
                }
                catch (Exception e)
                {
                    Debug.LogWarning("[QiyuHand] 重启手部子系统失败: " + e.Message);
                }
            }
            if (!ReferenceEquals(best, _subsystem))
            {
                _subsystem = best;
                _lastSubsystemId = best != null ? best.GetHashCode() : -1;
                Debug.Log($"[QiyuHand] 接入 XRHandSubsystem id={_lastSubsystemId} " +
                          $"running={best != null && best.running} " +
                          $"count={_subsystems.Count}");
            }
            if (!_warnedAboutSubsystem && Time.unscaledTime > 8f)
            {
                _warnedAboutSubsystem = true;
                Debug.LogWarning("[QiyuHand] 没找到运行中的 XRHandSubsystem，手部骨架不可用");
            }
        }

        private void CreateVisuals()
        {
            _sphere = BuildSphere();
            foreach (HandSide side in Enum.GetValues(typeof(HandSide)))
            {
                var visual = new HandVisual
                {
                    Side = side,
                    JointMaterial = CreateMaterial(
                        side == HandSide.Left ? leftColor : rightColor)
                };
                var root = new GameObject($"QiyuHand_{side}");
                root.transform.SetParent(transform, false);
                var lineMaterial = CreateMaterial(
                    side == HandSide.Left
                        ? new Color(leftColor.r, leftColor.g, leftColor.b, 0.75f)
                        : new Color(rightColor.r, rightColor.g, rightColor.b, 0.75f));
                foreach (var chain in Chains)
                {
                    var lineObject = new GameObject("Chain");
                    lineObject.transform.SetParent(root.transform, false);
                    var line = lineObject.AddComponent<LineRenderer>();
                    line.useWorldSpace = true;
                    line.positionCount = chain.Length;
                    line.startWidth = lineWidth;
                    line.endWidth = lineWidth * 0.7f;
                    line.numCapVertices = 2;
                    line.sharedMaterial = lineMaterial;
                    line.enabled = false;
                    visual.Lines.Add(line);
                }
                // 兜底位置指示球
                var marker = GameObject.CreatePrimitive(PrimitiveType.Sphere);
                marker.name = "FallbackMarker";
                marker.transform.SetParent(root.transform, false);
                marker.transform.localScale = Vector3.one * 0.035f;
                var collider = marker.GetComponent<Collider>();
                if (collider != null)
                {
                    Destroy(collider);
                }
                visual.FallbackRenderer = marker.GetComponent<Renderer>();
                if (visual.FallbackRenderer != null)
                {
                    visual.FallbackRenderer.sharedMaterial = visual.JointMaterial;
                }
                visual.FallbackMarker = marker.transform;
                marker.SetActive(false);
                _visuals.Add(visual);
            }
        }

        private void UpdateVisuals()
        {
            if (!visualize)
            {
                return;
            }
            foreach (var visual in _visuals)
            {
                visual.Matrices.Clear();
                var anyChainValid = false;
                for (var i = 0; i < Chains.Length; i++)
                {
                    var chain = Chains[i];
                    var line = visual.Lines[i];
                    var valid = true;
                    for (var j = 0; j < chain.Length; j++)
                    {
                        if (!TryGetJoint(visual.Side, chain[j], out var pose))
                        {
                            valid = false;
                            break;
                        }
                        line.SetPosition(j, pose.position);
                        if (i > 0)
                        {
                            visual.Matrices.Add(Matrix4x4.TRS(pose.position,
                                pose.rotation, Vector3.one * jointSize));
                        }
                    }
                    line.enabled = valid;
                    anyChainValid |= valid;
                }

                // 关节完全拿不到时，至少用 Meta 旧接口的 PointerPose 放一个位置指示球，
                // 保证“手在哪”始终看得见，而不是整条骨架突然消失。
                UpdateFallbackMarker(visual, !anyChainValid);
                if (visual.Matrices.Count > 0)
                {
                    Graphics.DrawMeshInstanced(_sphere, 0, visual.JointMaterial,
                        visual.Matrices.ToArray(), visual.Matrices.Count);
                }
            }
        }

        private void UpdateFallbackMarker(HandVisual visual, bool allowed)
        {
            if (visual.FallbackMarker == null)
            {
                return;
            }
            var hand = visual.Side == HandSide.Left ? _leftOvrHand : _rightOvrHand;
            var valid = false;
            var position = Vector3.zero;
            if (allowed && hand != null && hand.IsDataValid && hand.IsPointerPoseValid)
            {
                position = hand.PointerPose.position;
                // 旧接口退化时会返回 (0,0,0)，这种点不显示，免得球飞到世界原点。
                valid = position.sqrMagnitude > 0.01f;
            }
            if (visual.FallbackMarker.gameObject.activeSelf != valid)
            {
                visual.FallbackMarker.gameObject.SetActive(valid);
            }
            if (valid)
            {
                visual.FallbackMarker.position = position;
            }
        }

        private void LogDiagnostics()
        {
            var left = GetHand(HandSide.Left);
            var right = GetHand(HandSide.Right);
            Debug.Log($"[QiyuHand] sub={_lastSubsystemId} " +
                      $"running={_subsystem != null && _subsystem.running} " +
                      $"L(tracked={left.isTracked} joints={CountValidJoints(HandSide.Left)} " +
                      $"idx={Format(HandSide.Left, XRHandJointID.IndexTip)} " +
                      $"pinch={PinchDistance(HandSide.Left):F3}) " +
                      $"R(tracked={right.isTracked} joints={CountValidJoints(HandSide.Right)} " +
                      $"idx={Format(HandSide.Right, XRHandJointID.IndexTip)} " +
                      $"pinch={PinchDistance(HandSide.Right):F3}) " +
                      $"connected={OVRInput.GetConnectedControllers()}");
        }

        private string Format(HandSide side, XRHandJointID id)
        {
            return TryGetJoint(side, id, out var pose)
                ? $"({pose.position.x:F2},{pose.position.y:F2},{pose.position.z:F2})"
                : "-";
        }

        private static Mesh BuildSphere()
        {
            var mesh = new Mesh { name = "QiyuHandJoint" };
            const int segments = 8;
            const int rings = 6;
            var vertices = new List<Vector3>();
            var triangles = new List<int>();
            for (var ring = 0; ring <= rings; ring++)
            {
                var v = ring / (float)rings;
                var phi = v * Mathf.PI;
                for (var segment = 0; segment <= segments; segment++)
                {
                    var u = segment / (float)segments;
                    var theta = u * Mathf.PI * 2f;
                    vertices.Add(new Vector3(
                        Mathf.Sin(phi) * Mathf.Cos(theta),
                        Mathf.Cos(phi),
                        Mathf.Sin(phi) * Mathf.Sin(theta)) * 0.5f);
                }
            }
            for (var ring = 0; ring < rings; ring++)
            {
                for (var segment = 0; segment < segments; segment++)
                {
                    var current = ring * (segments + 1) + segment;
                    var next = current + segments + 1;
                    triangles.Add(current);
                    triangles.Add(next);
                    triangles.Add(current + 1);
                    triangles.Add(current + 1);
                    triangles.Add(next);
                    triangles.Add(next + 1);
                }
            }
            mesh.SetVertices(vertices);
            mesh.SetTriangles(triangles, 0);
            mesh.RecalculateNormals();
            mesh.RecalculateBounds();
            return mesh;
        }

        private static Material CreateMaterial(Color color)
        {
            var shader = Shader.Find("Universal Render Pipeline/Unlit")
                         ?? Shader.Find("Unlit/Color")
                         ?? Shader.Find("Sprites/Default");
            var material = new Material(shader) { enableInstancing = true };
            if (material.HasProperty("_BaseColor"))
            {
                material.SetColor("_BaseColor", color);
            }
            if (material.HasProperty("_Color"))
            {
                material.SetColor("_Color", color);
            }
            if (material.HasProperty("_Surface"))
            {
                material.SetFloat("_Surface", 1f);
            }
            material.EnableKeyword("_SURFACE_TYPE_TRANSPARENT");
            material.SetOverrideTag("RenderType", "Transparent");
            material.SetInt("_SrcBlend", (int)UnityEngine.Rendering.BlendMode.SrcAlpha);
            material.SetInt("_DstBlend",
                (int)UnityEngine.Rendering.BlendMode.OneMinusSrcAlpha);
            material.SetInt("_ZWrite", 0);
            material.renderQueue = (int)UnityEngine.Rendering.RenderQueue.Transparent;
            return material;
        }
    }
}
