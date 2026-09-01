import re

path = r"C:\Users\lmq20\Documents\Kimi\Workspaces\ai伴侣\ai-companion\gateway\static\index.html"

with open(path, 'r', encoding='utf-8') as f:
    text = f.read()

# ============================================
# 1. 增强 glass / glass-strong 类，增加圆角
# ============================================
text = text.replace(
    '''        .glass {
            background: rgba(255, 255, 255, 0.72);
            backdrop-filter: blur(24px);
            -webkit-backdrop-filter: blur(24px);
            border: 1px solid var(--border);
            box-shadow: var(--shadow);
        }
        .glass-strong {
            background: rgba(255, 255, 255, 0.88);
            backdrop-filter: blur(32px);
            -webkit-backdrop-filter: blur(32px);
            border: 1px solid var(--border);
            box-shadow: var(--shadow);
        }''',
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
        }''')

# ============================================
# 2. 增强 welcome-card：毛玻璃+圆角+悬浮阴影
# ============================================
text = text.replace(
    '''        .welcome-card {
            display: flex; flex-direction: column; align-items: center; justify-content: center;
            height: 100%; text-align: center; padding: 40px;
            animation: fadeIn 0.4s ease;
        }''',
    '''        .welcome-card {
            display: flex; flex-direction: column; align-items: center; justify-content: center;
            height: 100%; text-align: center; padding: 48px;
            animation: fadeIn 0.4s ease;
        }
        .welcome-card-inner {
            background: rgba(255, 255, 255, 0.8);
            backdrop-filter: blur(24px) saturate(1.2);
            -webkit-backdrop-filter: blur(24px) saturate(1.2);
            border: 1px solid rgba(255, 255, 255, 0.6);
            border-radius: var(--radius-xl);
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.06), 0 1px 3px rgba(0, 0, 0, 0.04);
            padding: 56px 48px;
            max-width: 420px;
            width: 100%;
        }''')

# ============================================
# 3. 修改 welcome-card HTML 结构：添加 inner 容器
# ============================================
text = text.replace(
    '''                        <div class="welcome-card" id="welcomeCard">
                            <div class="welcome-icon">
                                <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M12 2a10 10 0 1 0 10 10H12V2z"/><path d="M12 2a10 10 0 0 1 10 10"/><path d="M12 12 2.5 8.5"/></svg>
                            </div>
                            <h2>选择一位 AI 伙伴开始对话</h2>
                            <p>在「角色工坊」创建或选择角色，即可开始聊天。每个角色都有独特的性格和记忆。</p>
                            <button class="btn-welcome" onclick="app.switchView('characters')">前往角色工坊 <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg></button>
                        </div>''',
    '''                        <div class="welcome-card" id="welcomeCard">
                            <div class="welcome-card-inner">
                                <div class="welcome-icon">
                                    <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M12 2a10 10 0 1 0 10 10H12V2z"/><path d="M12 2a10 10 0 0 1 10 10"/><path d="M12 12 2.5 8.5"/></svg>
                                </div>
                                <h2>选择一位 AI 伙伴开始对话</h2>
                                <p>在「角色工坊」创建或选择角色，即可开始聊天。每个角色都有独特的性格和记忆。</p>
                                <button class="btn-welcome" onclick="app.switchView('characters')">前往角色工坊 <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg></button>
                            </div>
                        </div>''')

# ============================================
# 4. 用户消息气泡：从纯黑改成毛玻璃卡片风格
# ============================================
text = text.replace(
    '''        .msg.user .msg-content { background: var(--text-primary); color: #fff; border-radius: var(--radius-lg); border-bottom-right-radius: 4px; padding: 12px 16px; }''',
    '''        .msg.user .msg-content { background: rgba(17, 17, 17, 0.92); color: #fff; border-radius: var(--radius-lg); border-bottom-right-radius: 4px; padding: 12px 16px; backdrop-filter: blur(8px); box-shadow: 0 2px 8px rgba(0,0,0,0.1); }''')

# ============================================
# 5. 助理消息气泡：增强毛玻璃
# ============================================
text = text.replace(
    '''        .msg.assistant .msg-content { background: var(--bg-elevated); color: var(--text-primary); border: 1px solid var(--border); border-radius: var(--radius-lg); border-bottom-left-radius: 4px; padding: 12px 16px; backdrop-filter: blur(12px); }''',
    '''        .msg.assistant .msg-content { background: rgba(255, 255, 255, 0.85); color: var(--text-primary); border: 1px solid rgba(255, 255, 255, 0.6); border-radius: var(--radius-lg); border-bottom-left-radius: 4px; padding: 12px 16px; backdrop-filter: blur(16px) saturate(1.1); box-shadow: 0 2px 8px rgba(0,0,0,0.04); }''')

