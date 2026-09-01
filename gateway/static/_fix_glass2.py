import re

path = r"C:\Users\lmq20\Documents\Kimi\Workspaces\ai伴侣\ai-companion\gateway\static\index.html"

with open(path, 'r', encoding='utf-8') as f:
    text = f.read()

# ============================================
# 1. 背景改成有层次的渐变，让毛玻璃真正可见
# ============================================
text = text.replace(
    '''        html, body { font-family: var(--font-sans); background: var(--bg-base); color: var(--text-primary); height: 100%; overflow: hidden; -webkit-font-smoothing: antialiased; }''',
    '''        html, body { font-family: var(--font-sans); color: var(--text-primary); height: 100%; overflow: hidden; -webkit-font-smoothing: antialiased; }
        body {
            background:
                radial-gradient(ellipse 600px 400px at 15% 20%, rgba(220,220,228,0.5) 0%, transparent 70%),
                radial-gradient(ellipse 500px 350px at 85% 80%, rgba(218,218,226,0.45) 0%, transparent 70%),
                radial-gradient(ellipse 400px 300px at 50% 50%, rgba(225,225,232,0.35) 0%, transparent 60%),
                radial-gradient(ellipse 350px 280px at 75% 15%, rgba(228,228,235,0.3) 0%, transparent 60%),
                #f5f5f7;
        }''')

# ============================================
# 2. 顶部栏HTML初始内容改成干净的 AI Companion
# ============================================
text = text.replace(
    '''                <div class="topbar-left">
                    <div class="msg-avatar" id="chatHeaderAvatar" style="background:#888;">?</div>
                    <div>
                        <div class="topbar-title" id="chatHeaderName">未选择角色</div>
                        <div class="topbar-subtitle" id="chatHeaderStatus">请先在角色工坊选择一个角色</div>
                    </div>
                </div>''',
    '''                <div class="topbar-left">
                    <div class="msg-avatar" id="chatHeaderAvatar" style="background:transparent;"></div>
                    <div>
                        <div class="topbar-title" id="chatHeaderName">AI Companion</div>
                        <div class="topbar-subtitle" id="chatHeaderStatus"></div>
                    </div>
                </div>''')

# ============================================
# 3. 增强 glass / glass-strong：更明显的半透明+发光边框
# ============================================
text = text.replace(
    '''        .glass {
            background: rgba(255, 255, 255, 0.75);
            backdrop-filter: blur(24px) saturate(1.2);
            -webkit-backdrop-filter: blur(24px) saturate(1.2);
            border: 1px solid rgba(255, 255, 255, 0.5);
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.06), 0 1px 3px rgba(0, 0, 0, 0.04);
            border-radius: var(--radius-xl);
        }
        .glass-strong {
            background: rgba(255, 255, 255, 0.88);
            backdrop-filter: blur(32px) saturate(1.2);
            -webkit-backdrop-filter: blur(32px) saturate(1.2);
            border: 1px solid rgba(255, 255, 255, 0.6);
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.08), 0 1px 3px rgba(0, 0, 0, 0.04);
            border-radius: var(--radius-xl);
        }''',
    '''        .glass {
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
        }''')

# ============================================
# 4. 增强 welcome-card-inner
# ============================================
text = text.replace(
    '''        .welcome-card-inner {
            background: rgba(255, 255, 255, 0.8);
            backdrop-filter: blur(24px) saturate(1.2);
            -webkit-backdrop-filter: blur(24px) saturate(1.2);
            border: 1px solid rgba(255, 255, 255, 0.6);
            border-radius: var(--radius-xl);
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.06), 0 1px 3px rgba(0, 0, 0, 0.04);
            padding: 56px 48px;
            max-width: 420px;
            width: 100%;
        }''',
    '''        .welcome-card-inner {
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
        }''')

# ============================================
# 5. 顶部栏增强毛玻璃
# ============================================
text = text.replace(
    '''        .topbar { height: 64px; background: rgba(255, 255, 255, 0.85); border-bottom: 1px solid rgba(0,0,0,0.04); display: flex; align-items: center; justify-content: space-between; padding: 0 28px; flex-shrink: 0; backdrop-filter: blur(20px) saturate(1.1); }''',
    '''        .topbar { height: 64px; background: rgba(255, 255, 255, 0.72); border-bottom: 1px solid rgba(255,255,255,0.5); display: flex; align-items: center; justify-content: space-between; padding: 0 28px; flex-shrink: 0; backdrop-filter: blur(40px) saturate(1.3); box-shadow: 0 1px 0 rgba(0,0,0,0.03); }''')

