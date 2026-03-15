/**
 * 设置页面控制器
 */

import { PageController } from '../core/PageController.js';
import { apiService } from '../services/ApiService.js';
import { toast } from '../services/NotificationService.js';

export class SettingsPage extends PageController {
    constructor() {
        super('SettingsPage', 'page-settings');
        this.currentConfig = null;
        this.modelCatalog = { providers: [] };
        this.runtimeStatus = null;
        this._updateStateUnwatch = null;
        this._settingsCardsEnhanced = false;
    }

    async onInit() {
        await super.onInit();
        this._bindEvents();
        this._enhanceSettingsCards();
        this.watchState('updater.*', () => this._renderUpdateState());
    }

    async onEnter() {
        await super.onEnter();
        await this._loadConfig();
        this._renderUpdateState();
    }

    _renderUpdateState() {
        const statusText = this.$('#update-status-text');
        const statusMeta = this.$('#update-status-meta');
        const btnCheck = this.$('#btn-check-updates');
        const btnDownload = this.$('#btn-open-update-download');
        if (!statusText || !statusMeta || !btnCheck || !btnDownload) {
            return;
        }

        const enabled = this.getState('updater.enabled');
        const checking = this.getState('updater.checking');
        const available = this.getState('updater.available');
        const currentVersion = this.getState('updater.currentVersion') || '--';
        const latestVersion = this.getState('updater.latestVersion') || '';
        const lastCheckedAt = this.getState('updater.lastCheckedAt') || '';
        const error = this.getState('updater.error') || '';

        btnCheck.disabled = checking;
        btnDownload.style.display = available ? 'inline-flex' : 'none';

        if (!enabled) {
            statusText.textContent = '当前环境未启用更新检查';
            statusMeta.textContent = `当前版本：v${currentVersion}。开发模式下不会检查 GitHub Releases 更新。`;
            return;
        }

        if (checking) {
            statusText.textContent = '正在检查更新...';
            statusMeta.textContent = `当前版本：v${currentVersion}`;
            return;
        }

        if (available) {
            statusText.textContent = `发现新版本 v${latestVersion}`;
            statusMeta.textContent = lastCheckedAt
                ? `当前版本：v${currentVersion} · 最近检查：${new Date(lastCheckedAt).toLocaleString('zh-CN')}`
                : `当前版本：v${currentVersion}`;
            return;
        }

        if (error) {
            statusText.textContent = '检查更新失败';
            statusMeta.textContent = error;
            return;
        }

        statusText.textContent = '当前已是最新版本';
        statusMeta.textContent = lastCheckedAt
            ? `当前版本：v${currentVersion} · 最近检查：${new Date(lastCheckedAt).toLocaleString('zh-CN')}`
            : `当前版本：v${currentVersion}`;
    }

    async _checkForUpdates() {
        if (!window.electronAPI?.checkForUpdates) {
            toast.error('当前环境不支持检查更新');
            return;
        }

        const result = await window.electronAPI.checkForUpdates({ source: 'settings' });
        if (!result?.success) {
            toast.error(result?.error || '检查更新失败');
            return;
        }

        if (result.updateAvailable) {
            toast.success(`发现新版本 v${result.state?.latestVersion || ''}`);
        } else {
            toast.info('当前已是最新版本');
        }
    }

    async _openUpdateDownload() {
        if (!window.electronAPI?.openUpdateDownload) {
            toast.error('当前环境不支持下载更新');
            return;
        }

        const result = await window.electronAPI.openUpdateDownload();
        if (!result?.success) {
            toast.error(result?.error || '打开下载地址失败');
        }
    }

    // ═══════════════════════════════════════════════════════════════════════
    //                           事件绑定
    // ═══════════════════════════════════════════════════════════════════════

    _bindEvents() {
        // 刷新配置
        this.bindEvent('#btn-refresh-config', 'click', () => this._loadConfig());

        // 保存配置
        this.bindEvent('#btn-save-settings', 'click', () => this._saveConfig());
        this.bindEvent('#btn-preview-prompt', 'click', () => this._previewPrompt());

        // 新增预设
        this.bindEvent('#btn-add-preset', 'click', () => this._openPresetModal());

        // 模态框事件
        this.bindEvent('#btn-close-modal', 'click', () => this._closePresetModal());
        this.bindEvent('#btn-cancel-modal', 'click', () => this._closePresetModal());
        this.bindEvent('#btn-save-modal', 'click', () => this._savePreset());
        this.bindEvent('#btn-check-updates', 'click', () => this._checkForUpdates());
        this.bindEvent('#btn-open-update-download', 'click', () => this._openUpdateDownload());

        this.bindEvent('#btn-reset-close-behavior', 'click', async () => {
            if (!window.electronAPI?.resetCloseBehavior) {
                toast.error('当前环境不支持重置');
                return;
            }
            const result = await window.electronAPI.resetCloseBehavior();
            if (result?.success) {
                toast.success('已重置关闭选择');
            } else {
                toast.error('重置失败');
            }
        });
        
        // 模态框内服务商与模型变化
        this.bindEvent('#edit-preset-provider', 'change', () => {
            this._renderProviderModels();
            this._updateApiKeyHelp(this._getSelectedProviderId());
            void this._syncOllamaModels();
        });

        this.bindEvent('#edit-preset-model-select', 'change', (e) => {
            const customInput = this.$('#edit-preset-model-custom');
            if (e.target.value === 'custom') {
                customInput.style.display = 'block';
            } else {
                customInput.style.display = 'none';
            }
            this._updateApiKeyHelp(this._getSelectedProviderId());
        });

        // 防止标题栏拖拽事件冒泡导致错误
        this.bindEvent('.modal-header', 'mousedown', (e) => {
            e.stopPropagation();
        });

        // 切换 Key 显示
        this.bindEvent('#btn-toggle-key', 'click', () => {
            const input = this.$('#edit-preset-key');
            if (input.type === 'password') {
                input.type = 'text';
            } else {
                input.type = 'password';
            }
        });

        this.bindEvent('#edit-preset-name', 'input', () => {
            this._updateApiKeyHelp(this._getSelectedProviderId());
        });
    }

    _enhanceSettingsCards() {
        if (this._settingsCardsEnhanced) {
            return;
        }

        this.$$('.settings-card').forEach((card) => {
            if (card.dataset.enhanced === 'true') {
                return;
            }

            const title = card.querySelector('.settings-card-title');
            if (!title) {
                return;
            }

            const meta = this._getSettingsCardMeta(card);
            const header = Array.from(card.children).find(
                (child) => child.classList?.contains('settings-card-header')
            ) || document.createElement('div');
            const existingActions = Array.from(header.children).filter((child) => child !== title);

            if (!header.parentElement) {
                card.insertBefore(header, card.firstChild);
            }

            const body = document.createElement('div');
            body.className = 'settings-card-body';

            Array.from(card.children).forEach((child) => {
                if (child !== header) {
                    body.appendChild(child);
                }
            });

            const toggle = document.createElement('button');
            toggle.type = 'button';
            toggle.className = 'settings-card-toggle';

            const toggleMain = document.createElement('div');
            toggleMain.className = 'settings-card-toggle-main';

            const titleRow = document.createElement('div');
            titleRow.className = 'settings-card-toggle-top';
            titleRow.appendChild(title);

            const badge = document.createElement('span');
            badge.className = 'settings-card-badge';
            badge.textContent = meta.badge;
            titleRow.appendChild(badge);

            const summary = document.createElement('p');
            summary.className = 'settings-card-summary';
            summary.textContent = meta.summary;

            toggleMain.appendChild(titleRow);
            toggleMain.appendChild(summary);

            const chevron = document.createElement('span');
            chevron.className = 'settings-card-chevron';
            chevron.setAttribute('aria-hidden', 'true');
            chevron.textContent = '^';
            toggle.appendChild(toggleMain);
            toggle.appendChild(chevron);

            header.classList.add('settings-card-header', 'settings-card-header-collapsible');
            header.replaceChildren(toggle);

            if (existingActions.length > 0) {
                const actions = document.createElement('div');
                actions.className = 'settings-card-header-actions';
                existingActions.forEach((child) => actions.appendChild(child));
                header.appendChild(actions);
            }

            card.classList.add('is-collapsible');
            card.appendChild(body);
            card.dataset.enhanced = 'true';

            toggle.addEventListener('click', () => {
                this._setSettingsCardCollapsed(card, !card.classList.contains('is-collapsed'));
            });

            this._setSettingsCardCollapsed(card, !meta.defaultExpanded);
        });

        this._settingsCardsEnhanced = true;
    }

    _setSettingsCardCollapsed(card, collapsed) {
        card.classList.toggle('is-collapsed', collapsed);
        const toggle = card.querySelector('.settings-card-toggle');
        if (toggle) {
            toggle.setAttribute('aria-expanded', String(!collapsed));
        }
    }

