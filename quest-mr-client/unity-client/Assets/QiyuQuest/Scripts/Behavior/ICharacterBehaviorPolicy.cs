namespace Qiyu.Quest.Behavior
{
    /// <summary>
    /// Quest Runtime 只依赖该接口，不绑定单一模型实现。
    ///
    /// 当前实现：BehaviorPolicyV1（轻量 MLP Scorer）。
    /// 预留：Transformer / Imitation / VLAAdapter。
    /// 任何实现都必须只输出候选行为得分与连续参数，禁止输出骨骼/路径。
    /// </summary>
    public interface ICharacterBehaviorPolicy
    {
        bool IsReady { get; }
        string SourceName { get; }
        bool Load();
        bool Score(float[] features, out float score, out float[] parameters);
        float Blend(float utility, float learned);
    }
}
