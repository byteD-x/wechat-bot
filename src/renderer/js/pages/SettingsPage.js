import { PageController } from '../core/PageController.js';
import { apiService } from '../services/ApiService.js';
import { toast } from '../services/NotificationService.js';

const TEXT = {
    loading: '加载配置中...',
    loadFailed: '加载配置失败',
    saveFailed: '保存配置失败',
    previewFailed: '生成预览失败',
    updateFailed: '检查更新失败',
    resetCloseSuccess: '关闭方式已重置',
    presetMissing: '请至少保留一个 API 预设',
    presetNameMissing: '预设名称不能为空',
    presetModelMissing: '请填写模型名称',
    presetSaveSuccess: '预设草稿已更新，记得点击“保存配置”生效',
    noAudit: '未获取到配置审计信息',
};

const FIELD_DEFS = [];
const LIST_FIELD_DEFS = [];
const MAP_FIELD_DEFS = [];
const RANGE_FIELD_DEFS = [];

FIELD_DEFS.push(
    ['setting-self-name', 'bot', 'self_name', 'text'], ['setting-reply-suffix', 'bot', 'reply_suffix', 'text'],
    ['setting-group-at-only', 'bot', 'group_reply_only_when_at', 'checkbox'],
    ['setting-system-prompt', 'bot', 'system_prompt', 'text'],
    ['setting-emoji-policy', 'bot', 'emoji_policy', 'text'], ['setting-voice-to-text', 'bot', 'voice_to_text', 'checkbox'],
    ['setting-voice-to-text-fail-reply', 'bot', 'voice_to_text_fail_reply', 'text'], ['setting-memory-db-path', 'bot', 'memory_db_path', 'text'],
    ['setting-memory-context-limit', 'bot', 'memory_context_limit', 'number'], ['setting-memory-ttl-sec', 'bot', 'memory_ttl_sec', 'number', { nullable: true }],
    ['setting-memory-cleanup-interval-sec', 'bot', 'memory_cleanup_interval_sec', 'number'], ['setting-context-rounds', 'bot', 'context_rounds', 'number'],
    ['setting-context-max-tokens', 'bot', 'context_max_tokens', 'number'], ['setting-history-max-chats', 'bot', 'history_max_chats', 'number'],
    ['setting-history-ttl-sec', 'bot', 'history_ttl_sec', 'number', { nullable: true }], ['setting-poll-interval-min-sec', 'bot', 'poll_interval_min_sec', 'number'],
    ['setting-poll-interval-max-sec', 'bot', 'poll_interval_max_sec', 'number'], ['setting-poll-interval-backoff-factor', 'bot', 'poll_interval_backoff_factor', 'number'],
    ['setting-min-reply-interval-sec', 'bot', 'min_reply_interval_sec', 'number'], ['setting-merge-user-messages-sec', 'bot', 'merge_user_messages_sec', 'number'],
    ['setting-merge-user-messages-max-wait-sec', 'bot', 'merge_user_messages_max_wait_sec', 'number'], ['setting-reply-chunk-size', 'bot', 'reply_chunk_size', 'number'],
    ['setting-reply-chunk-delay-sec', 'bot', 'reply_chunk_delay_sec', 'number'], ['setting-reply-deadline-sec', 'bot', 'reply_deadline_sec', 'number'],
    ['setting-max-concurrency', 'bot', 'max_concurrency', 'number'],
    ['setting-natural-split-enabled', 'bot', 'natural_split_enabled', 'checkbox'], ['setting-natural-split-min-chars', 'bot', 'natural_split_min_chars', 'number'],
    ['setting-natural-split-max-chars', 'bot', 'natural_split_max_chars', 'number'], ['setting-natural-split-max-segments', 'bot', 'natural_split_max_segments', 'number'],
    ['setting-transport-backend', 'bot', 'transport_backend', 'text'], ['setting-required-wechat-version', 'bot', 'required_wechat_version', 'text'],
    ['setting-silent-mode-required', 'bot', 'silent_mode_required', 'checkbox'], ['setting-config-reload-sec', 'bot', 'config_reload_sec', 'number'],
    ['setting-reload-ai-client-on-change', 'bot', 'reload_ai_client_on_change', 'checkbox'], ['setting-reload-ai-client-module', 'bot', 'reload_ai_client_module', 'checkbox'],
    ['setting-keepalive-idle-sec', 'bot', 'keepalive_idle_sec', 'number'], ['setting-reconnect-max-retries', 'bot', 'reconnect_max_retries', 'number'],
    ['setting-reconnect-backoff-sec', 'bot', 'reconnect_backoff_sec', 'number'], ['setting-reconnect-max-delay-sec', 'bot', 'reconnect_max_delay_sec', 'number'],
    ['setting-group-include-sender', 'bot', 'group_include_sender', 'checkbox'], ['setting-send-exact-match', 'bot', 'send_exact_match', 'checkbox'],
    ['setting-send-fallback-current-chat', 'bot', 'send_fallback_current_chat', 'checkbox'], ['setting-filter-mute', 'bot', 'filter_mute', 'checkbox'],
    ['setting-ignore-official', 'bot', 'ignore_official', 'checkbox'], ['setting-ignore-service', 'bot', 'ignore_service', 'checkbox'],
    ['setting-allow-filehelper-self-message', 'bot', 'allow_filehelper_self_message', 'checkbox'],
    ['setting-personalization-enabled', 'bot', 'personalization_enabled', 'checkbox'], ['setting-profile-update-frequency', 'bot', 'profile_update_frequency', 'number'],
    ['setting-contact-prompt-update-frequency', 'bot', 'contact_prompt_update_frequency', 'number'],
    ['setting-remember-facts-enabled', 'bot', 'remember_facts_enabled', 'checkbox'], ['setting-max-context-facts', 'bot', 'max_context_facts', 'number'],
    ['setting-profile-inject-in-prompt', 'bot', 'profile_inject_in_prompt', 'checkbox'], ['setting-vector-memory-enabled', 'bot', 'rag_enabled', 'checkbox'],
    ['setting-vector-memory-embedding-model', 'bot', 'vector_memory_embedding_model', 'text'], ['setting-export-rag-enabled', 'bot', 'export_rag_enabled', 'checkbox'],
    ['setting-export-rag-auto-ingest', 'bot', 'export_rag_auto_ingest', 'checkbox'], ['setting-export-rag-dir', 'bot', 'export_rag_dir', 'text'],
    ['setting-export-rag-top-k', 'bot', 'export_rag_top_k', 'number'], ['setting-export-rag-max-chunks-per-chat', 'bot', 'export_rag_max_chunks_per_chat', 'number'],
    ['setting-control-commands-enabled', 'bot', 'control_commands_enabled', 'checkbox'], ['setting-control-command-prefix', 'bot', 'control_command_prefix', 'text'],
    ['setting-control-reply-visible', 'bot', 'control_reply_visible', 'checkbox'], ['setting-quiet-hours-enabled', 'bot', 'quiet_hours_enabled', 'checkbox'],
    ['setting-quiet-hours-start', 'bot', 'quiet_hours_start', 'text'], ['setting-quiet-hours-end', 'bot', 'quiet_hours_end', 'text'],
    ['setting-quiet-hours-reply', 'bot', 'quiet_hours_reply', 'text'], ['setting-usage-tracking-enabled', 'bot', 'usage_tracking_enabled', 'checkbox'],
    ['setting-daily-token-limit', 'bot', 'daily_token_limit', 'number'], ['setting-token-warning-threshold', 'bot', 'token_warning_threshold', 'number'],
    ['setting-emotion-detection-enabled', 'bot', 'emotion_detection_enabled', 'checkbox'], ['setting-emotion-detection-mode', 'bot', 'emotion_detection_mode', 'text'],
    ['setting-emotion-inject-in-prompt', 'bot', 'emotion_inject_in_prompt', 'checkbox'], ['setting-emotion-log-enabled', 'bot', 'emotion_log_enabled', 'checkbox'],
    ['setting-whitelist-enabled', 'bot', 'whitelist_enabled', 'checkbox'], ['setting-agent-enabled', 'agent', 'enabled', 'checkbox'],
    ['setting-agent-graph-mode', 'agent', 'graph_mode', 'text'],
    ['setting-agent-retriever-top-k', 'agent', 'retriever_top_k', 'number'], ['setting-agent-retriever-threshold', 'agent', 'retriever_score_threshold', 'number'],
    ['setting-agent-embedding-cache-ttl', 'agent', 'embedding_cache_ttl_sec', 'number'], ['setting-agent-max-parallel-retrievers', 'agent', 'max_parallel_retrievers', 'number'],
    ['setting-agent-background-facts', 'agent', 'background_fact_extraction_enabled', 'checkbox'], ['setting-agent-emotion-fast-path', 'agent', 'emotion_fast_path_enabled', 'checkbox'],
    ['setting-agent-langsmith-enabled', 'agent', 'langsmith_enabled', 'checkbox'], ['setting-agent-langsmith-project', 'agent', 'langsmith_project', 'text'],
    ['setting-agent-langsmith-endpoint', 'agent', 'langsmith_endpoint', 'text', { nullable: true }], ['setting-log-level', 'logging', 'level', 'text'],
    ['setting-log-format', 'logging', 'format', 'text'], ['setting-log-file', 'logging', 'file', 'text'],
    ['setting-log-max-bytes', 'logging', 'max_bytes', 'number'], ['setting-log-backup-count', 'logging', 'backup_count', 'number'],
    ['setting-log-message-content', 'logging', 'log_message_content', 'checkbox'], ['setting-log-reply-content', 'logging', 'log_reply_content', 'checkbox'],
);

