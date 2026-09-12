using System;
using System.Collections.Generic;
using UnityEngine;

namespace Qiyu.Quest.Avatar
{
    /// <summary>
    /// 表情/口型驱动：把高层 emotion 映射到真实 BlendShape 权重。
    ///
    /// 兼容三类命名：
    /// - VRM 0.x / 1.0（Joy/Happy/Angry/Sorrow/Relaxed/Surprised…）
    /// - MMD 日文形态键（笑い / まばたき / びっくり / 悲しむ / 怒り目 / なごみ…）
    /// - 常见中文/英文自定义命名
    ///
    /// 另外负责两件"本地自然待机"的事（LLM 不该管这种低级行为）：
    /// - 随机间隔眨眼；
    /// - 口型由音频幅度驱动的真实权重变化。
    /// </summary>
    public class BlendShapeAvatarDriver : MonoBehaviour
    {
        [Serializable]
        public struct Binding
        {
            public string emotion;
            public string blendShape;
            [Range(0f, 100f)] public float weight;
        }

        [Header("模型")]
        [SerializeField] private SkinnedMeshRenderer[] renderers;
        [SerializeField] private bool autoCollectRenderers = true;

        [Header("口型")]
        [SerializeField] private string[] mouthBlendShapes =
        {
            "あ", "A", "aa", "Fcl_MTH_A", "Mouth_A", "mouth_a", "jaw_open"
        };
        [SerializeField] private float mouthMaxWeight = 70f;

        [Header("本地眨眼")]
        [SerializeField] private bool idleBlink = true;
        [SerializeField] private float blinkIntervalMin = 2.5f;
        [SerializeField] private float blinkIntervalMax = 6.5f;
        [SerializeField] private float blinkDuration = 0.13f;
        [SerializeField] private float blinkWeight = 90f;

        [Header("手动映射（可选，留空则用内置预设）")]
        [SerializeField] private List<Binding> bindings = new List<Binding>();

        private readonly Dictionary<string, float> _current =
            new Dictionary<string, float>(StringComparer.OrdinalIgnoreCase);
        private readonly Dictionary<string, int> _shapeIndex =
            new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        private readonly Dictionary<string, SkinnedMeshRenderer> _shapeRenderer =
            new Dictionary<string, SkinnedMeshRenderer>(StringComparer.OrdinalIgnoreCase);
        private string _mouthShape = "";
        private string _blinkShape = "";
        private float _mouthAmplitude;
        private float _nextBlinkAt;
        private float _blinkStartedAt = -1f;

        /// <summary>true 时由 Ambient Life 统一驱动眨眼（生理表现独立于行为系统）。</summary>
        public bool ExternalBlinkControl { get; set; }

        public int IndexedShapeCount => _shapeIndex.Count;
        public string MouthShape => _mouthShape;
        public string BlinkShape => _blinkShape;
        /// <summary>上一次 ApplyEmotion 实际命中的形态键（空串表示没命中）。</summary>
        public string LastAppliedShape { get; private set; } = "";

        /// <summary>
        /// 情绪 → 候选形态键（按顺序取第一个存在的）。
        /// 日文名来自 MMD 标准，实测本模型可用：笑い / びっくり / 悲しむ / 怒り目 /
        /// なごみ / じと目 / まばたき。
        /// </summary>
        private static readonly Dictionary<string, string[]> EmotionPresets =
            new Dictionary<string, string[]>(StringComparer.OrdinalIgnoreCase)
            {
                ["neutral"] = new[] { "Neutral", "neutral" },
                ["happy"] = new[] { "Joy", "Happy", "笑い", "にやり", "なごみ" },
                ["laugh"] = new[] { "笑い", "Joy", "Happy" },
                ["calm"] = new[] { "Relaxed", "なごみ" },
                ["sad"] = new[] { "Sorrow", "Sad", "悲しむ", "しょんぼり" },
                ["annoyed"] = new[] { "Angry", "怒り目", "ジト目", "じと目" },
                ["angry"] = new[] { "Angry", "怒り目", "ジト目" },
                ["excited"] = new[] { "Joy", "Happy", "笑い", "びっくり" },
                ["shy"] = new[] { "なごみ", "照れ", "Relaxed", "Blink" },
                ["confused"] = new[] { "はちゅ目", "じと目", "びっくり", "Surprised" },
                ["tired"] = new[] { "ジト目", "じと目", "Sorrow" },
                ["surprised"] = new[] { "びっくり", "Surprised" },
                ["curious"] = new[] { "びっくり", "Surprised", "なごみ" },
                ["embarrassed"] = new[] { "なごみ", "照れ", "Relaxed" },
                ["thinking"] = new[] { "じと目", "ジト目", "なごみ" },
            };

