path = r"C:\Users\lmq20\Documents\Kimi\Workspaces\ai伴侣\ai-companion\gateway\static\index.html"

with open(path, 'r', encoding='utf-8') as f:
    text = f.read()

# ================================================================
# 1. 改名
# ================================================================
text = text.replace('<title>AI Companion</title>', '<title>茧语 · Cocoon</title>')
text = text.replace('logo-icon">AI</div><div class="logo-text">AI Companion</div>', 'logo-icon">茧</div><div class="logo-text">茧语</div>')
text = text.replace("name.textContent = 'AI Companion'; status.textContent = '';", "name.textContent = '茧语'; status.textContent = '';")
text = text.replace(
    '<div class="topbar-title" id="chatHeaderName">AI Companion</div>\n                        <div class="topbar-subtitle" id="chatHeaderStatus"></div>',
    '<div class="topbar-title" id="chatHeaderName">茧语</div>\n                        <div class="topbar-subtitle" id="chatHeaderStatus"></div>')

# ================================================================
# 2. "路由模型" → "路由设置"
# ================================================================
text = text.replace('>路由模型</button>', '>路由设置</button>')

# ================================================================
# 3. 深色模式CSS变量
# ================================================================
# 在 :root 闭合后添加 dark 主题变量
dark_css = '''        }
        :root[data-theme="dark"] {
            --primary: #f0f0f0;
            --primary-light: #ffffff;
            --primary-dark: #cccccc;
            --primary-glow: rgba(255, 255, 255, 0.08);
            --secondary: #aaaaaa;
            --bg-base: #0a0a0c;
            --bg-surface: #1a1a1e;
            --bg-elevated: rgba(30, 30, 35, 0.75);
            --bg-hover: rgba(255, 255, 255, 0.05);
            --bg-active: rgba(255, 255, 255, 0.08);
            --text-primary: #f0f0f0;
            --text-secondary: #b0b0b0;
            --text-tertiary: #808080;
            --text-muted: #555555;
            --border: rgba(255, 255, 255, 0.06);
            --border-light: rgba(255, 255, 255, 0.04);
            --border-focus: #f0f0f0;
            --liquid-bg: linear-gradient(180deg, rgba(40,40,48,0.55) 0%, rgba(25,25,30,0.28) 100%);
            --liquid-bg-strong: linear-gradient(180deg, rgba(50,50,58,0.70) 0%, rgba(30,30,38,0.40) 100%);
            --liquid-border: 1px solid rgba(255,255,255,0.10);
            --liquid-highlight: inset 0 1.5px 1px rgba(255,255,255,0.15), inset 0 -1px 1px rgba(0,0,0,0.20);
            --liquid-shadow: 0 12px 40px rgba(0,0,0,0.30), 0 2px 8px rgba(0,0,0,0.15);
            --shadow: 0 4px 24px rgba(0, 0, 0, 0.25);
            --shadow-sm: 0 2px 8px rgba(0, 0, 0, 0.15);
        }
        body[data-theme="dark"] {
            background:
                radial-gradient(ellipse 700px 500px at 10% 20%, rgba(60,60,80,0.35) 0%, transparent 70%),
                radial-gradient(ellipse 600px 450px at 90% 85%, rgba(50,50,70,0.30) 0%, transparent 70%),
                radial-gradient(ellipse 500px 400px at 50% 60%, rgba(55,55,75,0.25) 0%, transparent 60%),
                radial-gradient(ellipse 450px 350px at 80% 10%, rgba(45,45,65,0.20) 0%, transparent 60%),
                radial-gradient(ellipse 400px 300px at 30% 80%, rgba(50,50,70,0.18) 0%, transparent 50%),
                #0a0a0c;
            color-scheme: dark;
        }'''
# 找到 :root 的闭合位置并插入 dark 主题
old_root_close = '''            --transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
            --font-sans: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', 'Helvetica Neue', sans-serif;
        }'''
new_root_close = '''            --transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
            --font-sans: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', 'Helvetica Neue', sans-serif;
''' + dark_css

