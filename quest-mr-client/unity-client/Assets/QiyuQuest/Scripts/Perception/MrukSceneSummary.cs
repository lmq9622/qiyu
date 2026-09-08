using System.Collections.Generic;
using Meta.XR.MRUtilityKit;
using UnityEngine;

namespace Qiyu.Quest.Perception
{
    /// <summary>
    /// 直接复用 MRUK：汇总当前房间语义数量并在 HUD 显示。
    /// 这是 WorldState 聚合的输入源，不自行实现房间理解。
    /// </summary>
    public class MrukSceneSummary : MonoBehaviour
    {
        [SerializeField] private bool showHud = true;
        [SerializeField] private Vector2 hudOrigin = new Vector2(16f, 16f);

        private string _summary = "MRUK 未就绪";
        private MRUKRoom _room;

        public MRUKRoom CurrentRoom => _room;
        public string Summary => _summary;

        public delegate void SummaryChangedHandler(string summary, MRUKRoom room);
        public event SummaryChangedHandler OnSummaryChanged;

        private void Start()
        {
            if (MRUK.Instance == null)
            {
                Debug.LogError("[MrukScene] 场景缺少 MRUK 组件，请按 MRUK 官方流程初始化");
                return;
            }
            if (MRUK.Instance.IsInitialized)
            {
                LoadRoom();
                return;
            }
            MRUK.Instance.SceneLoadedEvent.AddListener(HandleSceneLoaded);
        }

        private void HandleSceneLoaded()
        {
            LoadRoom();
        }

        private void LoadRoom()
        {
            if (MRUK.Instance == null)
            {
                return;
            }
            _room = MRUK.Instance.GetCurrentRoom();
            if (_room == null)
            {
                _summary = "MRUK 已初始化但没有当前房间";
                return;
            }

            var counts = new Dictionary<string, int>();
            foreach (var anchor in _room.Anchors)
            {
                var label = anchor.Label.ToString();
                counts[label] = counts.GetValueOrDefault(label) + 1;
            }

            var bounds = _room.GetRoomBounds();
            var parts = new List<string>
            {
                $"房间: {_room.name}",
                $"语义锚点: {_room.Anchors.Count}",
                $"墙: {_room.WallAnchors.Count}",
                $"地面: {_room.FloorAnchors.Count}",
                $"天花板: {_room.CeilingAnchors.Count}",
                $"房间尺寸: {bounds.size.x:F1} x {bounds.size.y:F1} x {bounds.size.z:F1} m",
                $"座位: {_room.SeatPoses.Count}"
            };
            foreach (var kv in counts)
            {
                if (!kv.Key.Contains("FLOOR") && !kv.Key.Contains("CEILING") &&
                    !kv.Key.Contains("WALL_FACE"))
                {
                    parts.Add($"{kv.Key}: {kv.Value}");
                }
            }
            _summary = string.Join("\n", parts);
            Debug.Log($"[MrukScene]\n{_summary}");
            OnSummaryChanged?.Invoke(_summary, _room);
        }

        private void OnGUI()
        {
            if (!showHud)
            {
                return;
            }
            var style = new GUIStyle(GUI.skin.label)
            {
                fontSize = 18,
                normal = { textColor = Color.white }
            };
            GUI.Label(new Rect(hudOrigin.x, hudOrigin.y, 900f, 420f), _summary, style);
        }

        private void OnDestroy()
        {
            if (MRUK.Instance != null)
            {
                MRUK.Instance.SceneLoadedEvent.RemoveListener(HandleSceneLoaded);
            }
        }
    }
}
