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
        [SerializeField] private Color leftColor = new Color(0.42f, 0.84f, 1f, 0.95f);
        [SerializeField] private Color rightColor = new Color(1f, 0.60f, 0.72f, 0.95f);
        [SerializeField] private float jointSize = 0.012f;
        [SerializeField] private float lineWidth = 0.006f;
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
            public bool Visible;
        }

        private readonly List<HandVisual> _visuals = new List<HandVisual>();
        private readonly List<XRHandSubsystem> _subsystems = new List<XRHandSubsystem>();
        private XRHandSubsystem _subsystem;
        private Mesh _sphere;
        private float _nextLogAt;
        private bool _warnedAboutSubsystem;

        public bool IsReady => _subsystem != null && _subsystem.running;

        /// <summary>调试面板用：当前是否拿得到左手/右手关节。</summary>
        public bool IsTracked(HandSide side)
        {
            var hand = GetHand(side);
            return hand.isTracked;
        }

        private void Awake()
        {
            CreateVisuals();
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
            if (!hand.isTracked)
            {
                return false;
            }
            var joint = hand.GetJoint(id);
            return joint.TryGetPose(out pose);
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
            if (_subsystem != null && _subsystem.running)
            {
                return;
            }
            _subsystems.Clear();
            SubsystemManager.GetSubsystems(_subsystems);
            foreach (var candidate in _subsystems)
            {
                if (candidate != null && candidate.running)
                {
                    _subsystem = candidate;
                    Debug.Log("[QiyuHand] 已接入 XRHandSubsystem（OpenXR 手部追踪）");
                    return;
                }
            }
            _subsystem = _subsystems.Count > 0 ? _subsystems[0] : null;
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
                var hand = GetHand(visual.Side);
                var tracked = hand.isTracked;
                if (!tracked)
                {
                    SetVisible(visual, false);
                    continue;
                }

                visual.Matrices.Clear();
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
                }
                SetVisible(visual, true);
                if (visual.Matrices.Count > 0)
                {
                    Graphics.DrawMeshInstanced(_sphere, 0, visual.JointMaterial,
                        visual.Matrices.ToArray(), visual.Matrices.Count);
                }
            }
        }

        private static void SetVisible(HandVisual visual, bool visible)
        {
            if (visual.Visible == visible)
            {
                return;
            }
            visual.Visible = visible;
            foreach (var line in visual.Lines)
            {
                line.enabled = visible && line.positionCount > 1;
            }
        }

        private void LogDiagnostics()
        {
            var left = GetHand(HandSide.Left);
            var right = GetHand(HandSide.Right);
            Debug.Log($"[QiyuHand] subsystem={(_subsystem != null)} " +
                      $"running={_subsystem != null && _subsystem.running} " +
                      $"leftTracked={left.isTracked} rightTracked={right.isTracked} " +
                      $"leftIndex={Format(HandSide.Left, XRHandJointID.IndexTip)} " +
                      $"rightIndex={Format(HandSide.Right, XRHandJointID.IndexTip)} " +
                      $"pinchL={PinchDistance(HandSide.Left):F3} " +
                      $"pinchR={PinchDistance(HandSide.Right):F3}");
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