        /// <summary>口型（viseme）候选：MMD 的 あいうえお + VRM/英文命名。</summary>
        private static readonly Dictionary<string, string[]> VisemePresets =
            new Dictionary<string, string[]>(StringComparer.OrdinalIgnoreCase)
            {
                ["a"] = new[] { "あ", "あ2", "A", "aa" },
                ["i"] = new[] { "い", "い1", "い2", "I" },
                ["u"] = new[] { "う", "U" },
                ["e"] = new[] { "え", "E" },
                ["o"] = new[] { "お", "お2", "O" },
            };

        private static readonly string[] BlinkCandidates =
        {
            "まばたき", "Blink", "blink", "Fcl_EYE_Close"
        };

        private void Awake()
        {
            if (autoCollectRenderers || renderers == null || renderers.Length == 0)
            {
                renderers = GetComponentsInChildren<SkinnedMeshRenderer>(true);
            }
            IndexBlendShapes();
            ResetBlinkTimer();
        }

        private void Update()
        {
            if (!idleBlink || ExternalBlinkControl || string.IsNullOrEmpty(_blinkShape))
            {
                return;
            }
            var now = Time.unscaledTime;
            if (_blinkStartedAt < 0f)
            {
                if (now >= _nextBlinkAt)
                {
                    _blinkStartedAt = now;
                }
                return;
            }
            var progress = (now - _blinkStartedAt) / Mathf.Max(0.02f, blinkDuration);
            if (progress >= 1f)
            {
                SetShape(_blinkShape, 0f);
                _blinkStartedAt = -1f;
                ResetBlinkTimer();
                return;
            }
            // 0→1→0 的三角波，接近真实眨眼
            var weight = progress < 0.5f ? progress * 2f : (1f - progress) * 2f;
            SetShape(_blinkShape, weight * blinkWeight);
        }

        private void ResetBlinkTimer()
        {
            _nextBlinkAt = Time.unscaledTime +
                           UnityEngine.Random.Range(blinkIntervalMin, blinkIntervalMax);
        }

        private void IndexBlendShapes()
        {
            _shapeIndex.Clear();
            _shapeRenderer.Clear();
            if (renderers == null)
            {
                return;
            }
            foreach (var renderer in renderers)
            {
                if (renderer == null || renderer.sharedMesh == null)
                {
                    continue;
                }
                var mesh = renderer.sharedMesh;
                for (var i = 0; i < mesh.blendShapeCount; i++)
                {
                    var name = mesh.GetBlendShapeName(i);
                    if (string.IsNullOrEmpty(name))
                    {
                        continue;
                    }
                    _shapeIndex[name] = i;
                    _shapeRenderer[name] = renderer;
                }
            }
            _mouthShape = ResolveFirst(mouthBlendShapes);
            _blinkShape = ResolveFirst(BlinkCandidates);
            Debug.Log($"[AvatarBlendShape] 索引 {_shapeIndex.Count} 个形态键，" +
                      $"口型={(_mouthShape == "" ? "无" : _mouthShape)} " +
                      $"眨眼={(_blinkShape == "" ? "无" : _blinkShape)}");
            LogEmotionMapping();
        }

