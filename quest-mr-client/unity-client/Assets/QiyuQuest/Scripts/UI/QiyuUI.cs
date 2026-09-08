using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;

namespace Qiyu.Quest.UI
{
    /// <summary>
    /// Qiyu Quest UI 设计系统（与主体 App 的 liquid glass 风格一致）。
    ///
    /// 设计 token 来自 ai-companion/ui2/assets/app.css 暗色主题：
    ///   bg-base #0a0a0c / surface #1a1a1e
    ///   glass: rgba(40,40,48,.55) → rgba(25,25,30,.28)
    ///   border: rgba(255,255,255,.10) + 顶部高光 + 底部内阴影
    ///   radius: 12/18/24/32
    ///   text: #f0f0f0 / #b0b0b0 / #808080
    ///   success #059669 / warning #d97706 / danger #dc2626
    /// </summary>
    public static class QiyuUI
    {
        public static readonly Color BgBase = Hex("#0A0A0C");
        public static readonly Color Surface = Hex("#1A1A1E");
        public static readonly Color GlassTop = new Color(0.157f, 0.157f, 0.188f, 0.78f);
        public static readonly Color GlassBottom = new Color(0.098f, 0.098f, 0.118f, 0.62f);
        public static readonly Color GlassStrongTop = new Color(0.196f, 0.196f, 0.227f, 0.88f);
        public static readonly Color GlassStrongBottom = new Color(0.118f, 0.118f, 0.149f, 0.78f);
        public static readonly Color Border = new Color(1f, 1f, 1f, 0.10f);
        public static readonly Color TextPrimary = Hex("#F0F0F0");
        public static readonly Color TextSecondary = Hex("#B0B0B0");
        public static readonly Color TextTertiary = Hex("#808080");
        public static readonly Color Success = Hex("#059669");
        public static readonly Color Warning = Hex("#D97706");
        public static readonly Color Danger = Hex("#DC2626");
        public static readonly Color Accent = Hex("#F0F0F0");
        public static readonly Color ChipBg = new Color(1f, 1f, 1f, 0.06f);
        /// <summary>画布像素密度提升后同步放大字号，保证清晰度。</summary>
        public static float FontScale = 1.45f;

        private static Font _font;
        private static readonly Dictionary<string, Sprite> SpriteCache =
            new Dictionary<string, Sprite>();

        public static Font Font
        {
            get
            {
                if (_font == null)
                {
                    _font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
                    if (_font == null)
                    {
                        _font = Resources.GetBuiltinResource<Font>("Arial.ttf");
                    }
                    if (_font == null)
                    {
                        _font = Font.CreateDynamicFontFromOSFont("Arial", 24);
                    }
                }
                return _font;
            }
        }

        public static Color Hex(string hex)
        {
            if (ColorUtility.TryParseHtmlString(hex, out var color))
            {
                return color;
            }
            return Color.magenta;
        }

        /// <summary>生成圆角矩形 9-slice Sprite（带边框与柔和边缘）。</summary>
        public static Sprite RoundedSprite(int radius, Color fill, Color border,
                                           int borderWidth = 2, float alpha = 1f)
        {
            return RoundedSprite(radius, fill, fill, border, borderWidth, alpha);
        }

