using System;
using System.Collections.Generic;
using Newtonsoft.Json;
using UnityEngine;

namespace Qiyu.Quest.Behavior
{
    [Serializable]
    public sealed class MotionDefinition
    {
        public string id;
        public string clip;
        public string behavior;
        public string layer = "Base";
        public bool loop;
        public int priority;
        public float min_duration_s = 0.2f;
        public float max_duration_s = 0f;
        public float blend_s = 0.2f;
        public string interrupt = "on_higher_priority";
        public string[] tags = Array.Empty<string>();
        public bool asset_required = true;
    }

    [Serializable]
    public sealed class MotionLibraryFile
    {
        public string schema_version;
        public string library_version;
        public MotionDefinition[] motions;
    }

    /// <summary>
    /// 可扩展动作库。只描述动作选择/过渡策略，不把动作写死在行为层。
    /// 动画资产缺失时如实报告，并由 ProceduralMotionFallback 做低精度兜底。
    /// </summary>
    public class MotionLibrary : MonoBehaviour
    {
        [SerializeField] private string resourcePath = "Qiyu/motion_library";

        public bool Ready { get; private set; }
        public string LastError { get; private set; } = "";
        public string LibraryVersion { get; private set; } = "";
        public IReadOnlyList<MotionDefinition> Motions => _motions;

        private readonly List<MotionDefinition> _motions = new List<MotionDefinition>();
        private readonly Dictionary<string, MotionDefinition> _byId =
            new Dictionary<string, MotionDefinition>(StringComparer.Ordinal);
        private readonly Dictionary<string, MotionDefinition> _byBehavior =
            new Dictionary<string, MotionDefinition>(StringComparer.Ordinal);

        private void Awake()
        {
            Load();
        }

        public bool Load()
        {
            Ready = false;
            _motions.Clear();
            _byId.Clear();
            _byBehavior.Clear();
            var asset = Resources.Load<TextAsset>(resourcePath);
            if (asset == null)
            {
                LastError = $"Resources/{resourcePath}.json 不存在";
                return false;
            }
            try
            {
                var file = JsonConvert.DeserializeObject<MotionLibraryFile>(asset.text);
                if (file?.motions == null || file.motions.Length == 0)
                {
                    LastError = "动作库为空";
                    return false;
                }
                foreach (var motion in file.motions)
                {
                    if (motion == null || string.IsNullOrEmpty(motion.id))
                    {
                        continue;
                    }
                    _motions.Add(motion);
                    _byId[motion.id] = motion;
                    if (!string.IsNullOrEmpty(motion.behavior) &&
                        !_byBehavior.ContainsKey(motion.behavior))
                    {
                        _byBehavior[motion.behavior] = motion;
                    }
                }
                LibraryVersion = file.library_version ?? "";
                Ready = _motions.Count > 0;
                Debug.Log($"[QiyuMotionLibrary] 已加载 {_motions.Count} 个动作 " +
                          $"{LibraryVersion}");
                return Ready;
            }
            catch (Exception e)
            {
                LastError = $"解析失败: {e.Message}";
                Debug.LogWarning($"[QiyuMotionLibrary] {LastError}");
                return false;
            }
        }

        public MotionDefinition GetById(string id)
        {
            return !string.IsNullOrEmpty(id) && _byId.TryGetValue(id, out var motion)
                ? motion : null;
        }

        public MotionDefinition GetForBehavior(string behavior)
        {
            return !string.IsNullOrEmpty(behavior) &&
                   _byBehavior.TryGetValue(behavior, out var motion)
                ? motion : null;
        }
    }
}
