import re

path = r"C:\Users\lmq20\Documents\Kimi\Workspaces\ai伴侣\ai-companion\gateway\static\index.html"

with open(path, 'r', encoding='utf-8') as f:
    text = f.read()

# ============================================
# 1. 添加CSS：欢迎引导卡片、状态控制
# ============================================
css_addition = '''
        .welcome-card {
            display: flex; flex-direction: column; align-items: center; justify-content: center;
            height: 100%; text-align: center; padding: 40px;
            animation: fadeIn 0.4s ease;
        }
        .welcome-card .welcome-icon {
            width: 72px; height: 72px; border-radius: var(--radius-xl);
            background: var(--bg-surface); border: 1px solid var(--border);
            display: flex; align-items: center; justify-content: center;
            margin-bottom: 24px; box-shadow: var(--shadow-sm);
        }
        .welcome-card .welcome-icon svg { color: var(--text-secondary); }
        .welcome-card h2 { font-size: 1.25rem; font-weight: 700; color: var(--text-primary); margin-bottom: 8px; }
        .welcome-card p { font-size: 0.9rem; color: var(--text-secondary); max-width: 320px; line-height: 1.6; margin-bottom: 28px; }
        .welcome-card .btn-welcome {
            background: var(--primary); color: #fff; padding: 10px 24px; border-radius: var(--radius-lg);
            font-size: 0.9rem; font-weight: 600; cursor: pointer; border: none; transition: var(--transition);
            display: inline-flex; align-items: center; gap: 6px;
        }
        .welcome-card .btn-welcome:hover { background: var(--primary-light); transform: translateY(-1px); }

        .sidebar-empty-hint {
            display: flex; align-items: center; justify-content: center; gap: 6px;
            font-size: 0.8rem; color: var(--text-muted); padding: 10px; text-align: center;
            border: 1px dashed var(--border); border-radius: var(--radius-md); margin-top: 8px;
            cursor: pointer; transition: var(--transition);
        }
        .sidebar-empty-hint:hover { color: var(--text-primary); border-color: var(--text-muted); background: var(--bg-hover); }

        .chat-state-hidden { display: none !important; }
'''

# Insert CSS before the closing </style>
text = text.replace('    </style>', css_addition + '    </style>')

# ============================================
# 2. 修改侧边栏底部
# ============================================
old_sidebar_footer = '''            <div class="sidebar-footer">
                <div class="current-char-mini" id="sidebarCharInfo" style="display:none;">
                    <div class="avatar" id="sidebarCharAvatar"></div>
                    <div style="flex:1;min-width:0;"><div class="name" id="sidebarCharName"></div><div class="status"><span class="status-dot"></span>在线</div></div>
                </div>
                <div id="sidebarNoChar" style="font-size:0.8rem;color:var(--text-muted);text-align:center;padding:10px;">未选择角色</div>
            </div>'''

new_sidebar_footer = '''            <div class="sidebar-footer">
                <div class="current-char-mini" id="sidebarCharInfo" style="display:none;">
                    <div class="avatar" id="sidebarCharAvatar"></div>
                    <div style="flex:1;min-width:0;"><div class="name" id="sidebarCharName"></div><div class="status"><span class="status-dot"></span>在线</div></div>
                </div>
                <div class="sidebar-empty-hint" id="sidebarNoChar" onclick="app.switchView('characters')">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
                    点击前往角色工坊
                </div>
            </div>'''

text = text.replace(old_sidebar_footer, new_sidebar_footer)

# ============================================
# 3. 修改顶部栏：右侧清空按钮加id，方便JS控制显隐
# ============================================
old_topbar_right = '''                <div class="topbar-right">
                    <button class="btn btn-ghost btn-sm" onclick="app.clearChat()"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>清空对话</button>
                </div>'''

new_topbar_right = '''                <div class="topbar-right" id="topbarActions" style="opacity:0;pointer-events:none;transition:opacity 0.2s;">
                    <button class="btn btn-ghost btn-sm" onclick="app.clearChat()"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>清空对话</button>
                </div>'''

text = text.replace(old_topbar_right, new_topbar_right)

# ============================================
# 4. 修改聊天区域：添加welcome-card，给input-area加id
# ============================================
old_chat_layout = '''                <div class="chat-layout">
                    <div style="flex:1;display:flex;flex-direction:column;min-width:0;">
                        <div class="messages-area" id="messagesArea"></div>
                        <div class="chat-input-area">
                            <div style="display:flex;gap:12px;align-items:flex-end;max-width:768px;margin:0 auto;">
                                <textarea class="chat-input" id="chatInput" rows="1" placeholder="请先在角色工坊选择一个角色" onkeydown="app.handleChatKeydown(event)" oninput="this.style.height='auto';this.style.height=this.scrollHeight+'px';document.getElementById('chatSendBtn').disabled=!this.value.trim();"></textarea>
                                <button class="chat-send-btn" id="chatSendBtn" onclick="app.sendMessage()" disabled><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg></button>
                            </div>
                        </div>
                    </div>'''

