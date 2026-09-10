using System;
using UnityEditor;
using UnityEngine;

namespace Qiyu.Quest.Editor
{
    /// <summary>
    /// 把 Resources/Qiyu/Avatar 下的角色模型按 Humanoid 导入。
    ///
    /// 为什么必须 Humanoid：程序化动作兜底与动作重定向都走
    /// Animator.GetBoneTransform(HumanBodyBones.*)，模型不是 Humanoid 就没有骨骼可驱动。
    /// MMD 转出来的 FBX 骨骼已在 Blender 侧改成 Unity 标准名，这里只负责打开开关。
    /// </summary>
    public class QiyuAvatarImportSetup : AssetPostprocessor
    {
        private const string AvatarFolder = "Assets/QiyuQuest/Resources/Qiyu/Avatar/";

        private void OnPreprocessModel()
        {
            if (!assetPath.StartsWith(AvatarFolder, StringComparison.OrdinalIgnoreCase) ||
                !assetPath.EndsWith(".fbx", StringComparison.OrdinalIgnoreCase))
            {
                return;
            }
            var importer = (ModelImporter)assetImporter;
            importer.animationType = ModelImporterAnimationType.Human;
            importer.avatarSetup = ModelImporterAvatarSetup.CreateFromThisModel;
            importer.importAnimation = false;
            importer.importBlendShapes = true;
            importer.importNormals = ModelImporterNormals.Import;
            importer.materialImportMode = ModelImporterMaterialImportMode.ImportStandard;
            importer.optimizeGameObjects = false;
            importer.isReadable = false;
        }

        private void OnPostprocessModel(GameObject root)
        {
            if (!assetPath.StartsWith(AvatarFolder, StringComparison.OrdinalIgnoreCase))
            {
                return;
            }
            var animator = root.GetComponentInChildren<Animator>();
            var avatar = animator != null ? animator.avatar : null;
            var human = avatar != null && avatar.isHuman;
            Debug.Log($"[QiyuAvatarImport] {assetPath} Humanoid={human} " +
                      (human ? "" : "（绑定不完整，程序化动作会退化）"));
            if (!human)
            {
                Debug.LogWarning(
                    "[QiyuAvatarImport] Humanoid 绑定失败：请检查骨骼名是否为 " +
                    "Hips/Spine/Chest/UpperChest/Neck/Head/LeftUpperArm... 标准名");
            }
        }
    }
}
