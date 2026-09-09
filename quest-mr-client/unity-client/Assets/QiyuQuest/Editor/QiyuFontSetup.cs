using System;
using System.IO;
using System.IO.Compression;
using System.Net;
using System.Text;
using TMPro;
using UnityEditor;
using UnityEngine;
using UnityEngine.TextCore.LowLevel;

namespace Qiyu.Quest.Editor
{
    /// <summary>
    /// 中文 SDF 字体资源管线。
    ///
    /// 世界空间 Canvas 使用旧版 Text 时，字体是位图缩放，头显里移动头部会明显发糊、
    /// 边缘抖动。这里统一改用 TextMeshPro SDF 字体：
    ///   1. 下载 Noto Sans CJK SC（SIL OFL 1.1，可商用）；
    ///   2. 生成动态 TMP_FontAsset，运行时按需把用到的汉字打进图集；
    ///   3. 放入 Resources/Fonts，运行时用 Resources.Load 获取。
    ///
    /// 字体文件体积较大（约 16 MB），不提交进仓库；首次构建自动下载到 Unity 工程。
    /// </summary>
    public static class QiyuFontSetup
    {
        public const string FontFolder = "Assets/QiyuQuest/Fonts";
        public const string FontFileName = "NotoSansCJKsc-Regular.otf";
        public const string FontAssetPath =
            "Assets/QiyuQuest/Resources/Fonts/QiyuCJK SDF.asset";

        private const string FontUrl =
            "https://raw.githubusercontent.com/notofonts/noto-cjk/main/" +
            "Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Regular.otf";

        private const int SamplingPointSize = 64;
        private const int AtlasPadding = 6;
        private const int AtlasSize = 1024;

        [MenuItem("Qiyu/Ensure Chinese SDF Font")]
        public static void EnsureFontAssetsMenu()
        {
            EnsureFontAssets();
        }

        /// <summary>确保 TMP 基础资源、中文字体源文件与 SDF Font Asset 都存在。</summary>
        public static TMP_FontAsset EnsureFontAssets()
        {
            EnsureTmpEssentials();

            var existing = AssetDatabase.LoadAssetAtPath<TMP_FontAsset>(FontAssetPath);
            if (existing != null && existing.atlasTextures != null &&
                existing.atlasTextures.Length > 0)
            {
                ApplyAsDefault(existing);
                return existing;
            }

            var fontPath = EnsureSourceFont();
            var font = AssetDatabase.LoadAssetAtPath<Font>(fontPath);
            if (font == null)
            {
                throw new InvalidOperationException(
                    $"[QiyuFontSetup] Unity 未能导入字体: {fontPath}");
            }

            var fontAsset = TMP_FontAsset.CreateFontAsset(
                font,
                SamplingPointSize,
                AtlasPadding,
                GlyphRenderMode.SDFAA,
                AtlasSize,
                AtlasSize,
                AtlasPopulationMode.Dynamic,
                true);
            if (fontAsset == null)
            {
                throw new InvalidOperationException(
                    "[QiyuFontSetup] TMP 创建中文字体失败，请确认字体 Include Font Data 已开启");
            }

            fontAsset.name = "QiyuCJK SDF";
            fontAsset.atlasPopulationMode = AtlasPopulationMode.Dynamic;
            fontAsset.isMultiAtlasTexturesEnabled = true;
            if (fontAsset.atlasTextures != null && fontAsset.atlasTextures.Length > 0)
            {
                fontAsset.atlasTextures[0].name = "QiyuCJK SDF Atlas";
            }
            if (fontAsset.material != null)
            {
                fontAsset.material.name = "QiyuCJK SDF Material";
            }

            Directory.CreateDirectory(Path.GetDirectoryName(FontAssetPath) ?? FontFolder);
            AssetDatabase.CreateAsset(fontAsset, FontAssetPath);
            if (fontAsset.atlasTextures != null && fontAsset.atlasTextures.Length > 0)
            {
                AssetDatabase.AddObjectToAsset(fontAsset.atlasTextures[0], fontAsset);
            }
            if (fontAsset.material != null)
            {
                AssetDatabase.AddObjectToAsset(fontAsset.material, fontAsset);
            }
            EditorUtility.SetDirty(fontAsset);
            AssetDatabase.SaveAssets();
            AssetDatabase.ImportAsset(FontAssetPath, ImportAssetOptions.ForceUpdate);

            // 预热 UI 里固定会出现的字符，避免首次进入界面时一帧内批量生成字形。
            fontAsset.TryAddCharacters(StaticUiCharacters, out _);
            EditorUtility.SetDirty(fontAsset);
            AssetDatabase.SaveAssets();

            ApplyAsDefault(fontAsset);
            Debug.Log($"[QiyuFontSetup] 中文字体资源已生成: {FontAssetPath}");
            return fontAsset;
        }