# 但这样替换会把后面重复的也改掉，需要更精确
old_precise = '''            --transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
            --font-sans: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', 'Helvetica Neue', sans-serif;
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }'''
new_precise = '''            --transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
            --font-sans: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', 'Helvetica Neue', sans-serif;
        }
        :root[data-theme="dark"] {
            --primary: #f0f0f0;
            --primary-light: #ffffff;
            --primary-dark: #cccccc;
            --primary-glow: rgba(255, 255, 255, 0.08);
            --secondary: #aaaaaa;
            --bg-base: #0a0a0c;
            --bg-surface: #1a1a1e;
            --bg-elevated: rgba(30, 30, 35, 0.75);
            --bg-hover: rgba(255, 255, 255, 0.05);
            --bg-active: rgba(255, 255, 255, 0.08);
            --text-primary: #f0f0f0;
            --text-secondary: #b0b0b0;
            --text-tertiary: #808080;
            --text-muted: #555555;
            --border: rgba(255, 255, 255, 0.06);
            --border-light: rgba(255, 255, 255, 0.04);
            --border-focus: #f0f0f0;
            --liquid-bg: linear-gradient(180deg, rgba(40,40,48,0.55) 0%, rgba(25,25,30,0.28) 100%);
            --liquid-bg-strong: linear-gradient(180deg, rgba(50,50,58,0.70) 0%, rgba(30,30,38,0.40) 100%);
            --liquid-border: 1px solid rgba(255,255,255,0.10);
            --liquid-highlight: inset 0 1.5px 1px rgba(255,255,255,0.15), inset 0 -1px 1px rgba(0,0,0,0.20);
            --liquid-shadow: 0 12px 40px rgba(0,0,0,0.30), 0 2px 8px rgba(0,0,0,0.15);
            --shadow: 0 4px 24px rgba(0, 0, 0, 0.25);
            --shadow-sm: 0 2px 8px rgba(0, 0, 0, 0.15);
        }
        body[data-theme="dark"] {
            background:
                radial-gradient(ellipse 700px 500px at 10% 20%, rgba(60,60,80,0.35) 0%, transparent 70%),
                radial-gradient(ellipse 600px 450px at 90% 85%, rgba(50,50,70,0.30) 0%, transparent 70%),
                radial-gradient(ellipse 500px 400px at 50% 60%, rgba(55,55,75,0.25) 0%, transparent 60%),
                radial-gradient(ellipse 450px 350px at 80% 10%, rgba(45,45,65,0.20) 0%, transparent 60%),
                radial-gradient(ellipse 400px 300px at 30% 80%, rgba(50,50,70,0.18) 0%, transparent 50%),
                #0a0a0c;
            color-scheme: dark;
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }'''
text = text.replace(old_precise, new_precise)

# ================================================================
# 4. 添加设置tab平滑转场CSS
# ================================================================
transition_css = '''        .settings-tab-content {
            display: none;
            opacity: 0;
            transform: translateY(8px);
            transition: opacity 0.3s ease, transform 0.3s ease;
        }
        .settings-tab-content.active {
            display: block;
            opacity: 1;
            transform: translateY(0);
        }
        .settings-tab-content.leaving {
            opacity: 0;
            transform: translateY(-4px);
        }'''

# 替换旧的 settings-tab-content CSS
old_tab_css = '''        .settings-tab-content { display: none; }
        .settings-tab-content.active { display: block; }'''
text = text.replace(old_tab_css, transition_css)

# ================================================================
# 5. 添加按钮抖动动画CSS
# ================================================================
shake_css = '''        @keyframes shake { 0%,100%{transform:translateX(0)} 20%{transform:translateX(-6px)} 40%{transform:translateX(6px)} 60%{transform:translateX(-4px)} 80%{transform:translateX(4px)} }
        .shake { animation: shake 0.4s ease; }
        .btn-locked { opacity: 0.5; cursor: not-allowed; position: relative; }
        .btn-locked::after { content: '🔒'; position: absolute; right: 8px; font-size: 0.75rem; }'''
# 插入到 toast 动画后面
old_toast_anim = '''        .toast.info { background: var(--primary); }

        .view-section { display: none; height: 100%; }'''
new_toast_anim = '''        .toast.info { background: var(--primary); }
''' + shake_css + '''
        .view-section { display: none; height: 100%; }'''
