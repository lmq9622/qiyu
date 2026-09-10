# P7 验收模型（aplaybox）

来源：

```text
https://www.aplaybox.com/details/model/gF6QUvbECNUA
```

已通过 aplaybox 公开作品详情 API 确认真实元数据：

```text
作品名：【原神】茜特菈莉「星与烟帷的夜语」
work_uuid：gF6QUvbECNUA
work_id：73799
类型：人物
格式：MMD（不是 VRM / GLB）
模型提供：miHoYo
模型改造：观海（BiliBili：观海子）
作者账号：原神（aplaybox user_uid 680828836）
```

许可（作品页原文摘要）：

- 允许完善物理、修正模型权重/表情 bug；
- 允许改色、适度更改衣装、添加 spa/toon；
- **禁止二次配布**；
- **禁止拆取部件用于改造其他模型**；
- **禁止 18 禁、极端宗教宣传、血腥恐怖猎奇、人身攻击**；
- **禁止商业用途**；
- 下载需要登录并满足点赞/收藏等作品下载规则。

## 接入结论

1. 该模型是 MMD 资源，不是 VRM/GLB；不能假设 Unity 直接支持。
2. Quest 客户端需要额外 MMD 导入/转换链（例如 MMD4Mecanim、MMDPlayer 或先在授权范围内转为 Unity Humanoid 资源）。
3. 由于禁止二次配布，仓库不得提交模型本体或转换后的可再分发模型；只能记录元数据与本地导入路径。
4. 如果最终发布 APK 会包含该模型，必须先确认许可是否允许；当前许可明确禁止商业用途且禁止二次配布。
5. `QuestAvatarModelImporter` 已识别 `.pmx/.pmd`，未安装 MMD 导入器时会如实报错，不会假加载。

## 本地导入步骤

1. 登录 aplaybox，按作品页规则下载模型；
2. 在 Unity 中安装 MMD 导入/转换方案；
3. 把模型放在 `StreamingAssets/Qiyu/avatar.pmx` 或工程 Assets 下；
4. 导入为 Humanoid（必须有 Head/Chest/Hips/UpperArm/Hand 骨骼映射）；
5. 挂载 `Animator`，设置 Motion Library 的 Walk/Run/Idle 等 clip；
6. 设置 `QiyuSettings.AvatarUrl` 指向本地文件；
7. 运行 `Qiyu/Setup P0 Quest Scene` 重新装配 Avatar 行为组件；
8. 真机验收时确认模型许可与隐私合规。