        /// <summary>带纵向渐变的圆角矩形（液态玻璃的主体层次）。</summary>
        public static Sprite RoundedSprite(int radius, Color top, Color bottom, Color border,
                                           int borderWidth = 2, float alpha = 1f)
        {
            radius = Mathf.Max(2, radius);
            // 2x 超采样纹理，减少圆角锯齿
            var texRadius = radius * 2;
            var size = texRadius * 2 + 8;
            var key = $"g{radius}:{top}:{bottom}:{border}:{borderWidth}:{alpha}";
            if (SpriteCache.TryGetValue(key, out var cached))
            {
                return cached;
            }
            var tex = new Texture2D(size, size, TextureFormat.RGBA32, false)
            {
                filterMode = FilterMode.Bilinear,
                wrapMode = TextureWrapMode.Clamp
            };
            var pixels = new Color32[size * size];
            var r = texRadius;
            for (var y = 0; y < size; y++)
            {
                var v = size <= 1 ? 0f : y / (float)(size - 1);
                var baseColor = Color.Lerp(bottom, top, v);
                for (var x = 0; x < size; x++)
                {
                    // 距离圆角矩形的有符号距离
                    var dx = Mathf.Max(r - x, x - (size - 1 - r), 0);
                    var dy = Mathf.Max(r - y, y - (size - 1 - r), 0);
                    var dist = Mathf.Sqrt(dx * dx + dy * dy) - r;
                    var edge = Mathf.Clamp01(0.5f - dist);
                    if (edge <= 0f)
                    {
                        pixels[y * size + x] = new Color(0, 0, 0, 0);
                        continue;
                    }
                    var borderT = Mathf.Clamp01(1f - Mathf.Abs(dist + borderWidth * 0.5f) /
                                                Mathf.Max(0.5f, borderWidth * 0.5f));
                    var color = Color.Lerp(baseColor, border, borderT);
                    color.a *= edge * alpha;
                    pixels[y * size + x] = color;
                }
            }
            tex.SetPixels32(pixels);
            tex.Apply();
            var sprite = Sprite.Create(tex, new Rect(0, 0, size, size),
                new Vector2(0.5f, 0.5f), 100f, 0, SpriteMeshType.FullRect,
                new Vector4(texRadius, texRadius, texRadius, texRadius));
            sprite.name = key;
            SpriteCache[key] = sprite;
            return sprite;
        }

        public static RectTransform CreateRect(Transform parent, string name)
        {
            var go = new GameObject(name, typeof(RectTransform));
            go.transform.SetParent(parent, false);
            return (RectTransform)go.transform;
        }

        public static Image Card(Transform parent, string name, bool strong = false,
                                 int radius = 28)
        {
            var rect = CreateRect(parent, name);
            var image = rect.gameObject.AddComponent<Image>();
            var top = strong ? GlassStrongTop : GlassTop;
            var bottom = strong ? GlassStrongBottom : GlassBottom;
            // 1) 投影：3D 果冻立体感的底部阴影
            var shadow = CreateRect(rect, "Shadow");
            Stretch(shadow, -8f, -10f);
            shadow.anchoredPosition = new Vector2(0f, -8f);
            var shadowImage = shadow.gameObject.AddComponent<Image>();
            shadowImage.sprite = RoundedSprite(radius + 6,
                new Color(0f, 0f, 0f, 0.34f), new Color(0f, 0f, 0f, 0.10f),
                new Color(0f, 0f, 0f, 0f), 0);
            shadowImage.type = Image.Type.Sliced;
            shadowImage.raycastTarget = false;
            shadow.gameObject.AddComponent<LayoutElement>().ignoreLayout = true;

            // 2) 主体：纵向渐变玻璃
            image.sprite = RoundedSprite(radius, top, bottom, Border, 2);
            image.type = Image.Type.Sliced;
            image.color = Color.white;

            // 3) 顶部高光
            var highlight = CreateRect(rect, "Highlight");
            Stretch(highlight);
            var hi = highlight.gameObject.AddComponent<Image>();
            hi.sprite = RoundedSprite(radius,
                new Color(1f, 1f, 1f, 0.10f), new Color(1f, 1f, 1f, 0.02f),
                new Color(1f, 1f, 1f, 0.22f), 2);
            hi.type = Image.Type.Sliced;
            hi.raycastTarget = false;
            var highlightLayout = highlight.gameObject.AddComponent<LayoutElement>();
            highlightLayout.ignoreLayout = true;

            // 4) 左上角果冻高光
            var gloss = CreateRect(rect, "Gloss");
            SetAnchored(gloss, new Vector2(0f, 1f), new Vector2(0f, 1f),
                new Vector2(18f, -110f), new Vector2(360f, -18f));
            var glossImage = gloss.gameObject.AddComponent<Image>();
            glossImage.sprite = RoundedSprite(40, new Color(1f, 1f, 1f, 0.10f),
                new Color(1f, 1f, 1f, 0.0f), new Color(1f, 1f, 1f, 0.14f), 2);
            glossImage.type = Image.Type.Sliced;
            glossImage.raycastTarget = false;
            gloss.gameObject.AddComponent<LayoutElement>().ignoreLayout = true;
            return image;
        }