LIST_FIELD_DEFS.push(
    ['setting-ignore-names', 'bot', 'ignore_names'], ['setting-ignore-keywords', 'bot', 'ignore_keywords'],
    ['setting-control-allowed-users', 'bot', 'control_allowed_users'], ['setting-whitelist', 'bot', 'whitelist'],
);

MAP_FIELD_DEFS.push(
    ['setting-system-prompt-overrides', 'bot', 'system_prompt_overrides', '|'],
    ['setting-emoji-replacements', 'bot', 'emoji_replacements', '='],
);

RANGE_FIELD_DEFS.push(
    ['setting-random-delay-min-sec', 'setting-random-delay-max-sec', 'bot', 'random_delay_range_sec'],
    ['setting-natural-split-delay-min-sec', 'setting-natural-split-delay-max-sec', 'bot', 'natural_split_delay_sec'],
);

const FIELD_META_BY_ID = new Map();

FIELD_DEFS.forEach(([id, section, path, type, options = {}]) => {
    FIELD_META_BY_ID.set(id, { id, section, path, type, options, kind: 'field' });
});
LIST_FIELD_DEFS.forEach(([id, section, path]) => {
    FIELD_META_BY_ID.set(id, { id, section, path, kind: 'list' });
});
MAP_FIELD_DEFS.forEach(([id, section, path, separator]) => {
    FIELD_META_BY_ID.set(id, { id, section, path, separator, kind: 'map' });
});
RANGE_FIELD_DEFS.forEach(([minId, maxId, section, path]) => {
    FIELD_META_BY_ID.set(minId, { id: minId, pairId: maxId, section, path, kind: 'range' });
    FIELD_META_BY_ID.set(maxId, { id: maxId, pairId: minId, section, path, kind: 'range' });
});

function deepClone(value) {
    return JSON.parse(JSON.stringify(value ?? {}));
}

function getPathValue(target, path) {
    return String(path || '')
        .split('.')
        .filter(Boolean)
        .reduce((cursor, key) => (cursor && key in cursor ? cursor[key] : undefined), target);
}

function setPathValue(target, path, value) {
    const keys = String(path || '').split('.').filter(Boolean);
    let cursor = target;
    while (keys.length > 1) {
        const key = keys.shift();
        if (!cursor[key] || typeof cursor[key] !== 'object') {
            cursor[key] = {};
        }
        cursor = cursor[key];
    }
    cursor[keys[0]] = value;
}

function normalizeListText(value) {
    return String(value || '')
        .split(/\r?\n/)
        .map((item) => item.trim())
        .filter(Boolean);
}

function listToMultiline(value) {
    return Array.isArray(value) ? value.join('\n') : '';
}

function mapToMultiline(value, separator) {
    if (!value || typeof value !== 'object') {
        return '';
    }
    return Object.entries(value)
        .map(([key, next]) => `${key}${separator}${next}`)
        .join('\n');
}