    _getSettingsCardMeta(card) {
        const definitions = [
            {
                selector: '#preset-list',
                summary: '先在这里选一个可用模型。大多数情况下，只需要保证当前预设能连接成功。',
                badge: '推荐先看',
                defaultExpanded: true,
            },
            {
                selector: '#setting-self-name',
                summary: '这些是机器人最基础的说话方式和触发方式，不懂技术时优先看这里。',
                badge: '基础',
                defaultExpanded: true,
            },
            {
                selector: '#setting-reply-quote-mode',
                summary: '控制回复时是否引用原消息。想让聊天更像人工回复时可以在这里调整。',
                badge: '常用',
                defaultExpanded: false,
            },
            {
                selector: '#setting-system-prompt',
                summary: '决定机器人整体性格和说话原则。修改前建议先保留原文，再做小幅调整。',
                badge: '重要',
                defaultExpanded: true,
            },
            {
                selector: '#setting-preview-chat-name',
                summary: '用示例对话预览最终发给模型的提示词，适合改完系统提示后快速确认效果。',
                badge: '辅助',
                defaultExpanded: false,
            },
            {
                selector: '#setting-emoji-policy',
                summary: '控制表情和语音转文字的处理方式。只有你确实需要这些能力时再展开修改。',
                badge: '可选',
                defaultExpanded: false,
            },
            {
                selector: '#setting-memory-db-path',
                summary: '决定机器人记住多少上下文，以及记忆保存在哪里。想让它更“记事”时看这里。',
                badge: '进阶',
                defaultExpanded: true,
            },
            {
                selector: '#setting-poll-interval-sec',
                summary: '影响轮询速度和回复节奏。没有性能问题时，通常保持默认值即可。',
                badge: '高级',
                defaultExpanded: false,
            },
            {
                selector: '#setting-merge-user-messages-sec',
                summary: '控制多条消息是否合并后再回复。适合优化连续轰炸消息时的回复体验。',
                badge: '进阶',
                defaultExpanded: false,
            },
            {
                selector: '#setting-natural-split-enabled',
                summary: '让长回复自动拆成更自然的几段。担心刷屏时可以关闭或调小。',
                badge: '进阶',
                defaultExpanded: false,
            },
            {
                selector: '#setting-stream-buffer-chars',
                summary: '控制流式回复的显示节奏。只有你已经启用流式回复时，这里才会明显生效。',
                badge: '高级',
                defaultExpanded: false,
            },
            {
                selector: '#setting-reconnect-max-retries',
                summary: '决定配置热更新和断线重连策略。除非你在排查故障，否则建议保持默认。',
                badge: '高级',
                defaultExpanded: false,
            },
            {
                selector: '#setting-group-include-sender',
                summary: '群聊发消息的细节规则在这里设置。只在你经常用群聊场景时需要调整。',
                badge: '进阶',
                defaultExpanded: false,
            },
            {
                selector: '#setting-filter-mute',
                summary: '用于排除不该回复的人和关键词。机器人乱回消息时，优先检查这里。',
                badge: '重要',
                defaultExpanded: false,
            },
            {
                selector: '#setting-personalization-enabled',
                summary: '让机器人记住用户偏好和聊天事实。开启越多，越像“有记忆”的助手。',
                badge: '进阶',
                defaultExpanded: false,
            },
            {
                selector: '#setting-agent-enabled',
                summary: '这是 LangChain、RAG 和检索增强等高级能力区域，不熟悉时建议保持默认。',
                badge: '高级',
                defaultExpanded: false,
            },
            {
                selector: '#setting-log-level',
                summary: '日志越详细，排查越方便，但文件也会更大。日常使用一般不需要频繁改。',
                badge: '维护',
                defaultExpanded: false,
            },
            {
                selector: '#btn-check-updates',
                summary: '查看新版本和下载地址。这里不会影响机器人的日常对话行为。',
                badge: '应用',
                defaultExpanded: false,
            },
            {
                selector: '#btn-reset-close-behavior',
                summary: '控制点关闭按钮后是退出还是最小化到托盘，适合按你的使用习惯设置。',
                badge: '应用',
                defaultExpanded: false,
            },
            {
                selector: '#whitelist-table-body',
                summary: '管理白名单联系人，确保这些对象始终按你的规则工作。',
                badge: '管理',
                defaultExpanded: false,
            },
        ];

        return definitions.find((item) => card.querySelector(item.selector)) || {
            summary: '这一组设置用于控制更细的运行行为。不了解含义时，建议先保持默认值。',
            badge: '高级',
            defaultExpanded: false,
        };
    }

    // ═══════════════════════════════════════════════════════════════════════
    //                           辅助数据
    // ═══════════════════════════════════════════════════════════════════════

    _getFallbackModelCatalog() {
        return {
            providers: [
                {
                    id: 'openai',
                    label: 'OpenAI',
                    base_url: 'https://api.openai.com/v1',
                    api_key_url: 'https://platform.openai.com/api-keys',
                    aliases: ['openai', 'gpt'],
                    default_model: 'gpt-5-mini',
                    models: ['gpt-5', 'gpt-5-mini', 'gpt-5-nano', 'gpt-4.1', 'gpt-4.1-mini', 'gpt-4o', 'gpt-4o-mini']
                },
                {
                    id: 'doubao',
                    label: 'Doubao (豆包)',
                    base_url: 'https://ark.cn-beijing.volces.com/api/v3',
                    api_key_url: 'https://console.volcengine.com/ark',
                    aliases: ['doubao', '豆包', 'ark', 'volc'],
                    default_model: 'doubao-seed-1-8-251228',
                    models: ['doubao-seed-1-8-251228', 'doubao-seed-1-6-250615', 'doubao-seed-1-6-thinking-250615', 'doubao-seed-1-6-flash-250715']
                },
                {
                    id: 'deepseek',
                    label: 'DeepSeek',
                    base_url: 'https://api.deepseek.com/v1',
                    api_key_url: 'https://platform.deepseek.com/api_keys',
                    aliases: ['deepseek'],
                    default_model: 'deepseek-chat',
                    models: ['deepseek-chat', 'deepseek-reasoner']
                },
                {
                    id: 'qwen',
                    label: 'Qwen (通义千问)',
                    base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
                    api_key_url: 'https://dashscope.console.aliyun.com/apiKey',
                    aliases: ['qwen', '通义', '千问', 'dashscope', '百炼'],
                    default_model: 'qwen3.5-plus',
                    models: ['qwen-max-latest', 'qwen-plus-latest', 'qwen-flash-latest', 'qwen3-max', 'qwen3.5-plus', 'qwen3.5-flash', 'qwen3-coder-plus', 'qwen3-coder-flash']
                },
                {
                    id: 'zhipu',
                    label: 'Zhipu (智谱)',
                    base_url: 'https://open.bigmodel.cn/api/paas/v4',
                    api_key_url: 'https://open.bigmodel.cn/usercenter/apikeys',
                    aliases: ['zhipu', 'glm', '智谱'],
                    default_model: 'glm-4.5-air',
                    models: ['glm-5-plus', 'glm-5-air', 'glm-5-flash', 'glm-4.6', 'glm-4.5-air', 'glm-4.5-flash']
                },
                {
                    id: 'moonshot',
                    label: 'Moonshot (Kimi)',
                    base_url: 'https://api.moonshot.cn/v1',
                    api_key_url: 'https://platform.moonshot.cn/console/api-keys',
                    aliases: ['moonshot', 'kimi'],
                    default_model: 'kimi-k2-turbo-preview',
                    models: ['kimi-k2-turbo-preview', 'kimi-k2-0711-preview', 'kimi-thinking-preview', 'moonshot-v1-8k', 'moonshot-v1-32k', 'moonshot-v1-128k']
                },
                {
                    id: 'groq',
                    label: 'Groq',
                    base_url: 'https://api.groq.com/openai/v1',
                    api_key_url: 'https://console.groq.com/keys',
                    aliases: ['groq'],
                    default_model: 'qwen/qwen3-32b',
                    models: ['qwen/qwen3-32b', 'openai/gpt-oss-120b', 'meta-llama/llama-4-maverick-17b-128e-instruct', 'meta-llama/llama-4-scout-17b-16e-instruct']
                },
                {
                    id: 'ollama',
                    label: 'Ollama',
                    base_url: 'http://127.0.0.1:11434/v1',
                    api_key_url: 'https://ollama.com/',
                    aliases: ['ollama'],
                    allow_empty_key: true,
                    default_model: 'qwen3',
                    models: ['qwen3', 'llama3.1', 'gemma3', 'mistral']
                }
            ]
        };
    }

    _getCatalogProviders() {
        const providers = this.modelCatalog?.providers;
        if (Array.isArray(providers) && providers.length > 0) {
            return providers;
        }
        return this._getFallbackModelCatalog().providers;
    }

    _getProviderById(providerId) {
        const normalized = String(providerId || '').trim().toLowerCase();
        if (!normalized) return null;
        return this._getCatalogProviders().find(provider => provider.id === normalized) || null;
    }

    _guessProviderId(value) {
        const preset = typeof value === 'object' && value !== null ? value : {};
        const raw = typeof value === 'string' ? value : preset.name || '';
        const lowerName = String(raw || '').toLowerCase();
        const lowerBaseUrl = String(preset.base_url || '').toLowerCase();
        const lowerModel = String(preset.model || '').toLowerCase();

        for (const provider of this._getCatalogProviders()) {
            if (lowerBaseUrl && String(provider.base_url || '').toLowerCase() === lowerBaseUrl) {
                return provider.id;
            }
            if ((provider.models || []).some(model => String(model).toLowerCase() === lowerModel)) {
                return provider.id;
            }
            if ((provider.aliases || []).some(alias => lowerName.includes(String(alias).toLowerCase()) || lowerModel.includes(String(alias).toLowerCase()))) {
                return provider.id;
            }
            if (lowerName && lowerName.includes(provider.id)) {
                return provider.id;
            }
        }
        return '';
    }

    _getSelectedProviderId() {
        return this.$('#edit-preset-provider')?.value || '';
    }

    _populateProviderSelect(selectedProviderId = '') {
        const select = this.$('#edit-preset-provider');
        if (!select) return;

        const options = this._getCatalogProviders()
            .map(provider => `<option value="${provider.id}">${provider.label}</option>`)
            .join('');

        select.innerHTML = `<option value="">-- 选择服务商 --</option>${options}`;
        select.value = selectedProviderId || this._getCatalogProviders()[0]?.id || '';
    }

    _renderProviderModels(currentModel = '') {
        const select = this.$('#edit-preset-model-select');
        const customInput = this.$('#edit-preset-model-custom');
        if (!select || !customInput) return;

        const provider = this._getProviderById(this._getSelectedProviderId());
        const models = Array.isArray(provider?.models) ? provider.models : [];

        const options = models
            .map(model => `<option value="${model}">${model}</option>`)
            .join('');

        select.innerHTML = `${options}<option value="custom">自定义模型...</option>`;

        if (currentModel && models.includes(currentModel)) {
            select.value = currentModel;
            customInput.style.display = 'none';
            customInput.value = '';
            return;
        }

        if (currentModel) {
            select.value = 'custom';
            customInput.style.display = 'block';
            customInput.value = currentModel;
            return;
        }

        select.value = provider?.default_model || models[0] || 'custom';
        customInput.style.display = 'none';
        customInput.value = '';
    }

    _setProviderModels(providerId, models = []) {
        const provider = this._getProviderById(providerId);
        if (!provider || !Array.isArray(models) || models.length === 0) return;
        provider.models = [...models];
        if (!provider.default_model || !models.includes(provider.default_model)) {
            provider.default_model = models[0];
        }
    }

    async _syncOllamaModels(currentModel = '') {
        if (this._getSelectedProviderId() !== 'ollama') return;

        const provider = this._getProviderById('ollama');
        const baseUrl = provider?.base_url || 'http://127.0.0.1:11434/v1';

        try {
            const result = await apiService.getOllamaModels(baseUrl);
            if (!result?.success || !Array.isArray(result.models) || result.models.length === 0) {
                return;
            }
            this._setProviderModels('ollama', result.models);
            if (this._getSelectedProviderId() === 'ollama') {
                this._renderProviderModels(currentModel || result.models[0]);
            }
        } catch (error) {
            console.warn('加载 Ollama 模型失败:', error);
        }
    }

