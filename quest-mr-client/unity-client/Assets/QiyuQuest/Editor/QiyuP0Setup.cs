using System;
using System.IO;
using System.Linq;
using Meta.XR;
using Meta.XR.BuildingBlocks.AIBlocks;
using Meta.XR.EnvironmentDepth;
using Meta.XR.MRUtilityKit;
using Qiyu.Quest.Avatar;
using Qiyu.Quest.Networking;
using Qiyu.Quest.Perception;
using Qiyu.Quest.Spatial;
using Qiyu.Quest.UI;
using Qiyu.Quest.Voice;
using UnityEditor;
using UnityEditor.Build;
using UnityEditor.SceneManagement;
using UnityEditor.XR.Management;
using UnityEditor.XR.Management.Metadata;
using UnityEditor.XR.OpenXR.Features;
using UnityEngine;
using UnityEngine.Rendering.Universal;
using UnityEngine.SceneManagement;
using UnityEngine.XR.Management;

namespace Qiyu.Quest.Editor
{
    public static class QiyuP0Setup
    {
        private const string ScenePath = "Assets/QiyuQuest/Scenes/QiyuP0.unity";
        private const string XRSettingsPath = "Assets/XR/Settings/XRGeneralSettingsPerBuildTarget.asset";
        private const string OpenXRLoaderType = "UnityEngine.XR.OpenXR.OpenXRLoader";
        private const string MetaFeatureSetId = "com.unity.openxr.featureset.meta";

        [MenuItem("Qiyu/Setup P0 Quest Scene")]
        public static void SetupP0Scene()
        {
            ConfigurePlayer();
            ConfigureOpenXR();
            ConfigureRenderPipelineForPassthrough();
            EnsureAndroidGradleTemplate();
            CreateScene();
            ConfigureBuildSettings();
            AssetDatabase.SaveAssets();
            AssetDatabase.Refresh();
            Debug.Log("[QiyuP0Setup] P0 scene setup complete.");
        }

        [MenuItem("Qiyu/Build P0 APK")]
        public static void BuildP0Apk()
        {
            SetupP0Scene();
            if (EditorUserBuildSettings.activeBuildTarget != BuildTarget.Android)
            {
                EditorUserBuildSettings.SwitchActiveBuildTarget(
                    BuildTargetGroup.Android,
                    BuildTarget.Android);
            }
            var output = Path.GetFullPath(Path.Combine(Application.dataPath, "../Builds/QiyuQuestP0.apk"));
            Directory.CreateDirectory(Path.GetDirectoryName(output) ?? "Builds");
            var options = new BuildPlayerOptions
            {
                scenes = new[] { ScenePath },
                locationPathName = output,
                target = BuildTarget.Android,
                options = BuildOptions.None
            };
            var report = BuildPipeline.BuildPlayer(options);
            Debug.Log($"[QiyuP0Setup] Build result={report.summary.result} " +
                      $"size={report.summary.totalSize} output={output}");
            if (report.summary.result != UnityEditor.Build.Reporting.BuildResult.Succeeded)
            {
                throw new BuildFailedException("[QiyuP0Setup] Android build failed");
            }
        }

        private static void ConfigurePlayer()
        {
            PlayerSettings.companyName = "Qiyu";
            PlayerSettings.productName = "Qiyu Quest";
            PlayerSettings.colorSpace = ColorSpace.Linear;
            PlayerSettings.SetApplicationIdentifier(BuildTargetGroup.Android, "com.qiyu.quest");
            PlayerSettings.SetScriptingBackend(BuildTargetGroup.Android, ScriptingImplementation.IL2CPP);
            PlayerSettings.Android.targetArchitectures = AndroidArchitecture.ARM64;
            PlayerSettings.Android.minSdkVersion = AndroidSdkVersions.AndroidApiLevel32;
            PlayerSettings.Android.targetSdkVersion = AndroidSdkVersions.AndroidApiLevel34;
            PlayerSettings.SetManagedStrippingLevel(BuildTargetGroup.Android, ManagedStrippingLevel.Medium);
            EditorUserBuildSettings.androidBuildSystem = AndroidBuildSystem.Gradle;
            EditorUserBuildSettings.androidBuildSubtarget = MobileTextureSubtarget.ASTC;

            // P4：Passthrough Camera Access 需要在项目配置里开启，
            // 由 Meta 官方 OVRManifestPreprocessor 自动写入 manifest 权限。
            try
            {
                var projectConfig = OVRProjectConfig.CachedProjectConfig;
                if (projectConfig != null)
                {
                    projectConfig.isPassthroughCameraAccessEnabled = true;
                    // MR 必需：Passthrough + Scene + Anchor 必须在项目配置里启用，
                    // 否则 Meta 的 manifest 预处理器不会写入 PASSTHROUGH / USE_SCENE /
                    // horizonos.permission.HEADSET_CAMERA，运行时透视层也不会创建。
                    projectConfig.insightPassthroughEnabled = true;
                    projectConfig.insightPassthroughSupport =
                        OVRProjectConfig.FeatureSupport.Required;
                    projectConfig.sceneSupport =
                        OVRProjectConfig.FeatureSupport.Required;
                    projectConfig.anchorSupport = OVRProjectConfig.AnchorSupport.Enabled;
                    projectConfig.handTrackingSupport =
                        OVRProjectConfig.HandTrackingSupport.ControllersAndHands;
                    OVRProjectConfig.CommitProjectConfig(projectConfig);
                }
            }
            catch (Exception e)
            {
                Debug.LogWarning($"[QiyuP0Setup] 开启 Passthrough Camera Access 失败: {e.Message}");
            }
        }