new_chat_layout = '''                <div class="chat-layout">
                    <div style="flex:1;display:flex;flex-direction:column;min-width:0;position:relative;">
                        <!-- 欢迎引导（未选角色时显示） -->
                        <div class="welcome-card" id="welcomeCard">
                            <div class="welcome-icon">
                                <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M12 2a10 10 0 1 0 10 10H12V2z"/><path d="M12 2a10 10 0 0 1 10 10"/><path d="M12 12 2.5 8.5"/></svg>
                            </div>
                            <h2>选择一位 AI 伙伴开始对话</h2>
                            <p>在「角色工坊」创建或选择角色，即可开始聊天。每个角色都有独特的性格和记忆。</p>
                            <button class="btn-welcome" onclick="app.switchView('characters')">前往角色工坊 <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg></button>
                        </div>
                        <!-- 消息区域（选角色后显示） -->
                        <div class="messages-area chat-state-hidden" id="messagesArea"></div>
                        <!-- 输入框（选角色后显示） -->
                        <div class="chat-input-area chat-state-hidden" id="chatInputArea">
                            <div style="display:flex;gap:12px;align-items:flex-end;max-width:768px;margin:0 auto;">
                                <textarea class="chat-input" id="chatInput" rows="1" placeholder="和伙伴说点什么..." onkeydown="app.handleChatKeydown(event)" oninput="this.style.height='auto';this.style.height=this.scrollHeight+'px';document.getElementById('chatSendBtn').disabled=!this.value.trim();"></textarea>
                                <button class="chat-send-btn" id="chatSendBtn" onclick="app.sendMessage()" disabled><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg></button>
                            </div>
                        </div>
                    </div>'''

text = text.replace(old_chat_layout, new_chat_layout)

# ============================================
# 5. 修改JS：updateChatHeader 改为 updateChatState，统一控制显隐
# ============================================
old_update_header = '''        updateChatHeader() {
            const char = this.state.currentCharacter;
            const avatar = document.getElementById('chatHeaderAvatar');
            const name = document.getElementById('chatHeaderName');
            const status = document.getElementById('chatHeaderStatus');
            if (char) {
                const color = char.avatar_color || getAvatarColor(char.name);
                avatar.textContent = char.name[0]; avatar.style.background = color;
                name.textContent = char.name; status.textContent = char.tagline || '在线';
                document.getElementById('chatInput').placeholder = `和 ${char.name} 说点什么...`;
            } else {
                avatar.textContent = '?'; avatar.style.background = '#888';
                name.textContent = '未选择角色'; status.textContent = '请先在角色工坊选择一个角色';
                document.getElementById('chatInput').placeholder = '请先在角色工坊选择一个角色';
            }
        },'''

new_update_header = '''        updateChatState() {
            const char = this.state.currentCharacter;
            const avatar = document.getElementById('chatHeaderAvatar');
            const name = document.getElementById('chatHeaderName');
            const status = document.getElementById('chatHeaderStatus');
            const welcomeCard = document.getElementById('welcomeCard');
            const messagesArea = document.getElementById('messagesArea');
            const chatInputArea = document.getElementById('chatInputArea');
            const topbarActions = document.getElementById('topbarActions');
            const sidebarCharInfo = document.getElementById('sidebarCharInfo');
            const sidebarNoChar = document.getElementById('sidebarNoChar');

            if (char) {
                // 已选角色：显示聊天界面
                const color = char.avatar_color || getAvatarColor(char.name);
                avatar.textContent = char.name[0]; avatar.style.background = color;
                name.textContent = char.name; status.textContent = char.tagline || '在线';
                document.getElementById('chatInput').placeholder = `和 ${char.name} 说点什么...`;

                welcomeCard.style.display = 'none';
                messagesArea.classList.remove('chat-state-hidden');
                chatInputArea.classList.remove('chat-state-hidden');
                topbarActions.style.opacity = '1'; topbarActions.style.pointerEvents = 'auto';
                sidebarCharInfo.style.display = 'flex';
                sidebarNoChar.style.display = 'none';
            } else {
                // 未选角色：显示欢迎引导
                avatar.textContent = ''; avatar.style.background = 'transparent';
                name.textContent = 'AI Companion'; status.textContent = '';

                welcomeCard.style.display = 'flex';
                messagesArea.classList.add('chat-state-hidden');
                chatInputArea.classList.add('chat-state-hidden');
                topbarActions.style.opacity = '0'; topbarActions.style.pointerEvents = 'none';
                sidebarCharInfo.style.display = 'none';
                sidebarNoChar.style.display = 'flex';
            }
        },'''

text = text.replace(old_update_header, new_update_header)

# ============================================
# 6. 替换所有调用 updateChatHeader() 的地方为 updateChatState()
# ============================================
text = text.replace('this.updateChatHeader()', 'this.updateChatState()')
text = text.replace('app.updateChatHeader()', 'app.updateChatState()')

# ============================================
# 7. 修改 sendMessage 中的 toast 提示，更友好
# ============================================
text = text.replace(
    "if (!this.state.currentCharacter) { this.toast('请先在角色工坊选择一个角色', 'error'); return; }",
    "if (!this.state.currentCharacter) { this.switchView('characters'); this.toast('请先选择或创建一个角色', 'info'); return; }"
)

with open(path, 'w', encoding='utf-8') as f:
    f.write(text)

print("Done! Changes applied.")

# Verify the file is valid by checking line count and basic structure
with open(path, 'r', encoding='utf-8') as f:
    lines = f.readlines()
print(f"Total lines: {len(lines)}")