        private string ResolveFirst(string[] candidates)
        {
            if (candidates == null)
            {
                return "";
            }
            foreach (var candidate in candidates)
            {
                if (!string.IsNullOrEmpty(candidate) && _shapeIndex.ContainsKey(candidate))
                {
                    return candidate;
                }
            }
            return "";
        }

        /// <summary>启动时把每种情绪解析结果打出来，便于真机确认真实生效而不是"看起来在动"。</summary>
        private void LogEmotionMapping()
        {
            var lines = new List<string>();
            foreach (var pair in EmotionPresets)
            {
                var resolved = ResolveFirst(pair.Value);
                lines.Add($"{pair.Key}→{(resolved == "" ? "无" : resolved)}");
            }
            Debug.Log("[AvatarBlendShape] 情绪映射: " + string.Join(" ", lines));
        }

        public void ApplyEmotion(string emotion, float intensity)
        {
            intensity = Mathf.Clamp01(intensity);
            LastAppliedShape = "";
            if (bindings != null && bindings.Count > 0)
            {
                ApplyManualBindings(emotion, intensity);
            }
            else
            {
                ApplyPreset(emotion, intensity);
            }
        }

        private void ApplyManualBindings(string emotion, float intensity)
        {
            ResetAll();
            foreach (var binding in bindings)
            {
                if (!string.Equals(binding.emotion, emotion, StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }
                SetShape(binding.blendShape, binding.weight * intensity);
            }
        }

        private void ApplyPreset(string emotion, float intensity)
        {
            ResetAll();
            if (!EmotionPresets.TryGetValue(emotion, out var candidates))
            {
                return;
            }
            var shape = ResolveFirst(candidates);
            if (string.IsNullOrEmpty(shape))
            {
                return;
            }
            LastAppliedShape = shape;
            SetShape(shape, 100f * intensity);
        }

        /// <summary>口型：默认用幅度驱动 a 口型；传入 viseme 时用对应口型。</summary>
        public void SetMouthAmplitude(float amplitude, string viseme = "")
        {
            _mouthAmplitude = Mathf.Clamp01(amplitude);
            var shape = _mouthShape;
            if (!string.IsNullOrEmpty(viseme) &&
                VisemePresets.TryGetValue(viseme, out var candidates))
            {
                var resolved = ResolveFirst(candidates);
                if (!string.IsNullOrEmpty(resolved))
                {
                    shape = resolved;
                }
            }
            if (string.IsNullOrEmpty(shape))
            {
                return;
            }
            SetShape(shape, _mouthAmplitude * mouthMaxWeight);
        }

        public void SetBlink(float weight01)
        {
            if (!string.IsNullOrEmpty(_blinkShape))
            {
                SetShape(_blinkShape, Mathf.Clamp01(weight01) * blinkWeight);
            }
        }

        private void ResetAll()
        {
            var keys = new List<string>(_current.Keys);
            foreach (var key in keys)
            {
                if (string.Equals(key, _blinkShape, StringComparison.OrdinalIgnoreCase))
                {
                    continue; // 眨眼由本地定时器管理，不被表情复位打断
                }
                SetShape(key, 0f);
            }
        }

        private void SetShape(string name, float weight)
        {
            if (string.IsNullOrEmpty(name) || !_shapeIndex.TryGetValue(name, out var index))
            {
                return;
            }
            var renderer = _shapeRenderer[name];
            if (renderer == null)
            {
                return;
            }
            var clamped = Mathf.Clamp(weight, 0f, 100f);
            if (Mathf.Approximately(renderer.GetBlendShapeWeight(index), clamped))
            {
                return;
            }
            renderer.SetBlendShapeWeight(index, clamped);
            _current[name] = clamped;
        }
    }
}