function multilineToMap(value, separator) {
    const result = {};
    for (const line of normalizeListText(value)) {
        const index = line.indexOf(separator);
        if (index <= 0) {
            continue;
        }
        const key = line.slice(0, index).trim();
        const nextValue = line.slice(index + separator.length).trim();
        if (key) {
            result[key] = nextValue;
        }
    }
    return result;
}

function formatDateTime(value) {
    if (!value) {
        return '--';
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
        return '--';
    }
    return new Intl.DateTimeFormat('zh-CN', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
    }).format(date);
}

function createElement(tag, className, text) {
    const element = document.createElement(tag);
    if (className) {
        element.className = className;
    }
    if (text !== undefined) {
        element.textContent = text;
    }
    return element;
}

function pruneEmptySections(payload) {
    const nextPayload = payload && typeof payload === 'object' ? payload : {};
    Object.keys(nextPayload).forEach((section) => {
        const value = nextPayload[section];
        if (value && typeof value === 'object' && !Array.isArray(value) && Object.keys(value).length === 0) {
            delete nextPayload[section];
        }
    });
    return nextPayload;
}

export class SettingsPage extends PageController {
    constructor() {
        super('SettingsPage', 'page-settings');
        this._config = null;
        this._configAudit = null;
        this._modelCatalog = null;
        this._providersById = new Map();
        this._presetDrafts = [];
        this._activePreset = '';
        this._selectedPresetIndex = -1;
        this._loaded = false;
        this._loadingPromise = null;
        this._lastConfigVersion = 0;
        this._isSaving = false;
        this._mainContent = null;
        this._scrollTopButton = null;
    }

    async onInit() {
        await super.onInit();
        this._bindEvents();
        this._initModuleSaveButtons();
        this._initScrollControls();
        this._watchUpdaterState();
    }

    async onEnter() {
        await super.onEnter();
        this._handleMainScroll();
        const runtimeVersion = Number(this.getState('bot.status.config_snapshot.version') || 0);
        if (!this._loaded || (runtimeVersion && runtimeVersion > this._lastConfigVersion)) {
            await this.loadSettings({ preserveFeedback: true });
        } else {
            this._renderHero();
            this._renderUpdatePanel();
        }
    }

    _bindEvents() {
        this.bindEvent('#btn-refresh-config', 'click', () => void this.loadSettings({ silent: false }));
        this.bindEvent('#btn-save-settings', 'click', () => void this._saveSettings());
        this.bindEvent('#btn-preview-prompt', 'click', () => void this._previewPrompt());
        this.bindEvent('#btn-check-updates', 'click', () => void this._checkUpdates());
        this.bindEvent('#btn-open-update-download', 'click', () => void this._openUpdateDownload());
        this.bindEvent('#btn-reset-close-behavior', 'click', () => void this._resetCloseBehavior());
        this.bindEvent('#btn-settings-scroll-top', 'click', () => this._scrollToTop());
        this.bindEvent('#btn-add-preset', 'click', () => this._openPresetModal());
        this.bindEvent('#btn-close-modal', 'click', () => this._closePresetModal());
        this.bindEvent('#btn-cancel-modal', 'click', () => this._closePresetModal());
        this.bindEvent('#btn-save-modal', 'click', () => this._commitPresetModal());
        this.bindEvent('#btn-toggle-key', 'click', () => this._togglePresetKeyVisibility());

        this.$('#edit-preset-provider')?.addEventListener('change', () => void this._handlePresetProviderChange());
        this.$('#edit-preset-model-select')?.addEventListener('change', () => this._syncPresetModelInput());

        document.getElementById('preset-modal')?.addEventListener('click', (event) => {
            if (event.target?.id === 'preset-modal') {
                this._closePresetModal();
            }
        });
    }

    _watchUpdaterState() {
        [
            'updater.enabled', 'updater.checking', 'updater.available', 'updater.currentVersion',
            'updater.latestVersion', 'updater.lastCheckedAt', 'updater.releaseDate', 'updater.error',
        ].forEach((path) => {
            this.watchState(path, () => {
                if (this.isActive()) {
                    this._renderUpdatePanel();
                }
            });
        });
        this.watchState('bot.status', () => {
            if (this.isActive()) {
                this._renderHero();
            }
            this._maybeRefreshForRuntimeConfigChange();
        });
    }

    async loadSettings(options = {}) {
        if (this._loadingPromise) {
            return this._loadingPromise;
        }

        const { silent = true, preserveFeedback = false } = options;
        const hero = this.$('#current-config-hero');
        if (hero && !this._loaded) {
            hero.innerHTML = `<div class="config-hero-card" style="opacity:0.7;"><div class="hero-content"><div class="hero-title"><span class="hero-name">${TEXT.loading}</span></div></div></div>`;
        }

        this._loadingPromise = (async () => {
            try {
                const [configResult, auditResult, catalogResult] = await Promise.all([
                    apiService.getConfig(),
                    apiService.getConfigAudit().catch((error) => ({ success: false, message: error?.message || TEXT.noAudit })),
                    apiService.getModelCatalog().catch(() => ({ success: false, providers: [] })),
                ]);

                if (!configResult?.success) {
                    throw new Error(configResult?.message || TEXT.loadFailed);
                }

                this._config = {
                    api: deepClone(configResult.api || {}),
                    bot: deepClone(configResult.bot || {}),
                    logging: deepClone(configResult.logging || {}),
                    agent: deepClone(configResult.agent || {}),
                };
                this._configAudit = auditResult?.success ? auditResult : null;
                this._modelCatalog = catalogResult?.success ? catalogResult : { providers: [] };
                this._providersById = new Map((this._modelCatalog.providers || []).map((provider) => [provider.id, provider]));
                this._presetDrafts = deepClone(this._config.api.presets || []);
                this._activePreset = String(this._config.api.active_preset || '').trim();
                this._lastConfigVersion = Number(this._configAudit?.version || this.getState('bot.status.config_snapshot.version') || 0);

                this._fillForm();
                this._renderPresetList();
                this._renderHero();
                this._renderUpdatePanel();
                this._renderExportRagStatus();
                if (!preserveFeedback) {
                    this._hideSaveFeedback();
                }
                this._loaded = true;
                if (!silent) {
                    toast.success('配置已刷新');
                }
            } catch (error) {
                console.error('[SettingsPage] load failed:', error);
                if (!silent) {
                    toast.error(toast.getErrorMessage(error, TEXT.loadFailed));
                }
                this._renderLoadError(toast.getErrorMessage(error, TEXT.loadFailed));
            } finally {
                this._loadingPromise = null;
            }
        })();

        return this._loadingPromise;
    }