    _getProviderIcon(name) {
        const lower = String(name || '').toLowerCase();
        if (lower.includes('openai') || lower.includes('gpt')) return '🟢';
        if (lower.includes('doubao') || lower.includes('豆包')) return '📦';
        if (lower.includes('deepseek')) return '🦈';
        if (lower.includes('moonshot') || lower.includes('kimi')) return '🌙';
        if (lower.includes('zhipu') || lower.includes('glm')) return '🧠';
        if (lower.includes('qwen') || lower.includes('通义')) return '😺';
        if (lower.includes('silicon')) return '🌊';
        if (lower.includes('groq')) return '⚡';
        if (lower.includes('ollama')) return '🦙';
        return '🤖';
    }

    _getProviderKeyInfo(providerId) {
        const provider = this._getProviderById(providerId);
        if (provider?.api_key_url) {
            const text = provider.id === 'ollama'
                ? 'Ollama 无需 API Key，查看文档 →'
                : `获取 ${provider.label} API Key →`;
            return { text, url: provider.api_key_url };
        }
        return { text: '获取 API Key →', url: 'https://www.google.com/search?q=API+Key+%E8%8E%B7%E5%8F%96' };
    }

    _updateApiKeyHelp(providerId) {
        const help = this.$('#api-key-help');
        const link = this.$('#api-key-help-link');
        if (!help || !link) return;
        const info = this._getProviderKeyInfo(providerId);
        link.textContent = info.text;
        link.href = info.url;
        help.style.display = 'block';
    }

    // ═══════════════════════════════════════════════════════════════════════
    //                           配置加载与保存
    // ═══════════════════════════════════════════════════════════════════════

    async _loadConfig() {
        try {
            const [configResult, catalogResult, statusResult] = await Promise.all([
                apiService.getConfig(),
                apiService.getModelCatalog(),
                apiService.getStatus().catch(() => null)
            ]);

            if (catalogResult?.success) {
                this.modelCatalog = {
                    updated_at: catalogResult.updated_at || '',
                    providers: Array.isArray(catalogResult.providers) ? catalogResult.providers : []
                };
            } else {
                this.modelCatalog = this._getFallbackModelCatalog();
            }

            if (configResult.success) {
                // 后端返回的是扁平结构，剔除 success 字段后即为配置
                const { success, ...config } = configResult;
                this.currentConfig = config;
                this.runtimeStatus = statusResult;
                this._renderConfig(this.currentConfig);
                toast.success('配置已加载');
            } else {
                this.$('#preset-list').innerHTML = `<div class="empty-state error">加载失败: ${configResult.message}</div>`;
                toast.error('加载配置失败: ' + configResult.message);
            }
        } catch (error) {
            console.error('加载配置异常:', error);
            this.$('#preset-list').innerHTML = '<div class="empty-state error">加载异常，请检查服务</div>';
            toast.error(toast.getErrorMessage(error, '加载配置异常'));
        }
    }

    _extractConfigPayload(result) {
        if (!result?.success) return null;
        if (result.config) return result.config;
        const { success, message, ...config } = result;
        return config;
    }

    _setButtonLoading(button, isLoading, pendingHtml = '') {
        if (!button) return;

        if (isLoading) {
            if (!button.dataset.originalHtml) {
                button.dataset.originalHtml = button.innerHTML;
            }
            button.disabled = true;
            if (pendingHtml) {
                button.innerHTML = pendingHtml;
            }
            return;
        }

        button.disabled = false;
        if (button.dataset.originalHtml) {
            button.innerHTML = button.dataset.originalHtml;
            delete button.dataset.originalHtml;
        }
    }

    _getRuntimeSwitchMessage(isRunning) {
        return isRunning
            ? '运行中的机器人会在配置热重载后切换到新模型。'
            : '机器人当前未运行，下次启动后会使用该预设。';
    }