# ============================================
# 6. 侧边栏增强毛玻璃
# ============================================
text = text.replace(
    '''        .sidebar { width: 260px; background: rgba(255, 255, 255, 0.88); border-right: 1px solid rgba(0,0,0,0.04); display: flex; flex-direction: column; flex-shrink: 0; z-index: 10; backdrop-filter: blur(20px) saturate(1.1); }''',
    '''        .sidebar { width: 260px; background: rgba(255, 255, 255, 0.78); border-right: 1px solid rgba(255,255,255,0.5); display: flex; flex-direction: column; flex-shrink: 0; z-index: 10; backdrop-filter: blur(40px) saturate(1.3); }''')

# ============================================
# 7. 记忆侧边栏增强
# ============================================
text = text.replace(
    '''        .memory-sidebar { width: 300px; border-left: 1px solid rgba(0,0,0,0.04); background: rgba(255, 255, 255, 0.92); display: flex; flex-direction: column; flex-shrink: 0; transition: width 0.3s ease; backdrop-filter: blur(20px) saturate(1.1); border-radius: var(--radius-xl) 0 0 var(--radius-xl); margin: 8px 0 8px 0; overflow: hidden; box-shadow: -4px 0 24px rgba(0,0,0,0.04); }''',
    '''        .memory-sidebar { width: 300px; border-left: 1px solid rgba(255,255,255,0.5); background: rgba(255, 255, 255, 0.82); display: flex; flex-direction: column; flex-shrink: 0; transition: width 0.3s ease; backdrop-filter: blur(40px) saturate(1.3); border-radius: var(--radius-xl) 0 0 var(--radius-xl); margin: 8px 0 8px 0; overflow: hidden; box-shadow: -8px 0 32px rgba(0,0,0,0.06); }''')

# ============================================
# 8. 聊天输入区增强
# ============================================
text = text.replace(
    '''        .chat-input-area { padding: 16px 28px 24px; border-top: 1px solid rgba(0,0,0,0.04); background: rgba(255, 255, 255, 0.85); backdrop-filter: blur(20px) saturate(1.1); }''',
    '''        .chat-input-area { padding: 16px 28px 24px; border-top: 1px solid rgba(255,255,255,0.5); background: rgba(255, 255, 255, 0.72); backdrop-filter: blur(40px) saturate(1.3); }''')

# ============================================
# 9. 消息气泡增强
# ============================================
text = text.replace(
    '''        .msg.user .msg-content { background: rgba(17, 17, 17, 0.92); color: #fff; border-radius: var(--radius-lg); border-bottom-right-radius: 4px; padding: 12px 16px; backdrop-filter: blur(8px); box-shadow: 0 2px 8px rgba(0,0,0,0.1); }''',
    '''        .msg.user .msg-content { background: rgba(17, 17, 17, 0.9); color: #fff; border-radius: var(--radius-lg); border-bottom-right-radius: 4px; padding: 12px 16px; backdrop-filter: blur(8px); box-shadow: 0 4px 12px rgba(0,0,0,0.12); }''')

text = text.replace(
    '''        .msg.assistant .msg-content { background: rgba(255, 255, 255, 0.85); color: var(--text-primary); border: 1px solid rgba(255, 255, 255, 0.6); border-radius: var(--radius-lg); border-bottom-left-radius: 4px; padding: 12px 16px; backdrop-filter: blur(16px) saturate(1.1); box-shadow: 0 2px 8px rgba(0,0,0,0.04); }''',
    '''        .msg.assistant .msg-content { background: rgba(255, 255, 255, 0.75); color: var(--text-primary); border: 1px solid rgba(255, 255, 255, 0.7); border-radius: var(--radius-lg); border-bottom-left-radius: 4px; padding: 12px 16px; backdrop-filter: blur(24px) saturate(1.2); box-shadow: 0 4px 12px rgba(0,0,0,0.06), 0 0 0 1px rgba(255,255,255,0.4) inset; }''')

# ============================================
# 10. 角色卡片增强
# ============================================
text = text.replace(
    '''        .char-card { padding: 20px; border-radius: var(--radius-lg); background: rgba(255, 255, 255, 0.7); backdrop-filter: blur(16px); border: 1px solid var(--border); box-shadow: var(--shadow-sm); transition: var(--transition); cursor: pointer; position: relative; overflow: hidden; }''',
    '''        .char-card { padding: 20px; border-radius: var(--radius-xl); background: rgba(255, 255, 255, 0.72); backdrop-filter: blur(24px) saturate(1.2); border: 1px solid rgba(255,255,255,0.6); box-shadow: 0 4px 16px rgba(0,0,0,0.05), 0 0 0 1px rgba(255,255,255,0.4) inset; transition: var(--transition); cursor: pointer; position: relative; overflow: hidden; }''')

