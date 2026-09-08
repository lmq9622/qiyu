using System;
using System.Collections.Generic;
using UnityEngine;

namespace Qiyu.Quest.Avatar
{
    /// <summary>
    /// 表情/口型驱动：把高层 emotion 映射到真实 BlendShape 权重。
    ///
    /// 兼容 VRM 0.x（Joy/Angry/Sorrow/Relaxed/Surprised）与 VRM 1.0
    /// （Happy/Angry/Sad/Relaxed/Surprised）以及常见中文/日文命名模型。
    /// 口型为音频 RMS 驱动的真实权重变化；更高精度的 viseme 可接
    /// uLipSync/OVRLipSync 后替换 SetMouthAmplitude 数据源。
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
            "A", "aa", "Fcl_MTH_A", "Mouth_A", "mouth_a", "jaw_open"
        };
        [SerializeField] private float mouthMaxWeight = 70f;

        [Header("手动映射（可选，留空则用内置预设）")]
        [SerializeField] private List<Binding> bindings = new List<Binding>();

        private readonly Dictionary<string, float> _current =
            new Dictionary<string, float>(StringComparer.OrdinalIgnoreCase);
        private readonly Dictionary<string, int> _shapeIndex =
            new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        private readonly Dictionary<string, SkinnedMeshRenderer> _shapeRenderer =
            new Dictionary<string, SkinnedMeshRenderer>(StringComparer.OrdinalIgnoreCase);
        private string _mouthShape = "";
        private float _mouthAmplitude;

        private static readonly Dictionary<string, string[]> EmotionPresets =
            new Dictionary<string, string[]>(StringComparer.OrdinalIgnoreCase)
            {
                ["neutral"] = new[] { "Neutral", "neutral" },
                ["happy"] = new[] { "Joy", "Happy", "joy", "happy" },
                ["calm"] = new[] { "Relaxed", "relaxed" },
                ["sad"] = new[] { "Sorrow", "Sad", "sorrow", "sad" },
                ["annoyed"] = new[] { "Angry", "angry" },
                ["angry"] = new[] { "Angry", "angry" },
                ["excited"] = new[] { "Joy", "Happy", "Surprised", "excited" },
                ["shy"] = new[] { "Relaxed", "Blink", "shy" },
                ["confused"] = new[] { "Surprised", "confused" },
                ["tired"] = new[] { "Sorrow", "tired" },
                ["surprised"] = new[] { "Surprised", "surprised" },
            };

        private void Awake()
        {
            if (autoCollectRenderers || renderers == null || renderers.Length == 0)
            {
                renderers = GetComponentsInChildren<SkinnedMeshRenderer>(true);
            }
            IndexBlendShapes();
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
            foreach (var candidate in mouthBlendShapes)
            {
                if (_shapeIndex.ContainsKey(candidate))
                {
                    _mouthShape = candidate;
                    break;
                }
            }
            Debug.Log($"[AvatarBlendShape] 索引 {_shapeIndex.Count} 个 BlendShape，口型={_mouthShape}");
        }

        public void ApplyEmotion(string emotion, float intensity)
        {
            intensity = Mathf.Clamp01(intensity);
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
            foreach (var candidate in candidates)
            {
                if (!_shapeIndex.ContainsKey(candidate))
                {
                    continue;
                }
                SetShape(candidate, 100f * intensity);
                break;
            }
        }

        public void SetMouthAmplitude(float amplitude)
        {
            _mouthAmplitude = Mathf.Clamp01(amplitude);
            if (string.IsNullOrEmpty(_mouthShape))
            {
                return;
            }
            SetShape(_mouthShape, _mouthAmplitude * mouthMaxWeight);
        }

        private void ResetAll()
        {
            var keys = new List<string>(_current.Keys);
            foreach (var key in keys)
            {
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