    _renderConfig(config) {
        if (!config) return;

        // 渲染概览信息 - 优化版
        const api = config.api || {};
        const activePresetName = api.active_preset || '未设置';
        
        // 查找当前预设的完整信息以获取更多详情
        const presets = api.presets || [];
        const currentPreset = presets.find(p => p.name === activePresetName) || {};
        
        // 优先使用预设中的信息，回退到全局
        const activeModel = currentPreset.model || api.model || '--';
        const activeAlias = currentPreset.alias || api.alias || '--';
        const hasKey = currentPreset.api_key_configured;
        const keyRequired = currentPreset.api_key_required !== false;
        const keyStatus = keyRequired ? (hasKey ? '已配置' : '未配置') : '无需 Key';

        const icon = this._getProviderIcon(currentPreset.provider_id || activePresetName);

        // 更新顶部英雄卡片
        const heroContainer = this.$('#current-config-hero');
        if (heroContainer) {
             heroContainer.innerHTML = `
                <div class="config-hero-card">
                    <div class="hero-icon">${icon}</div>
                    <div class="hero-content">
                        <div class="hero-title">
                            <span class="hero-name">${activePresetName}</span>
                            <span class="status-badge active">
                                <span class="status-dot"></span>已激活
                            </span>
                        </div>
                        <div class="hero-details">
                            <div class="detail-item">
                                <span class="detail-label">模型</span>
                                <span class="detail-value">${activeModel}</span>
                            </div>
                            <div class="detail-item">
                                <span class="detail-label">别名</span>
                                <span class="detail-value">${activeAlias}</span>
                            </div>
                             <div class="detail-item">
                                <span class="detail-label">API Key</span>
                                <span class="detail-value mono">${keyStatus}</span>
                            </div>
                        </div>
                    </div>
                    <div class="hero-actions">
                        <button class="btn btn-sm btn-secondary" id="btn-ping-test">
                            <svg class="icon" viewBox="0 0 24 24"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>
                            测试连接
                        </button>
                        <div class="ping-result" id="ping-result">未测试</div>
                    </div>
                </div>
             `;
             
             // 绑定测试按钮
             const btnPing = heroContainer.querySelector('#btn-ping-test');
             const pingResult = heroContainer.querySelector('#ping-result');
             if (pingResult) {
                 pingResult.textContent = '未测试';
                 pingResult.className = 'ping-result';
             }
             if(btnPing) {
                 btnPing.onclick = async () => {
                     const btn = btnPing;
                     const originalText = btn.innerHTML;
                     btn.disabled = true;
                     btn.innerHTML = '<span class="spinner-sm"></span> 测试中...'; // 假设有 spinner 样式，或者用文字
                     if (pingResult) {
                         pingResult.textContent = '测试中...';
                         pingResult.className = 'ping-result pending';
                     }
                     
                     try {
                         const res = await apiService.testConnection(activePresetName);
                         if (res.success) {
                             toast.success('连接成功！API 配置有效。');
                             if (pingResult) {
                                 pingResult.textContent = '连接成功';
                                 pingResult.className = 'ping-result success';
                             }
                         } else {
                             toast.error(res.message || '连接测试失败');
                             if (pingResult) {
                                 pingResult.textContent = res.message || '连接失败';
                                 pingResult.className = 'ping-result error';
                             }
                         }
                     } catch (e) {
                         console.error(e);
                         toast.error(toast.getErrorMessage(e, '连接测试异常'));
                         if (pingResult) {
                             pingResult.textContent = '连接异常';
                             pingResult.className = 'ping-result error';
                         }
                     } finally {
                         btn.disabled = false;
                         btn.innerHTML = originalText;
                     }
                 };
             }
        } else {
            // 回退到旧的 DOM 结构
            if(this.$('#info-active-preset')) this.$('#info-active-preset').textContent = activePresetName;
            if(this.$('#info-model')) this.$('#info-model').textContent = activeModel;
            if(this.$('#info-alias')) this.$('#info-alias').textContent = activeAlias;
            if(this.$('#info-api-key')) this.$('#info-api-key').textContent = hasKey ? '已配置' : '未配置';
        }

        // 渲染机器人设置
        const bot = config.bot || {};
        this.$('#setting-self-name').value = bot.self_name || '';
        this.$('#setting-reply-suffix').value = bot.reply_suffix || '';
        if(this.$('#setting-stream-reply')) this.$('#setting-stream-reply').checked = !!bot.stream_reply;
        this.$('#setting-group-at-only').checked = !!bot.group_reply_only_when_at;
        this.$('#setting-whitelist-enabled').checked = !!bot.whitelist_enabled;
        this.$('#setting-whitelist').value = (bot.whitelist || []).join('\n');

        const systemPrompt = this.$('#setting-system-prompt');
        if (systemPrompt) {
            systemPrompt.value = bot.system_prompt || '';
        }
        const overridesInput = this.$('#setting-system-prompt-overrides');
        if (overridesInput) {
            const overrides = bot.system_prompt_overrides || {};
            const lines = Object.entries(overrides).map(([key, value]) => {
                const text = String(value ?? '').replace(/\n/g, '\\n');
                return `${key}|${text}`;
            });
            overridesInput.value = lines.join('\n');
        }

        const emojiPolicy = this.$('#setting-emoji-policy');
        if (emojiPolicy) {
            emojiPolicy.value = bot.emoji_policy || 'mixed';
        }
        const emojiReplacements = this.$('#setting-emoji-replacements');
        if (emojiReplacements) {
            const replacements = bot.emoji_replacements || {};
            const lines = Object.entries(replacements).map(([key, value]) => `${key}=${value}`);
            emojiReplacements.value = lines.join('\n');
        }
        const voiceToText = this.$('#setting-voice-to-text');
        if (voiceToText) {
            voiceToText.checked = bot.voice_to_text !== false;
        }
        const voiceFailReply = this.$('#setting-voice-to-text-fail-reply');
        if (voiceFailReply) {
            voiceFailReply.value = bot.voice_to_text_fail_reply || '';
        }

        const memoryDbPath = this.$('#setting-memory-db-path');
        if (memoryDbPath) {
            memoryDbPath.value = bot.memory_db_path || '';
        }
        const memoryContextLimit = this.$('#setting-memory-context-limit');
        if (memoryContextLimit) {
            memoryContextLimit.value = bot.memory_context_limit ?? 0;
        }
        const memoryTtl = this.$('#setting-memory-ttl-sec');
        if (memoryTtl) {
            memoryTtl.value = bot.memory_ttl_sec ?? '';
        }
        const memoryCleanup = this.$('#setting-memory-cleanup-interval-sec');
        if (memoryCleanup) {
            memoryCleanup.value = bot.memory_cleanup_interval_sec ?? 0;
        }
        const memorySeedFirst = this.$('#setting-memory-seed-on-first-reply');
        if (memorySeedFirst) {
            memorySeedFirst.checked = bot.memory_seed_on_first_reply !== false;
        }
        const memorySeedLimit = this.$('#setting-memory-seed-limit');
        if (memorySeedLimit) {
            memorySeedLimit.value = bot.memory_seed_limit ?? 0;
        }
        const memorySeedLoadMore = this.$('#setting-memory-seed-load-more');
        if (memorySeedLoadMore) {
            memorySeedLoadMore.value = bot.memory_seed_load_more ?? 0;
        }
        const memorySeedLoadMoreInterval = this.$('#setting-memory-seed-load-more-interval-sec');
        if (memorySeedLoadMoreInterval) {
            memorySeedLoadMoreInterval.value = bot.memory_seed_load_more_interval_sec ?? 0;
        }
        const memorySeedGroup = this.$('#setting-memory-seed-group');
        if (memorySeedGroup) {
            memorySeedGroup.checked = !!bot.memory_seed_group;
        }
        const contextRounds = this.$('#setting-context-rounds');
        if (contextRounds) {
            contextRounds.value = bot.context_rounds ?? 0;
        }
        const contextMaxTokens = this.$('#setting-context-max-tokens');
        if (contextMaxTokens) {
            contextMaxTokens.value = bot.context_max_tokens ?? 0;
        }
        const historyMaxChats = this.$('#setting-history-max-chats');
        if (historyMaxChats) {
            historyMaxChats.value = bot.history_max_chats ?? 0;
        }
        const historyTtl = this.$('#setting-history-ttl-sec');
        if (historyTtl) {
            historyTtl.value = bot.history_ttl_sec ?? '';
        }
        const historyLogInterval = this.$('#setting-history-log-interval-sec');
        if (historyLogInterval) {
            historyLogInterval.value = bot.history_log_interval_sec ?? 0;
        }

        const pollInterval = this.$('#setting-poll-interval-sec');
        if (pollInterval) {
            pollInterval.value = bot.poll_interval_sec ?? 0;
        }
        const pollMin = this.$('#setting-poll-interval-min-sec');
        if (pollMin) {
            pollMin.value = bot.poll_interval_min_sec ?? 0;
        }
        const pollMax = this.$('#setting-poll-interval-max-sec');
        if (pollMax) {
            pollMax.value = bot.poll_interval_max_sec ?? 0;
        }
        const pollBackoff = this.$('#setting-poll-interval-backoff-factor');
        if (pollBackoff) {
            pollBackoff.value = bot.poll_interval_backoff_factor ?? 0;
        }
        const minReplyInterval = this.$('#setting-min-reply-interval-sec');
        if (minReplyInterval) {
            minReplyInterval.value = bot.min_reply_interval_sec ?? 0;
        }
        const randomDelayMin = this.$('#setting-random-delay-min-sec');
        const randomDelayMax = this.$('#setting-random-delay-max-sec');
        if (Array.isArray(bot.random_delay_range_sec)) {
            if (randomDelayMin) randomDelayMin.value = bot.random_delay_range_sec[0] ?? 0;
            if (randomDelayMax) randomDelayMax.value = bot.random_delay_range_sec[1] ?? 0;
        } else {
            if (randomDelayMin) randomDelayMin.value = 0;
            if (randomDelayMax) randomDelayMax.value = 0;
        }

        const mergeSec = this.$('#setting-merge-user-messages-sec');
        if (mergeSec) {
            mergeSec.value = bot.merge_user_messages_sec ?? 0;
        }
        const mergeMaxWait = this.$('#setting-merge-user-messages-max-wait-sec');
        if (mergeMaxWait) {
            mergeMaxWait.value = bot.merge_user_messages_max_wait_sec ?? 0;
        }
        const replyChunkSize = this.$('#setting-reply-chunk-size');
        if (replyChunkSize) {
            replyChunkSize.value = bot.reply_chunk_size ?? 0;
        }
        const replyChunkDelay = this.$('#setting-reply-chunk-delay-sec');
        if (replyChunkDelay) {
            replyChunkDelay.value = bot.reply_chunk_delay_sec ?? 0;
        }
        const maxConcurrency = this.$('#setting-max-concurrency');
        if (maxConcurrency) {
            maxConcurrency.value = bot.max_concurrency ?? 0;
        }

        const naturalSplitEnabled = this.$('#setting-natural-split-enabled');
        if (naturalSplitEnabled) {
            naturalSplitEnabled.checked = !!bot.natural_split_enabled;
        }
        const naturalMin = this.$('#setting-natural-split-min-chars');
        if (naturalMin) {
            naturalMin.value = bot.natural_split_min_chars ?? 0;
        }
        const naturalMax = this.$('#setting-natural-split-max-chars');
        if (naturalMax) {
            naturalMax.value = bot.natural_split_max_chars ?? 0;
        }
        const naturalSegments = this.$('#setting-natural-split-max-segments');
        if (naturalSegments) {
            naturalSegments.value = bot.natural_split_max_segments ?? 0;
        }
        const naturalDelayMin = this.$('#setting-natural-split-delay-min-sec');
        const naturalDelayMax = this.$('#setting-natural-split-delay-max-sec');
        if (Array.isArray(bot.natural_split_delay_sec)) {
            if (naturalDelayMin) naturalDelayMin.value = bot.natural_split_delay_sec[0] ?? 0;
            if (naturalDelayMax) naturalDelayMax.value = bot.natural_split_delay_sec[1] ?? 0;
        } else {
            if (naturalDelayMin) naturalDelayMin.value = 0;
            if (naturalDelayMax) naturalDelayMax.value = 0;
        }

        const streamBuffer = this.$('#setting-stream-buffer-chars');
        if (streamBuffer) {
            streamBuffer.value = bot.stream_buffer_chars ?? 0;
        }
        const streamChunkMax = this.$('#setting-stream-chunk-max-chars');
        if (streamChunkMax) {
            streamChunkMax.value = bot.stream_chunk_max_chars ?? 0;
        }

        const configReload = this.$('#setting-config-reload-sec');
        if (configReload) {
            configReload.value = bot.config_reload_sec ?? 0;
        }
        const reloadClient = this.$('#setting-reload-ai-client-on-change');
        if (reloadClient) {
            reloadClient.checked = bot.reload_ai_client_on_change !== false;
        }
        const reloadModule = this.$('#setting-reload-ai-client-module');
        if (reloadModule) {
            reloadModule.checked = !!bot.reload_ai_client_module;
        }
        const keepaliveIdle = this.$('#setting-keepalive-idle-sec');
        if (keepaliveIdle) {
            keepaliveIdle.value = bot.keepalive_idle_sec ?? 0;
        }
        const reconnectRetries = this.$('#setting-reconnect-max-retries');
        if (reconnectRetries) {
            reconnectRetries.value = bot.reconnect_max_retries ?? 0;
        }
        const reconnectBackoff = this.$('#setting-reconnect-backoff-sec');
        if (reconnectBackoff) {
            reconnectBackoff.value = bot.reconnect_backoff_sec ?? 0;
        }
        const reconnectMaxDelay = this.$('#setting-reconnect-max-delay-sec');
        if (reconnectMaxDelay) {
            reconnectMaxDelay.value = bot.reconnect_max_delay_sec ?? 0;
        }

        const groupIncludeSender = this.$('#setting-group-include-sender');
        if (groupIncludeSender) {
            groupIncludeSender.checked = !!bot.group_include_sender;
        }
        const sendExactMatch = this.$('#setting-send-exact-match');
        if (sendExactMatch) {
            sendExactMatch.checked = !!bot.send_exact_match;
        }
        const sendFallback = this.$('#setting-send-fallback-current-chat');
        if (sendFallback) {
            sendFallback.checked = !!bot.send_fallback_current_chat;
        }

        const filterMute = this.$('#setting-filter-mute');
        if (filterMute) {
            filterMute.checked = !!bot.filter_mute;
        }
        const ignoreOfficial = this.$('#setting-ignore-official');
        if (ignoreOfficial) {
            ignoreOfficial.checked = !!bot.ignore_official;
        }
        const ignoreService = this.$('#setting-ignore-service');
        if (ignoreService) {
            ignoreService.checked = !!bot.ignore_service;
        }
        const ignoreNames = this.$('#setting-ignore-names');
        if (ignoreNames) {
            ignoreNames.value = (bot.ignore_names || []).join('\n');
        }
        const ignoreKeywords = this.$('#setting-ignore-keywords');
        if (ignoreKeywords) {
            ignoreKeywords.value = (bot.ignore_keywords || []).join('\n');
        }

        const personalizationEnabled = this.$('#setting-personalization-enabled');
        if (personalizationEnabled) {
            personalizationEnabled.checked = !!bot.personalization_enabled;
        }
        const profileUpdateFrequency = this.$('#setting-profile-update-frequency');
        if (profileUpdateFrequency) {
            profileUpdateFrequency.value = bot.profile_update_frequency ?? 0;
        }
        const rememberFactsEnabled = this.$('#setting-remember-facts-enabled');
        if (rememberFactsEnabled) {
            rememberFactsEnabled.checked = !!bot.remember_facts_enabled;
        }
        const maxContextFacts = this.$('#setting-max-context-facts');
        if (maxContextFacts) {
            maxContextFacts.value = bot.max_context_facts ?? 0;
        }
        const profileInject = this.$('#setting-profile-inject-in-prompt');
        if (profileInject) {
            profileInject.checked = !!bot.profile_inject_in_prompt;
        }
        const exportRagEnabled = this.$('#setting-export-rag-enabled');
        if (exportRagEnabled) {
            exportRagEnabled.checked = !!bot.export_rag_enabled;
        }
        const vectorMemoryEnabled = this.$('#setting-vector-memory-enabled');
        if (vectorMemoryEnabled) {
            vectorMemoryEnabled.checked = bot.vector_memory_enabled !== false;
        }
        const vectorMemoryEmbeddingModel = this.$('#setting-vector-memory-embedding-model');
        if (vectorMemoryEmbeddingModel) {
            vectorMemoryEmbeddingModel.value = bot.vector_memory_embedding_model || '';
        }
        const exportRagDir = this.$('#setting-export-rag-dir');
        if (exportRagDir) {
            exportRagDir.value = bot.export_rag_dir || 'chat_exports/聊天记录';
        }
        const exportRagAutoIngest = this.$('#setting-export-rag-auto-ingest');
        if (exportRagAutoIngest) {
            exportRagAutoIngest.checked = bot.export_rag_auto_ingest !== false;
        }
        const exportRagTopK = this.$('#setting-export-rag-top-k');
        if (exportRagTopK) {
            exportRagTopK.value = bot.export_rag_top_k ?? 3;
        }
        const exportRagChunks = this.$('#setting-export-rag-max-chunks-per-chat');
        if (exportRagChunks) {
            exportRagChunks.value = bot.export_rag_max_chunks_per_chat ?? 500;
        }
        this._renderExportRagStatus(this.runtimeStatus?.export_rag || null);
        this._renderVectorMemoryHelp(bot, api, currentPreset);

        const controlCommands = this.$('#setting-control-commands-enabled');
        if (controlCommands) {
            controlCommands.checked = !!bot.control_commands_enabled;
        }
        const controlPrefix = this.$('#setting-control-command-prefix');
        if (controlPrefix) {
            controlPrefix.value = bot.control_command_prefix ?? '';
        }
        const controlReplyVisible = this.$('#setting-control-reply-visible');
        if (controlReplyVisible) {
            controlReplyVisible.checked = bot.control_reply_visible !== false;
        }
        const controlAllowedUsers = this.$('#setting-control-allowed-users');
        if (controlAllowedUsers) {
            controlAllowedUsers.value = (bot.control_allowed_users || []).join('\n');
        }

        const quietEnabled = this.$('#setting-quiet-hours-enabled');
        if (quietEnabled) {
            quietEnabled.checked = !!bot.quiet_hours_enabled;
        }
        const quietStart = this.$('#setting-quiet-hours-start');
        if (quietStart) {
            quietStart.value = bot.quiet_hours_start ?? '';
        }
        const quietEnd = this.$('#setting-quiet-hours-end');
        if (quietEnd) {
            quietEnd.value = bot.quiet_hours_end ?? '';
        }
        const quietReply = this.$('#setting-quiet-hours-reply');
        if (quietReply) {
            quietReply.value = bot.quiet_hours_reply ?? '';
        }

        const usageTracking = this.$('#setting-usage-tracking-enabled');
        if (usageTracking) {
            usageTracking.checked = !!bot.usage_tracking_enabled;
        }
        const dailyTokenLimit = this.$('#setting-daily-token-limit');
        if (dailyTokenLimit) {
            dailyTokenLimit.value = bot.daily_token_limit ?? 0;
        }
        const tokenWarning = this.$('#setting-token-warning-threshold');
        if (tokenWarning) {
            tokenWarning.value = bot.token_warning_threshold ?? 0;
        }

        const emotionEnabled = this.$('#setting-emotion-detection-enabled');
        if (emotionEnabled) {
            emotionEnabled.checked = !!bot.emotion_detection_enabled;
        }
        const emotionMode = this.$('#setting-emotion-detection-mode');
        if (emotionMode) {
            emotionMode.value = bot.emotion_detection_mode || 'keywords';
        }
        const emotionInject = this.$('#setting-emotion-inject-in-prompt');
        if (emotionInject) {
            emotionInject.checked = !!bot.emotion_inject_in_prompt;
        }
        const emotionLog = this.$('#setting-emotion-log-enabled');
        if (emotionLog) {
            emotionLog.checked = !!bot.emotion_log_enabled;
        }

        const agent = config.agent || {};
        const agentEnabled = this.$('#setting-agent-enabled');
        if (agentEnabled) {
            agentEnabled.checked = agent.enabled !== false;
        }
        const agentStreaming = this.$('#setting-agent-streaming-enabled');
        if (agentStreaming) {
            agentStreaming.checked = agent.streaming_enabled !== false;
        }
        const agentGraphMode = this.$('#setting-agent-graph-mode');
        if (agentGraphMode) {
            agentGraphMode.value = agent.graph_mode || 'state_graph';
        }
        const agentHistoryStrategy = this.$('#setting-agent-history-strategy');
        if (agentHistoryStrategy) {
            agentHistoryStrategy.value = agent.history_strategy || 'sqlite_memory';
        }
        const agentTopK = this.$('#setting-agent-retriever-top-k');
        if (agentTopK) {
            agentTopK.value = agent.retriever_top_k ?? 3;
        }
        const agentThreshold = this.$('#setting-agent-retriever-threshold');
        if (agentThreshold) {
            agentThreshold.value = agent.retriever_score_threshold ?? 1.0;
        }
        const agentCacheTtl = this.$('#setting-agent-embedding-cache-ttl');
        if (agentCacheTtl) {
            agentCacheTtl.value = agent.embedding_cache_ttl_sec ?? 300;
        }
        const agentMaxParallel = this.$('#setting-agent-max-parallel-retrievers');
        if (agentMaxParallel) {
            agentMaxParallel.value = agent.max_parallel_retrievers ?? 3;
        }
        const agentFacts = this.$('#setting-agent-background-facts');
        if (agentFacts) {
            agentFacts.checked = agent.background_fact_extraction_enabled !== false;
        }
        const agentEmotionFastPath = this.$('#setting-agent-emotion-fast-path');
        if (agentEmotionFastPath) {
            agentEmotionFastPath.checked = agent.emotion_fast_path_enabled !== false;
        }
        const agentLangSmithEnabled = this.$('#setting-agent-langsmith-enabled');
        if (agentLangSmithEnabled) {
            agentLangSmithEnabled.checked = !!agent.langsmith_enabled;
        }
        const agentLangSmithProject = this.$('#setting-agent-langsmith-project');
        if (agentLangSmithProject) {
            agentLangSmithProject.value = agent.langsmith_project || 'wechat-chat';
        }
        const agentLangSmithEndpoint = this.$('#setting-agent-langsmith-endpoint');
        if (agentLangSmithEndpoint) {
            agentLangSmithEndpoint.value = agent.langsmith_endpoint || '';
        }
        const agentLangSmithKeyStatus = this.$('#setting-agent-langsmith-key-status');
        if (agentLangSmithKeyStatus) {
            agentLangSmithKeyStatus.value = agent.langsmith_api_key_configured ? '已配置' : '未配置';
        }

        const loggingCfg = config.logging || {};
        const logLevel = this.$('#setting-log-level');
        if (logLevel) {
            logLevel.value = loggingCfg.level || 'INFO';
        }
        const logFormat = this.$('#setting-log-format');
        if (logFormat) {
            logFormat.value = loggingCfg.format || 'text';
        }
        const logFile = this.$('#setting-log-file');
        if (logFile) {
            logFile.value = loggingCfg.file || '';
        }
        const logMaxBytes = this.$('#setting-log-max-bytes');
        if (logMaxBytes) {
            logMaxBytes.value = loggingCfg.max_bytes ?? 0;
        }
        const logBackup = this.$('#setting-log-backup-count');
        if (logBackup) {
            logBackup.value = loggingCfg.backup_count ?? 0;
        }
        const logMessageContent = this.$('#setting-log-message-content');
        if (logMessageContent) {
            logMessageContent.checked = !!loggingCfg.log_message_content;
        }
        const logReplyContent = this.$('#setting-log-reply-content');
        if (logReplyContent) {
            logReplyContent.checked = !!loggingCfg.log_reply_content;
        }

        const quoteMode = this.$('#setting-reply-quote-mode');
        if (quoteMode) {
            quoteMode.value = bot.reply_quote_mode || 'wechat';
        }
        const quoteTemplate = this.$('#setting-reply-quote-template');
        if (quoteTemplate) {
            quoteTemplate.value = bot.reply_quote_template || '引用：{content}\n';
        }
        const quoteMaxChars = this.$('#setting-reply-quote-max-chars');
        if (quoteMaxChars) {
            const maxChars = bot.reply_quote_max_chars ?? 120;
            quoteMaxChars.value = Number.isFinite(maxChars) ? String(maxChars) : '120';
        }
        const quoteTimeout = this.$('#setting-reply-quote-timeout');
        if (quoteTimeout) {
            const timeoutSec = bot.reply_quote_timeout_sec ?? 5.0;
            quoteTimeout.value = Number.isFinite(timeoutSec) ? String(timeoutSec) : '5';
        }
        const quoteFallback = this.$('#setting-reply-quote-fallback');
        if (quoteFallback) {
            quoteFallback.checked = bot.reply_quote_fallback_to_text !== false;
        }

        this._fillPromptPreviewDefaults(bot);
        void this._previewPrompt({ showToast: false });

        // 渲染预设列表
        this._renderPresetList(api.presets || {});
    }

