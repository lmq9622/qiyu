path = r"C:\Users\lmq20\Documents\Kimi\Workspaces\ai伴侣\ai-companion\gateway\static\index.html"

with open(path, 'r', encoding='utf-8') as f:
    text = f.read()

# ================================================================
# Apple Liquid Glass 风格重写
# ================================================================

# 1. 圆角变量全部加大
old_root = '''            --radius-sm: 8px;
            --radius-md: 12px;
            --radius-lg: 16px;
            --radius-xl: 20px;'''
new_root = '''            --radius-sm: 12px;
            --radius-md: 18px;
            --radius-lg: 24px;
            --radius-xl: 32px;
            --liquid-bg: linear-gradient(180deg, rgba(255,255,255,0.50) 0%, rgba(255,255,255,0.22) 100%);
            --liquid-bg-strong: linear-gradient(180deg, rgba(255,255,255,0.65) 0%, rgba(255,255,255,0.35) 100%);
            --liquid-border: 1px solid rgba(255,255,255,0.55);
            --liquid-highlight: inset 0 1.5px 1px rgba(255,255,255,0.92), inset 0 -1px 1px rgba(0,0,0,0.03);
            --liquid-shadow: 0 12px 40px rgba(0,0,0,0.10), 0 2px 8px rgba(0,0,0,0.04);'''
text = text.replace(old_root, new_root)

# 2. Body背景加深对比度，让玻璃更明显
old_body = '''        body {
            background:
                radial-gradient(ellipse 600px 400px at 15% 20%, rgba(220,220,228,0.5) 0%, transparent 70%),
                radial-gradient(ellipse 500px 350px at 85% 80%, rgba(218,218,226,0.45) 0%, transparent 70%),
                radial-gradient(ellipse 400px 300px at 50% 50%, rgba(225,225,232,0.35) 0%, transparent 60%),
                radial-gradient(ellipse 350px 280px at 75% 15%, rgba(228,228,235,0.3) 0%, transparent 60%),
                #f5f5f7;
        }'''
new_body = '''        body {
            background:
                radial-gradient(ellipse 700px 500px at 10% 20%, rgba(200,200,212,0.55) 0%, transparent 70%),
                radial-gradient(ellipse 600px 450px at 90% 85%, rgba(195,195,208,0.50) 0%, transparent 70%),
                radial-gradient(ellipse 500px 400px at 50% 60%, rgba(205,205,218,0.40) 0%, transparent 60%),
                radial-gradient(ellipse 450px 350px at 80% 10%, rgba(210,210,222,0.35) 0%, transparent 60%),
                radial-gradient(ellipse 400px 300px at 30% 80%, rgba(190,190,205,0.30) 0%, transparent 50%),
                #e8e8ec;
        }'''
text = text.replace(old_body, new_body)

# 3. glass / glass-strong → Liquid Glass
old_glass = '''        .glass {
            background: rgba(255, 255, 255, 0.65);
            backdrop-filter: blur(40px) saturate(1.4);
            -webkit-backdrop-filter: blur(40px) saturate(1.4);
            border: 1px solid rgba(255, 255, 255, 0.7);
            box-shadow:
                0 0 0 1px rgba(255,255,255,0.4) inset,
                0 8px 32px rgba(0, 0, 0, 0.06),
                0 1px 3px rgba(0, 0, 0, 0.04);
            border-radius: var(--radius-xl);
        }
        .glass-strong {
            background: rgba(255, 255, 255, 0.82);
            backdrop-filter: blur(48px) saturate(1.4);
            -webkit-backdrop-filter: blur(48px) saturate(1.4);
            border: 1px solid rgba(255, 255, 255, 0.75);
            box-shadow:
                0 0 0 1px rgba(255,255,255,0.5) inset,
                0 8px 32px rgba(0, 0, 0, 0.08),
                0 1px 3px rgba(0, 0, 0, 0.04);
            border-radius: var(--radius-xl);
        }'''