        private static void ConfigureOpenXR()
        {
            var perTarget = AssetDatabase.LoadAssetAtPath<XRGeneralSettingsPerBuildTarget>(XRSettingsPath);
            if (perTarget == null)
            {
                Directory.CreateDirectory(Path.GetDirectoryName(XRSettingsPath) ?? "Assets/XR/Settings");
                perTarget = ScriptableObject.CreateInstance<XRGeneralSettingsPerBuildTarget>();
                AssetDatabase.CreateAsset(perTarget, XRSettingsPath);
                EditorBuildSettings.AddConfigObject(XRGeneralSettings.settingsKey, perTarget, true);
            }

            if (!perTarget.HasSettingsForBuildTarget(BuildTargetGroup.Android))
            {
                perTarget.CreateDefaultSettingsForBuildTarget(BuildTargetGroup.Android);
            }
            var settings = perTarget.SettingsForBuildTarget(BuildTargetGroup.Android);
            if (settings.Manager == null)
            {
                perTarget.CreateDefaultManagerSettingsForBuildTarget(BuildTargetGroup.Android);
                settings = perTarget.SettingsForBuildTarget(BuildTargetGroup.Android);
            }
            if (!XRPackageMetadataStore.IsLoaderAssigned(OpenXRLoaderType, BuildTargetGroup.Android))
            {
                XRPackageMetadataStore.AssignLoader(
                    settings.Manager,
                    OpenXRLoaderType,
                    BuildTargetGroup.Android);
            }

            OpenXRFeatureSetManager.InitializeFeatureSets();
            var metaSet = OpenXRFeatureSetManager.GetFeatureSetWithId(
                BuildTargetGroup.Android,
                MetaFeatureSetId);
            if (metaSet != null)
            {
                metaSet.isEnabled = true;
                OpenXRFeatureSetManager.SetFeaturesFromEnabledFeatureSets(BuildTargetGroup.Android);
            }
            else
            {
                Debug.LogWarning($"[QiyuP0Setup] 未找到 OpenXR Feature Set: {MetaFeatureSetId}");
            }
            AssetDatabase.SaveAssets();
        }

        /// <summary>
        /// Passthrough Underlay 依赖眼睛缓冲区的 alpha=0。
        /// URP 默认关闭 "Allow Post Process Alpha Output"，会把 alpha 强制为 1，
        /// 导致真实世界被完全遮住（表现为纯黑）。这里为所有 URP Asset 打开。
        /// </summary>
        private static void ConfigureRenderPipelineForPassthrough()
        {
            var guids = AssetDatabase.FindAssets("t:UniversalRenderPipelineAsset");
            foreach (var guid in guids)
            {
                var path = AssetDatabase.GUIDToAssetPath(guid);
                var asset = AssetDatabase.LoadAssetAtPath<UniversalRenderPipelineAsset>(path);
                if (asset == null)
                {
                    continue;
                }
                var serialized = new SerializedObject(asset);
                var property = serialized.FindProperty("m_AllowPostProcessAlphaOutput");
                if (property != null && !property.boolValue)
                {
                    property.boolValue = true;
                    serialized.ApplyModifiedPropertiesWithoutUndo();
                    EditorUtility.SetDirty(asset);
                    Debug.Log($"[QiyuP0Setup] 已开启 URP Alpha Output: {path}");
                }
            }
            AssetDatabase.SaveAssets();
        }

