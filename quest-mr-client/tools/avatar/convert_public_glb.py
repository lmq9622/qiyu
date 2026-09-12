"""把公开的 glTF 人形模型转成 Unity 能用的 FBX（骨骼改名为 Unity Humanoid 标准名）。

用法：
    blender.exe --background --factory-startup --python convert_public_glb.py -- <in.glb> <out.fbx>

模型：Khronos glTF-Sample-Assets / CesiumMan（CC-BY 4.0，需保留署名）。
注意：CesiumMan 原骨架没有手部骨骼，而 Unity 的 Humanoid 要求手骨存在，
因此这里会补 LeftHand / RightHand 两根子骨骼（不加权重，只为让 Avatar 合法）。
"""
import os
import sys

import bpy

BONE_MAP = {
    "Skeleton_torso_joint_1": "Hips",
    "Skeleton_torso_joint_2": "Spine",
    "torso_joint_3": "Chest",
    "Skeleton_neck_joint_1": "Neck",
    "Skeleton_neck_joint_2": "Head",
    "Skeleton_arm_joint_L__4_": "LeftShoulder",
    "Skeleton_arm_joint_L__3_": "LeftUpperArm",
    "Skeleton_arm_joint_L__2_": "LeftLowerArm",
    "Skeleton_arm_joint_R": "RightShoulder",
    "Skeleton_arm_joint_R__2_": "RightUpperArm",
    "Skeleton_arm_joint_R__3_": "RightLowerArm",
    "leg_joint_L_1": "LeftUpperLeg",
    "leg_joint_L_2": "LeftLowerLeg",
    "leg_joint_L_3": "LeftFoot",
    "leg_joint_L_5": "LeftToes",
    "leg_joint_R_1": "RightUpperLeg",
    "leg_joint_R_2": "RightLowerLeg",
    "leg_joint_R_3": "RightFoot",
    "leg_joint_R_5": "RightToes",
}

DROP_OBJECTS = ("Icosphere",)


def add_hand_bones():
    added = 0
    for armature in [o for o in bpy.data.objects if o.type == "ARMATURE"]:
        bpy.context.view_layer.objects.active = armature
        bpy.ops.object.mode_set(mode="EDIT")
        edit_bones = armature.data.edit_bones
        for lower_name, hand_name in (("LeftLowerArm", "LeftHand"),
                                      ("RightLowerArm", "RightHand")):
            lower = edit_bones.get(lower_name)
            if lower is None or edit_bones.get(hand_name) is not None:
                continue
            direction = lower.tail - lower.head
            if direction.length < 1e-5:
                continue
            hand = edit_bones.new(hand_name)
            hand.head = lower.tail
            hand.tail = lower.tail + direction.normalized() * (direction.length * 0.35)
            hand.parent = lower
            hand.use_connect = True
            added += 1
        bpy.ops.object.mode_set(mode="OBJECT")
    print("[pub] 补手骨:", added)


def main():
    args = sys.argv[sys.argv.index("--") + 1:]
    glb_path, out_fbx = args[0], args[1]
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb_path)

    for name in DROP_OBJECTS:
        obj = bpy.data.objects.get(name)
        if obj is not None:
            bpy.data.objects.remove(obj, do_unlink=True)
            print("[pub] 删除装饰物:", name)

    renamed = 0
    for armature in [o for o in bpy.data.objects if o.type == "ARMATURE"]:
        existing = {b.name for b in armature.data.bones}
        for bone in armature.data.bones:
            target = BONE_MAP.get(bone.name)
            if target and target not in existing:
                bone.name = target
                existing.add(target)
                renamed += 1
    print("[pub] 骨骼改名:", renamed)
    add_hand_bones()

    for obj in [o for o in bpy.data.objects if o.type == "MESH"]:
        print("[pub] mesh", obj.name, "verts", len(obj.data.vertices),
              "dims", [round(v, 3) for v in obj.dimensions])

    bpy.ops.export_scene.fbx(
        filepath=out_fbx,
        use_selection=False,
        embed_textures=True,
        path_mode="COPY",
        add_leaf_bones=False,
        bake_anim=True,
        bake_anim_use_all_actions=True,
        mesh_smooth_type="FACE",
        axis_forward="-Z",
        axis_up="Y",
    )
    print("[pub] 导出完成:", out_fbx,
          os.path.getsize(out_fbx) if os.path.exists(out_fbx) else "MISSING")


if __name__ == "__main__":
    main()