    _initModuleSaveButtons() {
        this.$$('.settings-card').forEach((card) => {
            const meta = this._getCardConfigMeta(card);
            if (!meta) {
                return;
            }
            this._ensureCardSaveButton(card, meta);
        });
    }

    _getCardConfigMeta(card) {
        if (!card) {
            return null;
        }

        const ids = new Set(
            Array.from(card.querySelectorAll('[id]'))
                .map((element) => element.id)
                .filter((id) => FIELD_META_BY_ID.has(id))
        );
        const includeApiPresets = !!card.querySelector('#preset-list');
        const sections = new Set();
        ids.forEach((id) => {
            const meta = FIELD_META_BY_ID.get(id);
            if (meta?.section) {
                sections.add(meta.section);
            }
        });
        if (includeApiPresets) {
            sections.add('api');
        }
        if (!ids.size && !includeApiPresets) {
            return null;
        }

        return {
            title: card.querySelector('.settings-card-title')?.textContent?.trim() || '当前模块',
            ids,
            sections,
            includeApiPresets,
        };
    }

    _ensureCardSaveButton(card, meta) {
        if (card.querySelector('[data-card-save-button]')) {
            return;
        }

        let header = card.querySelector('.settings-card-header');
        const title = card.querySelector('.settings-card-title');
        if (!header && title) {
            header = createElement('div', 'settings-card-header');
            card.insertBefore(header, title);
            title.style.marginBottom = '0';
            header.appendChild(title);
        }
        if (!header) {
            return;
        }

        let actions = header.querySelector('.settings-card-header-actions');
        if (!actions) {
            actions = createElement('div', 'settings-card-header-actions');
            header.appendChild(actions);
        }

        const button = createElement('button', 'btn btn-primary btn-sm', '保存本模块');
        button.type = 'button';
        button.dataset.cardSaveButton = 'true';
        button.dataset.cardTitle = meta.title;
        button.addEventListener('click', () => {
            void this._saveSettings({ scope: meta, triggerButton: button });
        });
        actions.appendChild(button);
    }

    _initScrollControls() {
        this._mainContent = document.querySelector('.main-content');
        this._scrollTopButton = this.$('#btn-settings-scroll-top');
        if (!this._mainContent) {
            return;
        }

        const onScroll = () => this._handleMainScroll();
        this._mainContent.addEventListener('scroll', onScroll);
        this._eventCleanups.push(() => {
            this._mainContent?.removeEventListener('scroll', onScroll);
        });
    }

    _handleMainScroll() {
        if (!this._mainContent || !this._scrollTopButton) {
            return;
        }
        const visible = this.isActive() && this._mainContent.scrollTop > 240;
        this._scrollTopButton.classList.toggle('visible', visible);
    }

    _scrollToTop() {
        this._mainContent?.scrollTo({ top: 0, behavior: 'smooth' });
    }

    _maybeRefreshForRuntimeConfigChange() {
        if (!this.isActive() || this._loadingPromise || this._isSaving) {
            return;
        }

        const runtimeVersion = Number(this.getState('bot.status.config_snapshot.version') || 0);
        if (!runtimeVersion || runtimeVersion <= this._lastConfigVersion) {
            return;
        }

        this._lastConfigVersion = runtimeVersion;
        void this.loadSettings({ silent: true, preserveFeedback: true });
    }

    _setButtonLabel(button, label) {
        if (!button) {
            return;
        }
        const textNode = button.querySelector('span');
        if (textNode) {
            textNode.textContent = label;
            return;
        }
        button.textContent = label;
    }

    _setSavingState(isSaving, triggerButton = null) {
        this._isSaving = isSaving;
        const buttons = [this.$('#btn-save-settings'), ...this.$$('[data-card-save-button]')].filter(Boolean);
        buttons.forEach((button) => {
            if (!button.dataset.originalLabel) {
                button.dataset.originalLabel = button.querySelector('span')?.textContent || button.textContent || '保存';
            }
            button.disabled = isSaving;
            if (button === triggerButton) {
                button.classList.toggle('is-loading', isSaving);
                this._setButtonLabel(button, isSaving ? '保存中...' : button.dataset.originalLabel);
            } else if (!isSaving) {
                button.classList.remove('is-loading');
                this._setButtonLabel(button, button.dataset.originalLabel);
            }
        });
    }

    _renderLoadError(message) {
        const hero = this.$('#current-config-hero');
        if (hero) {
            hero.innerHTML = `<div class="config-hero-card"><div class="hero-content"><div class="hero-title"><span class="hero-name">${message}</span></div></div></div>`;
        }
    }

    _fillForm(scope = null) {
        const includeIds = scope?.ids instanceof Set ? scope.ids : null;
        const includeSections = scope?.sections instanceof Set ? scope.sections : null;

        FIELD_DEFS.forEach(([id, section, path, type, options = {}]) => {
            if ((includeSections && !includeSections.has(section)) || (includeIds && !includeIds.has(id))) {
                return;
            }
            const element = this.$(`#${id}`);
            if (!element) {
                return;
            }
            const value = getPathValue(this._config[section] || {}, path);
            if (type === 'checkbox') {
                element.checked = !!value;
            } else if (type === 'number') {
                element.value = value === null || value === undefined ? '' : String(value);
                if (options.nullable && (value === null || value === undefined)) {
                    element.placeholder = '留空';
                }
            } else {
                element.value = value ?? '';
            }
        });

        LIST_FIELD_DEFS.forEach(([id, section, path]) => {
            if ((includeSections && !includeSections.has(section)) || (includeIds && !includeIds.has(id))) {
                return;
            }
            const element = this.$(`#${id}`);
            if (element) {
                element.value = listToMultiline(getPathValue(this._config[section] || {}, path));
            }
        });

        MAP_FIELD_DEFS.forEach(([id, section, path, separator]) => {
            if ((includeSections && !includeSections.has(section)) || (includeIds && !includeIds.has(id))) {
                return;
            }
            const element = this.$(`#${id}`);
            if (element) {
                element.value = mapToMultiline(getPathValue(this._config[section] || {}, path), separator);
            }
        });

        RANGE_FIELD_DEFS.forEach(([minId, maxId, section, path]) => {
            if ((includeSections && !includeSections.has(section)) || (includeIds && !includeIds.has(minId) && !includeIds.has(maxId))) {
                return;
            }
            const range = getPathValue(this._config[section] || {}, path);
            const [minValue, maxValue] = Array.isArray(range) ? range : ['', ''];
            if (this.$(`#${minId}`)) {
                this.$(`#${minId}`).value = minValue ?? '';
            }
            if (this.$(`#${maxId}`)) {
                this.$(`#${maxId}`).value = maxValue ?? '';
            }
        });

        const langsmithStatus = document.getElementById('agent-langsmith-key-status');
        if (langsmithStatus) {
            langsmithStatus.value = this._config.agent?.langsmith_api_key_configured ? '已配置（已隐藏）' : '未配置';
        }
    }