        public static Text Label(Transform parent, string name, string text, int size,
                                 Color color, TextAnchor anchor = TextAnchor.UpperLeft,
                                 FontStyle style = FontStyle.Normal)
        {
            var rect = CreateRect(parent, name);
            var label = rect.gameObject.AddComponent<Text>();
            label.font = Font;
            label.text = text;
            label.fontSize = Mathf.RoundToInt(size * FontScale);
            label.color = color;
            label.alignment = anchor;
            label.fontStyle = style;
            label.horizontalOverflow = HorizontalWrapMode.Wrap;
            label.verticalOverflow = VerticalWrapMode.Overflow;
            label.raycastTarget = false;
            return label;
        }

        public static QiyuUIButton Button(Transform parent, string name, string text,
                                          Action onClick, ButtonVariant variant = ButtonVariant.Glass,
                                          int fontSize = 22, int height = 56)
        {
            var rect = CreateRect(parent, name);
            var image = rect.gameObject.AddComponent<Image>();
            var (fill, border, textColor) = VariantColors(variant);
            image.sprite = RoundedSprite(18, fill, border, 2);
            image.type = Image.Type.Sliced;
            var button = rect.gameObject.AddComponent<QiyuUIButton>();
            button.Configure(image, onClick);
            var label = Label(rect, "Label", text, fontSize, textColor, TextAnchor.MiddleCenter,
                FontStyle.Bold);
            Stretch(label.rectTransform, 10f, 4f);
            var layout = rect.gameObject.AddComponent<LayoutElement>();
            layout.minHeight = height;
            layout.preferredHeight = height;
            return button;
        }

        public enum ButtonVariant { Glass, Primary, Danger, Ghost }

