using System.Collections.Generic;
using Meta.XR;
using Meta.XR.BuildingBlocks.AIBlocks;
using Meta.XR.MRUtilityKit;
using Unity.Collections;
using UnityEngine;

namespace Qiyu.Quest.Perception
{
    /// <summary>
    /// 空间重建可视化层。
    ///
    /// 不是自己造空间理解，而是把 Meta 官方能力显式可视化出来：
    ///   * MRUK EffectMesh：房间几何网格（墙/地面/天花板/家具表面）；
    ///   * MRUK Scene API anchors：每个语义锚点（TABLE / BED / STORAGE / DOOR_FRAME…）
    ///     用彩色半透明盒 + 线框显示，位置和尺寸来自 SDK；
    ///   * Environment Depth：从 DepthTextureAccess 的 320x320 深度帧反投影成点云，
    ///     让“几何景深”在头显里可见。
    /// </summary>
    public class QiyuSpatialReconstruction : MonoBehaviour
    {
        [Header("依赖")]
        [SerializeField] private MrukSceneSummary sceneSummary;
        [SerializeField] private EffectMesh effectMesh;
        [SerializeField] private DepthTextureAccess depthAccess;
        [SerializeField] private PassthroughCameraAccess cameraAccess;

        [Header("显示")]
        [SerializeField] private bool showRoomMesh = true;
        [SerializeField] private bool showAnchors = true;
        [SerializeField] private bool showDepthCloud = false;
        [SerializeField] private int depthSampleStep = 10;
        [SerializeField] private float depthPointSize = 0.008f;
        [SerializeField] private float depthMaxDistance = 8f;

        private readonly List<GameObject> _anchorVisuals = new List<GameObject>();
        private readonly Dictionary<Color, Material> _materials = new Dictionary<Color, Material>();
        private readonly Dictionary<Color, Material> _lineMaterials = new Dictionary<Color, Material>();
        private Transform _root;
        private Transform _cameraTransform;
        private Mesh _quadMesh;
        private Material _pointMaterial;
        private Matrix4x4[] _pointMatrices;
        private int _pointCount;
        private float _nextDepthBuildAt;
        private int _depthFrameCount;
        private bool _depthAvailable;

        public bool ShowRoomMesh
        {
            get => showRoomMesh;
            set
            {
                showRoomMesh = value;
                ApplyVisibility();
            }
        }

        public bool ShowAnchors
        {
            get => showAnchors;
            set
            {
                showAnchors = value;
                ApplyVisibility();
            }
        }

        public bool ShowDepthCloud
        {
            get => showDepthCloud;
            set
            {
                showDepthCloud = value;
                ApplyVisibility();
            }
        }

        public int AnchorCount { get; private set; }
        public int SemanticObjectCount { get; private set; }
        public int PointCount => _pointCount;
        public bool DepthAvailable => _depthAvailable;
        public int DepthFrameCount => _depthFrameCount;

        private void Awake()
        {
            _root = new GameObject("QiyuReconstructionRoot").transform;
            _root.SetParent(transform, false);
            // Graphics.DrawMeshInstanced 单次上限 1023。
            _pointMatrices = new Matrix4x4[1023];
            CreatePointResources();
        }

        private void OnEnable()
        {
            if (sceneSummary != null)
            {
                sceneSummary.OnSummaryChanged += HandleRoomChanged;
            }
            if (depthAccess != null)
            {
                depthAccess.OnDepthTextureUpdateCPU += HandleDepthFrame;
            }
        }

        private void Start()
        {
            var centerEye = GameObject.Find("CenterEyeAnchor");
            _cameraTransform = centerEye != null ? centerEye.transform : Camera.main?.transform;
            if (sceneSummary != null && sceneSummary.CurrentRoom != null)
            {
                RebuildAnchors(sceneSummary.CurrentRoom);
            }
            ApplyVisibility();
        }

        private void OnDisable()
        {
            if (sceneSummary != null)
            {
                sceneSummary.OnSummaryChanged -= HandleRoomChanged;
            }
            if (depthAccess != null)
            {
                depthAccess.OnDepthTextureUpdateCPU -= HandleDepthFrame;
            }
        }

        private void LateUpdate()
        {
            if (!showDepthCloud || _pointCount <= 0 || _quadMesh == null || _pointMaterial == null)
            {
                return;
            }
            Graphics.DrawMeshInstanced(_quadMesh, 0, _pointMaterial, _pointMatrices,
                _pointCount);
        }

        private void HandleRoomChanged(string summary, MRUKRoom room)
        {
            RebuildAnchors(room);
            ApplyVisibility();
        }

        public void ApplyVisibility()
        {
            if (effectMesh != null)
            {
                effectMesh.HideMesh = !showRoomMesh;
                effectMesh.ToggleEffectMeshVisibility(showRoomMesh);
            }
            foreach (var visual in _anchorVisuals)
            {
                if (visual != null)
                {
                    visual.SetActive(showAnchors);
                }
            }
        }

