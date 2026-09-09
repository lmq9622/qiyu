using System;
using System.Collections.Generic;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace Qiyu.Quest.UI
{
    /// <summary>
    /// Qiyu 自绘世界空间键盘。
    ///
    /// Quest 的 Android 软键盘在 VR 里不可控，Meta 的虚拟键盘组件又需要额外 Interaction 包；
    /// 这里直接用现有 liquid glass 组件拼一个键盘，保证设置页的 URL / ID / 路径输入可用。
    /// </summary>
    public class QiyuVirtualKeyboard : MonoBehaviour
    {
        public static QiyuVirtualKeyboard Instance { get; private set; }

        private RectTransform _root;
        private RectTransform _panel;
        private TMP_Text _title;
        private TMP_Text _preview;
        private TMP_InputField _target;
        private bool _shift;
        private readonly List<KeyEntry> _letterKeys = new List<KeyEntry>();

        private struct KeyEntry
        {
            public QiyuUIButton Button;
            public string Lower;
            public string Upper;
        }

        public static void Show(TMP_InputField target, string label)
        {
            if (Instance == null)
            {
                Debug.LogWarning("[QiyuVirtualKeyboard] 键盘尚未初始化");
                return;
            }
            Instance.ShowInternal(target, label);
        }

        private void Awake()
        {
            Instance = this;
        }

        private void OnDestroy()
        {
            if (Instance == this)
            {
                Instance = null;
            }
            if (QiyuGazeInteractor.ModalRoot == _root)
            {
                QiyuGazeInteractor.ModalRoot = null;
            }
        }

        /// <summary>由 QiyuMRApp 在画布内创建。</summary>
        public void Build(RectTransform canvasRoot)
        {
            _root = QiyuUI.CreateRect(canvasRoot, "VirtualKeyboard");
            QiyuUI.Stretch(_root);
            _root.SetAsLastSibling();

            var backdrop = QiyuUI.CreateRect(_root, "Backdrop");
            QiyuUI.Stretch(backdrop);
            var backdropImage = backdrop.gameObject.AddComponent<Image>();
            backdropImage.color = new Color(0f, 0f, 0f, 0.48f);
            // 键盘打开时挡住后面的面板，避免射线穿透点击到设置项。
            backdropImage.raycastTarget = true;
            backdrop.gameObject.AddComponent<LayoutElement>().ignoreLayout = true;

            var panel = QiyuUI.Card(_root, "KeyboardPanel", true,
                QiyuUI.RadiusCard, 24, 10);
            _panel = panel.rectTransform;
            QiyuUI.SetAnchored(_panel, new Vector2(0f, 0f), new Vector2(1f, 0f),
                new Vector2(24f, 24f), new Vector2(-24f, 566f));

            var header = QiyuUI.CreateRect(_panel, "Header");
            QiyuUI.Layout(header.gameObject, 64f);
            _title = QiyuUI.Label(header, "Title", "输入", 24, QiyuUI.TextPrimary,
                TextAnchor.MiddleLeft, true);
            QiyuUI.SetAnchored(_title.rectTransform, new Vector2(0f, 0f), new Vector2(1f, 1f),
                new Vector2(2f, 24f), new Vector2(-220f, 0f));
            _preview = QiyuUI.Label(header, "Preview", "", 17, QiyuUI.TextSecondary,
                TextAnchor.LowerLeft, false, false);
            QiyuUI.SetAnchored(_preview.rectTransform, new Vector2(0f, 0f), new Vector2(1f, 1f),
                new Vector2(2f, 0f), new Vector2(-220f, -34f));
            var done = QiyuUI.Button(header, "DoneTop", "完成", Done,
                QiyuButtonVariant.Primary, 19, 44);
            QiyuUI.SetAnchored((RectTransform)done.transform,
                new Vector2(1f, 0.5f), new Vector2(1f, 0.5f),
                new Vector2(-190f, -22f), new Vector2(0f, 22f));

            QiyuUI.Divider(_panel);

            // URL 快捷插入
            var quick = QiyuUI.HBox(_panel, "QuickRow", 8f);
            QiyuUI.Layout(quick.gameObject, 50f);
            AddKey(quick, "https://", () => Append("https://"), null, 17);
            AddKey(quick, ".com", () => Append(".com"), null, 17);
            AddKey(quick, ".cn", () => Append(".cn"), null, 17);
            AddKey(quick, "/", () => Append("/"), null, 18);
            AddKey(quick, ":", () => Append(":"), null, 18);
            AddKey(quick, "?", () => Append("?"), null, 18);
            AddKey(quick, "&", () => Append("&"), null, 18);

            AddRow("1234567890-/:.");
            AddRow("qwertyuiop@");
            AddRow("asdfghjkl;'#");
            AddRow("zxcvbnm,?!_");

            var actionRow = QiyuUI.HBox(_panel, "ActionRow", 8f);
            QiyuUI.Layout(actionRow.gameObject, 58f);
            AddKey(actionRow, "⇧", ToggleShift, null, 22, QiyuButtonVariant.Ghost);
            AddKey(actionRow, "空格", () => Append(" "), null, 19, QiyuButtonVariant.Ghost);
            AddKey(actionRow, "⌫", Backspace, null, 22, QiyuButtonVariant.Ghost);
            AddKey(actionRow, "清空", Clear, null, 19, QiyuButtonVariant.Ghost);
            AddKey(actionRow, "取消", Hide, null, 19, QiyuButtonVariant.Danger);
            AddKey(actionRow, "完成", Done, null, 19, QiyuButtonVariant.Primary);

            _root.gameObject.SetActive(false);
        }

        private void AddRow(string characters)
        {
            var row = QiyuUI.HBox(_panel, "Row_" + characters, 8f);
            QiyuUI.Layout(row.gameObject, 58f);
            foreach (var c in characters)
            {
                var lower = c.ToString();
                var upper = char.IsLetter(c) ? char.ToUpperInvariant(c).ToString() : lower;
                AddKey(row, lower, () => Append(_shift ? upper : lower),
                    new KeyEntry { Lower = lower, Upper = upper }, 20);
            }
        }

        private void AddKey(Transform parent, string text, Action action, KeyEntry? entry,
                            int fontSize, QiyuButtonVariant variant = QiyuButtonVariant.Glass)
        {
            var button = QiyuUI.Button(parent, "Key_" + text, text, action, variant, fontSize, 50);
            if (entry.HasValue)
            {
                _letterKeys.Add(new KeyEntry
                {
                    Button = button,
                    Lower = entry.Value.Lower,
                    Upper = entry.Value.Upper
                });
            }
        }

        private void ShowInternal(TMP_InputField target, string label)
        {
            if (target == null || _panel == null)
            {
                return;
            }
            _target = target;
            _title.text = string.IsNullOrEmpty(label) ? "输入" : $"输入 · {label}";
            _root.gameObject.SetActive(true);
            _root.SetAsLastSibling();
            QiyuGazeInteractor.ModalRoot = _root;
            RefreshPreview();
        }

        public void Hide()
        {
            if (_root != null)
            {
                _root.gameObject.SetActive(false);
            }
            QiyuGazeInteractor.ModalRoot = null;
            _target = null;
        }

        private void Done()
        {
            if (_target != null)
            {
                _target.onEndEdit.Invoke(_target.text);
                _target.onSubmit.Invoke(_target.text);
            }
            Hide();
        }

        private void Clear()
        {
            if (_target == null)
            {
                return;
            }
            _target.text = "";
            _target.caretPosition = 0;
            _target.ForceLabelUpdate();
            RefreshPreview();
        }

        private void Backspace()
        {
            if (_target == null || string.IsNullOrEmpty(_target.text))
            {
                return;
            }
            _target.text = _target.text.Substring(0, _target.text.Length - 1);
            _target.caretPosition = _target.text.Length;
            _target.ForceLabelUpdate();
            RefreshPreview();
        }

        private void Append(string value)
        {
            if (_target == null || string.IsNullOrEmpty(value))
            {
                return;
            }
            _target.text += value;
            _target.caretPosition = _target.text.Length;
            _target.ForceLabelUpdate();
            RefreshPreview();
        }

        private void ToggleShift()
        {
            _shift = !_shift;
            foreach (var entry in _letterKeys)
            {
                if (entry.Button != null)
                {
                    entry.Button.SetLabel(_shift ? entry.Upper : entry.Lower);
                }
            }
        }

        private void RefreshPreview()
        {
            if (_preview == null)
            {
                return;
            }
            var text = _target != null ? _target.text : "";
            if (text.Length > 46)
            {
                text = "…" + text.Substring(text.Length - 45);
            }
            _preview.text = string.IsNullOrEmpty(text) ? "等待输入…" : text + "|";
        }
    }
}