        private static void EnsureTmpEssentials()
        {
            if (Resources.Load<TMP_Settings>("TMP Settings") != null)
            {
                return;
            }

            var packagePath = FindTmpEssentialsPackage();
            if (!string.IsNullOrEmpty(packagePath))
            {
                ExtractUnityPackage(packagePath, ProjectRoot);
                AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
                Debug.Log("[QiyuFontSetup] 已解包 TMP Essential Resources");
            }
            else
            {
                try
                {
                    TMP_PackageUtilities.ImportProjectResourcesMenu();
                    AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
                }
                catch (Exception e)
                {
                    throw new InvalidOperationException(
                        "[QiyuFontSetup] 导入 TMP Essential Resources 失败: " + e.Message, e);
                }
            }

            if (Resources.Load<TMP_Settings>("TMP Settings") == null)
            {
                throw new InvalidOperationException(
                    "[QiyuFontSetup] TMP Settings 仍未生成，请检查 " +
                    "Assets/TextMesh Pro/Resources/TMP Settings.asset");
            }
        }

        private static string ProjectRoot =>
            Path.GetFullPath(Path.Combine(Application.dataPath, ".."));

        private static string FindTmpEssentialsPackage()
        {
            var packageCache = Path.Combine(ProjectRoot, "Library", "PackageCache");
            if (!Directory.Exists(packageCache))
            {
                return null;
            }
            foreach (var dir in Directory.GetDirectories(packageCache, "com.unity.ugui@*"))
            {
                var candidate = Path.Combine(dir, "Package Resources",
                    "TMP Essential Resources.unitypackage");
                if (File.Exists(candidate))
                {
                    return candidate;
                }
            }
            return null;
        }

        /// <summary>
        /// 直接解包 Unity Package（gzip + tar）。
        /// batchmode 下 TMP 自带的异步导入在 -quit 前不会完成，这里同步解包最稳。
        /// </summary>
        private static void ExtractUnityPackage(string packagePath, string projectRoot)
        {
            using var file = File.OpenRead(packagePath);
            using var gzip = new GZipStream(file, CompressionMode.Decompress);
            var entries = new System.Collections.Generic.Dictionary<
                string, PackageEntry>();
            var header = new byte[512];

            while (true)
            {
                if (!ReadExactly(gzip, header, header.Length))
                {
                    break;
                }
                var name = ReadTarString(header, 0, 100);
                if (string.IsNullOrEmpty(name))
                {
                    break;
                }
                var size = ReadTarOctal(header, 124, 12);
                var type = (char)header[156];
                var data = new byte[(int)size];
                if (size > 0 && !ReadExactly(gzip, data, data.Length))
                {
                    break;
                }
                var padding = (int)((512 - (size % 512)) % 512);
                if (padding > 0)
                {
                    SkipExactly(gzip, padding);
                }
                if (type != '0' && type != '\0')
                {
                    continue;
                }

                var parts = name.TrimStart('/', '.').Split('/');
                if (parts.Length < 2)
                {
                    continue;
                }
                var guid = parts[0];
                var fileName = parts[1];
                if (!entries.TryGetValue(guid, out var entry))
                {
                    entry = new PackageEntry();
                    entries[guid] = entry;
                }
                if (fileName == "pathname")
                {
                    entry.Path = Encoding.UTF8.GetString(data).Trim();
                }
                else if (fileName == "asset")
                {
                    entry.Asset = data;
                }
                else if (fileName == "asset.meta")
                {
                    entry.Meta = data;
                }
            }

            foreach (var entry in entries.Values)
            {
                if (string.IsNullOrEmpty(entry.Path))
                {
                    continue;
                }
                var relative = entry.Path.Replace('\\', '/');
                var target = Path.Combine(projectRoot,
                    relative.Replace('/', Path.DirectorySeparatorChar));
                if (relative.EndsWith("/", StringComparison.Ordinal))
                {
                    Directory.CreateDirectory(target);
                    continue;
                }
                Directory.CreateDirectory(Path.GetDirectoryName(target) ?? projectRoot);
                if (entry.Asset != null)
                {
                    File.WriteAllBytes(target, entry.Asset);
                }
                if (entry.Meta != null)
                {
                    File.WriteAllBytes(target + ".meta", entry.Meta);
                }
            }
        }

        private sealed class PackageEntry
        {
            public string Path;
            public byte[] Asset;
            public byte[] Meta;
        }

        private static bool ReadExactly(Stream stream, byte[] buffer, int length)
        {
            var offset = 0;
            while (offset < length)
            {
                var read = stream.Read(buffer, offset, length - offset);
                if (read <= 0)
                {
                    return false;
                }
                offset += read;
            }
            return true;
        }

        private static void SkipExactly(Stream stream, int length)
        {
            var buffer = new byte[Math.Min(512, Math.Max(1, length))];
            var remaining = length;
            while (remaining > 0)
            {
                var read = stream.Read(buffer, 0, Math.Min(buffer.Length, remaining));
                if (read <= 0)
                {
                    return;
                }
                remaining -= read;
            }
        }