    _parsePromptOverridesInput(value) {
        const raw = String(value || '');
        const lines = raw.split('\n').map(item => item.trim()).filter(Boolean);
        const overrides = {};
        lines.forEach((line) => {
            const idx = line.indexOf('|');
            if (idx <= 0) return;
            const key = line.slice(0, idx).trim();
            const content = line.slice(idx + 1).trim().replace(/\\n/g, '\n');
            if (key) {
                overrides[key] = content;
            }
        });
        return overrides;
    }

    _fillPromptPreviewDefaults(bot = {}) {
        const chatName = this.$('#setting-preview-chat-name');
        const sender = this.$('#setting-preview-sender');
        const relationship = this.$('#setting-preview-relationship');
        const emotion = this.$('#setting-preview-emotion');
        const message = this.$('#setting-preview-message');
        const isGroup = this.$('#setting-preview-is-group');

        if (chatName && !chatName.value.trim()) {
            chatName.value = '预览联系人';
        }
        if (sender && !sender.value.trim()) {
            sender.value = '对方';
        }
        if (relationship && !relationship.value.trim()) {
            relationship.value = 'friend';
        }
        if (emotion && !emotion.value.trim()) {
            emotion.value = 'neutral';
        }
        if (message && !message.value.trim()) {
            const fallbackName = bot.self_name ? `我是${bot.self_name}，` : '';
            message.value = `${fallbackName}你今天有空吗？`;
        }
        if (isGroup && isGroup.indeterminate) {
            isGroup.checked = false;
        }
    }

    _collectPromptPreviewPayload() {
        return {
            bot: {
                system_prompt: this.$('#setting-system-prompt')?.value ?? '',
                system_prompt_overrides: this._parsePromptOverridesInput(this.$('#setting-system-prompt-overrides')?.value || ''),
                profile_inject_in_prompt: !!this.$('#setting-profile-inject-in-prompt')?.checked,
                emotion_inject_in_prompt: !!this.$('#setting-emotion-inject-in-prompt')?.checked,
            },
            sample: {
                chat_name: this.$('#setting-preview-chat-name')?.value?.trim() || '预览联系人',
                sender: this.$('#setting-preview-sender')?.value?.trim() || '对方',
                relationship: this.$('#setting-preview-relationship')?.value?.trim() || 'friend',
                emotion: this.$('#setting-preview-emotion')?.value?.trim() || 'neutral',
                message: this.$('#setting-preview-message')?.value ?? '',
                is_group: !!this.$('#setting-preview-is-group')?.checked,
            }
        };
    }