    _collectPayload(scope = null) {
        const includeIds = scope?.ids instanceof Set ? scope.ids : null;
        const includeSections = scope?.sections instanceof Set ? scope.sections : null;
        const includeApiPresets = !scope || !!scope.includeApiPresets;
        const payload = {};

        FIELD_DEFS.forEach(([id, section, path, type, options = {}]) => {
            const element = this.$(`#${id}`);
            if (!element) {
                return;
            }
            let value;
            if (type === 'checkbox') {
                value = !!element.checked;
            } else if (type === 'number') {
                const raw = String(element.value || '').trim();
                if (!raw && options.nullable) {
                    value = null;
                } else if (!raw) {
                    return;
                } else {
                    value = Number(raw);
                    if (!Number.isFinite(value)) {
                        return;
                    }
                }
            } else {
                value = element.value;
            }
            if (!payload[section]) {
                payload[section] = {};
            }
            setPathValue(payload[section], path, value);
        });

        LIST_FIELD_DEFS.forEach(([id, section, path]) => {
            if ((includeSections && !includeSections.has(section)) || (includeIds && !includeIds.has(id))) {
                return;
            }
            const element = this.$(`#${id}`);
            if (element) {
                if (!payload[section]) {
                    payload[section] = {};
                }
                setPathValue(payload[section], path, normalizeListText(element.value));
            }
        });

        MAP_FIELD_DEFS.forEach(([id, section, path, separator]) => {
            if ((includeSections && !includeSections.has(section)) || (includeIds && !includeIds.has(id))) {
                return;
            }
            const element = this.$(`#${id}`);
            if (element) {
                if (!payload[section]) {
                    payload[section] = {};
                }
                setPathValue(payload[section], path, multilineToMap(element.value, separator));
            }
        });

        RANGE_FIELD_DEFS.forEach(([minId, maxId, section, path]) => {
            if ((includeSections && !includeSections.has(section)) || (includeIds && !includeIds.has(minId) && !includeIds.has(maxId))) {
                return;
            }
            if (!payload[section]) {
                payload[section] = {};
            }
            setPathValue(payload[section], path, [Number(this.$(`#${minId}`)?.value || 0), Number(this.$(`#${maxId}`)?.value || 0)]);
        });

        if (includeApiPresets) {
            payload.api = {
                ...(payload.api || {}),
                active_preset: this._activePreset,
                presets: deepClone(this._presetDrafts),
            };
        }

        return pruneEmptySections(payload);
    }

    async _saveSettings(options = {}) {
        const { scope = null, triggerButton = null } = options;
        try {
            const payload = this._collectPayload(scope);
            if (payload.api && !this._presetDrafts.length) {
                throw new Error(TEXT.presetMissing);
            }
            if (!Object.keys(payload).length) {
                toast.info('当前模块没有可保存的配置项');
                return;
            }
            this._setSavingState(true, triggerButton);
            const result = await apiService.saveConfig(payload);
            if (!result?.success) {
                throw new Error(result?.message || TEXT.saveFailed);
            }

            await this.loadSettings({ silent: true, preserveFeedback: true });
            this._renderHero(true);
            this._renderSaveFeedback(result);
            this._renderExportRagStatus();
            this._setSavingState(false, triggerButton);
            toast.success(result?.runtime_apply?.message || '配置已保存');
        } catch (error) {
            console.error('[SettingsPage] save failed:', error);
            this._renderSaveFeedback({ success: false, message: toast.getErrorMessage(error, TEXT.saveFailed) });
            this._setSavingState(false, triggerButton);
            toast.error(toast.getErrorMessage(error, TEXT.saveFailed));
        }
    }

    async _previewPrompt() {
        try {
            const result = await apiService.previewPrompt({
                bot: this._collectPayload().bot,
                sample: {
                    chat_name: this.$('#setting-preview-chat-name')?.value || '',
                    sender: this.$('#setting-preview-sender')?.value || '',
                    relationship: this.$('#setting-preview-relationship')?.value || '',
                    emotion: this.$('#setting-preview-emotion')?.value || '',
                    message: this.$('#setting-preview-message')?.value || '',
                    is_group: !!this.$('#setting-preview-is-group')?.checked,
                },
            });
            if (!result?.success) {
                throw new Error(result?.message || TEXT.previewFailed);
            }
            if (this.$('#settings-preview-summary')) {
                const info = result.summary || {};
                this.$('#settings-preview-summary').dataset.state = 'success';
                this.$('#settings-preview-summary').textContent = `生成成功 · ${info.lines || 0} 行 / ${info.chars || 0} 字符`;
            }
            if (this.$('#settings-prompt-preview')) {
                this.$('#settings-prompt-preview').textContent = String(result.prompt || '');
            }
        } catch (error) {
            console.error('[SettingsPage] preview failed:', error);
            if (this.$('#settings-preview-summary')) {
                this.$('#settings-preview-summary').dataset.state = 'error';
                this.$('#settings-preview-summary').textContent = toast.getErrorMessage(error, TEXT.previewFailed);
            }
            if (this.$('#settings-prompt-preview')) {
                this.$('#settings-prompt-preview').textContent = '';
            }
            toast.error(toast.getErrorMessage(error, TEXT.previewFailed));
        }
    }

    async _checkUpdates() {
        try {
            if (!window.electronAPI?.checkForUpdates) {
                throw new Error('当前环境不支持更新检查');
            }
            const result = await window.electronAPI.checkForUpdates({ source: 'settings-page' });
            if (!result?.success && result?.error) {
                throw new Error(result.error);
            }
            this._renderUpdatePanel();
            toast.success(result?.updateAvailable ? '已发现新版本' : '当前已经是最新版本');
        } catch (error) {
            console.error('[SettingsPage] check updates failed:', error);
            toast.error(toast.getErrorMessage(error, TEXT.updateFailed));
        }
    }