text = text.replace(old_toast_anim, new_toast_anim)

# ================================================================
# 6. 添加主题设置到设置页面（外观设置tab）
# ================================================================
# 在设置tabs里加"外观"
old_tabs = '''                        <div class="settings-tabs">
                            <button class="settings-tab active" data-tab="llm" onclick="app.switchSettingsTab('llm')">LLM 设置</button>
                            <button class="settings-tab" data-tab="route" onclick="app.switchSettingsTab('route')">路由设置</button>
                            <button class="settings-tab" data-tab="rag" onclick="app.switchSettingsTab('rag')">知识库</button>
                            <button class="settings-tab" data-tab="wechat" onclick="app.switchSettingsTab('wechat')">微信</button>
                            <button class="settings-tab" data-tab="memory" onclick="app.switchSettingsTab('memory')">记忆标签</button>
                        </div>'''
new_tabs = '''                        <div class="settings-tabs">
                            <button class="settings-tab active" data-tab="llm" onclick="app.switchSettingsTab('llm')">LLM 设置</button>
                            <button class="settings-tab" data-tab="route" onclick="app.switchSettingsTab('route')">路由设置</button>
                            <button class="settings-tab" data-tab="rag" onclick="app.switchSettingsTab('rag')">知识库</button>
                            <button class="settings-tab" data-tab="wechat" onclick="app.switchSettingsTab('wechat')">微信</button>
                            <button class="settings-tab" data-tab="memory" onclick="app.switchSettingsTab('memory')">记忆标签</button>
                            <button class="settings-tab" data-tab="appearance" onclick="app.switchSettingsTab('appearance')">外观</button>
                        </div>'''
text = text.replace(old_tabs, new_tabs)

# 在wechat tab后面添加外观设置tab content
old_wechat_end = '''                        </div>
                    </div>
                </div>
            </section>
        </main>
    </div>'''

# 找到 wechat content 和 memory content 之间的位置来插入
# 实际上 memory 在 wechat 后面，所以我需要在 memory 后面插入
old_memory_end = '''                        </div>
                    </div>
                </div>
            </section>
        </main>
    </div>'''

# 先找到正确的插入位置 - 在 memory content 关闭后
memory_close = '''                            </div>
                        </div>

                        <div class="settings-tab-content" data-tab-content="memory">'''

# 让我换个方式，在 memory content 结束标签后插入
old_after_memory = '''                            </div>
                        </div>
                    </div>
                </div>
            </section>
        </main>
    </div>'''

# 这太复杂了，让我直接找 settings-layout 的闭合
old_settings_layout = '''                    </div>
                </div>
            </section>
        </main>
    </div>'''

# 实际上我要在最后一个 settings-tab-content (memory) 后面加外观 content
# 让我找 memory content 的结束
old_memory_content_end = '''                            </div>
                        </div>

                    </div>
                </div>
            </section>'''

# 这个匹配可能不精确，让我换一种方式：在 view-settings 内的 content-body 结束前插入
# 找到 </section> 之前的 </div> 闭合
old_end_section = '''            </section>
        </main>
    </div>'''

# 让我直接插入外观 tab content 在 memory tab 后面
old_memory_tab = '''                        <div class="settings-tab-content" data-tab-content="memory">
                            <div class="setting-section glass-strong">
                                <div class="setting-section-header"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="20" height="20"><path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/><line x1="7" y1="7" x2="7.01" y2="7"/></svg><h3>记忆标签</h3></div>
                                <div style="display:flex;gap:10px;margin-bottom:20px;"><input type="text" class="form-input" id="newTagInput" placeholder="输入新标签..." onkeydown="if(event.key==='Enter')app.addMemoryTag()"><button class="btn btn-primary" onclick="app.addMemoryTag()">添加</button></div>
                                <div id="memoryTagList" style="display:flex;flex-wrap:wrap;gap:8px;"></div>
                            </div>
                        </div>
                    </div>
                </div>
            </section>'''

