using System.Collections.Generic;
using Meta.XR.MRUtilityKit;
using Qiyu.Quest.Perception;
using UnityEngine;
using UnityEngine.AI;

namespace Qiyu.Quest.Spatial
{
    /// <summary>
    /// 用 MRUK 语义几何在运行时生成 NavMesh。
    ///
    /// 不自己写寻路：Unity AI Navigation（NavMeshAgent/NavMeshBuilder）负责路径与避障。
    /// Floor 锚点作为可行走面；Wall/Table/Chair/Sofa/Storage 等作为障碍体。
    /// </summary>
    public class RoomNavMeshBuilder : MonoBehaviour
    {
        [SerializeField] private MrukSceneSummary sceneSummary;
        [SerializeField] private bool buildOnRoomLoaded = true;

        [Header("Agent 参数")]
        [SerializeField] private float agentRadius = 0.25f;
        [SerializeField] private float agentHeight = 1.6f;
        [SerializeField] private float agentClimb = 0.3f;
        [SerializeField] private float agentSlope = 45f;

        private NavMeshData _navMeshData;
        private NavMeshDataInstance _instance;

        public bool Generated { get; private set; }
        public int Version { get; private set; }
        public float WalkableAreaM2 { get; private set; }
        public Bounds Bounds { get; private set; }

        private void OnEnable()
        {
            if (sceneSummary != null)
            {
                sceneSummary.OnSummaryChanged += HandleRoomChanged;
            }
        }

        private void OnDisable()
        {
            if (sceneSummary != null)
            {
                sceneSummary.OnSummaryChanged -= HandleRoomChanged;
            }
            if (_instance.valid)
            {
                _instance.Remove();
            }
        }

        private void Start()
        {
            if (buildOnRoomLoaded && sceneSummary != null &&
                sceneSummary.CurrentRoom != null)
            {
                Build(sceneSummary.CurrentRoom);
            }
        }

        private void HandleRoomChanged(string summary, MRUKRoom room)
        {
            if (buildOnRoomLoaded)
            {
                Build(room);
            }
        }

        public void Build(MRUKRoom room = null)
        {
            room = room ?? sceneSummary?.CurrentRoom;
            if (room == null)
            {
                Debug.LogWarning("[QuestNavMesh] 当前没有 MRUK 房间，跳过生成");
                return;
            }
            var sources = new List<NavMeshBuildSource>();
            foreach (var anchor in room.Anchors)
            {
                AddAnchorSources(anchor, sources);
            }
            if (sources.Count == 0)
            {
                Debug.LogWarning("[QuestNavMesh] 房间没有可用于 NavMesh 的几何");
                return;
            }

            var settings = NavMesh.GetSettingsByID(0);
            settings.agentRadius = agentRadius;
            settings.agentHeight = agentHeight;
            settings.agentClimb = agentClimb;
            settings.agentSlope = agentSlope;

            Bounds = room.GetRoomBounds();
            var buildBounds = Bounds;
            buildBounds.Expand(new Vector3(4f, 8f, 4f));
            _navMeshData = NavMeshBuilder.BuildNavMeshData(
                settings, sources, buildBounds, transform.position, transform.rotation);
            if (_navMeshData == null)
            {
                Debug.LogError("[QuestNavMesh] NavMeshBuilder 返回空");
                return;
            }
            if (_instance.valid)
            {
                _instance.Remove();
            }
            _instance = NavMesh.AddNavMeshData(_navMeshData);
            Generated = true;
            Version++;
            WalkableAreaM2 = ComputeWalkableArea();
            Debug.Log($"[QuestNavMesh] 生成完成 v{Version} 面积≈{WalkableAreaM2:F2}m²");
        }

        private static void AddAnchorSources(MRUKAnchor anchor, List<NavMeshBuildSource> sources)
        {
            if (anchor == null)
            {
                return;
            }
            var label = anchor.Label.ToString().ToUpperInvariant();
            var walkable = label.Contains("FLOOR");
            var area = walkable ? 0 : 1;

            if (anchor.VolumeBounds.HasValue)
            {
                var local = anchor.VolumeBounds.Value;
                var size = local.size;
                if (size.sqrMagnitude < 0.0001f)
                {
                    return;
                }
                sources.Add(new NavMeshBuildSource
                {
                    shape = NavMeshBuildSourceShape.Box,
                    size = size,
                    transform = Matrix4x4.TRS(
                        anchor.transform.TransformPoint(local.center),
                        anchor.transform.rotation,
                        Vector3.one),
                    area = area
                });
                return;
            }
            if (anchor.PlaneRect.HasValue)
            {
                var rect = anchor.PlaneRect.Value;
                var thickness = walkable ? 0.04f : 0.06f;
                Vector3 size;
                Vector3 center;
                if (walkable)
                {
                    size = new Vector3(rect.width, thickness, rect.height);
                    center = anchor.transform.TransformPoint(
                        new Vector3(rect.center.x, -thickness * 0.5f, rect.center.y));
                }
                else
                {
                    size = new Vector3(rect.width, rect.height, thickness);
                    center = anchor.transform.TransformPoint(
                        new Vector3(rect.center.x, rect.center.y, 0f));
                }
                sources.Add(new NavMeshBuildSource
                {
                    shape = NavMeshBuildSourceShape.Box,
                    size = size,
                    transform = Matrix4x4.TRS(center, anchor.transform.rotation, Vector3.one),
                    area = area
                });
            }
        }

        private static float ComputeWalkableArea()
        {
            var triangulation = NavMesh.CalculateTriangulation();
            var vertices = triangulation.vertices;
            var indices = triangulation.indices;
            var area = 0f;
            for (var i = 0; i + 2 < indices.Length; i += 3)
            {
                var a = vertices[indices[i]];
                var b = vertices[indices[i + 1]];
                var c = vertices[indices[i + 2]];
                area += Vector3.Cross(b - a, c - a).magnitude * 0.5f;
            }
            return area;
        }
    }
}