        private static string ReadTarString(byte[] buffer, int offset, int length)
        {
            var end = offset;
            var limit = offset + length;
            while (end < limit && buffer[end] != 0)
            {
                end++;
            }
            return Encoding.UTF8.GetString(buffer, offset, end - offset).Trim();
        }

        private static long ReadTarOctal(byte[] buffer, int offset, int length)
        {
            long value = 0;
            for (var i = offset; i < offset + length; i++)
            {
                var c = buffer[i];
                if (c == 0 || c == ' ')
                {
                    continue;
                }
                if (c < '0' || c > '7')
                {
                    break;
                }
                value = value * 8 + (c - '0');
            }
            return value;
        }

        private static string EnsureSourceFont()
        {
            Directory.CreateDirectory(FontFolder);
            var fontPath = Path.Combine(FontFolder, FontFileName);
            var fullPath = Path.GetFullPath(fontPath);
            if (File.Exists(fullPath) && new FileInfo(fullPath).Length > 1024 * 1024)
            {
                EnsureFontImportSettings(fontPath);
                return fontPath;
            }

            Debug.Log($"[QiyuFontSetup] 正在下载中文字体: {FontUrl}");
            var tempPath = fullPath + ".download";
            try
            {
                DownloadFile(FontUrl, tempPath);
                if (!File.Exists(tempPath) || new FileInfo(tempPath).Length < 1024 * 1024)
                {
                    throw new InvalidOperationException("下载文件不完整");
                }
                if (File.Exists(fullPath))
                {
                    File.Delete(fullPath);
                }
                File.Move(tempPath, fullPath);
            }
            catch (Exception e)
            {
                if (File.Exists(tempPath))
                {
                    File.Delete(tempPath);
                }
                throw new InvalidOperationException(
                    $"[QiyuFontSetup] 下载中文字体失败: {e.Message}\n" +
                    $"请手动下载 {FontUrl} 到 {fontPath}", e);
            }

            AssetDatabase.ImportAsset(fontPath, ImportAssetOptions.ForceUpdate);
            EnsureFontImportSettings(fontPath);
            Debug.Log($"[QiyuFontSetup] 中文字体已就绪: {fontPath}");
            return fontPath;
        }

        private static void EnsureFontImportSettings(string fontPath)
        {
            var importer = AssetImporter.GetAtPath(fontPath) as TrueTypeFontImporter;
            if (importer == null)
            {
                return;
            }
            if (!importer.includeFontData)
            {
                importer.includeFontData = true;
                importer.SaveAndReimport();
                Debug.Log("[QiyuFontSetup] 已开启字体 Include Font Data");
            }
        }

        private static void ApplyAsDefault(TMP_FontAsset fontAsset)
        {
            try
            {
                if (TMP_Settings.instance != null)
                {
                    TMP_Settings.defaultFontAsset = fontAsset;
                    EditorUtility.SetDirty(TMP_Settings.instance);
                    AssetDatabase.SaveAssets();
                }
            }
            catch (Exception e)
            {
                Debug.LogWarning("[QiyuFontSetup] 设置 TMP 默认字体失败: " + e.Message);
            }
        }

        private static void DownloadFile(string url, string targetPath)
        {
            ServicePointManager.SecurityProtocol |= SecurityProtocolType.Tls12;
            var request = (HttpWebRequest)WebRequest.Create(url);
            request.UserAgent = "QiyuQuest-Unity-Build";
            request.Timeout = 180000;
            request.ReadWriteTimeout = 180000;
            using var response = request.GetResponse();
            using var input = response.GetResponseStream();
            using var output = File.Create(targetPath);
            input?.CopyTo(output);
        }

        // UI 固定文案里出现的字符 + ASCII + 常用标点，构建时预热。
        private const string StaticUiCharacters =
            "栖语Quest MR Companion Runtime 首页对话环境角色设置模型决策调试" +
            "已未连接握手会话麦克风开关空闲播放最近事件快捷操作运行状态房间锚点墙" +
            "地面天花板导航可行走面积识别物体暂无抓帧重新扫描导入移除缩放高度偏移" +
            "表情动作说话支持格式本地下载未来后端下发链路主脑需要时复杂任务自动升级" +
            "说明骨骼路径由本地执行层决定温度灵敏度增益启用服务端心跳测试应用重连" +
            "恢复默认清空显示还没有记录戴上头显直接或回点语音输入打断确认取消完成" +
            "键盘空格删除清空返回发送内容输入模型地址路径预留视场角刷新率渲染倍率" +
            "抗锯齿注视点渲染质量高级诊断世界状态帧率延迟权限相机场景空间理解深度" +
            "物体检测空间动作情绪关系记忆长期人格主界面" +
            "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz" +
            " .,:;!?@#%&*()[]{}<>+-=_/\\|~`'\"·—…、。，！？；：（）【】《》“”‘’";
    }
}