new_memory_tab = '''                        <div class="settings-tab-content" data-tab-content="memory">
                            <div class="setting-section glass-strong">
                                <div class="setting-section-header"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="20" height="20"><path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/><line x1="7" y1="7" x2="7.01" y2="7"/></svg><h3>记忆标签</h3></div>
                                <div style="display:flex;gap:10px;margin-bottom:20px;"><input type="text" class="form-input" id="newTagInput" placeholder="输入新标签..." onkeydown="if(event.key==='Enter')app.addMemoryTag()"><button class="btn btn-primary" onclick="app.addMemoryTag()">添加</button></div>
                                <div id="memoryTagList" style="display:flex;flex-wrap:wrap;gap:8px;"></div>
                            </div>
                        </div>

                        <div class="settings-tab-content" data-tab-content="appearance">
                            <div class="setting-section glass-strong">
                                <div class="setting-section-header"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="20" height="20"><circle cx="12" cy="12" r="5"/><path d="M12 1v2"/><path d="M12 21v2"/><path d="M4.22 4.22l1.42 1.42"/><path d="M18.36 18.36l1.42 1.42"/><path d="M1 12h2"/><path d="M21 12h2"/><path d="M4.22 19.78l1.42-1.42"/><path d="M18.36 5.64l1.42-1.42"/></svg><h3>外观</h3></div>
                                <div class="form-group">
                                    <label class="form-label">主题模式</label>
                                    <div style="display:flex;gap:8px;">
                                        <button class="btn btn-secondary" id="themeLight" onclick="app.setTheme('light')">浅色</button>
                                        <button class="btn btn-secondary" id="themeDark" onclick="app.setTheme('dark')">深色</button>
                                        <button class="btn btn-secondary" id="themeAuto" onclick="app.setTheme('auto')">跟随系统</button>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </section>'''
text = text.replace(old_memory_tab, new_memory_tab)

# ================================================================
# 7. LLM设置：去掉hidden input，修复模型值传递
# ================================================================
# 去掉 hidden input 和 onchange 中的 hidden input 更新
old_model_select = '''                                        <select class="form-select" id="settingModelSelect" style="flex:1;" onchange="document.getElementById('settingModel').value=this.value">
                                            <option value="">-- 点击刷新获取模型列表 --</option>
                                        </select>'''
new_model_select = '''                                        <select class="form-select" id="settingModelSelect" style="flex:1;">
                                            <option value="">-- 点击刷新获取模型列表 --</option>
                                        </select>'''
text = text.replace(old_model_select, new_model_select)

# 去掉 hidden input 行
old_hidden = '''                                    <input type="hidden" id="settingModel">
                                    <div style="margin-top:6px;font-size:0.75rem;color:var(--text-tertiary);">如果下拉列表无法加载，也可以手动输入模型名称</div>'''
new_hidden = '''                                    <div style="margin-top:6px;font-size:0.75rem;color:var(--text-tertiary);">如果下拉列表无法加载，也可以手动输入模型名称</div>'''
text = text.replace(old_hidden, new_hidden)

# ================================================================
# 8. 修改 verifyLLM：读取 select.value 而不是 hidden input
# ================================================================
old_verify = '''        async verifyLLM() {
            const url = document.getElementById('settingApiUrl').value.trim() || LLM_API;
            const model = document.getElementById('settingModel').value.trim() || 'qwen3.6-35b';
            const apiKey = document.getElementById('settingApiKey').value.trim();'''
new_verify = '''        async verifyLLM() {
            const url = document.getElementById('settingApiUrl').value.trim() || LLM_API;
            const sel = document.getElementById('settingModelSelect');
            const model = (sel.value || '').trim() || 'qwen3.6-35b';
            const apiKey = document.getElementById('settingApiKey').value.trim();'''
text = text.replace(old_verify, new_verify)

# verifyLLM 成功后标记验证通过
old_verify_ok = '''                if (d.success) {
                    resultEl.className = 'verify-result ok';
                    resultEl.textContent = '✓ ' + d.message;'''
new_verify_ok = '''                if (d.success) {
                    resultEl.className = 'verify-result ok';
                    resultEl.textContent = '✓ ' + d.message;
                    this.state.llmVerified = true;
                    document.getElementById('saveSettingsBtn').classList.remove('btn-locked');
                    document.getElementById('saveSettingsBtn').title = '';'''