    _renderPromptPreview(result) {
        const summary = this.$('#settings-preview-summary');
        const output = this.$('#settings-prompt-preview');
        if (!summary || !output) {
            return;
        }

        if (!result?.success) {
            summary.textContent = result?.message || '预览失败';
            summary.dataset.state = 'error';
            output.textContent = result?.message || '预览失败';
            return;
        }

        const meta = result.summary || {};
        const flags = [];
        if (meta.override_applied) flags.push('已命中会话覆盖');
        if (meta.profile_injected) flags.push('已注入用户画像');
        if (meta.emotion_injected) flags.push('已注入情绪');
        if (flags.length === 0) flags.push('仅基础提示词');

        summary.textContent = `字符 ${meta.chars ?? 0} · 行数 ${meta.lines ?? 0} · ${flags.join(' · ')}`;
        summary.dataset.state = 'success';
        output.textContent = result.prompt || '';
    }

    async _previewPrompt({ showToast = true } = {}) {
        const previewButton = this.$('#btn-preview-prompt');
        if (!previewButton) {
            return;
        }

        this._setButtonLoading(
            previewButton,
            true,
            '<span class="spinner-sm" style="width:14px;height:14px;border-width:2px;"></span><span> 生成中...</span>'
        );

        try {
            const result = await apiService.previewPrompt(this._collectPromptPreviewPayload());
            this._renderPromptPreview(result);
            if (!result?.success) {
                throw new Error(result?.message || '预览失败');
            }
            if (showToast) {
                toast.success('提示词预览已更新');
            }
        } catch (error) {
            console.error('预览提示词异常:', error);
            const message = toast.getErrorMessage(error, '预览提示词失败');
            this._renderPromptPreview({ success: false, message });
            if (showToast) {
                toast.error(message);
            }
        } finally {
            this._setButtonLoading(previewButton, false);
        }
    }

    async _saveConfig() {
        if (!this.currentConfig) {
            toast.warning('配置尚未加载完成，请稍后再试');
            return;
        }

        const saveButton = this.$('#btn-save-settings');
        this._setButtonLoading(
            saveButton,
            true,
            '<span class="spinner-sm" style="width:14px;height:14px;border-width:2px;"></span><span> 保存中...</span>'
        );

        try {
            toast.info('正在保存配置...');

            // 收集表单数据
            const parseNumber = (value) => {
                if (value === '' || value == null) return undefined;
                const num = Number(value);
                return Number.isNaN(num) ? undefined : num;
            };
            const parseNumberOrNull = (value) => {
                if (value === '' || value == null) return null;
                const num = Number(value);
                return Number.isNaN(num) ? null : num;
            };
            const parseLines = (value) => value.split('\n').map(s => s.trim()).filter(s => s);
            const parseRange = (minVal, maxVal) => {
                if (minVal == null || maxVal == null) return undefined;
                const minNum = Number(minVal);
                const maxNum = Number(maxVal);
                if (Number.isNaN(minNum) || Number.isNaN(maxNum)) return undefined;
                return [minNum, maxNum];
            };

            const quoteMaxCharsRaw = this.$('#setting-reply-quote-max-chars')?.value;
            const quoteTimeoutRaw = this.$('#setting-reply-quote-timeout')?.value;
            const quoteMaxChars = quoteMaxCharsRaw === '' || quoteMaxCharsRaw == null ? undefined : Number(quoteMaxCharsRaw);
            const quoteTimeoutSec = quoteTimeoutRaw === '' || quoteTimeoutRaw == null ? undefined : Number(quoteTimeoutRaw);

            const overrides = this._parsePromptOverridesInput(this.$('#setting-system-prompt-overrides')?.value || '');

            const emojiReplacementInput = this.$('#setting-emoji-replacements')?.value || '';
            const emojiReplacementLines = parseLines(emojiReplacementInput);
            const emojiReplacements = {};
            emojiReplacementLines.forEach(line => {
                const idx = line.indexOf('=');
                if (idx <= 0) return;
                const key = line.slice(0, idx).trim();
                const value = line.slice(idx + 1).trim();
                if (key) emojiReplacements[key] = value;
            });

            const previousBot = this.currentConfig.bot || {};
            const previousVectorMemoryEnabled = previousBot.vector_memory_enabled !== false;
            const previousVectorMemoryRiskAcknowledged = !!previousBot.vector_memory_risk_acknowledged;
            const vectorMemoryEnabled = this.$('#setting-vector-memory-enabled')?.checked ?? previousVectorMemoryEnabled;
            const vectorMemoryEmbeddingModel = this.$('#setting-vector-memory-embedding-model')?.value?.trim() || '';
            const shouldConfirmVectorMemoryRisk =
                vectorMemoryEnabled && !previousVectorMemoryEnabled && !previousVectorMemoryRiskAcknowledged;

            if (shouldConfirmVectorMemoryRisk) {
                const confirmed = window.confirm(
                    [
                        '首次开启向量记忆 / RAG 前请确认：',
                        '1. 聊天内容可能会被写入本地索引或向量库，用于后续检索。',
                        '2. 首次建立或重建索引会占用更多 CPU、内存和磁盘，并拉长处理时间。',
                        '3. 如果 embedding 使用云端服务，可能产生额外调用成本；如果使用 Ollama，本地资源占用会明显增加。',
                        '',
                        '确认后将继续保存配置。'
                    ].join('\n')
                );
                if (!confirmed) {
                    this._setButtonLoading(saveButton, false);
                    return;
                }
            }

            const botSettings = {
                self_name: this.$('#setting-self-name').value,
                system_prompt: this.$('#setting-system-prompt')?.value ?? '',
                system_prompt_overrides: overrides,
                reply_suffix: this.$('#setting-reply-suffix').value,
                emoji_policy: this.$('#setting-emoji-policy')?.value,
                emoji_replacements: emojiReplacements,
                stream_reply: this.$('#setting-stream-reply')?.checked,
                group_reply_only_when_at: this.$('#setting-group-at-only').checked,
                whitelist_enabled: this.$('#setting-whitelist-enabled').checked,
                whitelist: parseLines(this.$('#setting-whitelist').value),
                voice_to_text: this.$('#setting-voice-to-text')?.checked,
                voice_to_text_fail_reply: this.$('#setting-voice-to-text-fail-reply')?.value,
                memory_db_path: this.$('#setting-memory-db-path')?.value,
                memory_context_limit: parseNumber(this.$('#setting-memory-context-limit')?.value),
                memory_ttl_sec: parseNumberOrNull(this.$('#setting-memory-ttl-sec')?.value),
                memory_cleanup_interval_sec: parseNumber(this.$('#setting-memory-cleanup-interval-sec')?.value),
                memory_seed_on_first_reply: this.$('#setting-memory-seed-on-first-reply')?.checked,
                memory_seed_limit: parseNumber(this.$('#setting-memory-seed-limit')?.value),
                memory_seed_load_more: parseNumber(this.$('#setting-memory-seed-load-more')?.value),
                memory_seed_load_more_interval_sec: parseNumber(this.$('#setting-memory-seed-load-more-interval-sec')?.value),
                memory_seed_group: this.$('#setting-memory-seed-group')?.checked,
                context_rounds: parseNumber(this.$('#setting-context-rounds')?.value),
                context_max_tokens: parseNumber(this.$('#setting-context-max-tokens')?.value),
                history_max_chats: parseNumber(this.$('#setting-history-max-chats')?.value),
                history_ttl_sec: parseNumberOrNull(this.$('#setting-history-ttl-sec')?.value),
                history_log_interval_sec: parseNumber(this.$('#setting-history-log-interval-sec')?.value),
                poll_interval_sec: parseNumber(this.$('#setting-poll-interval-sec')?.value),
                poll_interval_min_sec: parseNumber(this.$('#setting-poll-interval-min-sec')?.value),
                poll_interval_max_sec: parseNumber(this.$('#setting-poll-interval-max-sec')?.value),
                poll_interval_backoff_factor: parseNumber(this.$('#setting-poll-interval-backoff-factor')?.value),
                min_reply_interval_sec: parseNumber(this.$('#setting-min-reply-interval-sec')?.value),
                merge_user_messages_sec: parseNumber(this.$('#setting-merge-user-messages-sec')?.value),
                merge_user_messages_max_wait_sec: parseNumber(this.$('#setting-merge-user-messages-max-wait-sec')?.value),
                reply_chunk_size: parseNumber(this.$('#setting-reply-chunk-size')?.value),
                reply_chunk_delay_sec: parseNumber(this.$('#setting-reply-chunk-delay-sec')?.value),
                max_concurrency: parseNumber(this.$('#setting-max-concurrency')?.value),
                natural_split_enabled: this.$('#setting-natural-split-enabled')?.checked,
                natural_split_min_chars: parseNumber(this.$('#setting-natural-split-min-chars')?.value),
                natural_split_max_chars: parseNumber(this.$('#setting-natural-split-max-chars')?.value),
                natural_split_max_segments: parseNumber(this.$('#setting-natural-split-max-segments')?.value),
                stream_buffer_chars: parseNumber(this.$('#setting-stream-buffer-chars')?.value),
                stream_chunk_max_chars: parseNumber(this.$('#setting-stream-chunk-max-chars')?.value),
                config_reload_sec: parseNumber(this.$('#setting-config-reload-sec')?.value),
                reload_ai_client_on_change: this.$('#setting-reload-ai-client-on-change')?.checked,
                reload_ai_client_module: this.$('#setting-reload-ai-client-module')?.checked,
                keepalive_idle_sec: parseNumber(this.$('#setting-keepalive-idle-sec')?.value),
                reconnect_max_retries: parseNumber(this.$('#setting-reconnect-max-retries')?.value),
                reconnect_backoff_sec: parseNumber(this.$('#setting-reconnect-backoff-sec')?.value),
                reconnect_max_delay_sec: parseNumber(this.$('#setting-reconnect-max-delay-sec')?.value),
                group_include_sender: this.$('#setting-group-include-sender')?.checked,
                send_exact_match: this.$('#setting-send-exact-match')?.checked,
                send_fallback_current_chat: this.$('#setting-send-fallback-current-chat')?.checked,
                filter_mute: this.$('#setting-filter-mute')?.checked,
                ignore_official: this.$('#setting-ignore-official')?.checked,
                ignore_service: this.$('#setting-ignore-service')?.checked,
                ignore_names: parseLines(this.$('#setting-ignore-names')?.value || ''),
                ignore_keywords: parseLines(this.$('#setting-ignore-keywords')?.value || ''),
                personalization_enabled: this.$('#setting-personalization-enabled')?.checked,
                profile_update_frequency: parseNumber(this.$('#setting-profile-update-frequency')?.value),
                remember_facts_enabled: this.$('#setting-remember-facts-enabled')?.checked,
                max_context_facts: parseNumber(this.$('#setting-max-context-facts')?.value),
                profile_inject_in_prompt: this.$('#setting-profile-inject-in-prompt')?.checked,
                vector_memory_enabled: vectorMemoryEnabled,
                vector_memory_embedding_model: vectorMemoryEmbeddingModel,
                vector_memory_risk_acknowledged:
                    previousVectorMemoryRiskAcknowledged || shouldConfirmVectorMemoryRisk,
                export_rag_enabled: this.$('#setting-export-rag-enabled')?.checked,
                export_rag_dir: this.$('#setting-export-rag-dir')?.value,
                export_rag_auto_ingest: this.$('#setting-export-rag-auto-ingest')?.checked,
                export_rag_top_k: parseNumber(this.$('#setting-export-rag-top-k')?.value),
                export_rag_max_chunks_per_chat: parseNumber(this.$('#setting-export-rag-max-chunks-per-chat')?.value),
                control_commands_enabled: this.$('#setting-control-commands-enabled')?.checked,
                control_command_prefix: this.$('#setting-control-command-prefix')?.value,
                control_allowed_users: parseLines(this.$('#setting-control-allowed-users')?.value || ''),
                control_reply_visible: this.$('#setting-control-reply-visible')?.checked,
                quiet_hours_enabled: this.$('#setting-quiet-hours-enabled')?.checked,
                quiet_hours_start: this.$('#setting-quiet-hours-start')?.value,
                quiet_hours_end: this.$('#setting-quiet-hours-end')?.value,
                quiet_hours_reply: this.$('#setting-quiet-hours-reply')?.value,
                usage_tracking_enabled: this.$('#setting-usage-tracking-enabled')?.checked,
                daily_token_limit: parseNumber(this.$('#setting-daily-token-limit')?.value),
                token_warning_threshold: parseNumber(this.$('#setting-token-warning-threshold')?.value),
                emotion_detection_enabled: this.$('#setting-emotion-detection-enabled')?.checked,
                emotion_detection_mode: this.$('#setting-emotion-detection-mode')?.value,
                emotion_inject_in_prompt: this.$('#setting-emotion-inject-in-prompt')?.checked,
                emotion_log_enabled: this.$('#setting-emotion-log-enabled')?.checked
            };

            const randomDelay = parseRange(
                this.$('#setting-random-delay-min-sec')?.value,
                this.$('#setting-random-delay-max-sec')?.value
            );
            if (randomDelay) botSettings.random_delay_range_sec = randomDelay;

            const naturalDelay = parseRange(
                this.$('#setting-natural-split-delay-min-sec')?.value,
                this.$('#setting-natural-split-delay-max-sec')?.value
            );
            if (naturalDelay) botSettings.natural_split_delay_sec = naturalDelay;

            const replyQuoteMode = this.$('#setting-reply-quote-mode')?.value;
            if (replyQuoteMode) botSettings.reply_quote_mode = replyQuoteMode;

            const replyQuoteTemplate = this.$('#setting-reply-quote-template')?.value;
            if (replyQuoteTemplate != null) botSettings.reply_quote_template = replyQuoteTemplate;

            if (quoteMaxChars !== undefined && !Number.isNaN(quoteMaxChars)) {
                botSettings.reply_quote_max_chars = quoteMaxChars;
            }
            if (quoteTimeoutSec !== undefined && !Number.isNaN(quoteTimeoutSec)) {
                botSettings.reply_quote_timeout_sec = quoteTimeoutSec;
            }
            const quoteFallback = this.$('#setting-reply-quote-fallback');
            if (quoteFallback) {
                botSettings.reply_quote_fallback_to_text = quoteFallback.checked;
            }

            const loggingSettings = {
                level: this.$('#setting-log-level')?.value,
                format: this.$('#setting-log-format')?.value,
                file: this.$('#setting-log-file')?.value,
                max_bytes: parseNumber(this.$('#setting-log-max-bytes')?.value),
                backup_count: parseNumber(this.$('#setting-log-backup-count')?.value),
                log_message_content: this.$('#setting-log-message-content')?.checked,
                log_reply_content: this.$('#setting-log-reply-content')?.checked
            };

            const agentSettings = {
                enabled: this.$('#setting-agent-enabled')?.checked,
                streaming_enabled: this.$('#setting-agent-streaming-enabled')?.checked,
                graph_mode: this.$('#setting-agent-graph-mode')?.value,
                history_strategy: this.$('#setting-agent-history-strategy')?.value,
                retriever_top_k: parseNumber(this.$('#setting-agent-retriever-top-k')?.value),
                retriever_score_threshold: parseNumber(this.$('#setting-agent-retriever-threshold')?.value),
                embedding_cache_ttl_sec: parseNumber(this.$('#setting-agent-embedding-cache-ttl')?.value),
                max_parallel_retrievers: parseNumber(this.$('#setting-agent-max-parallel-retrievers')?.value),
                background_fact_extraction_enabled: this.$('#setting-agent-background-facts')?.checked,
                emotion_fast_path_enabled: this.$('#setting-agent-emotion-fast-path')?.checked,
                langsmith_enabled: this.$('#setting-agent-langsmith-enabled')?.checked,
                langsmith_project: this.$('#setting-agent-langsmith-project')?.value,
                langsmith_endpoint: this.$('#setting-agent-langsmith-endpoint')?.value
            };

            // 合并到当前配置
            let newConfig = {
                ...this.currentConfig,
                bot: {
                    ...this.currentConfig.bot,
                    ...botSettings
                },
                logging: {
                    ...this.currentConfig.logging,
                    ...loggingSettings
                },
                agent: {
                    ...(this.currentConfig.agent || {}),
                    ...agentSettings
                }
            };

            const result = await apiService.saveConfig(newConfig);
            if (result.success) {
                const savedConfig = this._extractConfigPayload(result);
                this.runtimeStatus = await apiService.getStatus().catch(() => this.runtimeStatus);
                if (savedConfig) {
                    this.currentConfig = savedConfig;
                    this._renderConfig(this.currentConfig);
                }
                const runtimeApply = result.runtime_apply;
                if (runtimeApply?.success) {
                    toast.success(runtimeApply.message || '配置已保存并立即应用');
                } else if (runtimeApply && runtimeApply.success === false) {
                    toast.warning(`配置已保存，但运行中机器人未完全应用：${runtimeApply.message}`);
                } else {
                    toast.success('配置已保存');
                }
            } else {
                toast.error('保存失败: ' + result.message);
            }
        } catch (error) {
            console.error('保存配置异常:', error);
            toast.error(toast.getErrorMessage(error, '保存配置异常'));
        } finally {
            this._setButtonLoading(saveButton, false);
        }
    }