    async _openUpdateDownload() {
        if (!window.electronAPI?.openUpdateDownload) {
            toast.warning('当前环境不支持打开下载页');
            return;
        }
        const result = await window.electronAPI.openUpdateDownload();
        if (!result?.success) {
            toast.warning(result?.error || '未找到更新下载地址');
        }
    }

    async _resetCloseBehavior() {
        try {
            if (!window.electronAPI?.resetCloseBehavior) {
                throw new Error('当前环境不支持重置关闭行为');
            }
            await window.electronAPI.resetCloseBehavior();
            toast.success(TEXT.resetCloseSuccess);
        } catch (error) {
            toast.error(toast.getErrorMessage(error, '重置关闭行为失败'));
        }
    }

    _renderHero(highlight = false) {
        const container = this.$('#current-config-hero');
        if (!container || !this._config) {
            return;
        }

        const activePreset = this._presetDrafts.find((preset) => preset.name === this._activePreset);
        const runtimePreset = this.getState('bot.status.runtime_preset') || '--';
        const audit = this._configAudit?.audit || null;
        const unknownCount = audit?.unknown_override_paths?.length || 0;
        const dormantCount = audit?.dormant_paths?.length || 0;
        const configuredPresets = this._presetDrafts.filter((preset) => preset.api_key_configured || preset.api_key_required === false).length;

        container.textContent = '';
        const card = createElement('div', `config-hero-card${highlight ? ' highlight-pulse' : ''}`);
        const content = createElement('div', 'hero-content');
        const title = createElement('div', 'hero-title');
        title.appendChild(createElement('span', 'hero-name', this._activePreset || '未设置激活预设'));
        content.appendChild(title);
        content.appendChild(createElement('div', 'detail-value', activePreset ? `${activePreset.alias || activePreset.provider_id || 'provider'} · ${activePreset.model || '--'}` : '请选择一个可用预设并保存'));

        const details = createElement('div', 'hero-details');
        details.appendChild(this._createHeroDetail('当前运行预设', String(runtimePreset || '--')));
        details.appendChild(this._createHeroDetail('已配置预设', `${configuredPresets}/${this._presetDrafts.length}`));
        details.appendChild(this._createHeroDetail('审计版本', String(this._configAudit?.version || '--')));
        details.appendChild(this._createHeroDetail('最后加载', formatDateTime(this._configAudit?.loaded_at)));
        content.appendChild(details);

        const extra = createElement('div', 'hero-details');
        extra.appendChild(this._createHeroDetail('未知覆写', `${unknownCount} 项`));
        extra.appendChild(this._createHeroDetail('未消费配置', `${dormantCount} 项`));
        extra.appendChild(this._createHeroDetail('LangSmith', this._config.agent?.langsmith_api_key_configured ? '已配置 Key' : '未配置 Key'));

        card.appendChild(content);
        card.appendChild(extra);
        container.appendChild(card);
    }

    _createHeroDetail(label, value) {
        const wrap = createElement('div', 'detail-item');
        wrap.appendChild(createElement('span', 'detail-label', label));
        wrap.appendChild(createElement('span', 'detail-value', value));
        return wrap;
    }

    _renderPresetList() {
        const list = this.$('#preset-list');
        if (!list) {
            return;
        }
        list.textContent = '';

        if (!this._presetDrafts.length) {
            list.appendChild(createElement('div', 'empty-state-text', '暂无预设，点击“新增”创建一个。'));
            return;
        }

        const fragment = document.createDocumentFragment();
        this._presetDrafts.forEach((preset, index) => {
            const provider = this._providersById.get(preset.provider_id) || null;
            const card = createElement('div', `preset-card${preset.name === this._activePreset ? ' active' : ''}`);
            const header = createElement('div', 'preset-card-header');
            const info = createElement('div', 'preset-info');
            const name = createElement('div', 'preset-name');
            name.appendChild(document.createTextNode(preset.name || '未命名预设'));
            if (preset.name === this._activePreset) {
                name.appendChild(createElement('span', 'config-save-feedback-badge live', '当前激活'));
            }
            info.appendChild(name);

            const meta = createElement('div', 'preset-meta');
            meta.appendChild(createElement('span', 'meta-item', provider?.label || preset.provider_id || '--'));
            meta.appendChild(createElement('span', 'meta-separator', '·'));
            meta.appendChild(createElement('span', 'meta-item model-name', preset.model || '--'));
            info.appendChild(meta);

            const detail = createElement('div', 'ping-result', preset.api_key_required === false ? '无需 API Key' : (preset.api_key_configured ? '已配置 API Key' : '未配置 API Key'));
            info.appendChild(detail);
            header.appendChild(info);
            card.appendChild(header);

            const actions = createElement('div', 'preset-card-actions');
            const useButton = createElement('button', 'btn btn-secondary btn-sm', preset.name === this._activePreset ? '已启用' : '设为当前');
            useButton.type = 'button';
            useButton.disabled = preset.name === this._activePreset;
            useButton.addEventListener('click', () => {
                this._activePreset = preset.name;
                this._renderPresetList();
                this._renderHero();
            });

            const testButton = createElement('button', 'btn btn-secondary btn-sm', '测试');
            testButton.type = 'button';
            testButton.addEventListener('click', () => void this._testPreset(index, detail));

            const editButton = createElement('button', 'btn btn-primary btn-sm', '编辑');
            editButton.type = 'button';
            editButton.addEventListener('click', () => this._openPresetModal(index));

            actions.appendChild(useButton);
            actions.appendChild(testButton);
            actions.appendChild(editButton);
            if (this._presetDrafts.length > 1) {
                const deleteButton = createElement('button', 'btn btn-secondary btn-sm', '删除');
                deleteButton.type = 'button';
                deleteButton.addEventListener('click', () => this._removePreset(index));
                actions.appendChild(deleteButton);
            }
            card.appendChild(actions);
            fragment.appendChild(card);
        });

        list.appendChild(fragment);
    }