text = text.replace(old_verify_ok, new_verify_ok)

# ================================================================
# 9. 修改 saveSettings：读取 select.value，验证后才能保存
# ================================================================
old_save = '''        async saveSettings() {
            const settings = {
                api_url: document.getElementById('settingApiUrl').value.trim() || LLM_API,
                model: document.getElementById('settingModel').value.trim() || 'qwen3.6-35b',
                api_key: document.getElementById('settingApiKey').value.trim(),
                global_temperature: parseFloat(document.getElementById('settingGlobalTemp').value)
            };
            try { await this.api('POST', '/v1/settings', settings); this.state.settings = settings; this.toast('设置已保存', 'success'); }
            catch (e) { this.toast('保存失败: ' + e.message, 'error'); }
        },'''
new_save = '''        async saveSettings() {
            if (!this.state.llmVerified) {
                const btn = document.getElementById('verifyLLMBtn');
                btn.classList.add('shake');
                setTimeout(() => btn.classList.remove('shake'), 500);
                this.toast('请先点击「验证配置」验证模型连接', 'warning');
                return;
            }
            const sel = document.getElementById('settingModelSelect');
            const settings = {
                api_url: document.getElementById('settingApiUrl').value.trim() || LLM_API,
                model: (sel.value || '').trim() || 'qwen3.6-35b',
                api_key: document.getElementById('settingApiKey').value.trim(),
                global_temperature: parseFloat(document.getElementById('settingGlobalTemp').value)
            };
            try { await this.api('POST', '/v1/settings', settings); this.state.settings = settings; this.toast('设置已保存', 'success'); }
            catch (e) { this.toast('保存失败: ' + e.message, 'error'); }
        },'''
text = text.replace(old_save, new_save)

# ================================================================
# 10. 修改 applySettingsToUI：去掉 hidden input 逻辑
# ================================================================
old_apply = '''        applySettingsToUI() {
            const s = this.state.settings;
            document.getElementById('settingApiUrl').value = s.api_url || LLM_API;
            document.getElementById('settingModel').value = s.model || 'qwen3.6-35b';
            const sel = document.getElementById('settingModelSelect');
            if (sel) {
                const opt = sel.querySelector(`option[value="${s.model || ''}"]`);
                if (opt) opt.selected = true;
            }
            document.getElementById('settingApiKey').value = s.api_key || '';
            const gt = s.global_temperature !== undefined ? s.global_temperature : 0.7;
            document.getElementById('settingGlobalTemp').value = gt;
            document.getElementById('globalTempDisplay').textContent = parseFloat(gt).toFixed(2);
        },'''
new_apply = '''        applySettingsToUI() {
            const s = this.state.settings;
            document.getElementById('settingApiUrl').value = s.api_url || LLM_API;
            const sel = document.getElementById('settingModelSelect');
            if (sel && s.model) {
                const opt = sel.querySelector(`option[value="${s.model}"]`);
                if (opt) opt.selected = true;
            }
            document.getElementById('settingApiKey').value = s.api_key || '';
            const gt = s.global_temperature !== undefined ? s.global_temperature : 0.7;
            document.getElementById('settingGlobalTemp').value = gt;
            document.getElementById('globalTempDisplay').textContent = parseFloat(gt).toFixed(2);
            this.applyThemeUI();
        },'''
text = text.replace(old_apply, new_apply)

# ================================================================
# 11. 修改 loadModelList：去掉 hidden input 同步，改为 select.value
# ================================================================
old_load = '''            try {
                const d = await this.api('GET', '/v1/models');
                const models = d.data || [];
                const sel = document.getElementById('settingModelSelect');
                sel.innerHTML = models.length > 0
                    ? models.map(m => `<option value="${this.esc(m.id)}">${this.esc(m.id)}</option>`).join('')
                    : '<option value="">未获取到模型列表</option>';
                const current = document.getElementById('settingModel').value;
                if (current) { const opt = sel.querySelector(`option[value="${current}"]`); if (opt) opt.selected = true; }
                this.toast('模型列表已更新', 'success');
            } catch (e) { this.toast('获取模型列表失败: ' + e.message, 'error'); }'''