    _renderExportRagStatus(status) {
        const el = this.$('#setting-export-rag-status');
        if (!el) return;
        if (!status) {
            el.textContent = '状态：未加载';
            return;
        }
        const parts = [
            `状态：${status.enabled ? '已启用' : '未启用'}`,
            `联系人：${status.indexed_contacts ?? 0}`,
            `片段：${status.indexed_chunks ?? 0}`
        ];
        if (status.last_scan_at) {
            parts.push(`最近扫描：${new Date(status.last_scan_at * 1000).toLocaleString('zh-CN')}`);
        }
        const summary = status.last_scan_summary || {};
        if (summary.reason) {
            parts.push(`结果：${summary.reason}`);
        }
        el.textContent = parts.join(' | ');
    }

    // ═══════════════════════════════════════════════════════════════════════
    //                           预设管理
    // ═══════════════════════════════════════════════════════════════════════

    _renderVectorMemoryHelp(bot = {}, api = {}, currentPreset = {}) {
        const el = this.$('#setting-vector-memory-help');
        if (!el) return;

        const vectorMemoryEnabled = bot.vector_memory_enabled !== false;
        const retrievalEnabled = !!(bot.rag_enabled || bot.export_rag_enabled);
        const explicitOverride = String(bot.vector_memory_embedding_model || '').trim();
        const presetEmbedding = String(currentPreset?.embedding_model || '').trim();
        const globalEmbedding = String(api.embedding_model || '').trim();

        let sourceText = '';
        if (explicitOverride) {
            sourceText = `当前使用单独配置的 embedding 模型：${explicitOverride}。`;
        } else if (presetEmbedding) {
            sourceText = `当前跟随预设 ${currentPreset?.name || ''} 的 embedding 模型：${presetEmbedding}。`;
        } else if (globalEmbedding) {
            sourceText = `当前跟随全局 embedding 配置：${globalEmbedding}。`;
        } else {
            sourceText = '当前没有可用的 embedding 模型，向量检索不会生效。';
        }

        const parts = [
            vectorMemoryEnabled
                ? '主开关已开启，允许向量记忆和 RAG 工作。'
                : '主开关已关闭，机器人不会写入或检索向量记忆。',
            retrievalEnabled
                ? '当前已启用至少一种检索能力。'
                : '当前还没有开启检索能力，只有在启用 RAG 后才会真正使用 embedding。',
            sourceText,
            'Ollama 可填写本地 embedding 模型，例如 nomic-embed-text。'
        ];
        el.textContent = parts.join(' ');
    }