text = text.replace(
    '''        .char-card:hover { transform: translateY(-2px); box-shadow: var(--shadow); border-color: rgba(0, 0, 0, 0.1); }''',
    '''        .char-card:hover { transform: translateY(-2px); box-shadow: 0 8px 32px rgba(0,0,0,0.08), 0 0 0 1px rgba(255,255,255,0.5) inset; border-color: rgba(255,255,255,0.8); }''')

# ============================================
# 11. 设置区块增强
# ============================================
text = text.replace(
    '''        .setting-section { border-radius: var(--radius-xl); padding: 28px; }''',
    '''        .setting-section { border-radius: var(--radius-xl); padding: 28px; background: rgba(255,255,255,0.75); backdrop-filter: blur(24px) saturate(1.2); border: 1px solid rgba(255,255,255,0.6); box-shadow: 0 4px 16px rgba(0,0,0,0.05), 0 0 0 1px rgba(255,255,255,0.4) inset; }''')

# ============================================
# 12. 路由/RAG/微信状态卡片增强
# ============================================
text = text.replace(
    '''        .route-item { padding: 16px; border-radius: var(--radius-lg); background: rgba(255, 255, 255, 0.8); border: 1px solid rgba(255, 255, 255, 0.5); display: grid; grid-template-columns: 1fr 1fr 1fr auto; gap: 12px; align-items: end; backdrop-filter: blur(16px) saturate(1.1); box-shadow: 0 2px 8px rgba(0,0,0,0.03); }''',
    '''        .route-item { padding: 16px; border-radius: var(--radius-lg); background: rgba(255, 255, 255, 0.75); border: 1px solid rgba(255, 255, 255, 0.6); display: grid; grid-template-columns: 1fr 1fr 1fr auto; gap: 12px; align-items: end; backdrop-filter: blur(24px) saturate(1.2); box-shadow: 0 2px 8px rgba(0,0,0,0.04), 0 0 0 1px rgba(255,255,255,0.4) inset; }''')

text = text.replace(
    '''        .rag-hint { display: flex; align-items: center; gap: 10px; padding: 12px 16px; background: rgba(255, 255, 255, 0.8); border-radius: var(--radius-lg); border: 1px solid rgba(255, 255, 255, 0.5); font-size: 0.85rem; color: var(--text-secondary); backdrop-filter: blur(16px) saturate(1.1); box-shadow: 0 2px 8px rgba(0,0,0,0.03); }''',
    '''        .rag-hint { display: flex; align-items: center; gap: 10px; padding: 12px 16px; background: rgba(255, 255, 255, 0.75); border-radius: var(--radius-lg); border: 1px solid rgba(255, 255, 255, 0.6); font-size: 0.85rem; color: var(--text-secondary); backdrop-filter: blur(24px) saturate(1.2); box-shadow: 0 2px 8px rgba(0,0,0,0.04), 0 0 0 1px rgba(255,255,255,0.4) inset; }''')

text = text.replace(
    '''        .wechat-status-card { display: flex; align-items: center; gap: 16px; padding: 20px; border-radius: var(--radius-lg); background: rgba(255, 255, 255, 0.8); border: 1px solid rgba(255, 255, 255, 0.5); margin-bottom: 16px; backdrop-filter: blur(16px) saturate(1.1); box-shadow: 0 2px 8px rgba(0,0,0,0.03); }''',
    '''        .wechat-status-card { display: flex; align-items: center; gap: 16px; padding: 20px; border-radius: var(--radius-lg); background: rgba(255, 255, 255, 0.75); border: 1px solid rgba(255, 255, 255, 0.6); margin-bottom: 16px; backdrop-filter: blur(24px) saturate(1.2); box-shadow: 0 2px 8px rgba(0,0,0,0.04), 0 0 0 1px rgba(255,255,255,0.4) inset; }''')

# ============================================
# 13. 当前角色迷你卡片增强
# ============================================
text = text.replace(
    '''        .current-char-mini { display: flex; align-items: center; gap: 10px; padding: 10px 12px; background: var(--bg-elevated); border-radius: var(--radius-md); border: 1px solid var(--border-light); backdrop-filter: blur(12px); }''',
    '''        .current-char-mini { display: flex; align-items: center; gap: 10px; padding: 10px 12px; background: rgba(255,255,255,0.75); border-radius: var(--radius-lg); border: 1px solid rgba(255,255,255,0.6); backdrop-filter: blur(24px) saturate(1.2); box-shadow: 0 2px 8px rgba(0,0,0,0.04), 0 0 0 1px rgba(255,255,255,0.4) inset; }''')

with open(path, 'w', encoding='utf-8') as f:
    f.write(text)

print("Done! All glass & rounded card fixes applied.")