# ============================================
# 6. 输入区域：增强毛玻璃卡片感
# ============================================
text = text.replace(
    '''        .chat-input-area { padding: 16px 28px 24px; border-top: 1px solid var(--border); background: rgba(255, 255, 255, 0.8); backdrop-filter: blur(16px); }''',
    '''        .chat-input-area { padding: 16px 28px 24px; border-top: 1px solid rgba(0,0,0,0.04); background: rgba(255, 255, 255, 0.85); backdrop-filter: blur(20px) saturate(1.1); }''')

# ============================================
# 7. 输入框本身：增强白色卡片感
# ============================================
text = text.replace(
    '''        .chat-input { flex: 1; padding: 12px 16px; border: 1px solid var(--border); border-radius: var(--radius-xl); font-size: 0.95rem; font-family: inherit; color: var(--text-primary); background: var(--bg-surface); outline: none; resize: none; max-height: 120px; line-height: 1.5; transition: var(--transition); }''',
    '''        .chat-input { flex: 1; padding: 12px 16px; border: 1px solid rgba(0,0,0,0.08); border-radius: var(--radius-xl); font-size: 0.95rem; font-family: inherit; color: var(--text-primary); background: rgba(255, 255, 255, 0.95); outline: none; resize: none; max-height: 120px; line-height: 1.5; transition: var(--transition); box-shadow: 0 1px 3px rgba(0,0,0,0.04); }''')

# ============================================
# 8. 顶部栏：增强毛玻璃
# ============================================
text = text.replace(
    '''        .topbar { height: 64px; background: rgba(255, 255, 255, 0.8); border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between; padding: 0 28px; flex-shrink: 0; backdrop-filter: blur(16px); }''',
    '''        .topbar { height: 64px; background: rgba(255, 255, 255, 0.85); border-bottom: 1px solid rgba(0,0,0,0.04); display: flex; align-items: center; justify-content: space-between; padding: 0 28px; flex-shrink: 0; backdrop-filter: blur(20px) saturate(1.1); }''')

# ============================================
# 9. 侧边栏：增强毛玻璃
# ============================================
text = text.replace(
    '''        .sidebar { width: 260px; background: rgba(255, 255, 255, 0.85); border-right: 1px solid var(--border); display: flex; flex-direction: column; flex-shrink: 0; z-index: 10; backdrop-filter: blur(16px); }''',
    '''        .sidebar { width: 260px; background: rgba(255, 255, 255, 0.88); border-right: 1px solid rgba(0,0,0,0.04); display: flex; flex-direction: column; flex-shrink: 0; z-index: 10; backdrop-filter: blur(20px) saturate(1.1); }''')

# ============================================
# 10. 记忆侧边栏：增加圆角和更好的玻璃效果
# ============================================
text = text.replace(
    '''        .memory-sidebar { width: 300px; border-left: 1px solid var(--border); background: rgba(255, 255, 255, 0.9); display: flex; flex-direction: column; flex-shrink: 0; transition: width 0.3s ease; backdrop-filter: blur(12px); }''',
    '''        .memory-sidebar { width: 300px; border-left: 1px solid rgba(0,0,0,0.04); background: rgba(255, 255, 255, 0.92); display: flex; flex-direction: column; flex-shrink: 0; transition: width 0.3s ease; backdrop-filter: blur(20px) saturate(1.1); border-radius: var(--radius-xl) 0 0 var(--radius-xl); margin: 8px 0 8px 0; overflow: hidden; box-shadow: -4px 0 24px rgba(0,0,0,0.04); }''')

# ============================================
# 11. 角色卡片选中状态：去掉硬编码蓝色
# ============================================
text = text.replace(
    '''        .char-card.selected { border-color: var(--primary); box-shadow: 0 0 0 1px var(--primary), 0 4px 20px rgba(37, 99, 235, 0.1); }''',
    '''        .char-card.selected { border-color: var(--primary); box-shadow: 0 0 0 1.5px var(--primary), 0 8px 24px rgba(0, 0, 0, 0.1); }''')

# ============================================
# 12. badge-primary：去掉硬编码蓝色
# ============================================
text = text.replace(
    '''        .badge-primary { background: var(--primary-glow); color: var(--primary); border: 1px solid rgba(37, 99, 235, 0.15); }''',
    '''        .badge-primary { background: rgba(0, 0, 0, 0.04); color: var(--primary); border: 1px solid rgba(0, 0, 0, 0.08); }''')

# ============================================
# 13. content-body 增加内边距，让卡片有呼吸感
# ============================================
text = text.replace(
    '''        .content-body { padding: 24px 32px; overflow-y: auto; flex: 1; }''',
    '''        .content-body { padding: 28px 36px; overflow-y: auto; flex: 1; }''')

# ============================================
# 14. 设置区块 glass-strong 已经应用，但增加统一的圆角
# ============================================
text = text.replace(
    '''        .setting-section { border-radius: var(--radius-lg); padding: 24px; }''',
    '''        .setting-section { border-radius: var(--radius-xl); padding: 28px; }''')