    _renderPresetList(presets) {
        const list = this.$('#preset-list');
        list.innerHTML = '';

        // 确保 presets 是数组
        const presetList = Array.isArray(presets) ? presets : [];

        if (presetList.length === 0) {
            list.innerHTML = '<div class="empty-state">暂无预设</div>';
            return;
        }

        presetList.forEach(preset => {
            const name = preset.name;
            const isActive = name === this.currentConfig.api?.active_preset;
            const provider = this._getProviderById(preset.provider_id || this._guessProviderId(preset));
            const icon = this._getProviderIcon(provider?.label || preset.provider_id || name);
            const keyTag = preset.api_key_required === false
                ? '<span class="tag" style="background: rgba(59, 130, 246, 0.2); color: #60a5fa; margin-left: 6px; font-size: 0.75em; padding: 2px 6px;">无需 Key</span>'
                : (preset.api_key_configured
                    ? '<span class="tag" style="background: rgba(16, 185, 129, 0.2); color: #10b981; margin-left: 6px; font-size: 0.75em; padding: 2px 6px;">已配 Key</span>'
                    : '<span class="tag" style="background: rgba(245, 158, 11, 0.2); color: #f59e0b; margin-left: 6px; font-size: 0.75em; padding: 2px 6px;">无 Key</span>');

            const item = document.createElement('div');
            // 使用 CSS 类控制样式
            item.className = `preset-card ${isActive ? 'active' : ''}`;
            
            item.innerHTML = `
                <div class="preset-card-header">
                    <div class="preset-icon">${icon}</div>
                    <div class="preset-info">
                        <div class="preset-name">
                            ${name}
                            ${isActive ? '<span class="tag tag-active">当前使用</span>' : ''}
                            ${keyTag}
                        </div>
                        <div class="preset-meta">
                            <span class="meta-item model-name" title="${preset.model}">${preset.model}</span>
                            ${preset.alias ? `<span class="meta-separator">·</span><span class="meta-item">${preset.alias}</span>` : ''}
                        </div>
                    </div>
                </div>
                <div class="preset-card-actions">
                    ${!isActive ? `<button class="btn-icon btn-ghost btn-activate" title="启用"><svg class="icon" viewBox="0 0 24 24"><path d="M5 3l14 9-14 9V3z"/></svg></button>` : ''}
                    <button class="btn-icon btn-ghost btn-edit" title="编辑"><svg class="icon" viewBox="0 0 24 24"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg></button>
                    <button class="btn-icon btn-ghost btn-delete" title="删除"><svg class="icon" viewBox="0 0 24 24"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg></button>
                </div>
            `;

            // 绑定列表项按钮事件
            item.querySelector('.btn-edit').onclick = () => this._openPresetModal(name, preset);
            item.querySelector('.btn-delete').onclick = () => this._deletePreset(name, item.querySelector('.btn-delete'));
            if (!isActive) {
                const btnActivate = item.querySelector('.btn-activate');
                if (btnActivate) {
                    btnActivate.onclick = async () => this._activatePreset(name, btnActivate);
                }
            }

            list.appendChild(item);
        });
    }

    _openPresetModal(name = null, preset = null) {
        const modal = this.$('#preset-modal');
        const isEdit = !!name;
        const providerId = preset?.provider_id || this._guessProviderId(preset || name) || 'openai';

        this.$('.modal-title').textContent = isEdit ? '编辑预设' : '新增预设';
        this.$('#edit-preset-original-name').value = name || '';
        this.$('#edit-preset-name').value = name || '';
        this.$('#edit-preset-name').disabled = isEdit; // 编辑时不允许改名(ID)
        this._populateProviderSelect(providerId);

        if (preset) {
            this.$('#edit-preset-alias').value = preset.alias || '';
            this.$('#edit-preset-embedding-model').value = preset.embedding_model || '';
            this.$('#edit-preset-key').value = ''; // 不回显 Key
            this._renderProviderModels(preset.model || '');
        } else {
            this.$('#edit-preset-alias').value = '';
            this.$('#edit-preset-embedding-model').value = '';
            this.$('#edit-preset-key').value = '';
            this._renderProviderModels();
        }

        this._updateApiKeyHelp(this._getSelectedProviderId());
        modal.classList.add('active');
        void this._syncOllamaModels(preset?.model || '');
    }

    _closePresetModal() {
        this.$('#preset-modal').classList.remove('active');
    }

    async _savePreset() {
        if (!this.currentConfig?.api) {
            toast.warning('配置尚未加载完成，请稍后再试');
            return;
        }

        const originalName = this.$('#edit-preset-original-name').value;
        const name = this.$('#edit-preset-name').value.trim();
        const providerId = this._getSelectedProviderId();
        const alias = this.$('#edit-preset-alias').value.trim();
        const embeddingModel = this.$('#edit-preset-embedding-model').value.trim();
        const key = this.$('#edit-preset-key').value.trim();
        const saveButton = this.$('#btn-save-modal');

        const select = this.$('#edit-preset-model-select');
        let model = select.value;
        if (model === 'custom') {
            model = this.$('#edit-preset-model-custom').value.trim();
        }

        if (!name || !providerId || !model) {
            toast.error('名称、服务商和模型不能为空');
            return;
        }

        let presets = [...(this.currentConfig.api.presets || [])];
        if (!Array.isArray(presets)) presets = [];

        const existingIndex = originalName
            ? presets.findIndex(p => p.name === originalName)
            : -1;

        const existingPreset = existingIndex !== -1 ? presets[existingIndex] : null;
        const existingProviderId = existingPreset?.provider_id || this._guessProviderId(existingPreset || originalName);
        const providerChanged = !!existingPreset && providerId !== existingProviderId;
        const provider = this._getProviderById(providerId);

        const providerDefaults = provider ? {
            provider_id: provider.id,
            base_url: provider.base_url,
            allow_empty_key: !!provider.allow_empty_key
        } : { provider_id: providerId };

        const preservedPreset = existingPreset && !providerChanged ? { ...existingPreset } : {};
        delete preservedPreset.api_key_configured;
        delete preservedPreset.api_key_masked;

        const newPreset = {
            ...providerDefaults,
            ...preservedPreset,
            name,
            model,
            alias,
            embedding_model: embeddingModel,
            provider_id: providerId,
            ...(key ? { api_key: key } : {})
        };

        if (existingIndex !== -1) {
            if (!key) {
                newPreset._keep_key = true;
            }
            presets[existingIndex] = newPreset;
        } else {
            if (presets.some(p => p.name === name)) {
                toast.error('预设名称已存在');
                return;
            }
            presets.push(newPreset);
        }

        const newConfig = {
            ...this.currentConfig,
            api: {
                ...this.currentConfig.api,
                presets
            }
        };

        this._setButtonLoading(
            saveButton,
            true,
            '<span class="spinner-sm" style="width:14px;height:14px;border-width:2px;"></span><span> 保存中...</span>'
        );

        try {
            toast.info(`正在保存预设: ${name}...`);
            const result = await apiService.saveConfig(newConfig);
            if (result.success) {
                const savedConfig = this._extractConfigPayload(result);
                if (savedConfig) {
                    this.currentConfig = savedConfig;
                    this._renderConfig(this.currentConfig);
                }
                this._closePresetModal();
                toast.success('预设已保存');
            } else {
                toast.error('保存失败: ' + result.message);
            }
        } catch (error) {
            console.error('保存预设异常:', error);
            toast.error(toast.getErrorMessage(error, '保存预设异常'));
        } finally {
            this._setButtonLoading(saveButton, false);
        }
    }

    async _deletePreset(name, triggerButton = null) {
        if (!this.currentConfig?.api) {
            toast.warning('配置尚未加载完成，请稍后再试');
            return;
        }
        if (!confirm(`确定要删除预设 "${name}" 吗？`)) return;

        let presets = [...(this.currentConfig.api.presets || [])];
        if (!Array.isArray(presets)) presets = [];
        
        presets = presets.filter(p => p.name !== name);

        const newConfig = {
            ...this.currentConfig,
            api: {
                ...this.currentConfig.api,
                presets
            }
        };

        this._setButtonLoading(
            triggerButton,
            true,
            '<span class="spinner-sm" style="width:14px;height:14px;border-width:2px;"></span>'
        );

        try {
            toast.info(`正在删除预设: ${name}...`);
            const result = await apiService.saveConfig(newConfig);
            if (result.success) {
                const savedConfig = this._extractConfigPayload(result);
                if (savedConfig) {
                    this.currentConfig = savedConfig;
                    this._renderConfig(this.currentConfig);
                }
                toast.success('预设已删除');
            } else {
                toast.error('删除失败: ' + result.message);
            }
        } catch (error) {
            console.error('删除预设异常:', error);
            toast.error(toast.getErrorMessage(error, '删除预设异常'));
        } finally {
            this._setButtonLoading(triggerButton, false);
        }
    }

    async _activatePreset(name, triggerButton = null) {
        if (!this.currentConfig?.api) {
            toast.warning('配置尚未加载完成，请稍后再试');
            return;
        }

        try {
            const targetPreset = (this.currentConfig.api.presets || []).find(p => p.name === name);
            if (!targetPreset) {
                toast.error(`未找到预设: ${name}`);
                return;
            }

            if (targetPreset.api_key_required !== false && !targetPreset.api_key_configured) {
                toast.error(`预设 ${name} 未配置 API Key，无法启用`);
                return;
            }

            this._setButtonLoading(
                triggerButton,
                true,
                '<span class="spinner-sm" style="width:14px;height:14px;border-width:2px;"></span>'
            );
            toast.info(`正在切换到预设: ${name}...`);

            const newConfig = {
                ...this.currentConfig,
                api: {
                    ...this.currentConfig.api,
                    active_preset: name
                }
            };

            const result = await apiService.saveConfig(newConfig);
            if (result.success) {
                const savedConfig = this._extractConfigPayload(result);
                this.runtimeStatus = await apiService.getStatus().catch(() => this.runtimeStatus);
                if (savedConfig) {
                    this.currentConfig = savedConfig;
                    this._renderConfig(this.currentConfig);
                }

                const status = await apiService.getStatus().catch(() => null);

                // 触发高亮特效
                const heroCard = this.$('.config-hero-card');
                if (heroCard) {
                    heroCard.classList.remove('highlight-pulse');
                    // 强制重绘以重置动画
                    void heroCard.offsetWidth;
                    heroCard.classList.add('highlight-pulse');
                    
                    // 动画结束后移除类(可选，但保持清洁更好)
                    setTimeout(() => {
                        heroCard.classList.remove('highlight-pulse');
                    }, 1500);
                }

                const runtimeApply = result.runtime_apply;
                if (runtimeApply?.success) {
                    toast.success(runtimeApply.message || `已切换到预设: ${name}`);
                } else if (runtimeApply && runtimeApply.success === false) {
                    toast.warning(`预设已保存为 ${name}，但运行中 AI 未立即切换：${runtimeApply.message}`);
                } else {
                    toast.success(`已切换到预设: ${name}。${this._getRuntimeSwitchMessage(!!status?.running)}`);
                }
            } else {
                toast.error('切换失败: ' + result.message);
                throw new Error(result.message); // 抛出异常以便外层捕获恢复按钮状态
            }
        } catch (error) {
            console.error('切换预设异常:', error);
            // 如果是主动抛出的错误，可能已经 toast 过了，但这里统一处理也没事
            if (!error.message || !error.message.includes('切换失败')) {
                toast.error(toast.getErrorMessage(error, '切换预设操作发生错误'));
            }
        } finally {
            this._setButtonLoading(triggerButton, false);
        }
    }
}