new_glass = '''        .glass {
            background: var(--liquid-bg);
            backdrop-filter: blur(60px) saturate(1.6);
            -webkit-backdrop-filter: blur(60px) saturate(1.6);
            border: var(--liquid-border);
            box-shadow: var(--liquid-highlight), var(--liquid-shadow);
            border-radius: var(--radius-xl);
        }
        .glass-strong {
            background: var(--liquid-bg-strong);
            backdrop-filter: blur(72px) saturate(1.6);
            -webkit-backdrop-filter: blur(72px) saturate(1.6);
            border: 1px solid rgba(255, 255, 255, 0.65);
            box-shadow: var(--liquid-highlight), 0 16px 48px rgba(0,0,0,0.12), 0 2px 8px rgba(0,0,0,0.04);
            border-radius: var(--radius-xl);
        }'''
text = text.replace(old_glass, new_glass)

# 4. sidebar → Liquid Glass
old_sidebar = '''        .sidebar { width: 260px; background: rgba(255, 255, 255, 0.78); border-right: 1px solid rgba(255,255,255,0.5); display: flex; flex-direction: column; flex-shrink: 0; z-index: 10; backdrop-filter: blur(40px) saturate(1.3); }'''
new_sidebar = '''        .sidebar { width: 260px; background: var(--liquid-bg); border-right: var(--liquid-border); display: flex; flex-direction: column; flex-shrink: 0; z-index: 10; backdrop-filter: blur(60px) saturate(1.6); box-shadow: var(--liquid-highlight); }'''
text = text.replace(old_sidebar, new_sidebar)

# 5. topbar → Liquid Glass
old_topbar = '''        .topbar { height: 64px; background: rgba(255, 255, 255, 0.72); border-bottom: 1px solid rgba(255,255,255,0.5); display: flex; align-items: center; justify-content: space-between; padding: 0 28px; flex-shrink: 0; backdrop-filter: blur(40px) saturate(1.3); box-shadow: 0 1px 0 rgba(0,0,0,0.03); }'''
new_topbar = '''        .topbar { height: 64px; background: var(--liquid-bg-strong); border-bottom: var(--liquid-border); display: flex; align-items: center; justify-content: space-between; padding: 0 28px; flex-shrink: 0; backdrop-filter: blur(72px) saturate(1.6); box-shadow: var(--liquid-highlight), 0 4px 16px rgba(0,0,0,0.04); border-radius: 0 0 var(--radius-xl) var(--radius-xl); margin: 0 8px; width: calc(100% - 16px); }'''
text = text.replace(old_topbar, new_topbar)

# 6. nav-item active → Liquid Glass发光
old_nav_active = '''        .nav-item.active { background: var(--primary-glow); color: var(--primary); font-weight: 600; }'''
new_nav_active = '''        .nav-item.active { background: rgba(255,255,255,0.6); color: var(--primary); font-weight: 600; backdrop-filter: blur(12px); box-shadow: inset 0 1px 1px rgba(255,255,255,0.8); border: 1px solid rgba(255,255,255,0.4); }'''
text = text.replace(old_nav_active, new_nav_active)

# 7. current-char-mini → Liquid Glass
old_char_mini = '''        .current-char-mini { display: flex; align-items: center; gap: 10px; padding: 10px 12px; background: rgba(255,255,255,0.75); border-radius: var(--radius-lg); border: 1px solid rgba(255,255,255,0.6); backdrop-filter: blur(24px) saturate(1.2); box-shadow: 0 2px 8px rgba(0,0,0,0.04), 0 0 0 1px rgba(255,255,255,0.4) inset; }'''
new_char_mini = '''        .current-char-mini { display: flex; align-items: center; gap: 10px; padding: 10px 12px; background: var(--liquid-bg); border-radius: var(--radius-lg); border: var(--liquid-border); backdrop-filter: blur(40px) saturate(1.4); box-shadow: var(--liquid-highlight), 0 4px 12px rgba(0,0,0,0.04); }'''
text = text.replace(old_char_mini, new_char_mini)

