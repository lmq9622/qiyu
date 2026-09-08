using System.Collections.Generic;
using Meta.XR.MRUtilityKit;
using UnityEngine;

namespace Qiyu.Quest.Perception
{
    /// <summary>
    /// 直接复用 MRUK：显示当前房间语义数量并暴露统计事件。
    /// 这是 P1 WorldState 聚合的输入源，不自行实现房间理解。
    /// </summary>
    public class MrukSceneSummary : MonoBehaviour
    {
        private bool _started;
        private string _summary = "MRUK 未就绪";
        private MRUKRoom _room;

        public MRUKRoom CurrentRoom => _room;

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

            var parts = new List<string>
            {
                $"房间={_room.name}",
                $"语义锚点={_room.Anchors.Count}",
                $"墙={_room.WallAnchors.Count}",
                $"地面={( _room.FloorAnchor != null ? 1 : 0)}",
                $"天花板={( _room.CeilingAnchor != null ? 1 : 0)}",
                $"座位={_room.SeatPoses.Count}"
            };
            foreach (var kv in counts)
            {
                if (!kv.Key.Contains("FLOOR") && !kv.Key.Contains("CEILING") && !kv.Key.Contains("WALL_FACE"))
                {
                    parts.Add($"{kv.Key}={kv.Value}");
                }
            }
            _summary = string.Join("\n", parts);
            Debug.Log($"[MrukScene]\n{_summary}");
            OnSummaryChanged?.Invoke(_summary, _room);
        }

        private void OnGUI()
        {
            GUI.Label(new Rect(16, 16, 800, 420), _summary);
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
