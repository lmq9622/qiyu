# MMD 模型（.pmx）→ Unity Humanoid 全流程

Unity 不能直接吃 MMD 的 `.pmx`，本项目用 Blender + mmd_tools 离线转成 FBX，
再由 Unity 以 Humanoid 导入。这条链已经真机跑通，记录如下。

## 为什么必须转成 Humanoid

程序化动作兜底与动作重定向都通过
`Animator.GetBoneTransform(HumanBodyBones.Head)` 这类接口取骨骼。
模型不是 Humanoid，就没有骨骼可驱动，角色只能是一个不会动的模型。

## 环境（一次性准备）

```text
Blender   4.2.23 LTS 便携版（解压即用）
mmd_tools 4.5.14（Blender 4.2 扩展）
opencc-python-reimplemented 0.1.7（mmd_tools 依赖，装进 Blender 自带 Python）
```

安装要点（踩过的坑）：

1. Blender **4.2 起不再扫描自带的 `scripts/addons`**，mmd_tools 必须装成扩展：
   `%APPDATA%\Blender Foundation\Blender\4.2\extensions\user_default\mmd_tools\`，
   模块名是 `bl_ext.user_default.mmd_tools`。
2. `bpy.ops.wm.read_factory_settings()` 会把已启用的扩展重置掉，
   **必须先 reset 再 enable**。
3. mmd_tools 需要 `opencc`，用扩展自带的 wheel 装进 Blender 的 Python：
   `blender/4.2/python/bin/python.exe -m pip install --no-deps <wheels/opencc_*.whl>`

## 转换

```powershell
# 1) 解压模型包（zip 内文件名是 GBK/Shift-JIS，直接解压会乱码，贴图会对不上）
python quest-mr-client/tools/avatar/extract_model.py `
  'D:\迅雷下载\xxx.zip' 'D:\Tools\qiyu-avatar\model'

# 2) PMX → FBX（骨骼已改名为 Unity 标准名）
blender.exe --background --factory-startup `
  --python quest-mr-client/tools/avatar/convert_pmx.py -- `
  'D:\Tools\qiyu-avatar\model\xxx.pmx' 'D:\Tools\qiyu-avatar\out\avatar.fbx'
```

`convert_pmx.py` 做三件事：

1. mmd_tools 导入（材质/贴图/骨骼/蒙皮/形态键）；
2. 删掉物理刚体与关节（Unity 用不到）；
3. 把 MMD 日文骨骼名改成 Unity Humanoid 标准名：

| MMD | Unity |
|---|---|
| 下半身 | Hips |
| 上半身 / 上半身1 / 上半身2 | Spine / Chest / UpperChest |
| 首 / 頭 | Neck / Head |
| 肩.L / 腕.L / ひじ.L / 手首.L | LeftShoulder / LeftUpperArm / LeftLowerArm / LeftHand |
| 足.L / ひざ.L / 足首.L / つま先.L | LeftUpperLeg / LeftLowerLeg / LeftFoot / LeftToes |

## 放进 Unity

```text
Assets/QiyuQuest/Resources/Qiyu/Avatar/QiyuAvatarModel.fbx   # 运行时 Resources.Load
Assets/QiyuQuest/AvatarAssets/Textures/*.png|*.bmp           # 贴图
```

`QiyuAvatarImportSetup`（AssetPostprocessor）会自动把该目录下的 FBX 设为：

```text
Animation Type   = Human
Avatar Setup     = Create From This Model
Import Animation = 关
Material         = Import Standard（外部材质）
```

导入后日志里应出现：

```text
[QiyuAvatarImport] .../QiyuAvatarModel.fbx Humanoid=True
[QiyuAvatar] 已载入角色模型 QiyuAvatarModel humanoid=True yawOffset=0
```

`humanoid=False` 时不要当成成功：说明骨骼绑定不完整，程序化动作会退化，
需要回到 Blender 检查骨骼名映射。

## 朝向与缩放

- `avatarModelYawOffset`：MMD 模型导入后如果背对用户，改成 180。
- `avatarModelScale`：FBX 已按 0.08 缩放，模型高约 1.58 m，正常无需再改。

## 许可

验收用模型见 [ACCEPTANCE_AVATAR.md](ACCEPTANCE_AVATAR.md)：
允许修改、禁止二次配布、禁止拆件改造、禁止商用。
**模型本体不入库**，只在本地转换与验收。