new_load = '''            try {
                const d = await this.api('GET', '/v1/models');
                const models = d.data || [];
                const sel = document.getElementById('settingModelSelect');
                const savedModel = (this.state.settings && this.state.settings.model) || '';
                sel.innerHTML = models.length > 0
                    ? models.map(m => `<option value="${this.esc(m.id)}">${this.esc(m.id)}</option>`).join('')
                    : '<option value="">未获取到模型列表</option>';
                if (savedModel) {
                    const opt = sel.querySelector(`option[value="${savedModel}"]`);
                    if (opt) opt.selected = true;
                }
                if (!sel.value && models.length > 0) {
                    sel.options[0].selected = true;
                }
                this.toast('模型列表已更新', 'success');
            } catch (e) { this.toast('获取模型列表失败: ' + e.message, 'error'); }'''
text = text.replace(old_load, new_load)

# ================================================================
# 12. 修改 switchSettingsTab：平滑转场动画
# ================================================================
old_switch = '''        switchSettingsTab(tab) {
            this.state.settingsTab = tab;
            document.querySelectorAll('.settings-tab').forEach(el => el.classList.toggle('active', el.dataset.tab === tab));
            document.querySelectorAll('.settings-tab-content').forEach(el => el.classList.toggle('active', el.dataset.tabContent === tab));
            if (tab === 'rag') { this.loadRagDocuments(); }
            if (tab === 'wechat') { this.loadWechatStatus(); }
        },'''
new_switch = '''        switchSettingsTab(tab) {
            this.state.settingsTab = tab;
            document.querySelectorAll('.settings-tab').forEach(el => el.classList.toggle('active', el.dataset.tab === tab));
            const contents = document.querySelectorAll('.settings-tab-content');
            const current = document.querySelector('.settings-tab-content.active');
            const next = document.querySelector(`.settings-tab-content[data-tab-content="${tab}"]`);
            if (current && next && current !== next) {
                current.classList.add('leaving');
                setTimeout(() => {
                    current.classList.remove('active', 'leaving');
                    next.classList.add('active');
                }, 150);
            } else {
                contents.forEach(el => el.classList.toggle('active', el.dataset.tabContent === tab));
            }
            if (tab === 'rag') { this.loadRagDocuments(); }
            if (tab === 'wechat') { this.loadWechatStatus(); }
            if (tab === 'appearance') { this.applyThemeUI(); }
        },'''
text = text.replace(old_switch, new_switch)

# ================================================================
# 13. 添加 saveSettingsBtn id 和 verifyLLMBtn id
# ================================================================
old_buttons = '''                                    <button class="btn btn-primary" onclick="app.saveSettings()">保存 LLM 设置</button>
                                    <button class="btn btn-secondary" onclick="app.verifyLLM()">验证配置</button>'''
new_buttons = '''                                    <button class="btn btn-primary btn-locked" id="saveSettingsBtn" onclick="app.saveSettings()" title="请先验证模型">保存 LLM 设置</button>
                                    <button class="btn btn-secondary" id="verifyLLMBtn" onclick="app.verifyLLM()">验证配置</button>'''
text = text.replace(old_buttons, new_buttons)

# ================================================================
# 14. 添加 theme 相关函数到 JS state 初始化后
# ================================================================
# 找到 state 初始化
old_state = '''            state: {
                currentView: 'chat',
                currentCharacter: null,
                messages: [],
                isLoading: false,
                settings: {},
                characters: [],
                selectedTags: new Set(),
                routes: [],
                memories: [],
                generatedCard: null,
                settingsTab: 'llm',
                wechatStatus: null,
                memoryTags: [],
            },'''
new_state = '''            state: {
                currentView: 'chat',
                currentCharacter: null,
                messages: [],
                isLoading: false,
                settings: {},
                characters: [],
                selectedTags: new Set(),
                routes: [],
                memories: [],
                generatedCard: null,
                settingsTab: 'llm',
                wechatStatus: null,
                memoryTags: [],
                llmVerified: false,
                theme: 'auto',
            },'''
text = text.replace(old_state, new_state)

