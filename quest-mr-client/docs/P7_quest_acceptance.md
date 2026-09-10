# P7 Quest 真机验收清单

> 前置：Quest 3/3S 已开启开发者模式、USB 调试、已安装 APK。
> 自动脚本：`quest-mr-client/tools/quest_p7_acceptance.ps1`

## 1. 自动检查

```powershell
powershell -ExecutionPolicy Bypass -File `
  'D:\Codex projects\ai-companion-codex\ai-companion\quest-mr-client\tools\quest_p7_acceptance.ps1' `
  -Apk 'D:\Codex projects\ai-companion-codex\QiyuQuest-MR-test.apk' `
  -DurationSeconds 120
```

脚本会：

1. 检查 `adb devices`；
2. 安装/覆盖安装 APK；
3. 启动 `com.qiyu.quest`；
4. 清空 logcat 并采集；
5. 汇总 WebSocket/MRUK/NavMesh/语音/Behavior/Reflex/动画/异常关键字。

## 2. 必须人工确认

### 空间

- [ ] MRUK 房间扫描完成，桌面/椅子/墙/地面语义正确；
- [ ] NavMesh 可行走区域不穿墙、不穿家具；
- [ ] 角色能走到桌子/椅子附近，路径自然；
- [ ] 用户突然靠近时角色后退或停住，不穿模；
- [ ] 遮挡时角色会换位或重新注视。

### 行为

- [ ] 叫角色：转向/看向用户，不机械重复；
- [ ] 用户说话：角色倾听，不抢话；
- [ ] 用户打断：TTS 立即停止，行为切到 listening；
- [ ] 用户沉默：角色有观察/换位/idle，不静止假死；
- [ ] 指向物体：角色看向/走向目标，目标消失后不继续追；
- [ ] 说“跟我来”：角色跟随/靠近，不撞家具；
- [ ] 说“坐这里”：只对真实椅子执行；
- [ ] 说“别过来”：保持距离，不靠近；
- [ ] 两个目标竞争：目标锁定稳定，不来回抽搐；
- [ ] 网络断开：本地 idle/Reflex 继续，不卡死。

### 语音/表情

- [ ] 口型与 TTS 同步；
- [ ] 情绪表情与行为一致；
- [ ] 视线不长期死盯，偶尔自然移开；
- [ ] 动作切换有 blend，不瞬移/抽搐。

### Human Motion / Human-Avatar Interaction

- [ ] `OVRHand` 手部追踪有效，`client.human_motion_state` 以 5–15Hz 上报；
- [ ] 挥手 → 角色识别 → LookAt → 挥手回应；
- [ ] 招手 → 角色 Approach / Follow；
- [ ] 指向物体 → 角色确认目标 → LookAt → 根据距离决定是否靠近；
- [ ] 伸手靠近 → 距离/手位判断 → 接近 → 抬手 High Five；
- [ ] 用户坐下/站起 → UserState 更新 → 角色等待/坐下/继续交流；
- [ ] 停止/推开动作 → 本地高优先级 interrupt + Reflex；
- [ ] Body Tracking（设备支持时）`body_tracked=true`，不支持时如实为 false；
- [ ] Eye Tracking（设备支持且授权时）有置信度；不支持时回退头部朝向，不伪装眼动；
- [ ] Shared Attention：用户看物体 → 角色看物体；用户看角色 → 角色回看；
- [ ] InteractionState 能 interrupt / cancel / resume / replan，不是单向 START→END；
- [ ] 原始骨骼没有持续上传云端。

### 验收模型

- [ ] 使用 [ACCEPTANCE_AVATAR.md](ACCEPTANCE_AVATAR.md) 记录的 aplaybox 模型；
- [ ] 由于是 MMD 格式，已安装真实 MMD 导入器或完成授权范围内转换；
- [ ] 模型许可允许当前验收/发布用途；禁止二次配布与商业用途已确认；
- [ ] Humanoid 骨骼映射完整（Head/Chest/Hips/UpperArm/Hand）。

### 性能

- [ ] FPS 稳定；
- [ ] Behavior Policy 推理无明显卡顿；
- [ ] WorldState 上报频率/带宽可接受；
- [ ] 连续运行 10 分钟无内存持续增长/崩溃。

## 3. 通过标准

- 自动日志：无 `Exception` / `NullReferenceException` / `server.error` 连环；
- 人工项：空间、行为、语音、性能全部通过；
- 失败项必须记录复现步骤、时间戳、logcat 片段，回流到行为策略硬负样本。
