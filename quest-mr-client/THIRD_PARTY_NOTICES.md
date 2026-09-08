# 第三方依赖与 License 清单

> 结论先行：本项目**直接依赖**的开源组件均可用于 Qiyu（MIT / Apache-2.0 / Unity 包许可）；
> Meta SDK 属于 **Meta Platform Technologies SDK License**，作为 Unity Package 依赖使用，
> 不复制、不分发 SDK 本体；参考项目只做架构参考，未复制代码。

## 直接依赖（随 APK/仓库分发或链接）

| 组件 | 版本/来源 | License | 用途 | 合规动作 |
|---|---|---|---|---|
| NativeWebSocket (`com.endel.nativewebsocket`) | 本地包 / MIT | MIT | Quest WebSocket 底层 | 保留版权声明 |
| Newtonsoft.Json (`com.unity.nuget.newtonsoft-json`) | Unity 包 | MIT | JSON 序列化 | 保留版权声明 |
| Unity AI Navigation (`com.unity.ai.navigation`) | Unity 包 | Unity Companion License | NavMeshAgent / 运行时 NavMesh | 作为 Unity 包依赖 |
| Unity OpenXR (`com.unity.xr.openxr`) | Unity 包 | Unity Companion License | XR Loader | 作为 Unity 包依赖 |
| Meta XR Core (`com.meta.xr.sdk.core`) | 205.0.0 | Meta Platform Technologies SDK License | OVRManager/CameraRig/Passthrough/权限/深度 | 仅作为 SDK 依赖，不复制 SDK 源码 |
| Meta MRUK (`com.meta.xr.mrutilitykit`) | 205.0.0 | Meta Platform Technologies SDK License | 房间语义、EffectMesh、PassthroughCameraAccess | 仅作为 SDK 依赖，不复制 SDK 源码 |
| Meta OpenXR (`com.unity.xr.meta-openxr`) | 2.6.1 | Unity Companion License | Quest OpenXR Feature Set | 作为 Unity 包依赖 |
| Qiyu 现有运行时（`runtime/stt.py`、`runtime/tts.py`、`runtime/vision.py` 等） | 本项目 | 随 Qiyu 仓库 | STT/TTS/Vision/Memory/Emotion/Relationship | 复用，不改写主链路 |

## 架构参考（未复制代码）

| 项目 | License | 参考内容 | 是否复制代码 |
|---|---|---|---|
| Meta Unity-Phanto | MIT（部分资源除外） | Scene Mesh / NavMesh / 家具空间关系设计 | 否（用 MRUK + Unity AI Navigation 自行实现） |
| Meta Unity-SpatialLingo | MIT | Passthrough Camera、2D 框→3D 投影、空间对象+LLM 交互 | 参考投影思路，未复制源文件 |
| Meta Spatial SDK Samples | 项目 MIT + Meta SDK License | Body Tracking、Interaction 语义 | 否 |
| JarvisVR | MIT | 版本化 Envelope、heartbeat、barge-in、并行通道 | 否（协议自研并冻结为 v1） |
| Conversational-AI-npc-Unity | MIT | STT→LLM→TTS→LipSync 状态机 | 否（Qiyu 已有 STT/TTS/Brain） |
| Quest MR Assistant | README 声明 MIT，但仓库无 LICENSE 文件 | Passthrough→云端视觉→MR overlay | **否**；若未来要复用其代码，需先让作者补充 LICENSE |
| Incarna | 需按仓库实际许可复核 | VRM Avatar 与 Agent 连接方式 | 否 |

## 风险提示

1. Quest MR Assistant 仓库根目录没有 LICENSE 文件，当前只参考模式，不复制代码；
   若未来需要复用，必须先取得明确授权。
2. Meta SDK 不是 MIT；它是 SDK 许可。不要把 Meta 的 `.aar`/源码复制进 Qiyu 仓库再以 MIT 分发。
3. 若未来引入 UniVRM（MIT）、uLipSync（MIT）等，请在此清单追加并保留版权声明。
4. Qiyu 现有后端代码的 License 以 `ai-companion` 仓库自身声明为准；本分支只新增 Quest 入口，
   不改变原有授权。
