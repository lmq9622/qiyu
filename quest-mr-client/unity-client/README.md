# Qiyu Quest Unity Client

Quest 3/3S MR 客户端源码（与 `D:\UnityProjects\QiyuQuestProject\Assets\QiyuQuest` 同步）。

## 目录

```text
Assets/QiyuQuest/
├── Editor/QiyuP0Setup.cs                  # 一键配置 Player/OpenXR/权限 + 建场景 + 构建 APK
├── Editor/Templates/launcherTemplate.gradle
├── Scripts/Networking/
│   ├── QuestEnvelope.cs                   # Protocol v1 JSON Envelope
│   ├── QuestBinaryProtocol.cs             # Protocol v1 二进制帧
│   └── QiyuQuestWebSocketClient.cs        # 握手/心跳/重连/分发/二进制发送
├── Scripts/Perception/
│   ├── MrukSceneSummary.cs                # MRUK 房间语义汇总 + HUD
│   ├── MrukWorldStatePublisher.cs         # WorldState v1 上报
│   ├── PassthroughFrameSource.cs          # Meta Passthrough Camera → JPEG
│   ├── ObjectDetectionProjector.cs        # 2D 框 → 深度/射线 → 世界坐标
│   └── QuestPermissionsBootstrap.cs       # Scene/麦克风/相机权限
├── Scripts/Voice/
│   ├── QuestMicrophoneCapture.cs          # 48k→16k + 能量 VAD + 二进制上行
│   ├── QuestTtsPlayer.cs                  # 流式 PCM 播放 + RMS 口型
│   └── QuestVoiceLoop.cs                  # 语音闭环 + barge-in
├── Scripts/Avatar/
│   ├── AvatarIntentRouter.cs              # avatar.intent / spatial.action 分发
│   ├── BlendShapeAvatarDriver.cs          # 情绪 → BlendShape，音频 → 口型
│   └── AvatarLookController.cs            # 头部/上身看向
└── Scripts/Spatial/
    ├── RoomNavMeshBuilder.cs              # MRUK 语义 → 运行时 NavMesh
    ├── SpatialActionExecutor.cs           # NavMeshAgent 执行高层动作
    └── QuestObjectRegistry.cs             # 检测物体世界坐标注册表
```

## 依赖

- Unity 6000.6.0f1 + URP
- `com.meta.xr.sdk.core` 205.0.0（Meta SDK License）
- `com.meta.xr.mrutilitykit` 205.0.0（Meta SDK License）
- `com.unity.xr.meta-openxr` + `com.unity.xr.openxr`
- `com.endel.nativewebsocket`（MIT，本地包）
- Newtonsoft Json、Unity AI Navigation

## 一键配置与构建

Unity 菜单：`Qiyu/Setup P0 Quest Scene`、`Qiyu/Build P0 APK`。

命令行：

```powershell
$env:JAVA_HOME='D:\Unity\Hub\Editor\6000.6.0f1\Editor\Data\PlaybackEngines\AndroidPlayer\OpenJDK'
$env:ANDROID_SDK_ROOT='D:\Unity\Hub\Editor\6000.6.0f1\Editor\Data\PlaybackEngines\AndroidPlayer\SDK'
$env:ANDROID_NDK_ROOT='D:\Unity\Hub\Editor\6000.6.0f1\Editor\Data\PlaybackEngines\AndroidPlayer\NDK'
& 'D:\Unity\Hub\Editor\6000.6.0f1\Editor\Unity.exe' -batchmode -nographics -quit `
  -projectPath 'D:\UnityProjects\QiyuQuestProject' `
  -executeMethod Qiyu.Quest.Editor.QiyuP0Setup.BuildP0Apk `
  -logFile 'D:\UnityProjects\QiyuQuestProject\Logs\p0_build.log'
```

默认 Gateway 地址：`ws://<Qiyu主机IP>:8766/v1/quest/ws`，
可用环境变量 `QIYU_QUEST_WS_URL` 覆盖。

## 真机验收清单

1. `adb install -r Builds\QiyuQuestP0.apk`
2. 授权 Scene / 麦克风 / Passthrough Camera 权限
3. 确认 MRUK 房间语义与 EffectMesh 显示
4. 确认 hello/heartbeat/world_state ACK
5. 说一句话，确认 `server.voice_transcript` → `agent.speech` → TTS 播放
6. TTS 播放中插话，确认 barge-in
7. 让角色靠近/看向桌子，确认 NavMesh 与避障

> 当前机器未连接 Quest，以上真机项尚未验收；不要把源码完成等同于真机通过。
