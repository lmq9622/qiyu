# 公开动捕 Avatar 模型来源与署名

本目录下的 `QiyuMirrorAvatar.fbx` 由公开模型转换而来，用于"用户动捕镜像 Avatar"
（把用户自己的实时动作套在模型上），与项目主角色模型分开。

- 原始模型：CesiumMan
- 来源：Khronos Group `glTF-Sample-Assets`
  https://github.com/KhronosGroup/glTF-Sample-Assets/tree/main/Models/CesiumMan
- 作者/版权：© 2017 Cesium
- 许可：Creative Commons Attribution 4.0 International (CC-BY-4.0)
  https://creativecommons.org/licenses/by/4.0/
- 说明：Cesium 商标/Logo 不在 CC-BY 授权范围内；本工程已移除模型上的装饰性球体，
  若对外发布需保留上面的署名信息。
- 转换：`quest-mr-client/tools/avatar/convert_public_glb.py`
  （Blender 导入 glTF → 骨骼改名为 Unity Humanoid 标准名 → 导出 FBX，保留 Walk 动画）