# 8. sidebar-footer 去掉深色border
old_sidebar_footer = '''        .sidebar-footer { padding: 16px 12px; border-top: 1px solid var(--border); }'''
new_sidebar_footer = '''        .sidebar-footer { padding: 16px 12px; border-top: 1px solid rgba(255,255,255,0.25); }'''
text = text.replace(old_sidebar_footer, new_sidebar_footer)

# 9. chat-input-area → Liquid Glass
old_chat_input_area = '''        .chat-input-area { padding: 16px 28px 24px; border-top: 1px solid rgba(255,255,255,0.5); background: rgba(255, 255, 255, 0.72); backdrop-filter: blur(40px) saturate(1.3); }'''
new_chat_input_area = '''        .chat-input-area { padding: 16px 28px 24px; border-top: var(--liquid-border); background: var(--liquid-bg-strong); backdrop-filter: blur(72px) saturate(1.6); box-shadow: var(--liquid-highlight), 0 -4px 16px rgba(0,0,0,0.04); border-radius: var(--radius-xl) var(--radius-xl) 0 0; margin: 0 8px; width: calc(100% - 16px); }'''
text = text.replace(old_chat_input_area, new_chat_input_area)

# 10. chat-input → 玻璃质感输入框
old_chat_input = '''        .chat-input { flex: 1; padding: 12px 16px; border: 1px solid rgba(0,0,0,0.08); border-radius: var(--radius-xl); font-size: 0.95rem; font-family: inherit; color: var(--text-primary); background: rgba(255, 255, 255, 0.95); outline: none; resize: none; max-height: 120px; line-height: 1.5; transition: var(--transition); box-shadow: 0 1px 3px rgba(0,0,0,0.04); }'''
new_chat_input = '''        .chat-input { flex: 1; padding: 12px 16px; border: 1px solid rgba(255,255,255,0.5); border-radius: var(--radius-xl); font-size: 0.95rem; font-family: inherit; color: var(--text-primary); background: rgba(255, 255, 255, 0.55); outline: none; resize: none; max-height: 120px; line-height: 1.5; transition: var(--transition); box-shadow: inset 0 1px 1px rgba(255,255,255,0.8), 0 2px 8px rgba(0,0,0,0.04); backdrop-filter: blur(20px) saturate(1.2); }'''
text = text.replace(old_chat_input, new_chat_input)

# 11. user消息气泡 → 液态黑玻璃
old_user_msg = '''        .msg.user .msg-content { background: rgba(17, 17, 17, 0.9); color: #fff; border-radius: var(--radius-lg); border-bottom-right-radius: 4px; padding: 12px 16px; backdrop-filter: blur(8px); box-shadow: 0 4px 12px rgba(0,0,0,0.12); }'''
new_user_msg = '''        .msg.user .msg-content { background: linear-gradient(180deg, rgba(30,30,30,0.92) 0%, rgba(10,10,10,0.92) 100%); color: #fff; border-radius: var(--radius-lg); border-bottom-right-radius: 6px; padding: 12px 16px; backdrop-filter: blur(8px); box-shadow: inset 0 1px 0 rgba(255,255,255,0.1), 0 4px 16px rgba(0,0,0,0.18); }'''
text = text.replace(old_user_msg, new_user_msg)

