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
        // 0.25 的腐蚀半径会沿 12.5m 墙周长吃掉约 3m²，小房间里角色会“没路可走”。
        // 角色是虚拟形象，0.16 足够避免明显穿模，同时能走到人去得了的位置。
        [SerializeField] private float agentRadius = 0.16f;
        [SerializeField] private float agentHeight = 1.5f;
        [SerializeField] private float agentClimb = 0.3f;
        [SerializeField] private float agentSlope = 45f;

        [Header("用户足迹覆盖率自检")]
        [SerializeField] private bool trackUserCoverage = true;
        [SerializeField] private float userSampleInterval = 1.5f;
        [SerializeField] private int userSampleLogEvery = 10;

        private NavMeshData _navMeshData;
        private NavMeshDataInstance _instance;
        private float _floorY;
        private int _userSamples;
        private int _userOnMeshSamples;
        private float _nextUserSampleAt;

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

        /// <summary>
        /// 用户足迹覆盖率：用户实际站过/走过的位置有多少落在 NavMesh 上。
        /// 这是判断“人能走的地方角色能不能走”最直接的指标——比几何推导可靠。
        /// </summary>
        private void Update()
        {
            if (!trackUserCoverage || !Generated)
            {
                return;
            }
            if (Time.unscaledTime < _nextUserSampleAt)
            {
                return;
            }
            _nextUserSampleAt = Time.unscaledTime + Mathf.Max(0.25f, userSampleInterval);
            var camera = Camera.main;
            if (camera == null)
            {
                return;
            }
            var p = camera.transform.position;
            p.y = _floorY + 0.05f;
            _userSamples++;
            var onMesh = NavMesh.SamplePosition(p, out _, 0.6f, NavMesh.AllAreas);
            if (onMesh)
            {
                _userOnMeshSamples++;
            }
            if (userSampleLogEvery > 0 && _userSamples % userSampleLogEvery == 0)
            {
                var percent = 100f * _userOnMeshSamples / Mathf.Max(1, _userSamples);
                Debug.Log(
                    $"[QuestNavMesh] 用户足迹覆盖 {_userOnMeshSamples}/{_userSamples} " +
                    $"({percent:F0}%) 当前位置 onMesh={onMesh}");
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
            Bounds = room.GetRoomBounds();
            var roomBounds = Bounds;
            _floorY = room.FloorAnchors != null && room.FloorAnchors.Count > 0 &&
                      room.FloorAnchors[0] != null
                ? room.FloorAnchors[0].transform.position.y
                : roomBounds.min.y;
            var sources = new List<NavMeshBuildSource>();
            var walkableCount = 0;
            var obstacleCount = 0;
            var skippedCount = 0;
            foreach (var anchor in room.Anchors)
            {
                var kind = AddAnchorSources(anchor, sources, roomBounds);
                if (kind == 1)
                {
                    walkableCount++;
                }
                else if (kind == 2)
                {
                    obstacleCount++;
                }
                else
                {
                    skippedCount++;
                }
            }
            Debug.Log(
                $"[QuestNavMesh] 锚点统计 walkable={walkableCount} " +
                $"obstacle={obstacleCount} skipped={skippedCount} " +
                $"room={roomBounds.size.x:F2}×{roomBounds.size.y:F2}×" +
                $"{roomBounds.size.z:F2}m 平面≈" +
                $"{roomBounds.size.x * roomBounds.size.z:F2}m²");
            AddRoomFloorFallback(room, sources);
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
            LogWalkableMap();
            LogReachability();
            // 角色对象通常在房间加载之后才创建，延迟再自检一次以拿到真实角色位置。
            CancelInvoke(nameof(LogReachability));
            Invoke(nameof(LogReachability), 6f);
            CancelInvoke(nameof(TryPlaceAvatarOnNavMesh));
            Invoke(nameof(TryPlaceAvatarOnNavMesh), 6f);
            if (WalkableAreaM2 < 2f)
            {
                Debug.LogWarning(
                    $"[QuestNavMesh] 警告：可行走面积仅 {WalkableAreaM2:F2}m²，" +
                    "角色将以原地行为为主（不允许穿家具），请在大房间复测。");
            }
        }

        /// <summary>
        /// 把可行走区域打成 ASCII 图，用于在真机上判断 NavMesh 是否被家具/
        /// 容器几何错误吞掉。横轴=世界 X，纵轴=世界 Z，'+Z'朝上打印。
        /// </summary>
        private void LogWalkableMap()
        {
            var b = Bounds;
            const int nx = 18;
            const int nz = 15;
            var sb = new System.Text.StringBuilder();
            sb.Append(
                $"[QuestNavMesh] 可行走图 X∈[{b.min.x:F2},{b.max.x:F2}] " +
                $"Z∈[{b.min.z:F2},{b.max.z:F2}] floorY={_floorY:F2}\n");
            var walkableCells = 0;
            var sampleY = _floorY + 0.03f;
            for (var iz = nz - 1; iz >= 0; iz--)
            {
                sb.Append("  ");
                for (var ix = 0; ix < nx; ix++)
                {
                    var p = new Vector3(
                        b.min.x + (ix + 0.5f) * b.size.x / nx,
                        sampleY,
                        b.min.z + (iz + 0.5f) * b.size.z / nz);
                    if (NavMesh.SamplePosition(p, out var hit, 0.2f, NavMesh.AllAreas))
                    {
                        sb.Append('#');
                        walkableCells++;
                    }
                    else
                    {
                        sb.Append('.');
                    }
                }
                sb.Append('\n');
            }
            var total = nx * nz;
            sb.Append(
                $"  可走格={walkableCells}/{total} " +
                $"≈{walkableCells * b.size.x * b.size.z / total:F2}m²");
            Debug.Log(sb.ToString());
        }

        /// <summary>
        /// MRUK Floor PlaneRect 在部分房间扫描结果中只覆盖局部区域。
        /// 用真实 room bounds 生成一块薄地板兜底，家具/墙仍作为障碍。
        /// </summary>
        private static void AddRoomFloorFallback(MRUKRoom room,
                                                 List<NavMeshBuildSource> sources)
        {
            if (room == null)
            {
                return;
            }
            var bounds = room.GetRoomBounds();
            if (bounds.size.x <= 0.1f || bounds.size.z <= 0.1f)
            {
                return;
            }
            var floorY = bounds.min.y;
            if (room.FloorAnchors != null && room.FloorAnchors.Count > 0 &&
                room.FloorAnchors[0] != null)
            {
                floorY = room.FloorAnchors[0].transform.position.y;
            }
            sources.Add(new NavMeshBuildSource
            {
                shape = NavMeshBuildSourceShape.Box,
                size = new Vector3(bounds.size.x, 0.04f, bounds.size.z),
                transform = Matrix4x4.TRS(
                    new Vector3(bounds.center.x, floorY - 0.02f, bounds.center.z),
                    Quaternion.identity,
                    Vector3.one),
                area = 0
            });
            Debug.Log(
                $"[QuestNavMesh] 地面兜底 bounds={bounds.size.x:F2}×" +
                $"{bounds.size.z:F2}m floorY={floorY:F2}");
        }

        /// <summary>
        /// 返回 0=跳过，1=可行走面，2=障碍体。
        /// </summary>
        private static int AddAnchorSources(MRUKAnchor anchor,
                                            List<NavMeshBuildSource> sources,
                                            Bounds roomBounds)
        {
            if (anchor == null)
            {
                return 0;
            }
            var label = anchor.Label.ToString().ToUpperInvariant();
            var walkable = label.Contains("FLOOR");
            // GLOBAL_MESH 是整个房间的网格容器，ROOM/UNKNOWN/CEILING 也不是
            // 地面障碍；把它们当障碍会直接吞掉全部可行走区域。
            // 其余语义锚点（WALL/BED/TABLE/COUCH/STORAGE/...)一律视为障碍：
            // 白名单漏标签会让角色穿床穿柜，黑名单才是安全方向。
            var container =
                label.Contains("GLOBAL_MESH") || label.Contains("ROOM") ||
                label.Contains("UNKNOWN") || label.Contains("CEILING");
            if (container)
            {
                Debug.Log($"[QuestNavMesh] 跳过锚点 label={label}（容器/非地面几何）");
                return 0;
            }
            var area = walkable ? 0 : 1;

            Vector3 size;
            Matrix4x4 trs;
            string kind;
            if (anchor.VolumeBounds.HasValue && anchor.VolumeBounds.Value.size.sqrMagnitude >= 0.0001f)
            {
                var local = anchor.VolumeBounds.Value;
                size = local.size;
                trs = Matrix4x4.TRS(
                    anchor.transform.TransformPoint(local.center),
                    anchor.transform.rotation,
                    Vector3.one);
                kind = "Volume";
            }
            else if (anchor.PlaneRect.HasValue)
            {
                var rect = anchor.PlaneRect.Value;
                var thickness = walkable ? 0.04f : 0.06f;
                // MRUK PlaneRect 的 X/Y 是锚点本地平面坐标，本地 Z 是平面法线。
                // Floor/Wall 必须使用同一构造方式；把厚度沿本地 Z 偏移，
                // 不能把 floor 误当成已经转好的世界 XZ 平面。
                size = new Vector3(rect.width, rect.height, thickness);
                var center = anchor.transform.TransformPoint(
                    new Vector3(rect.center.x, rect.center.y, -thickness * 0.5f));
                trs = Matrix4x4.TRS(center, anchor.transform.rotation, Vector3.one);
                kind = "Plane";
            }
            else
            {
                Debug.Log($"[QuestNavMesh] 跳过锚点 label={label}（无几何）");
                return 0;
            }

            var worldSize = RotatedBoxWorldSize(size, anchor.transform.rotation);
            var worldCenter = trs.GetColumn(3);
            var bottomY = worldCenter.y - worldSize.y * 0.5f;
            var footprint = worldSize.x * worldSize.z;
            var roomFootprint = Mathf.Max(0.01f, roomBounds.size.x * roomBounds.size.z);
            // 容器型几何（整房网格/包围盒）会把可行走区整块吞掉，直接排除。
            if (!walkable && footprint > roomFootprint * 0.6f)
            {
                Debug.Log(
                    $"[QuestNavMesh] 跳过容器几何 label={label} kind={kind} " +
                    $"worldSize=({worldSize.x:F2},{worldSize.y:F2},{worldSize.z:F2}) " +
                    $"footprint={footprint:F2}m²/{roomFootprint:F2}m²");
                return 0;
            }

            // 挂画/台灯/窗框这类悬空物不阻挡行走，只有伸进膝高以下的空间才挡路。
            if (!walkable && bottomY > roomBounds.min.y + 0.45f)
            {
                Debug.Log(
                    $"[QuestNavMesh] 悬空锚点不挡路 label={label} " +
                    $"bottomY={bottomY:F2} baseY={roomBounds.min.y:F2}");
                return 0;
            }
            Debug.Log(
                $"[QuestNavMesh] 锚点 label={label} kind={kind} " +
                $"localSize=({size.x:F2},{size.y:F2},{size.z:F2}) " +
                $"worldSize=({worldSize.x:F2},{worldSize.y:F2},{worldSize.z:F2}) " +
                $"bottomY={bottomY:F2} footprint={footprint:F2}m² area={area}");
            sources.Add(new NavMeshBuildSource
            {
                shape = NavMeshBuildSourceShape.Box,
                size = size,
                transform = trs,
                area = area
            });
            return walkable ? 1 : 2;
        }

        /// <summary>
        /// 旋转盒在世界坐标下的 AABB 尺寸（用于识别包住整个房间的容器几何）。
        /// </summary>
        private static Vector3 RotatedBoxWorldSize(Vector3 localSize, Quaternion rotation)
        {
            var m = Matrix4x4.Rotate(rotation);
            return new Vector3(
                Mathf.Abs(m.m00) * localSize.x + Mathf.Abs(m.m01) * localSize.y +
                Mathf.Abs(m.m02) * localSize.z,
                Mathf.Abs(m.m10) * localSize.x + Mathf.Abs(m.m11) * localSize.y +
                Mathf.Abs(m.m12) * localSize.z,
                Mathf.Abs(m.m20) * localSize.x + Mathf.Abs(m.m21) * localSize.y +
                Mathf.Abs(m.m22) * localSize.z);
        }

        /// <summary>
        /// 角色出生点常常不在 NavMesh 上（房间很小时尤其明显）。优先放到用户
        /// 前方，否则吸附到最近可行走点；实在没有空间就保持原地行为。
        /// 这是正常运行时步骤，不是兜底 mock：放不进去会明确打警告。
        /// </summary>
        private void TryPlaceAvatarOnNavMesh()
        {
            var avatar = GameObject.Find("QiyuAvatar");
            if (avatar == null)
            {
                return;
            }
            var agent = avatar.GetComponent<UnityEngine.AI.NavMeshAgent>();
            if (agent == null || !agent.enabled || agent.isOnNavMesh)
            {
                return;
            }
            var camera = Camera.main;
            if (camera != null)
            {
                var head = camera.transform.position;
                var flat = head - avatar.transform.position;
                flat.y = 0f;
                if (flat.sqrMagnitude > 0.01f)
                {
                    flat = flat.normalized;
                    var p = new Vector3(head.x, _floorY, head.z) + flat * 1.35f;
                    if (NavMesh.SamplePosition(p, out var userSide, 0.8f, NavMesh.AllAreas))
                    {
                        agent.Warp(userSide.position);
                        Debug.Log(
                            "[QuestNavMesh] 角色已放到用户前方 " +
                            $"dist={Vector3.Distance(avatar.transform.position, head):F2}m");
                        return;
                    }
                }
            }
            if (NavMesh.SamplePosition(avatar.transform.position, out var hit, 4f,
                    NavMesh.AllAreas))
            {
                var moved = Vector3.Distance(avatar.transform.position, hit.position);
                agent.Warp(hit.position);
                Debug.Log($"[QuestNavMesh] 角色已吸附到最近可行走点 距离={moved:F2}m");
                return;
            }
            Debug.LogWarning(
                "[QuestNavMesh] 角色 4m 内没有可行走点：保持原地行为" +
                "（仅视线/手势/说话，不尝试穿家具移动）");
        }

        /// <summary>
        /// 真机可达性自检：用户位置、角色位置、房间中心/四角到 NavMesh 的距离，
        /// 以及从角色出发到这些点能否真正寻路。给验收报告提供真实设备证据。
        /// </summary>
        private void LogReachability()
        {
            var b = Bounds;
            var probes = new List<KeyValuePair<string, Vector3>>
            {
                new KeyValuePair<string, Vector3>("center", b.center),
                new KeyValuePair<string, Vector3>(
                    "corner_min", new Vector3(b.min.x + 0.2f, b.center.y, b.min.z + 0.2f)),
                new KeyValuePair<string, Vector3>(
                    "corner_max", new Vector3(b.max.x - 0.2f, b.center.y, b.max.z - 0.2f)),
                new KeyValuePair<string, Vector3>(
                    "corner_xz", new Vector3(b.max.x - 0.2f, b.center.y, b.min.z + 0.2f)),
                new KeyValuePair<string, Vector3>(
                    "corner_zx", new Vector3(b.min.x + 0.2f, b.center.y, b.max.z - 0.2f))
            };
            var cam = Camera.main;
            if (cam == null)
            {
                var eyeAnchor = GameObject.Find("CenterEyeAnchor");
                if (eyeAnchor != null)
                {
                    cam = eyeAnchor.GetComponentInChildren<Camera>();
                }
            }
            if (cam != null)
            {
                probes.Add(new KeyValuePair<string, Vector3>(
                    "user_head", cam.transform.position));
            }
            var avatar = GameObject.Find("QiyuAvatar");
            if (avatar != null)
            {
                probes.Add(new KeyValuePair<string, Vector3>(
                    "avatar", avatar.transform.position));
            }

            NavMeshPath path = null;
            var hasStart = false;
            var start = Vector3.zero;
            if (avatar != null && NavMesh.SamplePosition(
                    avatar.transform.position, out var startHit, 3f, NavMesh.AllAreas))
            {
                start = startHit.position;
                hasStart = true;
                path = new NavMeshPath();
            }

            var sb = new System.Text.StringBuilder();
            sb.Append("[QuestNavMesh] 可达性自检 floorY=").Append(_floorY.ToString("F2"));
            foreach (var probe in probes)
            {
                var p = probe.Value;
                p.y = _floorY + 0.05f;
                var onMesh = NavMesh.SamplePosition(p, out var hit, 0.6f, NavMesh.AllAreas);
                var lateral = onMesh
                    ? Vector2.Distance(new Vector2(p.x, p.z),
                        new Vector2(hit.position.x, hit.position.z))
                    : -1f;
                var reach = "n/a";
                if (hasStart && onMesh && path != null)
                {
                    reach = NavMesh.CalculatePath(start, hit.position,
                        NavMesh.AllAreas, path)
                        ? path.status.ToString()
                        : "calc_failed";
                }
                sb.Append('\n').Append("  ").Append(probe.Key)
                    .Append(" onMesh=").Append(onMesh ? "yes" : "no")
                    .Append(" dist=").Append(lateral.ToString("F2")).Append("m")
                    .Append(" pathFromAvatar=").Append(reach);
            }
            Debug.Log(sb.ToString());
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
