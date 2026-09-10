using System;
using Newtonsoft.Json;
using UnityEngine;

namespace Qiyu.Quest.Behavior
{
    /// <summary>
    /// 轻量候选行为打分器（MLP，纯 C# 推理）。
    ///
    /// 不是 VLA，不输出骨骼/路径：
    /// 输入固定特征 → 输出候选行为得分 + 连续参数。
    /// 权重来自 behavior_policy/train.py，可由 Resources 热更新。
    /// </summary>
    public class TinyBehaviorPolicy : MonoBehaviour, ICharacterBehaviorPolicy
    {
        [SerializeField] private string resourcePath = "Qiyu/behavior_policy_v1";
        [SerializeField] private bool loadOnAwake = true;
        [Range(0f, 1f)]
        [SerializeField] private float learnedWeight = 0.35f;

        public bool Ready { get; private set; }
        public bool IsReady => Ready;
        public string SourceName => "BehaviorPolicyV1";
        public string LastError { get; private set; } = "";
        public string ModelVersion { get; private set; } = "";
        public float LearnedWeight => learnedWeight;

        [Serializable]
        private sealed class DenseLayer
        {
            public float[][] w;
            public float[] b;
        }

        [Serializable]
        private sealed class PolicyFile
        {
            public string schema_version;
            public string model_type;
            public string model_version;
            public int input_dim;
            public int[] hidden_sizes;
            public DenseLayer[] layers;
            public DenseLayer score_layer;
            public DenseLayer param_layer;
            public string[] feature_names;
            public string[] behavior_names;
            public string[] param_names;
            public float[] param_scale;
            public float[] param_offset;
        }

        private PolicyFile _policy;
        private float[] _hiddenA;
        private float[] _hiddenB;

        private void Awake()
        {
            if (loadOnAwake)
            {
                Load();
            }
        }

        public bool Load()
        {
            Ready = false;
            LastError = "";
            var asset = Resources.Load<TextAsset>(resourcePath);
            if (asset == null)
            {
                LastError = $"Resources/{resourcePath}.json 不存在";
                return false;
            }
            try
            {
                _policy = JsonConvert.DeserializeObject<PolicyFile>(asset.text);
                if (_policy == null || _policy.layers == null ||
                    _policy.score_layer == null || _policy.param_layer == null)
                {
                    LastError = "策略 JSON 缺少网络层";
                    return false;
                }
                if (_policy.input_dim != BehaviorFeatureEncoder.InputDimension)
                {
                    LastError =
                        $"特征维度不匹配：模型 {_policy.input_dim} / 运行时 " +
                        $"{BehaviorFeatureEncoder.InputDimension}";
                    return false;
                }
                if (_policy.layers.Length != 2)
                {
                    LastError = $"第一版只支持 2 层隐藏层，当前 {_policy.layers.Length}";
                    return false;
                }
                if (_policy.layers[0].w == null || _policy.layers[0].w.Length == 0 ||
                    _policy.layers[0].w[0] == null)
                {
                    LastError = "第一层权重为空";
                    return false;
                }
                _hiddenA = new float[_policy.layers[0].w.Length];
                _hiddenB = new float[_policy.layers[1].w.Length];
                ModelVersion = _policy.model_version ?? "";
                Ready = true;
                Debug.Log($"[QiyuBehaviorPolicy] 已加载 {resourcePath} " +
                          $"{ModelVersion} input={_policy.input_dim}");
                return true;
            }
            catch (Exception e)
            {
                LastError = $"解析失败: {e.Message}";
                Debug.LogWarning($"[QiyuBehaviorPolicy] {LastError}");
                return false;
            }
        }

        public bool Score(float[] features, out float score, out float[] parameters)
        {
            score = 0f;
            parameters = new float[_policy?.param_layer?.w?.Length ?? 0];
            if (!Ready || features == null ||
                features.Length != BehaviorFeatureEncoder.InputDimension)
            {
                return false;
            }
            try
            {
                var h = Forward(_policy.layers[0], features, _hiddenA);
                h = Forward(_policy.layers[1], h, _hiddenB);
                score = Sigmoid(Dot(_policy.score_layer.w[0], h) +
                                _policy.score_layer.b[0]);
                for (var i = 0; i < parameters.Length; i++)
                {
                    var raw = Sigmoid(Dot(_policy.param_layer.w[i], h) +
                                      _policy.param_layer.b[i]);
                    var scale = _policy.param_scale != null && i < _policy.param_scale.Length
                        ? _policy.param_scale[i] : 1f;
                    var offset = _policy.param_offset != null && i < _policy.param_offset.Length
                        ? _policy.param_offset[i] : 0f;
                    parameters[i] = raw * scale + offset;
                }
                return true;
            }
            catch (Exception e)
            {
                LastError = $"推理失败: {e.Message}";
                Ready = false;
                return false;
            }
        }

        public float Blend(float utility, float learned)
        {
            return Mathf.Clamp01(utility * (1f - learnedWeight) +
                                 learned * learnedWeight);
        }

        private static float[] Forward(DenseLayer layer, float[] input, float[] output)
        {
            if (layer == null || layer.w == null || output == null)
            {
                return Array.Empty<float>();
            }
            for (var row = 0; row < layer.w.Length; row++)
            {
                var sum = layer.b != null && row < layer.b.Length ? layer.b[row] : 0f;
                var weights = layer.w[row];
                var count = Mathf.Min(weights.Length, input.Length);
                for (var col = 0; col < count; col++)
                {
                    sum += weights[col] * input[col];
                }
                output[row] = sum > 0f ? sum : 0f;
            }
            return output;
        }

        private static float Dot(float[] weights, float[] input)
        {
            var sum = 0f;
            var count = Mathf.Min(weights?.Length ?? 0, input?.Length ?? 0);
            for (var i = 0; i < count; i++)
            {
                sum += weights[i] * input[i];
            }
            return sum;
        }

        private static float Sigmoid(float value)
        {
            return 1f / (1f + Mathf.Exp(-Mathf.Clamp(value, -30f, 30f)));
        }
    }
}
