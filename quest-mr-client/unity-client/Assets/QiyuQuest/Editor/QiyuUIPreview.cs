#if UNITY_EDITOR
using System;
using System.IO;
using System.Reflection;
using Qiyu.Quest.UI;
using TMPro;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.UI;

namespace Qiyu.Quest.EditorTools
{
    /// <summary>
    /// 编辑器离屏 UI 预览：把真实的 QiyuMRApp 界面渲染成 PNG。
    ///
    /// 目的：UI 是在头显里的世界空间 Canvas 上运行时搭建的，肉眼只能在头显里看，
    /// 改一次要打包装一次，迭代极慢且容易越改越糟。这里直接在编辑器里
    /// 复现同一套构建代码并截图，用于逐像素核对圆角、遮挡、文字换行。
    ///
    /// 用法：菜单 Qiyu / 渲染 UI 预览图，或命令行
    ///   -executeMethod Qiyu.Quest.EditorTools.QiyuUIPreview.RenderAll
    /// 输出：&lt;工程&gt;/Logs/ui_preview/*.png
    /// </summary>
    public static class QiyuUIPreview
    {
        private const int Width = 1680;
        private const int Height = 1050;
        private const float PanelScale = 0.00105f;

        private static readonly string[] Pages =
        {
            "首页", "对话", "环境", "角色", "设置", "模型决策", "调试",
        };

        [MenuItem("Qiyu/渲染 UI 预览图")]
        public static void RenderAll()
        {
            var outputDir = Path.GetFullPath(
                Path.Combine(Application.dataPath, "..", "Logs", "ui_preview"));
            Directory.CreateDirectory(outputDir);
            Debug.Log($"[QiyuUIPreview] 输出目录 {outputDir}");

            var background = new Color(0.46f, 0.50f, 0.55f, 1f);
            var ok = 0;
            foreach (var page in Pages)
            {
                try
                {
                    var path = Path.Combine(outputDir, $"ui_{Page2Slug(page)}.png");
                    if (RenderPage(page, background, path))
                    {
                        ok++;
                    }
                }
                catch (Exception e)
                {
                    Debug.LogError($"[QiyuUIPreview] 渲染 {page} 失败: {e}");
                }
            }
            Debug.Log($"[QiyuUIPreview] 完成，成功 {ok}/{Pages.Length}");
        }

        /// <summary>
        /// 把界面布局树（名称 / 位置 / 尺寸 / 贴图 / 颜色）打到日志里。
        /// 头显里看不清的问题，用数字最快定位：重叠、零高度、越界都会直接暴露。
        /// </summary>
        [MenuItem("Qiyu/转储 UI 布局树")]
        public static void DumpLayoutMenu()
        {
            DumpLayout("首页", 5);
        }

        private static void DumpLayout(string page, int maxDepth)
        {
            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene,
                NewSceneMode.Single);
            var appObject = new GameObject("QiyuMRApp");
            appObject.SetActive(false);
            var app = appObject.AddComponent<QiyuMRApp>();
            appObject.SetActive(true);
            try
            {
                Invoke(app, "BuildShell");
                Invoke(app, "ShowTab", page);
            }
            catch (Exception e)
            {
                Debug.LogError($"[QiyuUIPreview] 构建 {page} 异常: {e}");
            }

            var canvas = UnityEngine.Object.FindAnyObjectByType<Canvas>();
            if (canvas == null)
            {
                Debug.LogError("[QiyuUIPreview] 没有 Canvas");
                return;
            }
            Canvas.ForceUpdateCanvases();
            LayoutRebuilder.ForceRebuildLayoutImmediate((RectTransform)canvas.transform);
            DumpNode((RectTransform)canvas.transform, 0, maxDepth);
        }

        private static void DumpNode(RectTransform rect, int depth, int maxDepth)
        {
            if (rect == null || depth > maxDepth)
            {
                return;
            }
            var indent = new string(' ', depth * 2);
            var image = rect.GetComponent<Image>();
            var text = rect.GetComponent<TMP_Text>();
            var extra = "";
            if (image != null)
            {
                extra += $" <Image sprite={image.sprite?.name} type={image.type} " +
                         $"color={image.color} enabled={image.enabled}>";
            }
            if (text != null)
            {
                extra += $" <TMP text=\"{Trim(text.text)}\" size={text.fontSize} " +
                         $"color={text.color} wrap={text.textWrappingMode}>";
            }
            Debug.Log($"[UILayout] {indent}{rect.name} size={rect.rect.size} " +
                      $"anchored={rect.anchoredPosition} active={rect.gameObject.activeSelf}" +
                      extra);
            for (var i = 0; i < rect.childCount; i++)
            {
                DumpNode(rect.GetChild(i) as RectTransform, depth + 1, maxDepth);
            }
        }