        private void RebuildAnchors(MRUKRoom room)
        {
            foreach (var visual in _anchorVisuals)
            {
                if (visual != null)
                {
                    Destroy(visual);
                }
            }
            _anchorVisuals.Clear();
            AnchorCount = 0;
            SemanticObjectCount = 0;
            if (room == null)
            {
                return;
            }

            foreach (var anchor in room.Anchors)
            {
                if (anchor == null)
                {
                    continue;
                }
                var label = anchor.Label.ToString().ToUpperInvariant();
                if (label.Contains("GLOBAL_MESH"))
                {
                    continue;
                }
                if (!TryGetAnchorBounds(anchor, out var center, out var size, out var rotation))
                {
                    continue;
                }
                var color = LabelColor(anchor.Label);
                var visual = new GameObject("Anchor_" + anchor.Label);
                visual.transform.SetParent(_root, false);
                visual.transform.SetPositionAndRotation(center, rotation);
                visual.transform.localScale = size;

                var filter = visual.AddComponent<MeshFilter>();
                filter.sharedMesh = GetCubeMesh();
                var renderer = visual.AddComponent<MeshRenderer>();
                renderer.sharedMaterial = GetMaterial(color);
                _anchorVisuals.Add(visual);

                CreateWireframe(center, size, rotation, color);
                AnchorCount++;
                if (!label.Contains("WALL") && !label.Contains("FLOOR") &&
                    !label.Contains("CEILING"))
                {
                    SemanticObjectCount++;
                }
            }
            ApplyVisibility();
            Debug.Log($"[QiyuReconstruction] anchors={AnchorCount} " +
                      $"semanticObjects={SemanticObjectCount} room={room.name}");
        }

        private static bool TryGetAnchorBounds(MRUKAnchor anchor, out Vector3 center,
                                               out Vector3 size, out Quaternion rotation)
        {
            center = Vector3.zero;
            size = Vector3.one;
            rotation = anchor.transform.rotation;
            if (anchor.VolumeBounds.HasValue)
            {
                var bounds = anchor.VolumeBounds.Value;
                center = anchor.transform.TransformPoint(bounds.center);
                size = bounds.size;
                return size.sqrMagnitude > 0.0001f;
            }
            if (anchor.PlaneRect.HasValue)
            {
                var rect = anchor.PlaneRect.Value;
                center = anchor.transform.TransformPoint(
                    new Vector3(rect.center.x, rect.center.y, 0f));
                size = new Vector3(rect.width, rect.height, 0.04f);
                return size.sqrMagnitude > 0.0001f;
            }
            return false;
        }

        private void CreateWireframe(Vector3 center, Vector3 size, Quaternion rotation,
                                     Color color)
        {
            var lineObject = new GameObject("Wireframe");
            lineObject.transform.SetParent(_root, false);
            var line = lineObject.AddComponent<LineRenderer>();
            line.useWorldSpace = true;
            line.positionCount = 24;
            line.startWidth = 0.008f;
            line.endWidth = 0.008f;
            line.loop = false;
            line.sharedMaterial = GetLineMaterial(color);

            var extents = size * 0.5f;
            var corners = new Vector3[8];
            var index = 0;
            for (var sx = -1; sx <= 1; sx += 2)
            {
                for (var sy = -1; sy <= 1; sy += 2)
                {
                    for (var sz = -1; sz <= 1; sz += 2)
                    {
                        corners[index++] = center + rotation * Vector3.Scale(extents,
                            new Vector3(sx, sy, sz));
                    }
                }
            }
            var edges = new[]
            {
                0, 1, 1, 3, 3, 2, 2, 0,
                4, 5, 5, 7, 7, 6, 6, 4,
                0, 4, 1, 5, 2, 6, 3, 7
            };
            for (var i = 0; i < edges.Length; i++)
            {
                line.SetPosition(i, corners[edges[i]]);
            }
            _anchorVisuals.Add(lineObject);
        }

        private void HandleDepthFrame(DepthTextureAccess.DepthFrameData frame)
        {
            _depthAvailable = true;
            _depthFrameCount++;
            if (!showDepthCloud || cameraAccess == null ||
                Time.unscaledTime < _nextDepthBuildAt)
            {
                return;
            }
            _nextDepthBuildAt = Time.unscaledTime + 0.1f; // 10 Hz 足够看清几何
            var texSize = depthAccess != null ? depthAccess.TextureSize : 320;
            if (!frame.DepthTexturePixels.IsCreated || texSize <= 0)
            {
                return;
            }
            var step = Mathf.Clamp(depthSampleStep, 2, 32);
            var count = 0;
            var maxPoints = _pointMatrices.Length;
            for (var y = 0; y < texSize && count < maxPoints; y += step)
            {
                for (var x = 0; x < texSize && count < maxPoints; x += step)
                {
                    var index = y * texSize + x;
                    if (index < 0 || index >= frame.DepthTexturePixels.Length)
                    {
                        continue;
                    }
                    var depth = frame.DepthTexturePixels[index];
                    if (depth <= 0.15f || depth > depthMaxDistance ||
                        float.IsInfinity(depth) || float.IsNaN(depth))
                    {
                        continue;
                    }
                    var u = (x + 0.5f) / texSize;
                    var v = 1f - (y + 0.5f) / texSize;
                    var ray = cameraAccess.ViewportPointToRay(new Vector2(u, v),
                        frame.CameraPose);
                    var world = ray.origin + ray.direction * depth;
                    var cameraPosition = _cameraTransform != null
                        ? _cameraTransform.position
                        : frame.CameraPose.position;
                    var rotation = Quaternion.LookRotation(world - cameraPosition);
                    _pointMatrices[count++] = Matrix4x4.TRS(world, rotation,
                        Vector3.one * depthPointSize);
                }
            }
            _pointCount = count;
        }