# 12. assistant消息气泡 → 液态白玻璃
old_assist_msg = '''        .msg.assistant .msg-content { background: rgba(255, 255, 255, 0.75); color: var(--text-primary); border: 1px solid rgba(255, 255, 255, 0.7); border-radius: var(--radius-lg); border-bottom-left-radius: 4px; padding: 12px 16px; backdrop-filter: blur(24px) saturate(1.2); box-shadow: 0 4px 12px rgba(0,0,0,0.06), 0 0 0 1px rgba(255,255,255,0.4) inset; }'''
new_assist_msg = '''        .msg.assistant .msg-content { background: var(--liquid-bg); color: var(--text-primary); border: var(--liquid-border); border-radius: var(--radius-lg); border-bottom-left-radius: 6px; padding: 12px 16px; backdrop-filter: blur(40px) saturate(1.4); box-shadow: var(--liquid-highlight), 0 4px 16px rgba(0,0,0,0.06); }'''
text = text.replace(old_assist_msg, new_assist_msg)

# 13. memory-sidebar → Liquid Glass
old_mem = '''        .memory-sidebar { width: 300px; border-left: 1px solid rgba(255,255,255,0.5); background: rgba(255, 255, 255, 0.82); display: flex; flex-direction: column; flex-shrink: 0; transition: width 0.3s ease; backdrop-filter: blur(40px) saturate(1.3); border-radius: var(--radius-xl) 0 0 var(--radius-xl); margin: 8px 0 8px 0; overflow: hidden; box-shadow: -8px 0 32px rgba(0,0,0,0.06); }'''
new_mem = '''        .memory-sidebar { width: 300px; border-left: var(--liquid-border); background: var(--liquid-bg-strong); display: flex; flex-direction: column; flex-shrink: 0; transition: width 0.3s ease; backdrop-filter: blur(72px) saturate(1.6); border-radius: var(--radius-xl) 0 0 var(--radius-xl); margin: 8px 0 8px 0; overflow: hidden; box-shadow: var(--liquid-highlight), -12px 0 40px rgba(0,0,0,0.08); }'''
text = text.replace(old_mem, new_mem)

# 14. char-card → Liquid Glass
old_char_card = '''        .char-card { padding: 20px; border-radius: var(--radius-xl); background: rgba(255, 255, 255, 0.72); backdrop-filter: blur(24px) saturate(1.2); border: 1px solid rgba(255,255,255,0.6); box-shadow: 0 4px 16px rgba(0,0,0,0.05), 0 0 0 1px rgba(255,255,255,0.4) inset; transition: var(--transition); cursor: pointer; position: relative; overflow: hidden; }'''
new_char_card = '''        .char-card { padding: 20px; border-radius: var(--radius-xl); background: var(--liquid-bg); backdrop-filter: blur(40px) saturate(1.4); border: var(--liquid-border); box-shadow: var(--liquid-highlight), 0 8px 24px rgba(0,0,0,0.06); transition: var(--transition); cursor: pointer; position: relative; overflow: hidden; }'''
text = text.replace(old_char_card, new_char_card)

old_char_hover = '''        .char-card:hover { transform: translateY(-2px); box-shadow: 0 8px 32px rgba(0,0,0,0.08), 0 0 0 1px rgba(255,255,255,0.5) inset; border-color: rgba(255,255,255,0.8); }'''
new_char_hover = '''        .char-card:hover { transform: translateY(-3px); box-shadow: var(--liquid-highlight), 0 16px 48px rgba(0,0,0,0.10); border-color: rgba(255,255,255,0.75); }'''
text = text.replace(old_char_hover, new_char_hover)

# 15. setting-section → Liquid Glass
old_setting = '''        .setting-section { border-radius: var(--radius-xl); padding: 28px; background: rgba(255,255,255,0.75); backdrop-filter: blur(24px) saturate(1.2); border: 1px solid rgba(255,255,255,0.6); box-shadow: 0 4px 16px rgba(0,0,0,0.05), 0 0 0 1px rgba(255,255,255,0.4) inset; }'''
new_setting = '''        .setting-section { border-radius: var(--radius-xl); padding: 28px; background: var(--liquid-bg); backdrop-filter: blur(40px) saturate(1.4); border: var(--liquid-border); box-shadow: var(--liquid-highlight), 0 8px 24px rgba(0,0,0,0.06); }'''
text = text.replace(old_setting, new_setting)