        private static string Trim(string value)
        {
            if (string.IsNullOrEmpty(value))
            {
                return "";
            }
            var flat = value.Replace("\n", "\\n");
            return flat.Length <= 24 ? flat : flat.Substring(0, 24) + "…";
        }

        /// <summary>只渲染指定页面（逗号分隔），便于快速迭代单页。</summary>
        public static void RenderSelected()
        {
            var spec = Environment.GetEnvironmentVariable("QIYU_PREVIEW_PAGES");
            if (string.IsNullOrEmpty(spec))
            {
                RenderAll();
                return;
            }
            var outputDir = Path.GetFullPath(
                Path.Combine(Application.dataPath, "..", "Logs", "ui_preview"));
            Directory.CreateDirectory(outputDir);
            foreach (var page in spec.Split(','))
            {
                var name = page.Trim();
                if (name.Length == 0)
                {
                    continue;
                }
                RenderPage(name, new Color(0.46f, 0.50f, 0.55f, 1f),
                    Path.Combine(outputDir, $"ui_{Page2Slug(name)}.png"));
            }
        }

        private static string Page2Slug(string page)
        {
            switch (page)
            {
                case "首页": return "home";
                case "对话": return "chat";
                case "环境": return "perception";
                case "角色": return "avatar";
                case "设置": return "settings";
                case "模型决策": return "brain";
                case "调试": return "debug";
                default: return page;
            }
        }

        private static bool RenderPage(string page, Color background, string path)
        {
            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene,
                NewSceneMode.Single);

            var cameraObject = new GameObject("PreviewCamera");
            var camera = cameraObject.AddComponent<Camera>();
            camera.orthographic = true;
            camera.orthographicSize = Height * PanelScale * 0.5f + 0.02f;
            camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = background;
            camera.nearClipPlane = 0.01f;
            camera.farClipPlane = 40f;
            cameraObject.transform.SetPositionAndRotation(
                new Vector3(0f, 0f, -1.5f), Quaternion.identity);

            var appObject = new GameObject("QiyuMRApp");
            appObject.SetActive(false);
            var app = appObject.AddComponent<QiyuMRApp>();
            appObject.SetActive(true);

            var built = false;
            try
            {
                Invoke(app, "BuildShell");
                Invoke(app, "ShowTab", page);
                built = true;
            }
            catch (Exception e)
            {
                Debug.LogError($"[QiyuUIPreview] 构建 {page} 时异常（继续渲染已构建部分）: {e}");
            }
            if (!built)
            {
                // BuildShell 失败时也尽量渲染，方便定位问题。
                Debug.LogWarning($"[QiyuUIPreview] {page} 未完整构建");
            }

            var canvas = UnityEngine.Object.FindFirstObjectByType<Canvas>();
            if (canvas == null)
            {
                Debug.LogError($"[QiyuUIPreview] {page}: 没有找到 Canvas");
                return false;
            }
            var canvasRect = (RectTransform)canvas.transform;
            canvasRect.SetPositionAndRotation(Vector3.zero, Quaternion.identity);
            canvasRect.localScale = Vector3.one * PanelScale;
            canvas.renderMode = RenderMode.WorldSpace;
            canvas.worldCamera = camera;

            Canvas.ForceUpdateCanvases();
            LayoutRebuilder.ForceRebuildLayoutImmediate(canvasRect);
            Canvas.ForceUpdateCanvases();

