# Quest 开发环境状态

> 更新时间：2026-09-08

## 已安装

- Unity Hub 3.21.1（MSIX）
- Unity CLI 1.0.0-beta.6
- Unity Editor 6000.6.0f1，安装目录：`D:\Unity\Hub\Editor\6000.6.0f1`
- Android Build Support
- Android NDK
- Android SDK & Platform Tools
- OpenJDK 17
- Unity 工程已注册：
  - `D:\UnityProjects\QiyuQuestProject`
  - 版本：6000.6.0f1
  - URP：com.unity.render-pipelines.universal 17.6.0
  - 已包含 QiyuQuest C# 源码与 manifest

## 已安装到的组件

```text
D:\Unity\Hub\Editor\6000.6.0f1
D:\UnityProjects\QiyuQuestProject
```

## 尚未满足

### Unity 许可证

当前 Unity 未登录、无许可证：

```text
unity auth status → 尚未登录
license status   → active=false
```

需要用户执行：

```powershell
& 'C:\Users\lmq20\AppData\Local\Packages\UnityTechnologies.UnityHub_2vrhnee42bhxm\LocalCache\Local\Unity\bin\unity.exe' auth login
& 'C:\Users\lmq20\AppData\Local\Packages\UnityTechnologies.UnityHub_2vrhnee42bhxm\LocalCache\Local\Unity\bin\unity.exe' license activate --personal --accept-eula
```

### Meta XR SDK

Meta XR All-in-One SDK / MRUK 需要 Unity 许可并登录 Unity Asset Store 后从 Package Manager 安装；这是 Meta 的授权约束，无法绕过。

### Quest 真机

本机未连接 Meta Quest 3 / 3S，且 Unity Editor 无法运行，因此：

- Passthrough 真机权限和画面未验证；
- MRUK Scene 可视化未验证；
- APK 未构建；
- Quest ↔ Qiyu Gateway 端到端未验证。

## 解锁后第一步

```powershell
cd D:\UnityProjects\QiyuQuestProject
& 'D:\Unity\Hub\Editor\6000.6.0f1\Editor\Unity.exe' -projectPath 'D:\UnityProjects\QiyuQuestProject'
```

打开后按 `quest-mr-client/unity-client/README.md` 导入 Meta XR All-in-One SDK 和 MRUK。