# ============================================
# 15. slider thumb 去掉硬编码蓝色阴影
# ============================================
text = text.replace(
    '''        .form-slider::-webkit-slider-thumb { -webkit-appearance: none; width: 18px; height: 18px; border-radius: 50%; background: var(--primary); cursor: pointer; border: 2px solid #fff; box-shadow: 0 2px 6px rgba(37, 99, 235, 0.3); }''',
    '''        .form-slider::-webkit-slider-thumb { -webkit-appearance: none; width: 18px; height: 18px; border-radius: 50%; background: var(--primary); cursor: pointer; border: 2px solid #fff; box-shadow: 0 2px 6px rgba(0, 0, 0, 0.15); }''')

# ============================================
# 16. 路由条目、RAG提示等增强毛玻璃
# ============================================
text = text.replace(
    '''        .route-item { padding: 16px; border-radius: var(--radius-md); background: var(--bg-elevated); border: 1px solid var(--border); display: grid; grid-template-columns: 1fr 1fr 1fr auto; gap: 12px; align-items: end; backdrop-filter: blur(12px); }''',
    '''        .route-item { padding: 16px; border-radius: var(--radius-lg); background: rgba(255, 255, 255, 0.8); border: 1px solid rgba(255, 255, 255, 0.5); display: grid; grid-template-columns: 1fr 1fr 1fr auto; gap: 12px; align-items: end; backdrop-filter: blur(16px) saturate(1.1); box-shadow: 0 2px 8px rgba(0,0,0,0.03); }''')

text = text.replace(
    '''        .rag-hint { display: flex; align-items: center; gap: 10px; padding: 12px 16px; background: var(--bg-elevated); border-radius: var(--radius-md); border: 1px solid var(--border); font-size: 0.85rem; color: var(--text-secondary); backdrop-filter: blur(12px); }''',
    '''        .rag-hint { display: flex; align-items: center; gap: 10px; padding: 12px 16px; background: rgba(255, 255, 255, 0.8); border-radius: var(--radius-lg); border: 1px solid rgba(255, 255, 255, 0.5); font-size: 0.85rem; color: var(--text-secondary); backdrop-filter: blur(16px) saturate(1.1); box-shadow: 0 2px 8px rgba(0,0,0,0.03); }''')

text = text.replace(
    '''        .wechat-status-card { display: flex; align-items: center; gap: 16px; padding: 20px; border-radius: var(--radius-lg); background: var(--bg-elevated); border: 1px solid var(--border); margin-bottom: 16px; backdrop-filter: blur(12px); }''',
    '''        .wechat-status-card { display: flex; align-items: center; gap: 16px; padding: 20px; border-radius: var(--radius-lg); background: rgba(255, 255, 255, 0.8); border: 1px solid rgba(255, 255, 255, 0.5); margin-bottom: 16px; backdrop-filter: blur(16px) saturate(1.1); box-shadow: 0 2px 8px rgba(0,0,0,0.03); }''')

# ============================================
# 17. 标签芯片增强
# ============================================
text = text.replace(
    '''        .tag-chip { display: inline-flex; align-items: center; gap: 4px; padding: 4px 10px; border-radius: 20px; font-size: 0.8rem; background: var(--bg-elevated); color: var(--text-secondary); border: 1px solid var(--border); }''',
    '''        .tag-chip { display: inline-flex; align-items: center; gap: 4px; padding: 4px 10px; border-radius: 20px; font-size: 0.8rem; background: rgba(255, 255, 255, 0.8); color: var(--text-secondary); border: 1px solid rgba(0,0,0,0.06); backdrop-filter: blur(8px); }''')

# ============================================
# 18. Toast 增加圆角和阴影
# ============================================
text = text.replace(
    '''        .toast { padding: 12px 20px; border-radius: var(--radius-md); font-size: 0.9rem; font-weight: 500; color: #fff; animation: toastIn 0.3s ease; box-shadow: var(--shadow); }''',
    '''        .toast { padding: 12px 20px; border-radius: var(--radius-lg); font-size: 0.9rem; font-weight: 500; color: #fff; animation: toastIn 0.3s ease; box-shadow: 0 8px 24px rgba(0,0,0,0.12); }''')

# ============================================
# 19. setting-hint 去掉硬编码蓝色边框，改用黑色主题
# ============================================
text = text.replace(
    '''        .setting-hint { font-size: 0.8rem; color: var(--text-tertiary); margin-bottom: 16px; line-height: 1.5; padding: 10px 14px; background: var(--primary-glow); border-radius: var(--radius-md); border-left: 3px solid var(--primary); }''',
    '''        .setting-hint { font-size: 0.8rem; color: var(--text-tertiary); margin-bottom: 16px; line-height: 1.5; padding: 10px 14px; background: rgba(0, 0, 0, 0.02); border-radius: var(--radius-md); border-left: 3px solid var(--primary); }''')

with open(path, 'w', encoding='utf-8') as f:
    f.write(text)

print("Glassmorphism & rounded card enhancements applied!")
print(f"File size: {len(text)} chars")