            return Capture(camera, path, page);
        }

        private static bool Capture(Camera camera, string path, string page)
        {
            var descriptor = new RenderTextureDescriptor(Width, Height,
                RenderTextureFormat.ARGB32, 24);
            descriptor.msaaSamples = 1;
            var target = new RenderTexture(descriptor);
            target.Create();

            RenderInto(camera, target, false);
            var contrast = ReadBack(target, path);
            if (contrast < 12)
            {
                // Camera.Render 在 URP 下可能拿不到内容，改走 URP 的提交渲染请求。
                RenderInto(camera, target, true);
                contrast = ReadBack(target, path);
            }

            target.Release();
            UnityEngine.Object.DestroyImmediate(target);

            var flat = contrast < 12;
            Debug.Log($"[QiyuUIPreview] {page} → {path} 对比度={contrast} " +
                      (flat ? "【疑似空白，渲染管线未生效】" : "OK"));
            return !flat;
        }

        /// <summary>读取 RenderTexture 并写出 PNG，返回采样对比度（用于判断是否空白）。</summary>
        private static int ReadBack(RenderTexture target, string path)
        {
            var previous = RenderTexture.active;
            RenderTexture.active = target;
            var texture = new Texture2D(Width, Height, TextureFormat.RGBA32, false);
            texture.ReadPixels(new Rect(0f, 0f, Width, Height), 0, 0);
            texture.Apply();
            RenderTexture.active = previous;

            var pixels = texture.GetPixels32();
            var min = 765;
            var max = 0;
            for (var i = 0; i < pixels.Length; i += 37)
            {
                var value = pixels[i].r + pixels[i].g + pixels[i].b;
                if (value < min)
                {
                    min = value;
                }
                if (value > max)
                {
                    max = value;
                }
            }

            File.WriteAllBytes(path, texture.EncodeToPNG());
            UnityEngine.Object.DestroyImmediate(texture);
            return max - min;
        }

        private static void RenderInto(Camera camera, RenderTexture target, bool useUrpRequest)
        {
            if (useUrpRequest && TryRenderWithUrpRequest(camera, target))
            {
                return;
            }
            camera.targetTexture = target;
            camera.Render();
            camera.targetTexture = null;
        }

        /// <summary>
        /// URP 在编辑器里对 Camera.Render 支持不稳定，这里用反射调用 Unity 6 的
        /// RenderPipeline.SubmitRenderRequest + URP SingleCameraRequest，
        /// 避免编译期强依赖 URP 版本。
        /// </summary>
        private static bool TryRenderWithUrpRequest(Camera camera, RenderTexture target)
        {
            try
            {
                var requestType = FindType("UnityEngine.Rendering.Universal." +
                                           "UniversalRenderPipeline+SingleCameraRequest");
                var pipelineType = FindType("UnityEngine.Rendering.RenderPipeline");
                if (requestType == null || pipelineType == null)
                {
                    return false;
                }
                var request = Activator.CreateInstance(requestType);
                var destinationField = requestType.GetField("destination");
                var destinationProperty = requestType.GetProperty("destination");
                if (destinationField != null)
                {
                    destinationField.SetValue(request, target);
                }
                else if (destinationProperty != null)
                {
                    destinationProperty.SetValue(request, target);
                }
                else
                {
                    return false;
                }

                var supports = pipelineType.GetMethod("SupportsRenderRequest");
                var submit = pipelineType.GetMethod("SubmitRenderRequest");
                if (supports == null || submit == null)
                {
                    return false;
                }
                var supportsGeneric = supports.MakeGenericMethod(requestType);
                var submitGeneric = submit.MakeGenericMethod(requestType);
                if (!(bool)supportsGeneric.Invoke(null, new[] { camera, request }))
                {
                    return false;
                }
                submitGeneric.Invoke(null, new[] { camera, request });
                (request as IDisposable)?.Dispose();
                return true;
            }
            catch (Exception e)
            {
                Debug.LogWarning($"[QiyuUIPreview] URP 提交渲染失败: {e.Message}");
                return false;
            }
        }

        private static Type FindType(string fullName)
        {
            var type = Type.GetType(fullName + ", UnityEngine.CoreModule") ??
                       Type.GetType(fullName);
            if (type != null)
            {
                return type;
            }
            foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
            {
                type = assembly.GetType(fullName);
                if (type != null)
                {
                    return type;
                }
            }
            return null;
        }

        private static void Invoke(object target, string method, params object[] args)
        {
            var info = target.GetType().GetMethod(method,
                BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public);
            if (info == null)
            {
                throw new MissingMethodException(target.GetType().Name, method);
            }
            try
            {
                info.Invoke(target, args);
            }
            catch (TargetInvocationException e) when (e.InnerException != null)
            {
                throw e.InnerException;
            }
        }
    }
}
#endif
