"""把 MMD 的 .pmx 转成 Unity 能直接吃的 FBX。

用法：
    blender.exe --background --factory-startup --python convert_pmx.py -- <in.pmx> <out.fbx>

做三件事：
  1) mmd_tools 导入（含材质/贴图/骨骼/蒙皮）；
  2) 删掉物理刚体与关节（Unity 里用不到，还会拖慢导入）；
  3) 把骨骼改名成 Unity Humanoid 认得的英文名，省掉手工映射。
"""
import sys
import os

import addon_utils
import bpy


# MMD 日文骨骼名 → Unity Humanoid 标准名。
# 实测本模型骨骼名为日文（mmd_tools 未做英文化），上半身有 上半身/上半身1/上半身2
# 三层，正好对应 Unity 的 Spine/Chest/UpperChest。
BONE_MAP = {
    "全ての親": "Root",
    "センター": "Center",
    "下半身": "Hips",
    "上半身": "Spine",
    "上半身1": "Chest",
    "上半身2": "UpperChest",
    "首": "Neck",
    "頭": "Head",
    "肩.L": "LeftShoulder",
    "腕.L": "LeftUpperArm",
    "ひじ.L": "LeftLowerArm",
    "手首.L": "LeftHand",
    "肩.R": "RightShoulder",
    "腕.R": "RightUpperArm",
    "ひじ.R": "RightLowerArm",
    "手首.R": "RightHand",
    "足.L": "LeftUpperLeg",
    "ひざ.L": "LeftLowerLeg",
    "足首.L": "LeftFoot",
    "つま先.L": "LeftToes",
    "足.R": "RightUpperLeg",
    "ひざ.R": "RightLowerLeg",
    "足首.R": "RightFoot",
    "つま先.R": "RightToes",
}


def enable_mmd_tools():
    # Blender 4.2 起 mmd_tools 是“扩展”，模块名形如 bl_ext.<repo>.mmd_tools
    for name in ("bl_ext.user_default.mmd_tools", "bl_ext.blender_org.mmd_tools"):
        try:
            addon_utils.enable(name, default_set=False, persistent=True)
            print("[convert] 已启用扩展:", name)
            return
        except Exception as exc:  # noqa: BLE001
            print("[convert] 启用", name, "失败:", exc)
    for mod in addon_utils.modules():
        if mod.__name__ in ("mmd_tools", "mmd_tools.blender_manifest"):
            addon_utils.enable(mod.__name__, default_set=False, persistent=True)
            return
    addon_utils.enable("mmd_tools", default_set=False, persistent=True)


def import_model(pmx_path):
    kwargs = dict(
        filepath=pmx_path,
        scale=0.08,
        types={"MESH", "ARMATURE", "MORPHS"},
        clean_model=True,
        rename_bones=True,
    )
    try:
        bpy.ops.mmd_tools.import_model(**kwargs)
    except TypeError as exc:
        print("[convert] import_model 参数不兼容，改用最小参数:", exc)
        bpy.ops.mmd_tools.import_model(filepath=pmx_path, scale=0.08)


def remove_physics():
    doomed = []
    for obj in bpy.data.objects:
        name = obj.name.lower()
        if obj.type == "EMPTY" and ("rigidbody" in name or "joint" in name
                                    or name.startswith("rb_") or name.startswith("j_")):
            doomed.append(obj)
    for obj in doomed:
        bpy.data.objects.remove(obj, do_unlink=True)
    print("[convert] 清理物理对象:", len(doomed))


def rename_bones():
    renamed = 0
    for armature in [o for o in bpy.data.objects if o.type == "ARMATURE"]:
        existing = {b.name for b in armature.data.bones}
        for bone in armature.data.bones:
            target = BONE_MAP.get(bone.name)
            if target and target not in existing:
                bone.name = target
                existing.add(target)
                renamed += 1
    print("[convert] 骨骼改名:", renamed)


def report():
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    tris = sum(len(o.data.loop_triangles) for o in meshes
               if (o.data.calc_loop_triangles() or True))
    images = [i for i in bpy.data.images if i.filepath]
    print("[convert] mesh 数:", len(meshes), " 三角面:", tris,
          " 贴图:", len(images))
    for img in images[:40]:
        exists = os.path.exists(bpy.path.abspath(img.filepath))
        if not exists:
            print("   !! 贴图缺失:", img.name, img.filepath)


def main():
    args = sys.argv[sys.argv.index("--") + 1:]
    pmx_path, out_fbx = args[0], args[1]
    bpy.ops.wm.read_factory_settings(use_empty=True)
    # 注意：必须在 read_factory_settings 之后启用，否则扩展会被重置掉。
    enable_mmd_tools()
    import_model(pmx_path)
    remove_physics()
    rename_bones()
    report()
    bpy.ops.export_scene.fbx(
        filepath=out_fbx,
        use_selection=False,
        embed_textures=False,
        path_mode="COPY",
        add_leaf_bones=False,
        bake_anim=False,
        mesh_smooth_type="FACE",
        axis_forward="-Z",
        axis_up="Y",
    )
    print("[convert] 导出完成:", out_fbx,
          os.path.getsize(out_fbx) if os.path.exists(out_fbx) else "MISSING")


if __name__ == "__main__":
    main()