# 16. slider-group → Liquid Glass
old_slider = '''        .slider-group { background: var(--bg-elevated); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 14px; backdrop-filter: blur(12px); }'''
new_slider = '''        .slider-group { background: var(--liquid-bg); border: var(--liquid-border); border-radius: var(--radius-lg); padding: 14px; backdrop-filter: blur(40px) saturate(1.4); box-shadow: var(--liquid-highlight); }'''
text = text.replace(old_slider, new_slider)

# 17. route-item → Liquid Glass
old_route = '''        .route-item { padding: 16px; border-radius: var(--radius-lg); background: rgba(255, 255, 255, 0.75); border: 1px solid rgba(255, 255, 255, 0.6); display: grid; grid-template-columns: 1fr 1fr 1fr auto; gap: 12px; align-items: end; backdrop-filter: blur(24px) saturate(1.2); box-shadow: 0 2px 8px rgba(0,0,0,0.04), 0 0 0 1px rgba(255,255,255,0.4) inset; }'''
new_route = '''        .route-item { padding: 16px; border-radius: var(--radius-lg); background: var(--liquid-bg); border: var(--liquid-border); display: grid; grid-template-columns: 1fr 1fr 1fr auto; gap: 12px; align-items: end; backdrop-filter: blur(40px) saturate(1.4); box-shadow: var(--liquid-highlight), 0 4px 12px rgba(0,0,0,0.04); }'''
text = text.replace(old_route, new_route)

# 18. rag-hint → Liquid Glass
old_rag = '''        .rag-hint { display: flex; align-items: center; gap: 10px; padding: 12px 16px; background: rgba(255, 255, 255, 0.75); border-radius: var(--radius-lg); border: 1px solid rgba(255, 255, 255, 0.6); font-size: 0.85rem; color: var(--text-secondary); backdrop-filter: blur(24px) saturate(1.2); box-shadow: 0 2px 8px rgba(0,0,0,0.04), 0 0 0 1px rgba(255,255,255,0.4) inset; }'''
new_rag = '''        .rag-hint { display: flex; align-items: center; gap: 10px; padding: 12px 16px; background: var(--liquid-bg); border-radius: var(--radius-lg); border: var(--liquid-border); font-size: 0.85rem; color: var(--text-secondary); backdrop-filter: blur(40px) saturate(1.4); box-shadow: var(--liquid-highlight), 0 4px 12px rgba(0,0,0,0.04); }'''
text = text.replace(old_rag, new_rag)

# 19. wechat-status-card → Liquid Glass
old_wx = '''        .wechat-status-card { display: flex; align-items: center; gap: 16px; padding: 20px; border-radius: var(--radius-lg); background: rgba(255, 255, 255, 0.75); border: 1px solid rgba(255, 255, 255, 0.6); margin-bottom: 16px; backdrop-filter: blur(24px) saturate(1.2); box-shadow: 0 2px 8px rgba(0,0,0,0.04), 0 0 0 1px rgba(255,255,255,0.4) inset; }'''
new_wx = '''        .wechat-status-card { display: flex; align-items: center; gap: 16px; padding: 20px; border-radius: var(--radius-lg); background: var(--liquid-bg); border: var(--liquid-border); margin-bottom: 16px; backdrop-filter: blur(40px) saturate(1.4); box-shadow: var(--liquid-highlight), 0 4px 12px rgba(0,0,0,0.04); }'''
text = text.replace(old_wx, new_wx)