        /// <summary>
        /// 安装自定义 Launcher Gradle 模板。
        /// 仅用于修复 OpenXR 包与 Meta OVRPlugin 重复携带
        /// libopenxr_loader.so 导致 AGP 9 mergeNativeLibs 失败的问题，
        /// 不覆盖任何 Unity 官方能力。
        /// </summary>
        private static void EnsureAndroidGradleTemplate()
        {
            const string sourcePath =
                "Assets/QiyuQuest/Editor/Templates/launcherTemplate.gradle";
            const string targetDir = "Assets/Plugins/Android";
            const string targetPath = targetDir + "/launcherTemplate.gradle";

            var sourceFullPath = Path.GetFullPath(sourcePath);
            if (!File.Exists(sourceFullPath))
            {
                throw new FileNotFoundException(
                    $"找不到 Launcher Gradle 模板: {sourcePath}");
            }
            var sourceText = File.ReadAllText(sourceFullPath);

            Directory.CreateDirectory(targetDir);
            var targetFullPath = Path.GetFullPath(targetPath);
            if (!File.Exists(targetFullPath) ||
                File.ReadAllText(targetFullPath) != sourceText)
            {
                File.WriteAllText(targetFullPath, sourceText);
                Debug.Log($"[QiyuP0Setup] 已写入 Android Launcher Gradle 模板: {targetPath}");
            }
            AssetDatabase.ImportAsset(targetPath, ImportAssetOptions.ForceUpdate);
        }