    async _testPreset(index, detailElement) {
        const preset = this._presetDrafts[index];
        if (!preset?.name) {
            return;
        }
        try {
            if (detailElement) {
                detailElement.className = 'ping-result pending';
                detailElement.textContent = '连接测试中...';
            }
            const result = await apiService.testConnection(preset.name);
            if (!result?.success) {
                throw new Error(result?.message || '测试失败');
            }
            if (detailElement) {
                detailElement.className = 'ping-result success';
                detailElement.textContent = result.message || '连接成功';
            }
            toast.success(`${preset.name} 连接测试成功`);
        } catch (error) {
            if (detailElement) {
                detailElement.className = 'ping-result error';
                detailElement.textContent = toast.getErrorMessage(error, '连接测试失败');
            }
            toast.error(`${preset.name}：${toast.getErrorMessage(error, '连接测试失败')}`);
        }
    }

    _removePreset(index) {
        const preset = this._presetDrafts[index];
        this._presetDrafts.splice(index, 1);
        if (preset?.name === this._activePreset) {
            this._activePreset = this._presetDrafts[0]?.name || '';
        }
        this._renderPresetList();
        this._renderHero();
        toast.info('预设已从草稿中移除，记得点击“保存配置”生效');
    }

    _openPresetModal(index = -1) {
        const modal = document.getElementById('preset-modal');
        if (!modal) {
            return;
        }
        this._selectedPresetIndex = index;
        const preset = index >= 0 ? deepClone(this._presetDrafts[index]) : this._createDefaultPreset();
        this._populateProviderOptions(preset.provider_id);
        this._fillPresetModal(preset);
        modal.classList.add('active');
    }

    _closePresetModal() {
        document.getElementById('preset-modal')?.classList.remove('active');
        this._selectedPresetIndex = -1;
    }

    _createDefaultPreset() {
        const firstProvider = this._modelCatalog?.providers?.[0] || { id: '', default_model: '' };
        return { name: '', provider_id: firstProvider.id || '', alias: '', base_url: firstProvider.base_url || '', api_key: '', model: firstProvider.default_model || '', embedding_model: '', allow_empty_key: !!firstProvider.allow_empty_key, timeout_sec: 10, max_retries: 2, temperature: 0.6, max_tokens: 512 };
    }

    _populateProviderOptions(selectedId) {
        const select = this.$('#edit-preset-provider');
        if (!select) {
            return;
        }
        select.textContent = '';
        const placeholder = document.createElement('option');
        placeholder.value = '';
        placeholder.textContent = '-- 选择服务商 --';
        select.appendChild(placeholder);
        (this._modelCatalog?.providers || []).forEach((provider) => {
            const option = document.createElement('option');
            option.value = provider.id;
            option.textContent = provider.label;
            select.appendChild(option);
        });
        select.value = selectedId || '';
    }

    _fillPresetModal(preset) {
        if (this.$('#edit-preset-original-name')) this.$('#edit-preset-original-name').value = this._selectedPresetIndex >= 0 ? String(preset.name || '') : '';
        if (this.$('#edit-preset-name')) this.$('#edit-preset-name').value = preset.name || '';
        if (this.$('#edit-preset-provider')) this.$('#edit-preset-provider').value = preset.provider_id || '';
        if (this.$('#edit-preset-alias')) this.$('#edit-preset-alias').value = preset.alias || '';
        if (this.$('#edit-preset-embedding-model')) this.$('#edit-preset-embedding-model').value = preset.embedding_model || '';
        if (this.$('#edit-preset-key')) {
            this.$('#edit-preset-key').type = 'password';
            this.$('#edit-preset-key').value = '';
            this.$('#edit-preset-key').placeholder = preset.api_key_configured ? '已配置，留空则保持不变' : '输入 API Key';
        }
        this._updatePresetHelpLink(preset.provider_id);
        void this._populateModelOptions(preset.provider_id, preset.model);
    }

    async _handlePresetProviderChange() {
        const providerId = this.$('#edit-preset-provider')?.value || '';
        const provider = this._providersById.get(providerId) || {};
        this._updatePresetHelpLink(providerId);
        await this._populateModelOptions(providerId, provider.default_model || '');
    }

    async _populateModelOptions(providerId, selectedModel) {
        const select = this.$('#edit-preset-model-select');
        if (!select) {
            return;
        }
        const provider = this._providersById.get(providerId) || null;
        let models = Array.isArray(provider?.models) ? [...provider.models] : [];
        select.textContent = '';
        [['', '-- 选择模型 --'], ...models.map((item) => [item, item]), ['__custom__', '自定义模型']].forEach(([value, label]) => {
            const option = document.createElement('option');
            option.value = value;
            option.textContent = label;
            select.appendChild(option);
        });
        select.value = selectedModel && models.includes(selectedModel) ? selectedModel : (selectedModel ? '__custom__' : '');
        if (this.$('#edit-preset-model-custom')) {
            this.$('#edit-preset-model-custom').value = !models.includes(selectedModel) ? (selectedModel || '') : '';
        }
        this._syncPresetModelInput();
    }

    _syncPresetModelInput() {
        const select = this.$('#edit-preset-model-select');
        const customInput = this.$('#edit-preset-model-custom');
        if (!select || !customInput) {
            return;
        }
        customInput.style.display = select.value === '__custom__' ? 'block' : 'none';
        if (select.value !== '__custom__') {
            customInput.value = '';
        }
    }

    _updatePresetHelpLink(providerId) {
        const provider = this._providersById.get(providerId) || null;
        const help = document.getElementById('api-key-help');
        const link = document.getElementById('api-key-help-link');
        if (!help || !link || !provider?.api_key_url) {
            if (help) help.style.display = 'none';
            return;
        }
        help.style.display = 'block';
        link.href = provider.api_key_url;
        link.onclick = async (event) => {
            event.preventDefault();
            if (window.electronAPI?.openExternal) {
                await window.electronAPI.openExternal(provider.api_key_url);
            } else {
                window.open(provider.api_key_url, '_blank', 'noopener,noreferrer');
            }
        };
    }

    _togglePresetKeyVisibility() {
        if (this.$('#edit-preset-key')) {
            this.$('#edit-preset-key').type = this.$('#edit-preset-key').type === 'password' ? 'text' : 'password';
        }
    }