# 20. tag-chip → Liquid Glass
old_tag = '''        .tag-chip { display: inline-flex; align-items: center; gap: 4px; padding: 4px 10px; border-radius: 20px; font-size: 0.8rem; background: rgba(255, 255, 255, 0.8); color: var(--text-secondary); border: 1px solid rgba(0,0,0,0.06); backdrop-filter: blur(8px); }'''
new_tag = '''        .tag-chip { display: inline-flex; align-items: center; gap: 4px; padding: 4px 10px; border-radius: 20px; font-size: 0.8rem; background: var(--liquid-bg); color: var(--text-secondary); border: var(--liquid-border); backdrop-filter: blur(20px) saturate(1.2); box-shadow: inset 0 1px 1px rgba(255,255,255,0.7); }'''
text = text.replace(old_tag, new_tag)

# 21. welcome-card-inner → Liquid Glass
old_welcome = '''        .welcome-card-inner {
            background: rgba(255, 255, 255, 0.72);
            backdrop-filter: blur(40px) saturate(1.4);
            -webkit-backdrop-filter: blur(40px) saturate(1.4);
            border: 1px solid rgba(255, 255, 255, 0.75);
            border-radius: var(--radius-xl);
            box-shadow:
                0 0 0 1px rgba(255,255,255,0.5) inset,
                0 12px 40px rgba(0, 0, 0, 0.08),
                0 2px 8px rgba(0, 0, 0, 0.04);
            padding: 56px 48px;
            max-width: 420px;
            width: 100%;
        }'''
new_welcome = '''        .welcome-card-inner {
            background: var(--liquid-bg);
            backdrop-filter: blur(60px) saturate(1.6);
            -webkit-backdrop-filter: blur(60px) saturate(1.6);
            border: var(--liquid-border);
            border-radius: var(--radius-xl);
            box-shadow: var(--liquid-highlight), 0 16px 48px rgba(0,0,0,0.10), 0 2px 8px rgba(0,0,0,0.04);
            padding: 56px 48px;
            max-width: 420px;
            width: 100%;
        }'''
text = text.replace(old_welcome, new_welcome)

# 22. welcome-icon → 玻璃质感
old_icon = '''        .welcome-card .welcome-icon {
            width: 72px; height: 72px; border-radius: var(--radius-xl);
            background: var(--bg-surface); border: 1px solid var(--border);
            display: flex; align-items: center; justify-content: center;
            margin-bottom: 24px; box-shadow: var(--shadow-sm);
        }'''
new_icon = '''        .welcome-card .welcome-icon {
            width: 72px; height: 72px; border-radius: var(--radius-xl);
            background: var(--liquid-bg-strong); border: var(--liquid-border);
            display: flex; align-items: center; justify-content: center;
            margin-bottom: 24px; box-shadow: var(--liquid-highlight), 0 4px 16px rgba(0,0,0,0.06);
            backdrop-filter: blur(20px) saturate(1.2);
        }'''
text = text.replace(old_icon, new_icon)

# 23. toast → 更大圆角
old_toast = '''        .toast { padding: 12px 20px; border-radius: var(--radius-lg); font-size: 0.9rem; font-weight: 500; color: #fff; animation: toastIn 0.3s ease; box-shadow: 0 8px 24px rgba(0,0,0,0.12); }'''
new_toast = '''        .toast { padding: 12px 20px; border-radius: var(--radius-xl); font-size: 0.9rem; font-weight: 500; color: #fff; animation: toastIn 0.3s ease; box-shadow: 0 12px 32px rgba(0,0,0,0.15); backdrop-filter: blur(20px) saturate(1.2); }'''
text = text.replace(old_toast, new_toast)

# 24. modal → Liquid Glass
old_modal = '''        .modal { width: 100%; max-width: 560px; max-height: 90vh; overflow-y: auto; border-radius: var(--radius-xl); padding: 24px; position: relative; }'''
new_modal = '''        .modal { width: 100%; max-width: 560px; max-height: 90vh; overflow-y: auto; border-radius: var(--radius-xl); padding: 24px; position: relative; background: var(--liquid-bg-strong); backdrop-filter: blur(72px) saturate(1.6); border: var(--liquid-border); box-shadow: var(--liquid-highlight), 0 24px 64px rgba(0,0,0,0.18); }'''
text = text.replace(old_modal, new_modal)