        private void CreatePointResources()
        {
            _quadMesh = new Mesh { name = "QiyuDepthPointQuad" };
            _quadMesh.vertices = new[]
            {
                new Vector3(-0.5f, -0.5f, 0f),
                new Vector3(0.5f, -0.5f, 0f),
                new Vector3(0.5f, 0.5f, 0f),
                new Vector3(-0.5f, 0.5f, 0f)
            };
            _quadMesh.uv = new[]
            {
                new Vector2(0f, 0f), new Vector2(1f, 0f),
                new Vector2(1f, 1f), new Vector2(0f, 1f)
            };
            _quadMesh.triangles = new[] { 0, 1, 2, 0, 2, 3 };
            _quadMesh.RecalculateNormals();

            var shader = Shader.Find("Universal Render Pipeline/Unlit")
                         ?? Shader.Find("Unlit/Color")
                         ?? Shader.Find("Sprites/Default");
            _pointMaterial = CreateMaterial(shader, "QiyuDepthPoint",
                new Color(0.35f, 0.95f, 1f, 0.72f));
            if (_pointMaterial != null)
            {
                _pointMaterial.enableInstancing = true;
            }
        }

        private static Mesh _cubeMesh;

        private static Mesh GetCubeMesh()
        {
            if (_cubeMesh != null)
            {
                return _cubeMesh;
            }
            var temp = GameObject.CreatePrimitive(PrimitiveType.Cube);
            _cubeMesh = temp.GetComponent<MeshFilter>().sharedMesh;
            Object.Destroy(temp);
            return _cubeMesh;
        }

        private Material GetMaterial(Color color)
        {
            if (_materials.TryGetValue(color, out var material) && material != null)
            {
                return material;
            }
            var shader = Shader.Find("Universal Render Pipeline/Unlit")
                         ?? Shader.Find("Unlit/Color")
                         ?? Shader.Find("Sprites/Default");
            material = CreateMaterial(shader, "QiyuAnchor_" + ColorUtility.ToHtmlStringRGB(color),
                new Color(color.r, color.g, color.b, 0.18f));
            _materials[color] = material;
            return material;
        }

        private Material GetLineMaterial(Color color)
        {
            if (_lineMaterials.TryGetValue(color, out var material) && material != null)
            {
                return material;
            }
            var shader = Shader.Find("Universal Render Pipeline/Unlit")
                         ?? Shader.Find("Unlit/Color")
                         ?? Shader.Find("Sprites/Default");
            material = CreateMaterial(shader, "QiyuAnchorLine_" + ColorUtility.ToHtmlStringRGB(color),
                new Color(color.r, color.g, color.b, 0.9f));
            _lineMaterials[color] = material;
            return material;
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
            if (material.HasProperty("_Surface"))
            {
                material.SetFloat("_Surface", 1f);
            }
            if (material.HasProperty("_Blend"))
            {
                material.SetFloat("_Blend", 0f);
            }
            if (material.HasProperty("_ZWrite"))
            {
                material.SetFloat("_ZWrite", 0f);
            }
            material.renderQueue = 3000;
            return material;
        }

        private static Color LabelColor(MRUKAnchor.SceneLabels label)
        {
            var text = label.ToString().ToUpperInvariant();
            if (text.Contains("WALL")) return new Color(0.20f, 0.72f, 1f);
            if (text.Contains("FLOOR")) return new Color(0.19f, 0.82f, 0.35f);
            if (text.Contains("CEILING")) return new Color(0.35f, 0.85f, 1f);
            if (text.Contains("TABLE")) return new Color(1f, 0.62f, 0.04f);
            if (text.Contains("CHAIR") || text.Contains("COUCH"))
                return new Color(1f, 0.84f, 0.04f);
            if (text.Contains("BED")) return new Color(0.75f, 0.35f, 0.95f);
            if (text.Contains("STORAGE")) return new Color(1f, 0.22f, 0.37f);
            if (text.Contains("DOOR") || text.Contains("WINDOW"))
                return new Color(0.95f, 0.95f, 1f);
            return new Color(0.65f, 0.65f, 0.75f);
        }
    }
}
