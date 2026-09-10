using UnityEngine;

namespace Qiyu.Quest.Behavior
{
    /// <summary>
    /// 可升级策略占位实现。
    ///
    /// 这些类不会假装可用：IsReady=false，Load() 明确 TODO；
    /// 只有真正接入对应权重/推理后，才允许返回 true 并被 Runtime 选中。
    /// </summary>
    public abstract class UnimplementedBehaviorPolicy : MonoBehaviour,
        ICharacterBehaviorPolicy
    {
        public virtual bool IsReady => false;
        public abstract string SourceName { get; }

        public virtual bool Load()
        {
            Debug.LogWarning($"[QiyuPolicy] {SourceName} 尚未实现：TODO 接入真实权重/推理后端");
            return false;
        }

        public virtual bool Score(float[] features, out float score, out float[] parameters)
        {
            score = 0f;
            parameters = new float[6];
            return false;
        }

        public virtual float Blend(float utility, float learned)
        {
            return utility;
        }
    }

    public sealed class BehaviorPolicyTransformer : UnimplementedBehaviorPolicy
    {
        public override string SourceName => "BehaviorPolicyTransformer";
    }

    public sealed class ImitationPolicy : UnimplementedBehaviorPolicy
    {
        public override string SourceName => "ImitationPolicy";
    }

    public sealed class VLAAdapter : UnimplementedBehaviorPolicy
    {
        public override string SourceName => "VLAAdapter";
    }
}
