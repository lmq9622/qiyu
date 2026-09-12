using System;
using System.Collections.Generic;
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
        /// <summary>用户动捕镜像 Avatar（公开模型，独立于主角色模型）。</summary>
        private const string MirrorFolder = "Assets/QiyuQuest/Resources/Qiyu/Mirror/";

        private void OnPreprocessModel()
        {
            var isAvatar = assetPath.StartsWith(AvatarFolder, StringComparison.OrdinalIgnoreCase);
            var isMirror = assetPath.StartsWith(MirrorFolder, StringComparison.OrdinalIgnoreCase);
            if ((!isAvatar && !isMirror) ||
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
            if (isMirror)
            {
                // 优先用已生成的 Avatar 资产（ModelImporter 自动映射在这个骨架上不生效）
                var avatarPath = MirrorFolder + "QiyuMirrorAvatar.asset";
                var mirrorAvatar = AssetDatabase.LoadAssetAtPath<UnityEngine.Avatar>(avatarPath);
                if (mirrorAvatar != null && mirrorAvatar.isValid)
                {
                    importer.avatarSetup = ModelImporterAvatarSetup.CopyFromOther;
                    importer.sourceAvatar = mirrorAvatar;
                }
                else
                {
                    ApplyExplicitHumanoid(importer);
                }
            }
        }

        /// <summary>
        /// 显式声明 Humanoid 骨骼映射。
        /// 镜像模型（CesiumMan）没有手部骨骼，Unity 自动映射会失败，
        /// 这里把我们实际有的骨骼按标准名一一对应上。
        /// </summary>
        private static void ApplyExplicitHumanoid(ModelImporter importer)
        {
            var bones = new List<HumanBone>();
            void Add(string humanName)
            {
                bones.Add(new HumanBone
                {
                    boneName = humanName,
                    humanName = humanName,
                    limit = new HumanLimit { useDefaultValues = true },
                });
            }
            Add("Hips");
            Add("Spine");
            Add("Chest");
            Add("Neck");
            Add("Head");
            Add("LeftShoulder");
            Add("LeftUpperArm");
            Add("LeftLowerArm");
            Add("LeftHand");
            Add("RightShoulder");
            Add("RightUpperArm");
            Add("RightLowerArm");
            Add("RightHand");
            Add("LeftUpperLeg");
            Add("LeftLowerLeg");
            Add("LeftFoot");
            Add("LeftToes");
            Add("RightUpperLeg");
            Add("RightLowerLeg");
            Add("RightFoot");
            Add("RightToes");
            var description = importer.humanDescription;
            description.human = bones.ToArray();
            importer.humanDescription = description;
            Debug.Log($"[QiyuAvatarImport] 镜像模型使用显式 Humanoid 映射（{bones.Count} 根骨骼）");
        }

        /// <summary>
        /// 为镜像模型生成并回填 Humanoid Avatar 资产。
        ///
        /// 为什么需要：ModelImporter 的自动映射在这个骨架上不生效（导入结果 Humanoid=False），
        /// 但 AvatarBuilder 用同一套映射能构建出 valid=True 的 Avatar。
        /// 因此这里显式生成 .asset 并用 CopyFromOther 回填给导入器。
        /// 打包前调用，保证每次构建都是 Humanoid。
        /// </summary>
        public static void EnsureMirrorAvatarAsset()
        {
            const string modelPath = MirrorFolder + "QiyuMirrorAvatar.fbx";
            const string avatarPath = MirrorFolder + "QiyuMirrorAvatar.asset";
            var model = AssetDatabase.LoadAssetAtPath<GameObject>(modelPath);
            if (model == null)
            {
                Debug.LogWarning($"[QiyuAvatarImport] 找不到镜像模型 {modelPath}，跳过");
                return;
            }
            var importer = AssetImporter.GetAtPath(modelPath) as ModelImporter;
            var existing = AssetDatabase.LoadAssetAtPath<UnityEngine.Avatar>(avatarPath);
            if (existing == null || !existing.isValid)
            {
                var instance = UnityEngine.Object.Instantiate(model);
                var description = BuildDescription();
                var built = AvatarBuilder.BuildHumanAvatar(instance, description);
                if (built != null && built.isValid)
                {
                    built.name = "QiyuMirrorAvatar";
                    AssetDatabase.CreateAsset(built, avatarPath);
                    AssetDatabase.SaveAssets();
                    Debug.Log("[QiyuAvatarImport] 已生成镜像 Humanoid Avatar 资产");
                }
                else
                {
                    Debug.LogWarning("[QiyuAvatarImport] AvatarBuilder 构建失败");
                }
                UnityEngine.Object.DestroyImmediate(instance);
            }
            var avatar = AssetDatabase.LoadAssetAtPath<UnityEngine.Avatar>(avatarPath);
            if (avatar == null || importer == null)
            {
                return;
            }
            if (importer.animationType != ModelImporterAnimationType.Human ||
                importer.avatarSetup != ModelImporterAvatarSetup.CopyFromOther ||
                importer.sourceAvatar != avatar)
            {
                importer.animationType = ModelImporterAnimationType.Human;
                importer.avatarSetup = ModelImporterAvatarSetup.CopyFromOther;
                importer.sourceAvatar = avatar;
                importer.SaveAndReimport();
                Debug.Log("[QiyuAvatarImport] 已把镜像 Avatar 回填给导入器");
            }
        }

        private static HumanDescription BuildDescription()
        {
            var bones = new List<HumanBone>();
            foreach (var humanName in BoneNames)
            {
                bones.Add(new HumanBone
                {
                    boneName = humanName,
                    humanName = humanName,
                    limit = new HumanLimit { useDefaultValues = true },
                });
            }
            return new HumanDescription
            {
                human = bones.ToArray(),
                skeleton = new SkeletonBone[0],
                upperArmTwist = 0.5f,
                lowerArmTwist = 0.5f,
                upperLegTwist = 0.5f,
                lowerLegTwist = 0.5f,
                armStretch = 0.05f,
                legStretch = 0.05f,
                feetSpacing = 0f,
                hasTranslationDoF = false,
            };
        }

        /// <summary>重新导入镜像模型并输出 Humanoid 结果（调试用）。</summary>
        public static void ReimportMirrorAvatar()
        {
            const string path = MirrorFolder + "QiyuMirrorAvatar.fbx";
            AssetDatabase.ImportAsset(path, ImportAssetOptions.ForceUpdate);
            var model = AssetDatabase.LoadAssetAtPath<GameObject>(path);
            if (model == null)
            {
                Debug.LogWarning($"[QiyuAvatarImport] 找不到 {path}");
                return;
            }
            var prefabAnimator = model.GetComponentInChildren<Animator>();
            var prefabAvatar = prefabAnimator != null ? prefabAnimator.avatar : null;
            Debug.Log($"[QiyuAvatarImport] 资产级 Humanoid=" +
                      $"{(prefabAvatar != null && prefabAvatar.isHuman)} path={path}");
            // 运行时真正起作用的是实例上的 Animator，这里以实例为准
            var probe = UnityEngine.Object.Instantiate(model);
            var instanceAnimator = probe.GetComponentInChildren<Animator>();
            var instanceAvatar = instanceAnimator != null ? instanceAnimator.avatar : null;
            Debug.Log($"[QiyuAvatarImport] 实例级 Humanoid=" +
                      $"{(instanceAvatar != null && instanceAvatar.isHuman)}");
            UnityEngine.Object.DestroyImmediate(probe);
            Diagnose(model);
        }

        /// <summary>打印实际骨骼并尝试手工构建 Avatar，暴露真实失败原因。</summary>
        private static void Diagnose(GameObject model)
        {
            var instance = UnityEngine.Object.Instantiate(model);
            var names = new List<string>();
            foreach (var t in instance.GetComponentsInChildren<Transform>(true))
            {
                names.Add(t.name);
            }
            Debug.Log("[QiyuAvatarImport] 骨骼/节点: " + string.Join(", ", names));
            var bones = new List<HumanBone>();
            foreach (var humanName in BoneNames)
            {
                if (!names.Contains(humanName))
                {
                    Debug.LogWarning($"[QiyuAvatarImport] 缺少骨骼: {humanName}");
                }
                bones.Add(new HumanBone
                {
                    boneName = humanName,
                    humanName = humanName,
                    limit = new HumanLimit { useDefaultValues = true },
                });
            }
            var description = new HumanDescription
            {
                human = bones.ToArray(),
                skeleton = new SkeletonBone[0],
                upperArmTwist = 0.5f,
                lowerArmTwist = 0.5f,
                upperLegTwist = 0.5f,
                lowerLegTwist = 0.5f,
                armStretch = 0.05f,
                legStretch = 0.05f,
                feetSpacing = 0f,
                hasTranslationDoF = false,
            };
            var avatar = AvatarBuilder.BuildHumanAvatar(instance, description);
            Debug.Log($"[QiyuAvatarImport] AvatarBuilder 结果 valid={avatar.isValid} " +
                      $"human={avatar.isHuman}");
            UnityEngine.Object.DestroyImmediate(instance);
        }

        private static readonly string[] BoneNames =
        {
            "Hips", "Spine", "Chest", "Neck", "Head",
            "LeftShoulder", "LeftUpperArm", "LeftLowerArm", "LeftHand",
            "RightShoulder", "RightUpperArm", "RightLowerArm", "RightHand",
            "LeftUpperLeg", "LeftLowerLeg", "LeftFoot", "LeftToes",
            "RightUpperLeg", "RightLowerLeg", "RightFoot", "RightToes",
        };

        private void OnPostprocessModel(GameObject root)
        {
            if (!assetPath.StartsWith(AvatarFolder, StringComparison.OrdinalIgnoreCase) &&
                !assetPath.StartsWith(MirrorFolder, StringComparison.OrdinalIgnoreCase))
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