        private static (Color fill, Color border, Color text) VariantColors(ButtonVariant variant)
        {
            return variant switch
            {
                ButtonVariant.Primary => (new Color(0.94f, 0.94f, 0.96f, 0.95f),
                    new Color(1f, 1f, 1f, 0.7f), Hex("#111111")),
                ButtonVariant.Danger => (new Color(0.72f, 0.12f, 0.12f, 0.92f),
                    new Color(1f, 0.4f, 0.4f, 0.5f), Color.white),
                ButtonVariant.Ghost => (new Color(1f, 1f, 1f, 0.04f),
                    new Color(1f, 1f, 1f, 0.08f), TextSecondary),
                _ => (new Color(1f, 1f, 1f, 0.08f), new Color(1f, 1f, 1f, 0.16f), TextPrimary),
            };
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

        public static Image Pill(Transform parent, string name, string text, Color color,
                                 int fontSize = 18)
        {
            var rect = CreateRect(parent, name);
            var image = rect.gameObject.AddComponent<Image>();
            image.sprite = RoundedSprite(14, new Color(color.r, color.g, color.b, 0.18f),
                new Color(color.r, color.g, color.b, 0.35f), 2);
            image.type = Image.Type.Sliced;
            var label = Label(rect, "Label", text, fontSize, color, TextAnchor.MiddleCenter,
                FontStyle.Bold);
            Stretch(label.rectTransform, 14f, 4f);
            var layout = rect.gameObject.AddComponent<LayoutElement>();
            layout.minHeight = 34;
            layout.preferredHeight = 34;
            layout.minWidth = 90;
            return image;
        }

        public static QiyuUIToggle Toggle(Transform parent, string name, string label,
                                          bool initial, Action<bool> onChanged)
        {
            var rect = CreateRect(parent, name);
            var layout = rect.gameObject.AddComponent<LayoutElement>();
            layout.minHeight = 52;
            layout.preferredHeight = 52;
            var text = Label(rect, "Label", label, 21, TextPrimary, TextAnchor.MiddleLeft);
            SetAnchored(text.rectTransform, new Vector2(0, 0), new Vector2(1, 1),
                new Vector2(6, 0), new Vector2(-90, 0));
            var knobRect = CreateRect(rect, "Knob");
            SetAnchored(knobRect, new Vector2(1, 0.5f), new Vector2(1, 0.5f),
                new Vector2(-74, -16), new Vector2(-10, 16));
            var knobImage = knobRect.gameObject.AddComponent<Image>();
            knobImage.sprite = RoundedSprite(16, new Color(1f, 1f, 1f, 0.10f), Border, 2);
            knobImage.type = Image.Type.Sliced;
            var knob = knobRect.gameObject.AddComponent<QiyuUIToggle>();
            knob.Configure(knobImage, initial, onChanged);
            return knob;
        }

        public static QiyuUISlider Slider(Transform parent, string name, string label,
                                          float min, float max, float initial, Action<float> onChanged,
                                          string suffix = "")
        {
            var rect = CreateRect(parent, name);
            var layout = rect.gameObject.AddComponent<LayoutElement>();
            layout.minHeight = 66;
            layout.preferredHeight = 66;
            var text = Label(rect, "Label", label, 20, TextSecondary, TextAnchor.UpperLeft);
            SetAnchored(text.rectTransform, new Vector2(0, 0.5f), new Vector2(1, 1),
                new Vector2(6, 0), new Vector2(-6, -4));
            var sliderRect = CreateRect(rect, "Slider");
            SetAnchored(sliderRect, new Vector2(0, 0), new Vector2(1, 0.5f),
                new Vector2(6, 10), new Vector2(-6, -2));
            var slider = sliderRect.gameObject.AddComponent<QiyuUISlider>();
            slider.Configure(min, max, initial, onChanged, suffix);
            return slider;
        }

        public static InputField Input(Transform parent, string name, string placeholder,
                                       string initial, Action<string> onChanged, int height = 56)
        {
            var rect = CreateRect(parent, name);
            var image = rect.gameObject.AddComponent<Image>();
            image.sprite = RoundedSprite(16, new Color(1f, 1f, 1f, 0.06f),
                new Color(1f, 1f, 1f, 0.14f), 2);
            image.type = Image.Type.Sliced;
            var input = rect.gameObject.AddComponent<InputField>();
            var textComponent = Label(rect, "Text", "", 21, TextPrimary, TextAnchor.MiddleLeft);
            Stretch(textComponent.rectTransform, 16f, 6f);
            var placeholderComponent = Label(rect, "Placeholder", placeholder, 21,
                TextTertiary, TextAnchor.MiddleLeft);
            Stretch(placeholderComponent.rectTransform, 16f, 6f);
            input.textComponent = textComponent;
            input.placeholder = placeholderComponent;
            input.text = initial ?? "";
            input.onEndEdit.AddListener(value => onChanged?.Invoke(value));
            input.onSubmit.AddListener(value => onChanged?.Invoke(value));
            var layout = rect.gameObject.AddComponent<LayoutElement>();
            layout.minHeight = height;
            layout.preferredHeight = height;
            return input;
        }

        public static RectTransform VBox(Transform parent, string name, float spacing = 12f,
                                         int padding = 16)
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

        public static RectTransform HBox(Transform parent, string name, float spacing = 10f)
        {
            var rect = CreateRect(parent, name);
            var layout = rect.gameObject.AddComponent<HorizontalLayoutGroup>();
            layout.spacing = spacing;
            layout.childControlWidth = true;
            layout.childControlHeight = false;
            layout.childForceExpandWidth = true;
            layout.childForceExpandHeight = false;
            return rect;
        }

        public static RectTransform ScrollView(Transform parent, string name,
                                               out RectTransform content, float spacing = 14f)
        {
            var root = CreateRect(parent, name);
            var scroll = root.gameObject.AddComponent<ScrollRect>();
            scroll.horizontal = false;
            scroll.vertical = true;
            scroll.movementType = ScrollRect.MovementType.Clamped;
            scroll.scrollSensitivity = 30f;

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
            layout.padding = new RectOffset(4, 4, 4, 4);
            layout.childControlWidth = true;
            layout.childControlHeight = false;
            layout.childForceExpandWidth = true;
            layout.childForceExpandHeight = false;
            var fitter = content.gameObject.AddComponent<ContentSizeFitter>();
            fitter.verticalFit = ContentSizeFitter.FitMode.PreferredSize;
            scroll.content = content;
            return root;
        }
    }
}