    _commitPresetModal() {
        const name = String(this.$('#edit-preset-name')?.value || '').trim();
        const providerId = String(this.$('#edit-preset-provider')?.value || '').trim();
        const alias = String(this.$('#edit-preset-alias')?.value || '').trim();
        const embeddingModel = String(this.$('#edit-preset-embedding-model')?.value || '').trim();
        const key = String(this.$('#edit-preset-key')?.value || '').trim();
        const originalName = String(this.$('#edit-preset-original-name')?.value || '').trim();
        const selectValue = this.$('#edit-preset-model-select')?.value || '';
        const customModel = String(this.$('#edit-preset-model-custom')?.value || '').trim();
        const model = (selectValue === '__custom__' ? customModel : selectValue).trim();
        if (!name) {
            toast.error(TEXT.presetNameMissing);
            return;
        }
        if (!model) {
            toast.error(TEXT.presetModelMissing);
            return;
        }
        const provider = this._providersById.get(providerId) || {};
        const existing = this._selectedPresetIndex >= 0 ? deepClone(this._presetDrafts[this._selectedPresetIndex]) : this._createDefaultPreset();
        if (this._selectedPresetIndex >= 0 && originalName && originalName !== name && existing.api_key_configured && !key) {
            toast.error('重命名已配置 Key 的预设时，请重新填写 API Key');
            return;
        }
        const nextPreset = { ...existing, name, provider_id: providerId, alias, base_url: provider.base_url || '', model, embedding_model: embeddingModel, allow_empty_key: !!provider.allow_empty_key };
        if (key) {
            nextPreset.api_key = key;
        } else if (existing.api_key_configured) {
            nextPreset._keep_key = true;
        }
        if (this._selectedPresetIndex >= 0) this._presetDrafts[this._selectedPresetIndex] = nextPreset;
        else this._presetDrafts.push(nextPreset);
        if (!this._activePreset || originalName === this._activePreset) this._activePreset = name;
        this._renderPresetList();
        this._renderHero();
        this._closePresetModal();
        toast.success(TEXT.presetSaveSuccess);
    }

    _renderUpdatePanel() {
        const statusText = this.$('#update-status-text');
        const statusMeta = this.$('#update-status-meta');
        const downloadButton = this.$('#btn-open-update-download');
        if (!statusText || !statusMeta || !downloadButton) {
            return;
        }
        const enabled = !!this.getState('updater.enabled');
        const checking = !!this.getState('updater.checking');
        const available = !!this.getState('updater.available');
        const currentVersion = this.getState('updater.currentVersion') || '--';
        const latestVersion = this.getState('updater.latestVersion') || '';
        const lastCheckedAt = this.getState('updater.lastCheckedAt');
        const releaseDate = this.getState('updater.releaseDate');
        const error = this.getState('updater.error');

        if (!enabled) {
            statusText.textContent = '当前环境未启用更新检查';
            statusMeta.textContent = `当前版本：v${currentVersion}`;
            downloadButton.style.display = 'none';
        } else if (checking) {
            statusText.textContent = '正在检查更新...';
            statusMeta.textContent = `当前版本：v${currentVersion}`;
            downloadButton.style.display = 'none';
        } else if (error) {
            statusText.textContent = error;
            statusMeta.textContent = `当前版本：v${currentVersion} · 最近检查：${formatDateTime(lastCheckedAt)}`;
            downloadButton.style.display = available ? 'inline-flex' : 'none';
        } else if (available && latestVersion) {
            statusText.textContent = `发现新版本 v${latestVersion}`;
            statusMeta.textContent = `当前版本：v${currentVersion} · 发布日期：${formatDateTime(releaseDate)} · 最近检查：${formatDateTime(lastCheckedAt)}`;
            downloadButton.style.display = 'inline-flex';
        } else {
            statusText.textContent = '当前已经是最新版本';
            statusMeta.textContent = `当前版本：v${currentVersion} · 最近检查：${formatDateTime(lastCheckedAt)}`;
            downloadButton.style.display = 'none';
        }
    }

    _renderSaveFeedback(result) {
        const container = this.$('#config-save-feedback');
        const summary = this.$('#config-save-feedback-summary');
        const meta = this.$('#config-save-feedback-meta');
        const groups = this.$('#config-save-feedback-groups');
        if (!container || !summary || !meta || !groups) {
            return;
        }
        container.hidden = false;
        groups.textContent = '';

        if (!result?.success) {
            container.dataset.state = 'error';
            summary.textContent = result?.message || TEXT.saveFailed;
            meta.textContent = '本次保存未写入配置，请先修正问题后重试。';
            return;
        }

        const changedPaths = Array.isArray(result.changed_paths) ? result.changed_paths : [];
        const runtimeApply = result.runtime_apply;
        const reloadPlan = Array.isArray(result.reload_plan) ? result.reload_plan : [];
        const defaultConfigSync = result.default_config_synced
            ? (result.default_config_sync_message || '默认配置文件已同步更新')
            : '默认配置文件：未同步';
        container.dataset.state = changedPaths.length > 0 ? 'warning' : 'success';
        summary.textContent = changedPaths.length > 0 ? '配置已保存' : '未检测到有效配置变更';
        meta.textContent = [
            `变更项：${changedPaths.length} 个`,
            runtimeApply?.message ? `运行时反馈：${runtimeApply.message}` : '运行时反馈：无',
            defaultConfigSync,
        ].join(' · ');

        reloadPlan.forEach((item) => {
            const block = createElement('div', 'config-save-feedback-item');
            const top = createElement('div', 'config-save-feedback-item-top');
            top.appendChild(createElement('div', 'config-save-feedback-item-title', item.component || 'unknown'));
            top.appendChild(createElement('span', `config-save-feedback-badge ${item.mode || 'unknown'}`, item.mode || 'unknown'));
            block.appendChild(top);
            block.appendChild(createElement('div', 'config-save-feedback-item-note', item.note || ''));
            block.appendChild(createElement('div', 'config-save-feedback-item-paths', (item.paths || []).join(', ')));
            groups.appendChild(block);
        });
    }

    _hideSaveFeedback() {
        if (this.$('#config-save-feedback')) {
            this.$('#config-save-feedback').hidden = true;
        }
    }

    _renderExportRagStatus() {
        const status = this.$('#export-rag-status');
        if (!status || !this._config) {
            return;
        }
        status.textContent = this._config.bot?.rag_enabled
            ? `状态：运行期向量记忆已开启${this._config.bot?.export_rag_enabled ? '，导出聊天记录 RAG 已开启' : ''}`
            : '状态：向量记忆总开关已关闭，运行期 RAG 和导出 RAG 都不会执行召回';
    }
}

export default SettingsPage;