        private static void CreateScene()
        {
            Directory.CreateDirectory("Assets/QiyuQuest/Scenes");
            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            scene.name = "QiyuP0";

            var cameraRigPrefab = AssetDatabase.LoadAssetAtPath<GameObject>(
                "Packages/com.meta.xr.sdk.core/Prefabs/OVRCameraRig.prefab");
            if (cameraRigPrefab == null)
            {
                throw new InvalidOperationException("找不到 Meta OVRCameraRig prefab");
            }
            var cameraRig = (GameObject)PrefabUtility.InstantiatePrefab(cameraRigPrefab, scene);
            cameraRig.name = "OVRCameraRig";

            var manager = cameraRig.GetComponentInChildren<OVRManager>(true);
            if (manager != null)
            {
                manager.isInsightPassthroughEnabled = true;
                EditorUtility.SetDirty(manager);
            }

            var centerEye = cameraRig.GetComponentsInChildren<Transform>(true)
                .FirstOrDefault(t => t.name == "CenterEyeAnchor");
            if (centerEye != null)
            {
                var passthrough = centerEye.GetComponent<OVRPassthroughLayer>();
                if (passthrough == null)
                {
                    passthrough = centerEye.gameObject.AddComponent<OVRPassthroughLayer>();
                }
                passthrough.overlayType = OVROverlay.OverlayType.Underlay;
                passthrough.hidden = false;
                EditorUtility.SetDirty(passthrough);

                // Passthrough 是 Underlay：眼睛相机必须输出透明背景，
                // 否则 Skybox/不透明黑色会把真实世界完全挡住。
                var eyeCamera = centerEye.GetComponent<Camera>();
                if (eyeCamera != null)
                {
                    eyeCamera.clearFlags = CameraClearFlags.SolidColor;
                    eyeCamera.backgroundColor = new Color(0f, 0f, 0f, 0f);
                    EditorUtility.SetDirty(eyeCamera);
                }
            }

            var runtimeRoot = new GameObject("QiyuP0Runtime");
            runtimeRoot.AddComponent<MRUK>();

            var effectMesh = runtimeRoot.AddComponent<EffectMesh>();
            effectMesh.MeshMaterial = AssetDatabase.LoadAssetAtPath<Material>(
                "Packages/com.meta.xr.mrutilitykit/Core/Materials/MRUKLit.mat");
            effectMesh.Colliders = true;
            effectMesh.HideMesh = false;
            effectMesh.SpawnOnStart = MRUK.RoomFilter.CurrentRoomOnly;

            var summary = runtimeRoot.AddComponent<MrukSceneSummary>();
            var client = runtimeRoot.AddComponent<QiyuQuestWebSocketClient>();
            var publisher = runtimeRoot.AddComponent<MrukWorldStatePublisher>();
            var navMeshBuilder = runtimeRoot.AddComponent<RoomNavMeshBuilder>();

            // P2：语音闭环
            var ttsObject = new GameObject("QiyuTTS");
            ttsObject.transform.SetParent(runtimeRoot.transform, false);
            var audioSource = ttsObject.AddComponent<AudioSource>();
            audioSource.playOnAwake = false;
            audioSource.spatialBlend = 0f;
            var ttsPlayer = ttsObject.AddComponent<QuestTtsPlayer>();
            var microphone = runtimeRoot.AddComponent<QuestMicrophoneCapture>();
            var voiceLoop = runtimeRoot.AddComponent<QuestVoiceLoop>();

            // P3：AvatarIntent 路由（Avatar 骨骼/驱动后续挂到场景角色上）
            var avatarRouter = runtimeRoot.AddComponent<AvatarIntentRouter>();

            // P4：Passthrough Camera + 深度 + 物体投影
            var cameraAccess = runtimeRoot.AddComponent<PassthroughCameraAccess>();
            cameraAccess.CameraPosition = PassthroughCameraAccess.CameraPositionType.Left;
            cameraAccess.RequestedResolution = new Vector2Int(1280, 960);
            var frameSource = runtimeRoot.AddComponent<PassthroughFrameSource>();

            var depthObject = new GameObject("QiyuDepth");
            depthObject.transform.SetParent(runtimeRoot.transform, false);
            DepthTextureAccess depthAccess = null;
            try
            {
                depthObject.AddComponent<EnvironmentDepthManager>();
                depthAccess = depthObject.AddComponent<DepthTextureAccess>();
            }
            catch (Exception e)
            {
                Debug.LogWarning($"[QiyuP0Setup] Environment Depth 组件不可用: {e.Message}");
            }
            var projector = runtimeRoot.AddComponent<ObjectDetectionProjector>();
            runtimeRoot.AddComponent<QuestPermissionsBootstrap>();
            var debugPanel = runtimeRoot.AddComponent<QuestDebugPanel>();
            runtimeRoot.AddComponent<PassthroughDiagnostics>();

            var serverUrl = Environment.GetEnvironmentVariable("QIYU_QUEST_WS_URL");
            if (string.IsNullOrWhiteSpace(serverUrl))
            {
                serverUrl = "ws://192.168.2.68:8766/v1/quest/ws";
            }
            var clientSerialized = new SerializedObject(client);
            clientSerialized.FindProperty("serverUrl").stringValue = serverUrl;
            clientSerialized.ApplyModifiedPropertiesWithoutUndo();

            var publisherSerialized = new SerializedObject(publisher);
            publisherSerialized.FindProperty("webSocketClient").objectReferenceValue = client;
            publisherSerialized.FindProperty("sceneSummary").objectReferenceValue = summary;
            publisherSerialized.FindProperty("navMeshBuilder").objectReferenceValue = navMeshBuilder;
            publisherSerialized.ApplyModifiedPropertiesWithoutUndo();

            Wire(navMeshBuilder, ("sceneSummary", summary));
            Wire(microphone, ("webSocketClient", client));
            Wire(ttsPlayer, ("webSocketClient", client));
            Wire(voiceLoop, ("webSocketClient", client), ("microphone", microphone),
                ("ttsPlayer", ttsPlayer));
            Wire(avatarRouter, ("webSocketClient", client), ("ttsPlayer", ttsPlayer));
            Wire(frameSource, ("webSocketClient", client), ("cameraAccess", cameraAccess));
            Wire(projector, ("webSocketClient", client), ("cameraAccess", cameraAccess),
                ("depthAccess", depthAccess), ("sceneSummary", summary),
                ("worldStatePublisher", publisher));
            Wire(debugPanel, ("webSocketClient", client), ("microphone", microphone),
                ("ttsPlayer", ttsPlayer), ("frameSource", frameSource),
                ("sceneSummary", summary));

            var lightObject = new GameObject("Directional Light");
            var light = lightObject.AddComponent<Light>();
            light.type = LightType.Directional;
            light.intensity = 1.0f;
            lightObject.transform.rotation = Quaternion.Euler(50f, -30f, 0f);

            EditorSceneManager.SaveScene(scene, ScenePath);
            Selection.activeGameObject = runtimeRoot;
        }

        private static void Wire(UnityEngine.Object target,
                                 params (string field, UnityEngine.Object value)[] fields)
        {
            var serialized = new SerializedObject(target);
            foreach (var (field, value) in fields)
            {
                var property = serialized.FindProperty(field);
                if (property == null)
                {
                    Debug.LogWarning($"[QiyuP0Setup] 字段不存在: {target.GetType().Name}.{field}");
                    continue;
                }
                property.objectReferenceValue = value;
            }
            serialized.ApplyModifiedPropertiesWithoutUndo();
        }

        private static void ConfigureBuildSettings()
        {
            EditorBuildSettings.scenes = new[]
            {
                new EditorBuildSettingsScene(ScenePath, true)
            };
        }
    }
}