# ================================================================
# 15. 添加 theme 方法
# ================================================================
old_refresh = '''        async refreshData() {
            await Promise.all([this.loadCharacters(), this.loadSettings(), this.loadRoutes(), this.loadMemories(), this.loadMemoryTags()]);
            this.toast('数据已刷新', 'success');
        },'''
new_refresh = '''        async refreshData() {
            await Promise.all([this.loadCharacters(), this.loadSettings(), this.loadRoutes(), this.loadMemories(), this.loadMemoryTags()]);
            this.toast('数据已刷新', 'success');
        },

        setTheme(mode) {
            this.state.theme = mode;
            this.applyTheme();
            localStorage.setItem('cocoon-theme', mode);
        },

        applyTheme() {
            const mode = this.state.theme;
            const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
            const isDark = mode === 'dark' || (mode === 'auto' && prefersDark);
            document.body.setAttribute('data-theme', isDark ? 'dark' : 'light');
            this.applyThemeUI();
        },

        applyThemeUI() {
            const mode = this.state.theme;
            document.querySelectorAll('#themeLight, #themeDark, #themeAuto').forEach(btn => {
                const active = (btn.id === 'themeLight' && mode === 'light') ||
                               (btn.id === 'themeDark' && mode === 'dark') ||
                               (btn.id === 'themeAuto' && mode === 'auto');
                btn.classList.toggle('btn-primary', active);
                btn.classList.toggle('btn-secondary', !active);
            });
        },

        initTheme() {
            const saved = localStorage.getItem('cocoon-theme') || 'auto';
            this.state.theme = saved;
            this.applyTheme();
        },'''
text = text.replace(old_refresh, new_refresh)

# ================================================================
# 16. 修改 init 调用 initTheme
# ================================================================
old_init = '''        async init() {
            await this.loadCharacters();
            await this.loadSettings();
            await this.loadRoutes();'''
new_init = '''        async init() {
            this.initTheme();
            await this.loadCharacters();
            await this.loadSettings();
            await this.loadRoutes();'''
text = text.replace(old_init, new_init)

# ================================================================
# 17. 监听系统主题变化
# ================================================================
# 在 script 末尾的 DOMContentLoaded 前添加
old_dom = '''            document.addEventListener('DOMContentLoaded', () => app.init());
        </script>'''
new_dom = '''            window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
                if (app.state.theme === 'auto') app.applyTheme();
            });
            document.addEventListener('DOMContentLoaded', () => app.init());
        </script>'''
text = text.replace(old_dom, new_dom)

# ================================================================
# 18. 监听 LLM 表单变化重置验证状态
# ================================================================
# 在 saveSettings 前面添加一个 markLLMChanged 函数
old_before_save = '''        async saveSettings() {
            if (!this.state.llmVerified) {'''
new_before_save = '''        markLLMChanged() {
            this.state.llmVerified = false;
            const btn = document.getElementById('saveSettingsBtn');
            if (btn) { btn.classList.add('btn-locked'); btn.title = '请先验证模型'; }
        },

        async saveSettings() {
            if (!this.state.llmVerified) {'''
text = text.replace(old_before_save, new_before_save)

# 给 LLM 输入框添加 oninput 监听
old_api_input = '''                                    <input type="text" class="form-input" id="settingApiUrl" placeholder="http://192.168.2.6:8081/v1">'''
new_api_input = '''                                    <input type="text" class="form-input" id="settingApiUrl" placeholder="http://192.168.2.6:8081/v1" oninput="app.markLLMChanged()">'''
text = text.replace(old_api_input, new_api_input)

old_key_input = '''                                    <input type="password" class="form-input" id="settingApiKey" placeholder="sk-...">'''
new_key_input = '''                                    <input type="password" class="form-input" id="settingApiKey" placeholder="sk-..." oninput="app.markLLMChanged()">'''
text = text.replace(old_key_input, new_key_input)

old_model_input = '''                                        <select class="form-select" id="settingModelSelect" style="flex:1;">'''
new_model_input = '''                                        <select class="form-select" id="settingModelSelect" style="flex:1;" onchange="app.markLLMChanged()">'''
text = text.replace(old_model_input, new_model_input)

with open(path, 'w', encoding='utf-8') as f:
    f.write(text)

print("All changes applied!")
print(f"File size: {len(text)} chars")
