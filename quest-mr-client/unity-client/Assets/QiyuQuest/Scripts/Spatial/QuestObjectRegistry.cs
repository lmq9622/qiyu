using System.Collections.Generic;
using UnityEngine;

namespace Qiyu.Quest.Spatial
{
    /// <summary>
    /// P4 视觉检测到的真实物体世界坐标注册表（带 TTL）。
    /// SpatialActionExecutor 通过 target_id 在这里解析目标位置。
    /// </summary>
    public static class QuestObjectRegistry
    {
        private struct Entry
        {
            public Vector3 Position;
            public float UpdatedAt;
            public string Label;
        }

        private static readonly Dictionary<string, Entry> Objects =
            new Dictionary<string, Entry>();

        public static void Set(string id, Vector3 position, string label = "")
        {
            if (string.IsNullOrEmpty(id))
            {
                return;
            }
            Objects[id] = new Entry
            {
                Position = position,
                UpdatedAt = Time.realtimeSinceStartup,
                Label = label ?? ""
            };
        }

        public static bool TryGet(string id, out Vector3 position, out string label)
        {
            position = Vector3.zero;
            label = "";
            if (string.IsNullOrEmpty(id) || !Objects.TryGetValue(id, out var entry))
            {
                return false;
            }
            position = entry.Position;
            label = entry.Label;
            return true;
        }

        public static void Remove(string id)
        {
            if (!string.IsNullOrEmpty(id))
            {
                Objects.Remove(id);
            }
        }

        public static void Prune(float ttlSeconds)
        {
            var now = Time.realtimeSinceStartup;
            var expired = new List<string>();
            foreach (var kv in Objects)
            {
                if (now - kv.Value.UpdatedAt > ttlSeconds)
                {
                    expired.Add(kv.Key);
                }
            }
            foreach (var id in expired)
            {
                Objects.Remove(id);
            }
        }

        public static void Clear()
        {
            Objects.Clear();
        }
    }
}