# 25. ai-gen-section 去掉蓝色渐变
old_ai = '''        .ai-gen-section { margin-bottom: 20px; padding: 16px; border-radius: var(--radius-lg); background: linear-gradient(135deg, rgba(37,99,235,0.05) 0%, rgba(5,150,105,0.05) 100%); border: 1px dashed var(--primary); }'''
new_ai = '''        .ai-gen-section { margin-bottom: 20px; padding: 16px; border-radius: var(--radius-lg); background: var(--liquid-bg); border: 1px dashed rgba(0,0,0,0.15); box-shadow: var(--liquid-highlight); backdrop-filter: blur(40px) saturate(1.4); }'''
text = text.replace(old_ai, new_ai)

# 26. ai-gen-preview → Liquid Glass
old_preview = '''        .ai-gen-preview { margin-top: 16px; padding: 16px; border-radius: var(--radius-md); background: var(--bg-surface); border: 1px solid var(--border); font-size: 0.9rem; line-height: 1.7; color: var(--text-primary); white-space: pre-wrap; max-height: 300px; overflow-y: auto; }'''
new_preview = '''        .ai-gen-preview { margin-top: 16px; padding: 16px; border-radius: var(--radius-lg); background: var(--liquid-bg-strong); border: var(--liquid-border); font-size: 0.9rem; line-height: 1.7; color: var(--text-primary); white-space: pre-wrap; max-height: 300px; overflow-y: auto; box-shadow: var(--liquid-highlight); backdrop-filter: blur(40px) saturate(1.4); }'''
text = text.replace(old_preview, new_preview)

# 27. btn-secondary → Liquid Glass
old_btn2 = '''        .btn-secondary { background: var(--bg-elevated); color: var(--text-secondary); border: 1px solid var(--border); backdrop-filter: blur(12px); }'''
new_btn2 = '''        .btn-secondary { background: var(--liquid-bg); color: var(--text-secondary); border: var(--liquid-border); backdrop-filter: blur(20px) saturate(1.2); box-shadow: inset 0 1px 1px rgba(255,255,255,0.7); }'''
text = text.replace(old_btn2, new_btn2)

# 28. verify-result → 更大圆角
old_verify = '''        .verify-result { padding: 12px 16px; border-radius: var(--radius-md); font-size: 0.85rem; margin-top: 12px; }'''
new_verify = '''        .verify-result { padding: 12px 16px; border-radius: var(--radius-lg); font-size: 0.85rem; margin-top: 12px; }'''
text = text.replace(old_verify, new_verify)

# 29. setting-hint → 更大圆角
old_hint = '''        .setting-hint { font-size: 0.8rem; color: var(--text-tertiary); margin-bottom: 16px; line-height: 1.5; padding: 10px 14px; background: rgba(0, 0, 0, 0.02); border-radius: var(--radius-md); border-left: 3px solid var(--primary); }'''
new_hint = '''        .setting-hint { font-size: 0.8rem; color: var(--text-tertiary); margin-bottom: 16px; line-height: 1.5; padding: 10px 14px; background: rgba(0, 0, 0, 0.02); border-radius: var(--radius-lg); border-left: 3px solid var(--primary); }'''
text = text.replace(old_hint, new_hint)

# 30. content-body padding调整
old_body_pad = '''        .content-body { flex: 1; overflow-y: auto; padding: 28px; }'''
new_body_pad = '''        .content-body { flex: 1; overflow-y: auto; padding: 24px 32px; }'''
text = text.replace(old_body_pad, new_body_pad)

with open(path, 'w', encoding='utf-8') as f:
    f.write(text)

print("Liquid Glass rewrite complete!")
print(f"File: {len(text)} chars")
