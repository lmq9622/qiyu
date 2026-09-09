using System;
using System.Collections.Generic;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace Qiyu.Quest.UI
{
    public enum QiyuButtonVariant
    {
        Glass,
        Primary,
        Danger,
        Ghost,
        Accent
    }

    /// <summary>
    /// Qiyu Quest UI 设计系统（visionOS / liquid glass 风格）。
    ///
    /// 关键渲染约定：
    ///   * 全部文字使用 TextMeshPro SDF（世界空间移动头部时不会像旧 Text 一样发糊）；
    ///   * 所有圆角精灵 4x 超采样 + mipmap + 三线性过滤，避免缩小时的边缘闪烁；
    ///   * 卡片由多层组成：远/中/近投影、渐变玻璃主体、顶部高光、底部折射、
    ///     左上角果冻高光、极细噪点，形成真实的厚度感而不是“平面贴图”。
    /// </summary>
    public static class QiyuUI
    {
        // ---------------- 颜色 ----------------
        public static readonly Color BgBase = Hex("#08080B");
        public static readonly Color Surface = Hex("#15151A");
        public static readonly Color GlassTop = new Color(0.130f, 0.170f, 0.280f, 0.70f);
        public static readonly Color GlassBottom = new Color(0.060f, 0.080f, 0.160f, 0.66f);
        public static readonly Color GlassStrongTop = new Color(0.160f, 0.210f, 0.340f, 0.84f);
        public static readonly Color GlassStrongBottom = new Color(0.070f, 0.090f, 0.180f, 0.82f);
        public static readonly Color BorderTop = new Color(1f, 1f, 1f, 0.26f);
        public static readonly Color BorderBottom = new Color(1f, 1f, 1f, 0.06f);
        public static readonly Color Border = new Color(1f, 1f, 1f, 0.12f);
        public static readonly Color TextPrimary = Hex("#FFFFFF");
        public static readonly Color TextSecondary = Hex("#C7C7CC");
        public static readonly Color TextTertiary = Hex("#8E8E93");
        public static readonly Color Success = Hex("#30D158");
        public static readonly Color Warning = Hex("#FFD60A");
        public static readonly Color Danger = Hex("#FF453A");
        public static readonly Color Accent = Hex("#32D7FF");
        public static readonly Color AccentWarm = Hex("#FF9F0A");
        public static readonly Color AccentPurple = Hex("#BF5AF2");
        public static readonly Color AccentPink = Hex("#FF375F");
        public static readonly Color ChipBg = new Color(1f, 1f, 1f, 0.055f);

        // ---------------- 尺度 ----------------
        public const float Space1 = 4f;
        public const float Space2 = 8f;
        public const float Space3 = 12f;
        public const float Space4 = 16f;
        public const float Space5 = 20f;
        public const float Space6 = 24f;
        public const float Space8 = 32f;
        public const float Space10 = 40f;
        public const int RadiusCard = 28;
        public const int RadiusPanel = 42;
        public const int RadiusButton = 16;
        public const int RadiusSmall = 18;
        public const int RadiusInput = 18;

        /// <summary>兼容旧调用；TMP SDF 不再需要字号补偿。</summary>
        public static float FontScale = 1.2f;

        private const int Supersample = 4;
        private const float BasePixelsPerUnit = 100f;
        private static TMP_FontAsset _fontAsset;
        private static readonly Dictionary<string, Sprite> SpriteCache =
            new Dictionary<string, Sprite>();
        private static Sprite _noiseSprite;

        // ---------------- 字体 ----------------
        public static TMP_FontAsset FontAsset
        {
            get
            {
                if (_fontAsset != null)
                {
                    return _fontAsset;
                }
                _fontAsset = Resources.Load<TMP_FontAsset>("Fonts/QiyuCJK SDF");
                if (_fontAsset == null)
                {
                    try
                    {
                        _fontAsset = TMP_Settings.defaultFontAsset;
                    }
                    catch
                    {
                        _fontAsset = null;
                    }
                }
                if (_fontAsset == null)
                {
                    var fallback = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
                    if (fallback != null)
                    {
                        _fontAsset = TMP_FontAsset.CreateFontAsset(fallback);
                    }
                    Debug.LogWarning(
                        "[QiyuUI] 未找到 QiyuCJK SDF，中文可能显示为方块。请先执行 Qiyu/Ensure Chinese SDF Font");
                }
                return _fontAsset;
            }
        }

        public static Color Hex(string hex)
        {
            return ColorUtility.TryParseHtmlString(hex, out var color) ? color : Color.magenta;
        }

        // ---------------- 基础布局工具 ----------------
        public static RectTransform CreateRect(Transform parent, string name)
        {
            var go = new GameObject(name, typeof(RectTransform));
            go.transform.SetParent(parent, false);
            return (RectTransform)go.transform;
        }

        public static void Stretch(RectTransform rect, float padding = 0f, float vertical = 0f)
        {
            rect.anchorMin = Vector2.zero;
            rect.anchorMax = Vector2.one;
            rect.offsetMin = new Vector2(padding, vertical);
            rect.offsetMax = new Vector2(-padding, -vertical);
        }

        public static void SetAnchored(RectTransform rect, Vector2 anchorMin, Vector2 anchorMax,
                                       Vector2 offsetMin, Vector2 offsetMax)
        {
            rect.anchorMin = anchorMin;
            rect.anchorMax = anchorMax;
            rect.offsetMin = offsetMin;
            rect.offsetMax = offsetMax;
        }

        public static LayoutElement Layout(GameObject go, float minHeight,
                                           float preferredHeight = -1f,
                                           float flexibleWidth = -1f)
        {
            var layout = go.GetComponent<LayoutElement>() ?? go.AddComponent<LayoutElement>();
            layout.minHeight = minHeight;
            layout.preferredHeight = preferredHeight < 0f ? minHeight : preferredHeight;
            if (flexibleWidth >= 0f)
            {
                layout.flexibleWidth = flexibleWidth;
            }
            return layout;
        }

        public static RectTransform VBox(Transform parent, string name, float spacing = Space5,
                                         int padding = 24)
        {
            var rect = CreateRect(parent, name);
            var layout = rect.gameObject.AddComponent<VerticalLayoutGroup>();
            layout.spacing = spacing;
            layout.padding = new RectOffset(padding, padding, padding, padding);
            layout.childControlWidth = true;
            layout.childControlHeight = false;
            layout.childForceExpandWidth = true;
            layout.childForceExpandHeight = false;
            var fitter = rect.gameObject.AddComponent<ContentSizeFitter>();
            fitter.verticalFit = ContentSizeFitter.FitMode.PreferredSize;
            return rect;
        }

        public static RectTransform HBox(Transform parent, string name, float spacing = Space3,
                                         int padding = 0)
        {
            var rect = CreateRect(parent, name);
            var layout = rect.gameObject.AddComponent<HorizontalLayoutGroup>();
            layout.spacing = spacing;
            layout.padding = new RectOffset(padding, padding, padding, padding);
            layout.childControlWidth = true;
            layout.childControlHeight = true;
            layout.childForceExpandWidth = true;
            layout.childForceExpandHeight = true;
            layout.childAlignment = TextAnchor.MiddleCenter;
            return rect;
        }

        public static RectTransform ScrollView(Transform parent, string name,
                                               out RectTransform content,
                                               float spacing = Space6)
        {
            var root = CreateRect(parent, name);
            var scroll = root.gameObject.AddComponent<ScrollRect>();
            scroll.horizontal = false;
            scroll.vertical = true;
            scroll.movementType = ScrollRect.MovementType.Clamped;
            scroll.scrollSensitivity = 42f;
            scroll.inertia = true;
            scroll.decelerationRate = 0.12f;

            var viewport = CreateRect(root, "Viewport");
            Stretch(viewport);
            var viewportImage = viewport.gameObject.AddComponent<Image>();
            viewportImage.color = new Color(0f, 0f, 0f, 0.002f);
            var mask = viewport.gameObject.AddComponent<Mask>();
            mask.showMaskGraphic = false;
            scroll.viewport = viewport;

            content = CreateRect(viewport, "Content");
            content.anchorMin = new Vector2(0f, 1f);
            content.anchorMax = new Vector2(1f, 1f);
            content.pivot = new Vector2(0.5f, 1f);
            content.anchoredPosition = Vector2.zero;
            var layout = content.gameObject.AddComponent<VerticalLayoutGroup>();
            layout.spacing = spacing;
            // 左右留 20px：避免卡片圆角/阴影正好贴在 ScrollRect Mask 边缘被裁掉。
            layout.padding = new RectOffset(20, 20, 4, 24);
            layout.childControlWidth = true;
            layout.childControlHeight = false;
            layout.childForceExpandWidth = true;
            layout.childForceExpandHeight = false;
            var fitter = content.gameObject.AddComponent<ContentSizeFitter>();
            fitter.verticalFit = ContentSizeFitter.FitMode.PreferredSize;
            scroll.content = content;
            return root;
        }

        public static RectTransform Divider(Transform parent, float alpha = 0.07f)
        {
            var rect = CreateRect(parent, "Divider");
            Layout(rect.gameObject, 2f);
            var image = rect.gameObject.AddComponent<Image>();
            image.color = new Color(1f, 1f, 1f, alpha);
            image.raycastTarget = false;
            return rect;
        }

        public static RectTransform Spacer(Transform parent, float height)
        {
            var rect = CreateRect(parent, "Spacer");
            Layout(rect.gameObject, height);
            return rect;
        }

        // ---------------- 文字 ----------------
        public static TMP_Text Label(Transform parent, string name, string text, int size,
                                     Color color, TextAnchor anchor = TextAnchor.UpperLeft,
                                     bool bold = false, bool wrap = true)
        {
            var rect = CreateRect(parent, name);
            var label = rect.gameObject.AddComponent<TextMeshProUGUI>();
            label.font = FontAsset;
            label.text = text ?? "";
            label.fontSize = size * FontScale;
            label.color = color;
            label.alignment = ToTmpAlignment(anchor);
            label.fontStyle = bold ? FontStyles.Bold : FontStyles.Normal;
            label.textWrappingMode = wrap ? TextWrappingModes.Normal
                : TextWrappingModes.NoWrap;
            label.overflowMode = TextOverflowModes.Overflow;
            label.raycastTarget = false;
            label.extraPadding = true;
            label.characterSpacing = 0.5f;
            label.lineSpacing = 4f;
            return label;
        }

        public static TextAlignmentOptions ToTmpAlignment(TextAnchor anchor)
        {
            return anchor switch
            {
                TextAnchor.UpperLeft => TextAlignmentOptions.TopLeft,
                TextAnchor.UpperCenter => TextAlignmentOptions.Top,
                TextAnchor.UpperRight => TextAlignmentOptions.TopRight,
                TextAnchor.MiddleLeft => TextAlignmentOptions.Left,
                TextAnchor.MiddleCenter => TextAlignmentOptions.Center,
                TextAnchor.MiddleRight => TextAlignmentOptions.Right,
                TextAnchor.LowerLeft => TextAlignmentOptions.BottomLeft,
                TextAnchor.LowerCenter => TextAlignmentOptions.Bottom,
                TextAnchor.LowerRight => TextAlignmentOptions.BottomRight,
                _ => TextAlignmentOptions.TopLeft
            };
        }

        // ---------------- 精灵生成 ----------------

        /// <summary>圆角矩形（单色）。</summary>
        public static Sprite RoundedSprite(int radius, Color fill, Color border,
                                           float borderWidth = 1.5f)
        {
            return RoundedSprite(radius, fill, fill, border, border, borderWidth);
        }

        /// <summary>圆角矩形（纵向渐变 + 统一边框色）。</summary>
        public static Sprite RoundedSprite(int radius, Color top, Color bottom, Color border,
                                           float borderWidth = 1.5f)
        {
            return RoundedSprite(radius, top, bottom, border, border, borderWidth);
        }

        /// <summary>圆角矩形（纵向渐变 + 上下不同边框色）。</summary>
        public static Sprite RoundedSprite(int radius, Color top, Color bottom,
                                           Color borderTop, Color borderBottom,
                                           float borderWidth = 1.5f)
        {
            radius = Mathf.Max(2, radius);
            var key = $"r{radius}:{C(top)}:{C(bottom)}:{C(borderTop)}:{C(borderBottom)}:{borderWidth:0.###}";
            if (SpriteCache.TryGetValue(key, out var cached))
            {
                return cached;
            }

            var texRadius = radius * Supersample;
            var center = Supersample * 4;
            var size = texRadius * 2 + center * 2;
            var borderTexels = Mathf.Max(1f, borderWidth * Supersample);
            var tex = NewTexture(size, size);
            var pixels = new Color32[size * size];

            for (var y = 0; y < size; y++)
            {
                var v = size <= 1 ? 0f : y / (float)(size - 1);
                var fill = Color.Lerp(bottom, top, v);
                var borderColor = Color.Lerp(borderBottom, borderTop, v);
                for (var x = 0; x < size; x++)
                {
                    var dx = Mathf.Max(texRadius - x, x - (size - 1 - texRadius), 0);
                    var dy = Mathf.Max(texRadius - y, y - (size - 1 - texRadius), 0);
                    var dist = Mathf.Sqrt(dx * dx + dy * dy) - texRadius;
                    var coverage = Mathf.Clamp01(0.5f - dist);
                    if (coverage <= 0f)
                    {
                        pixels[y * size + x] = new Color32(0, 0, 0, 0);
                        continue;
                    }
                    var borderT = Mathf.Clamp01(
                        1f - Mathf.Abs(dist + borderTexels * 0.5f) /
                        Mathf.Max(0.5f, borderTexels * 0.5f));
                    var color = Color.Lerp(fill, borderColor, borderT);
                    color.a *= coverage;
                    pixels[y * size + x] = color;
                }
            }

            tex.SetPixels32(pixels);
            tex.Apply(true, false);
            var border = new Vector4(texRadius, texRadius, texRadius, texRadius);
            var sprite = Sprite.Create(tex, new Rect(0, 0, size, size),
                new Vector2(0.5f, 0.5f), BasePixelsPerUnit * Supersample, 0,
                SpriteMeshType.FullRect, border);
            sprite.name = key;
            SpriteCache[key] = sprite;
            return sprite;
        }

        /// <summary>径向柔光（用于果冻高光、指示灯、光晕）。</summary>
        public static Sprite RadialSprite(int size, Color inner, Color outer)
        {
            size = Mathf.Clamp(size, 16, 512);
            var key = $"rad{size}:{C(inner)}:{C(outer)}";
            if (SpriteCache.TryGetValue(key, out var cached))
            {
                return cached;
            }
            var tex = NewTexture(size, size);
            var pixels = new Color32[size * size];
            var half = (size - 1) * 0.5f;
            for (var y = 0; y < size; y++)
            {
                for (var x = 0; x < size; x++)
                {
                    var d = Mathf.Sqrt((x - half) * (x - half) +
                                       (y - half) * (y - half)) / half;
                    var t = Mathf.Clamp01(1f - d);
                    var eased = t * t * (3f - 2f * t);
                    pixels[y * size + x] = Color.Lerp(outer, inner, eased);
                }
            }
            tex.SetPixels32(pixels);
            tex.Apply(true, false);
            var sprite = Sprite.Create(tex, new Rect(0, 0, size, size),
                new Vector2(0.5f, 0.5f), BasePixelsPerUnit);
            sprite.name = key;
            SpriteCache[key] = sprite;
            return sprite;
        }

        /// <summary>极细噪点，模拟磨砂玻璃的微观颗粒。</summary>
        public static Sprite NoiseSprite()
        {
            if (_noiseSprite != null)
            {
                return _noiseSprite;
            }
            const int size = 128;
            var random = new System.Random(20260908);
            var tex = NewTexture(size, size);
            tex.wrapMode = TextureWrapMode.Repeat;
            var pixels = new Color32[size * size];
            for (var i = 0; i < pixels.Length; i++)
            {
                var v = (byte)random.Next(0, 256);
                pixels[i] = new Color32(v, v, v, 255);
            }
            tex.SetPixels32(pixels);
            tex.Apply(true, false);
            _noiseSprite = Sprite.Create(tex, new Rect(0, 0, size, size),
                new Vector2(0.5f, 0.5f), BasePixelsPerUnit);
            _noiseSprite.name = "QiyuNoise";
            return _noiseSprite;
        }

        /// <summary>对角线性渐变，用于液态玻璃的镜面扫光。</summary>
        public static Sprite LinearGradientSprite(int size, Color start, Color end,
                                                  float angleDegrees = 135f)
        {
            size = Mathf.Clamp(size, 16, 512);
            var key = $"lin{size}:{C(start)}:{C(end)}:{angleDegrees:0.#}";
            if (SpriteCache.TryGetValue(key, out var cached))
            {
                return cached;
            }
            var tex = NewTexture(size, size);
            var pixels = new Color32[size * size];
            var angle = angleDegrees * Mathf.Deg2Rad;
            var direction = new Vector2(Mathf.Cos(angle), Mathf.Sin(angle)).normalized;
            for (var y = 0; y < size; y++)
            {
                for (var x = 0; x < size; x++)
                {
                    var uv = new Vector2(x / (float)(size - 1), y / (float)(size - 1));
                    var t = Mathf.Clamp01(Vector2.Dot(uv - new Vector2(0.5f, 0.5f),
                        direction) + 0.5f);
                    pixels[y * size + x] = Color.Lerp(start, end, t);
                }
            }
            tex.SetPixels32(pixels);
            tex.Apply(true, false);
            var sprite = Sprite.Create(tex, new Rect(0, 0, size, size),
                new Vector2(0.5f, 0.5f), BasePixelsPerUnit);
            sprite.name = key;
            SpriteCache[key] = sprite;
            return sprite;
        }

        private static Texture2D NewTexture(int width, int height)
        {
            return new Texture2D(width, height, TextureFormat.RGBA32, true)
            {
                filterMode = FilterMode.Trilinear,
                wrapMode = TextureWrapMode.Clamp,
                anisoLevel = 4,
                mipMapBias = 0f
            };
        }

        private static string C(Color color)
        {
            var c = (Color32)color;
            return $"{c.r:x2}{c.g:x2}{c.b:x2}{c.a:x2}";
        }

        // ---------------- 玻璃面板 ----------------

        /// <summary>纯视觉玻璃面板（不带布局）。返回根 Image，视觉层均为 ignoreLayout 子节点。</summary>
        public static Image Panel(Transform parent, string name, bool strong = false,
                                  int radius = RadiusCard, float alpha = 1f)
        {
            var root = CreateRect(parent, name);
            var rootImage = root.gameObject.AddComponent<Image>();
            rootImage.color = new Color(1f, 1f, 1f, 0f);
            rootImage.raycastTarget = false;

            AddShadow(root, "Shadow", radius, new Vector2(0f, -14f), 14f, 0.24f * alpha);

            var top = strong ? GlassStrongTop : GlassTop;
            var bottom = strong ? GlassStrongBottom : GlassBottom;
            var body = CreateRect(root, "Body");
            Stretch(body);
            var bodyImage = body.gameObject.AddComponent<Image>();
            bodyImage.sprite = RoundedSprite(radius, top, bottom, BorderTop, BorderBottom, 1.6f);
            bodyImage.type = Image.Type.Sliced;
            bodyImage.raycastTarget = false;
            body.gameObject.AddComponent<LayoutElement>().ignoreLayout = true;

            // 顶部内侧高光：让玻璃看起来有“上边缘厚度”。
            var sheen = CreateRect(root, "Sheen");
            Stretch(sheen, 2f);
            var sheenImage = sheen.gameObject.AddComponent<Image>();
            sheenImage.sprite = RoundedSprite(radius - 2,
                new Color(1f, 1f, 1f, 0.10f), new Color(1f, 1f, 1f, 0.008f),
                new Color(1f, 1f, 1f, 0.14f), new Color(1f, 1f, 1f, 0.0f), 1.1f);
            sheenImage.type = Image.Type.Sliced;
            sheenImage.raycastTarget = false;
            sheen.gameObject.AddComponent<LayoutElement>().ignoreLayout = true;

            // 蓝紫色彩洗：用圆角 Sprite，不再用方形贴图，避免破坏圆角。
            var wash = CreateRect(root, "ColorWash");
            Stretch(wash, 1.5f);
            var washImage = wash.gameObject.AddComponent<Image>();
            washImage.sprite = RoundedSprite(radius - 2,
                new Color(0.10f, 0.55f, 1f, 0.12f),
                new Color(0.65f, 0.25f, 1f, 0.07f),
                new Color(1f, 1f, 1f, 0f), new Color(1f, 1f, 1f, 0f), 1f);
            washImage.type = Image.Type.Sliced;
            washImage.raycastTarget = false;
            wash.gameObject.AddComponent<LayoutElement>().ignoreLayout = true;

            // 底部折射光：模拟玻璃下缘把环境光“兜”回来。
            var refraction = CreateRect(root, "Refraction");
            SetAnchored(refraction, new Vector2(0f, 0f), new Vector2(1f, 0f),
                new Vector2(10f, 6f), new Vector2(-10f, 54f));
            var refractionImage = refraction.gameObject.AddComponent<Image>();
            refractionImage.sprite = RoundedSprite(radius - 8,
                new Color(1f, 1f, 1f, 0f), new Color(0.62f, 0.74f, 1f, 0.05f),
                new Color(1f, 1f, 1f, 0f), new Color(0.7f, 0.82f, 1f, 0.10f), 1f);
            refractionImage.type = Image.Type.Sliced;
            refractionImage.raycastTarget = false;
            refraction.gameObject.AddComponent<LayoutElement>().ignoreLayout = true;

            // 左上角果冻高光。
            var gloss = CreateRect(root, "Gloss");
            SetAnchored(gloss, new Vector2(0f, 1f), new Vector2(0f, 1f),
                new Vector2(10f, -128f), new Vector2(430f, -8f));
            var glossImage = gloss.gameObject.AddComponent<Image>();
            glossImage.sprite = RadialSprite(256,
                new Color(1f, 1f, 1f, 0.10f), new Color(1f, 1f, 1f, 0f));
            glossImage.raycastTarget = false;
            gloss.gameObject.AddComponent<LayoutElement>().ignoreLayout = true;

            return rootImage;
        }

        /// <summary>带纵向布局的卡片。直接往 card.transform 里加子节点即可。</summary>
        public static Image Card(Transform parent, string name, bool strong = false,
                                 int radius = RadiusCard, int padding = 32,
                                 float spacing = 18f)
        {
            var panel = Panel(parent, name, strong, radius);
            var layout = panel.gameObject.AddComponent<VerticalLayoutGroup>();
            layout.spacing = spacing;
            layout.padding = new RectOffset(padding, padding, padding, padding);
            layout.childControlWidth = true;
            layout.childControlHeight = false;
            layout.childForceExpandWidth = true;
            layout.childForceExpandHeight = false;
            layout.childAlignment = TextAnchor.UpperCenter;
            // 高度按内容自适应；宽度由父级 ScrollView 视口控制。
            var fitter = panel.gameObject.AddComponent<ContentSizeFitter>();
            fitter.verticalFit = ContentSizeFitter.FitMode.PreferredSize;
            fitter.horizontalFit = ContentSizeFitter.FitMode.Unconstrained;
            var layoutElement = panel.gameObject.AddComponent<LayoutElement>();
            layoutElement.flexibleWidth = 1f;
            layoutElement.minWidth = 0f;
            return panel;
        }

        private static void AddShadow(RectTransform parent, string name, int radius,
                                      Vector2 offset, float spread, float alpha)
        {
            var shadow = CreateRect(parent, name);
            Stretch(shadow, -spread);
            shadow.anchoredPosition = offset;
            var image = shadow.gameObject.AddComponent<Image>();
            image.sprite = RoundedSprite(radius + (int)spread,
                new Color(0f, 0f, 0f, alpha), new Color(0f, 0f, 0f, alpha * 0.35f),
                new Color(0f, 0f, 0f, 0f), 1f);
            image.type = Image.Type.Sliced;
            image.raycastTarget = false;
            shadow.gameObject.AddComponent<LayoutElement>().ignoreLayout = true;
        }

        // ---------------- 常用组合件 ----------------

        public static RectTransform CardHeader(Transform parent, string title,
                                               string subtitle = null, string trailing = null,
                                               Color? trailingColor = null)
        {
            var header = CreateRect(parent, "Header");
            var headerLayout = header.gameObject.AddComponent<HorizontalLayoutGroup>();
            headerLayout.spacing = 10f;
            headerLayout.childControlWidth = true;
            headerLayout.childControlHeight = true;
            headerLayout.childForceExpandWidth = false;
            headerLayout.childForceExpandHeight = true;
            headerLayout.childAlignment = TextAnchor.MiddleLeft;
            Layout(header.gameObject, subtitle == null ? 44f : 74f);

            // 左侧彩色 accent bar
            var accent = CreateRect(header, "Accent");
            var accentLayout = Layout(accent.gameObject, subtitle == null ? 32f : 48f);
            accentLayout.minWidth = 5f;
            accentLayout.preferredWidth = 5f;
            accentLayout.flexibleWidth = 0f;
            var accentImage = accent.gameObject.AddComponent<Image>();
            var accentColor = trailingColor ?? Accent;
            accentImage.sprite = RoundedSprite(3,
                new Color(accentColor.r, accentColor.g, accentColor.b, 0.95f),
                new Color(accentColor.r, accentColor.g, accentColor.b, 0.55f), 1f);
            accentImage.type = Image.Type.Sliced;
            accentImage.raycastTarget = false;

            // 标题/副标题放进垂直布局，避免手工锚点重叠和超框。
            var column = CreateRect(header, "TextColumn");
            var columnLayout = column.gameObject.AddComponent<VerticalLayoutGroup>();
            columnLayout.spacing = 2f;
            columnLayout.childControlWidth = true;
            columnLayout.childControlHeight = true;
            columnLayout.childForceExpandWidth = true;
            columnLayout.childForceExpandHeight = false;
            columnLayout.childAlignment = TextAnchor.MiddleLeft;
            var columnElement = column.gameObject.AddComponent<LayoutElement>();
            columnElement.flexibleWidth = 1f;
            columnElement.minWidth = 0f;

            var titleLabel = Label(column, "Title", title, 24, TextPrimary,
                TextAnchor.MiddleLeft, true);
            Layout(titleLabel.gameObject, 32f);
            if (!string.IsNullOrEmpty(subtitle))
            {
                var subtitleLabel = Label(column, "Subtitle", subtitle, 14, TextTertiary,
                    TextAnchor.MiddleLeft);
                Layout(subtitleLabel.gameObject, 22f);
            }

            if (!string.IsNullOrEmpty(trailing))
            {
                var pill = Pill(header, "Trailing", trailing, trailingColor ?? Success, 13);
                var pillLayout = pill.GetComponent<LayoutElement>();
                if (pillLayout != null)
                {
                    pillLayout.minWidth = 110f;
                    pillLayout.preferredWidth = 140f;
                    pillLayout.flexibleWidth = 0f;
                }
            }
            return header;
        }

        public static Image Pill(Transform parent, string name, string text, Color color,
                                 int fontSize = 16, float height = 32f)
        {
            var rect = CreateRect(parent, name);
            var image = rect.gameObject.AddComponent<Image>();
            image.sprite = RoundedSprite((int)(height * 0.5f),
                new Color(color.r, color.g, color.b, 0.20f),
                new Color(color.r, color.g, color.b, 0.12f),
                new Color(color.r, color.g, color.b, 0.55f),
                new Color(color.r, color.g, color.b, 0.28f), 1.2f);
            image.type = Image.Type.Sliced;
            image.raycastTarget = false;
            var label = Label(rect, "Label", text, fontSize, color,
                TextAnchor.MiddleCenter, true);
            Stretch(label.rectTransform, 16f, 2f);
            var layout = Layout(rect.gameObject, height, height);
            layout.minWidth = 72f;
            return image;
        }

        public static Image StatChip(Transform parent, string name, string label, string value,
                                     Color accent)
        {
            var chip = Panel(parent, name, false, RadiusSmall, 0.9f);
            Layout(chip.gameObject, 96f);

            var accentDot = CreateRect(chip.rectTransform, "Dot");
            SetAnchored(accentDot, new Vector2(0f, 1f), new Vector2(0f, 1f),
                new Vector2(22f, -30f), new Vector2(30f, -22f));
            var dotImage = accentDot.gameObject.AddComponent<Image>();
            dotImage.sprite = RadialSprite(64, accent,
                new Color(accent.r, accent.g, accent.b, 0f));
            dotImage.raycastTarget = false;
            accentDot.gameObject.AddComponent<LayoutElement>().ignoreLayout = true;

            var valueLabel = Label(chip.rectTransform, "Value", value, 26, TextPrimary,
                TextAnchor.UpperLeft, true);
            SetAnchored(valueLabel.rectTransform, new Vector2(0f, 0f), new Vector2(1f, 1f),
                new Vector2(42f, 34f), new Vector2(-16f, -18f));
            valueLabel.gameObject.AddComponent<LayoutElement>().ignoreLayout = true;

            var labelLabel = Label(chip.rectTransform, "Label", label, 15, TextSecondary,
                TextAnchor.LowerLeft);
            SetAnchored(labelLabel.rectTransform, new Vector2(0f, 0f), new Vector2(1f, 1f),
                new Vector2(22f, 14f), new Vector2(-16f, -62f));
            labelLabel.gameObject.AddComponent<LayoutElement>().ignoreLayout = true;
            return chip;
        }

        // ---------------- 交互控件 ----------------

        public static QiyuUIButton Button(Transform parent, string name, string text,
                                          Action onClick,
                                          QiyuButtonVariant variant = QiyuButtonVariant.Glass,
                                          int fontSize = 18, int height = 52)
        {
            var rect = CreateRect(parent, name);
            var rootImage = rect.gameObject.AddComponent<Image>();
            rootImage.color = new Color(1f, 1f, 1f, 0f);
            rootImage.raycastTarget = true;

            var (top, bottom, borderTop, borderBottom, textColor) = VariantColors(variant);
            var effectiveHeight = !string.IsNullOrEmpty(text) && text.Contains("\n")
                ? height + 16
                : height;
            var radius = Mathf.Min(RadiusButton, Mathf.Max(8, effectiveHeight / 2));

            // 阴影 + 挤出厚度（3D 果冻的关键：底部先垫一层更深的实体）。
            var shadow = CreateRect(rect, "Shadow");
            Stretch(shadow, 2f);
            shadow.anchoredPosition = new Vector2(0f, -8f);
            var shadowImage = shadow.gameObject.AddComponent<Image>();
            shadowImage.sprite = RoundedSprite(radius, new Color(0f, 0f, 0f, 0.30f),
                new Color(0f, 0f, 0f, 0.08f), new Color(0f, 0f, 0f, 0f), 1f);
            shadowImage.type = Image.Type.Sliced;
            shadowImage.raycastTarget = false;
            shadow.gameObject.AddComponent<LayoutElement>().ignoreLayout = true;

            var extrusion = CreateRect(rect, "Extrusion");
            Stretch(extrusion);
            extrusion.anchoredPosition = new Vector2(0f, -5f);
            var extrusionImage = extrusion.gameObject.AddComponent<Image>();
            extrusionImage.sprite = RoundedSprite(radius,
                Multiply(top, 0.42f), Multiply(bottom, 0.34f),
                new Color(0f, 0f, 0f, 0.20f), new Color(0f, 0f, 0f, 0.08f), 1.2f);
            extrusionImage.type = Image.Type.Sliced;
            extrusionImage.raycastTarget = false;
            extrusion.gameObject.AddComponent<LayoutElement>().ignoreLayout = true;

            var body = CreateRect(rect, "Body");
            Stretch(body);
            var bodyImage = body.gameObject.AddComponent<Image>();
            bodyImage.sprite = RoundedSprite(radius, top, bottom, borderTop, borderBottom, 1.4f);
            bodyImage.type = Image.Type.Sliced;
            bodyImage.raycastTarget = false;
            body.gameObject.AddComponent<LayoutElement>().ignoreLayout = true;

            var gloss = CreateRect(rect, "Gloss");
            SetAnchored(gloss, new Vector2(0f, 0.5f), new Vector2(1f, 1f),
                new Vector2(6f, -2f), new Vector2(-6f, -2f));
            var glossImage = gloss.gameObject.AddComponent<Image>();
            glossImage.sprite = RoundedSprite(radius - 4,
                new Color(1f, 1f, 1f, 0.20f), new Color(1f, 1f, 1f, 0f),
                new Color(1f, 1f, 1f, 0.10f), new Color(1f, 1f, 1f, 0f), 1f);
            glossImage.type = Image.Type.Sliced;
            glossImage.raycastTarget = false;
            gloss.gameObject.AddComponent<LayoutElement>().ignoreLayout = true;

            var label = Label(rect, "Label", text, fontSize, textColor,
                TextAnchor.MiddleCenter, true);
            label.textWrappingMode = TextWrappingModes.NoWrap;
            label.overflowMode = TextOverflowModes.Overflow;
            Stretch(label.rectTransform, 24f, 6f);
            label.gameObject.AddComponent<LayoutElement>().ignoreLayout = true;

            Layout(rect.gameObject, effectiveHeight, effectiveHeight);
            var button = rect.gameObject.AddComponent<QiyuUIButton>();
            button.Configure(rootImage, bodyImage, extrusionImage, glossImage, label, onClick,
                effectiveHeight);
            return button;
        }

        private static (Color top, Color bottom, Color borderTop, Color borderBottom,
            Color text) VariantColors(QiyuButtonVariant variant)
        {
            return variant switch
            {
                QiyuButtonVariant.Primary => (
                    new Color(1f, 1f, 1f, 0.98f), new Color(0.82f, 0.84f, 0.90f, 0.96f),
                    new Color(1f, 1f, 1f, 0.95f), new Color(1f, 1f, 1f, 0.35f),
                    Hex("#0A0A0C")),
                QiyuButtonVariant.Danger => (
                    new Color(0.98f, 0.28f, 0.22f, 0.96f), new Color(0.72f, 0.10f, 0.08f, 0.96f),
                    new Color(1f, 0.62f, 0.56f, 0.70f), new Color(0.35f, 0.02f, 0.02f, 0.55f),
                    Color.white),
                QiyuButtonVariant.Ghost => (
                    new Color(1f, 1f, 1f, 0.075f), new Color(1f, 1f, 1f, 0.035f),
                    new Color(1f, 1f, 1f, 0.16f), new Color(1f, 1f, 1f, 0.045f),
                    TextSecondary),
                QiyuButtonVariant.Accent => (
                    new Color(0.30f, 0.82f, 1f, 0.92f), new Color(0.10f, 0.48f, 0.78f, 0.94f),
                    new Color(0.72f, 0.94f, 1f, 0.75f), new Color(0.05f, 0.25f, 0.42f, 0.55f),
                    Hex("#04141C")),
                _ => (
                    new Color(1f, 1f, 1f, 0.135f), new Color(1f, 1f, 1f, 0.060f),
                    new Color(1f, 1f, 1f, 0.28f), new Color(1f, 1f, 1f, 0.07f),
                    TextPrimary)
            };
        }

        private static Color Multiply(Color color, float factor)
        {
            return new Color(color.r * factor, color.g * factor, color.b * factor, color.a);
        }

        public static QiyuUITab Tab(Transform parent, string name, string text,
                                    Action onClick)
        {
            var rect = CreateRect(parent, name);
            var rootImage = rect.gameObject.AddComponent<Image>();
            rootImage.color = new Color(1f, 1f, 1f, 0f);
            rootImage.raycastTarget = true;

            var background = CreateRect(rect, "Background");
            Stretch(background, 2f);
            var backgroundImage = background.gameObject.AddComponent<Image>();
            backgroundImage.sprite = RoundedSprite(RadiusButton,
                new Color(1f, 1f, 1f, 0.98f), new Color(0.82f, 0.84f, 0.90f, 0.96f),
                new Color(1f, 1f, 1f, 0.95f), new Color(1f, 1f, 1f, 0.35f), 1.4f);
            backgroundImage.type = Image.Type.Sliced;
            backgroundImage.color = new Color(1f, 1f, 1f, 0f);
            backgroundImage.raycastTarget = false;
            background.gameObject.AddComponent<LayoutElement>().ignoreLayout = true;

            var label = Label(rect, "Label", text, 18, TextSecondary,
                TextAnchor.MiddleCenter, true);
            Stretch(label.rectTransform, 10f, 4f);
            label.gameObject.AddComponent<LayoutElement>().ignoreLayout = true;

            var dot = CreateRect(rect, "Dot");
            SetAnchored(dot, new Vector2(0.5f, 0f), new Vector2(0.5f, 0f),
                new Vector2(-16f, 3f), new Vector2(16f, 6f));
            var dotImage = dot.gameObject.AddComponent<Image>();
            dotImage.sprite = RoundedSprite(2, Color.white, Color.white, 0f);
            dotImage.type = Image.Type.Sliced;
            dotImage.color = new Color(1f, 1f, 1f, 0f);
            dotImage.raycastTarget = false;
            dot.gameObject.AddComponent<LayoutElement>().ignoreLayout = true;

            var tab = rect.gameObject.AddComponent<QiyuUITab>();
            tab.Configure(backgroundImage, label, dotImage, onClick);
            return tab;
        }

        public static QiyuUIToggle Toggle(Transform parent, string name, string labelText,
                                          bool initial, Action<bool> onChanged)
        {
            var rect = CreateRect(parent, name);
            var rootImage = rect.gameObject.AddComponent<Image>();
            rootImage.color = new Color(1f, 1f, 1f, 0f);
            rootImage.raycastTarget = true;
            Layout(rect.gameObject, 58f);

            var label = Label(rect, "Label", labelText, 18, TextPrimary,
                TextAnchor.MiddleLeft);
            SetAnchored(label.rectTransform, new Vector2(0f, 0f), new Vector2(1f, 1f),
                new Vector2(4f, 0f), new Vector2(-108f, 0f));

            var track = CreateRect(rect, "Track");
            SetAnchored(track, new Vector2(1f, 0.5f), new Vector2(1f, 0.5f),
                new Vector2(-88f, -18f), new Vector2(-12f, 18f));
            var trackImage = track.gameObject.AddComponent<Image>();
            trackImage.sprite = RoundedSprite(18, new Color(1f, 1f, 1f, 0.10f),
                new Color(1f, 1f, 1f, 0.055f), new Color(1f, 1f, 1f, 0.18f),
                new Color(1f, 1f, 1f, 0.06f), 1.2f);
            trackImage.type = Image.Type.Sliced;
            trackImage.raycastTarget = false;

            var knob = CreateRect(track, "Knob");
            SetAnchored(knob, new Vector2(0f, 0.5f), new Vector2(0f, 0.5f),
                new Vector2(4f, -14f), new Vector2(32f, 14f));
            var knobImage = knob.gameObject.AddComponent<Image>();
            knobImage.sprite = RoundedSprite(14, Color.white,
                new Color(0.86f, 0.87f, 0.92f, 1f), new Color(1f, 1f, 1f, 0.9f),
                new Color(0.7f, 0.72f, 0.8f, 0.8f), 1.2f);
            knobImage.type = Image.Type.Sliced;
            knobImage.raycastTarget = false;

            var toggle = rect.gameObject.AddComponent<QiyuUIToggle>();
            toggle.Configure(trackImage, knobImage, knob, initial, onChanged);
            return toggle;
        }

        public static QiyuUISlider Slider(Transform parent, string name, string labelText,
                                          float min, float max, float initial,
                                          Action<float> onChanged, string suffix = "")
        {
            var rect = CreateRect(parent, name);
            Layout(rect.gameObject, 76f);

            var label = Label(rect, "Label", labelText, 17, TextSecondary,
                TextAnchor.UpperLeft);
            SetAnchored(label.rectTransform, new Vector2(0f, 0.5f), new Vector2(1f, 1f),
                new Vector2(4f, 0f), new Vector2(-120f, -2f));

            var value = Label(rect, "Value", "", 17, TextPrimary,
                TextAnchor.UpperRight, true);
            SetAnchored(value.rectTransform, new Vector2(1f, 0.5f), new Vector2(1f, 1f),
                new Vector2(-120f, 0f), new Vector2(-4f, -2f));

            var sliderRect = CreateRect(rect, "Slider");
            SetAnchored(sliderRect, new Vector2(0f, 0f), new Vector2(1f, 0.5f),
                new Vector2(4f, 10f), new Vector2(-4f, -2f));

            var slider = sliderRect.gameObject.AddComponent<QiyuUISlider>();
            slider.Configure(min, max, initial, onChanged, suffix, value);
            return slider;
        }

        public static QiyuUIInputField Input(Transform parent, string name, string placeholder,
                                             string initial, Action<string> onChanged,
                                             int height = 58)
        {
            var rect = CreateRect(parent, name);
            var rootImage = rect.gameObject.AddComponent<Image>();
            rootImage.sprite = RoundedSprite(RadiusInput,
                new Color(1f, 1f, 1f, 0.075f), new Color(1f, 1f, 1f, 0.035f),
                new Color(1f, 1f, 1f, 0.22f), new Color(1f, 1f, 1f, 0.06f), 1.4f);
            rootImage.type = Image.Type.Sliced;
            rootImage.raycastTarget = true;
            Layout(rect.gameObject, height, height);

            var viewport = CreateRect(rect, "TextArea");
            SetAnchored(viewport, new Vector2(0f, 0f), new Vector2(1f, 1f),
                new Vector2(18f, 6f), new Vector2(-56f, -6f));
            viewport.gameObject.AddComponent<RectMask2D>();

            var text = Label(viewport, "Text", "", 20, TextPrimary,
                TextAnchor.MiddleLeft, false, false);
            Stretch(text.rectTransform);
            var placeholderLabel = Label(viewport, "Placeholder", placeholder, 20,
                TextTertiary, TextAnchor.MiddleLeft, false, false);
            Stretch(placeholderLabel.rectTransform);

            var input = rect.gameObject.AddComponent<TMP_InputField>();
            input.textViewport = viewport;
            input.textComponent = text;
            input.placeholder = placeholderLabel;
            input.fontAsset = FontAsset;
            input.pointSize = 20;
            input.lineType = TMP_InputField.LineType.SingleLine;
            input.caretColor = Accent;
            input.selectionColor = new Color(0.39f, 0.82f, 1f, 0.28f);
            input.customCaretColor = true;
            input.text = initial ?? "";
            input.onEndEdit.AddListener(value => onChanged?.Invoke(value));
            input.onSubmit.AddListener(value => onChanged?.Invoke(value));

            var hint = Label(rect, "Hint", "⌨", 18, TextTertiary,
                TextAnchor.MiddleCenter, false, false);
            SetAnchored(hint.rectTransform, new Vector2(1f, 0f), new Vector2(1f, 1f),
                new Vector2(-52f, 0f), new Vector2(-12f, 0f));

            var wrapper = rect.gameObject.AddComponent<QiyuUIInputField>();
            wrapper.Configure(input, placeholder);
            return wrapper;
        }
    }
}
