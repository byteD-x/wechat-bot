import test from 'node:test';
import assert from 'node:assert/strict';

import {
    checkUpdates,
    openUpdateDownload,
    previewPrompt,
    resetCloseBehavior,
    saveSettings,
} from '../../src/renderer/js/pages/settings/action-controller.js';
import { renderSettingsPageShell } from '../../src/renderer/js/app-shell/pages/settings.js';
import {
    bindSettingsAutoSave,
    bindSettingsEvents,
} from '../../src/renderer/js/pages/settings/page-shell.js';
import { renderBackupPanel } from '../../src/renderer/js/pages/settings/backup-panel.js';
import { renderSettingsHero } from '../../src/renderer/js/pages/settings/hero-renderer.js';
import {
    buildModelSummaryView,
    loadSettings,
    scheduleAutoSave,
    shouldRefreshAudit,
    watchConfigChanges,
} from '../../src/renderer/js/pages/settings/runtime-sync.js';
import {
    EMAIL_VISIBILITY_STORAGE_KEY,
    maskEmailAddress,
} from '../../src/renderer/js/pages/model-auth-display.js';
import {
    commitPresetModal,
    openPresetModal,
} from '../../src/renderer/js/pages/settings/preset-controller.js';
import SettingsPage from '../../src/renderer/js/pages/SettingsPage.js';
import ModelsPage, {
    getActionWorkflowKind,
    getLocalizedActionLabel,
    groupAuthStates,
    parseCallbackPayload,
    resolveCardViewMode,
    sortCardsForDisplay,
    summarizeCards,
} from '../../src/renderer/js/pages/ModelsPage.js';
import { Events } from '../../src/renderer/js/core/EventBus.js';
import { apiService } from '../../src/renderer/js/services/ApiService.js';
import { toast } from '../../src/renderer/js/services/NotificationService.js';
import { installDomStub } from './dom-stub.mjs';

async function withDom(run) {
    const env = installDomStub();
    const previousWindow = globalThis.window;
    const previousSetTimeout = globalThis.setTimeout;
    const previousClearTimeout = globalThis.clearTimeout;
    globalThis.window = {
        electronAPI: {},
        open: () => {},
        setTimeout: globalThis.setTimeout,
        clearTimeout: globalThis.clearTimeout,
    };
    try {
        await run(env);
    } finally {
        if (previousWindow === undefined) {
            delete globalThis.window;
        } else {
            globalThis.window = previousWindow;
        }
        globalThis.setTimeout = previousSetTimeout;
        globalThis.clearTimeout = previousClearTimeout;
        env.restore();
    }
}

async function withMockStorage(initialState, run) {
    const previousLocalStorage = globalThis.localStorage;
    const state = new Map(Object.entries(initialState || {}));
    globalThis.localStorage = {
        getItem(key) {
            return state.has(String(key)) ? state.get(String(key)) : null;
        },
        setItem(key, value) {
            state.set(String(key), String(value));
        },
        removeItem(key) {
            state.delete(String(key));
        },
        clear() {
            state.clear();
        },
    };
    try {
        await run({ state });
    } finally {
        if (previousLocalStorage === undefined) {
            delete globalThis.localStorage;
        } else {
            globalThis.localStorage = previousLocalStorage;
        }
    }
}

test('runtime-sync loadSettings refreshes page state and schedules audit when needed', async () => {
    const originalGetConfig = apiService.getConfig;
    try {
        apiService.getConfig = async () => ({
            success: true,
            api: {
                active_preset: 'default',
                presets: [{ name: 'default', provider_id: 'openai', model: 'gpt-4.1' }],
            },
            bot: { rag_enabled: true },
            logging: {},
            agent: {},
            services: {},
            modelCatalog: {
                providers: [
                    {
                        id: 'openai',
                        label: 'OpenAI',
                        base_url: 'https://api.openai.com/v1',
                        default_model: 'gpt-4.1',
                    },
                    {
                        id: 'qwen',
                        label: 'Qwen',
                        base_url: 'https://coding.dashscope.aliyuncs.com/v1',
                        default_model: 'qwen3-coder-next',
                    },
                ],
            },
        });

        await withDom(async () => {
            const calls = [];
            const page = {
                _config: null,
                _modelCatalog: null,
                _providersById: new Map(),
                _configAudit: null,
                _loaded: false,
                _loadingPromise: null,
                _auditPromise: null,
                _auditStatus: 'idle',
                _auditMessage: '',
                _lastConfigVersion: 0,
                _auditRequestId: 0,
                _shouldRefreshAudit() {
                    return shouldRefreshAudit(this);
                },
                getState(path) {
                    if (path === 'bot.connected') {
                        return true;
                    }
                    if (path === 'bot.status.config_snapshot.version') {
                        return 4;
                    }
                    return undefined;
                },
                $(selector) {
                    if (selector === '#current-config-hero') {
                        return { innerHTML: '' };
                    }
                    return null;
                },
                _fillForm() {
                    calls.push('fill');
                },
                _renderHero() {
                    calls.push('hero');
                },
                _renderExportRagStatus() {
                    calls.push('export-rag');
                },
                _hideSaveFeedback() {
                    calls.push('hide-feedback');
                },
                _renderLoadError(message) {
                    calls.push(`load-error:${message}`);
                },
                _loadConfigAudit(options) {
                    calls.push(`audit:${options.force ? 'forced' : 'normal'}`);
                },
            };

            await loadSettings(page, { silent: true }, {
                loading: 'loading',
                loadFailed: 'load failed',
                noAudit: 'no audit',
            });

            assert.equal(page._loaded, true);
            assert.equal(page._lastConfigVersion, 4);
            assert.equal(page._modelCatalog.providers.length, 2);
            assert.equal(page._providersById.get('qwen')?.default_model, 'qwen3-coder-next');
            assert.deepEqual(calls, [
                'fill',
                'hero',
                'export-rag',
                'hide-feedback',
                'audit:normal',
            ]);
        });
    } finally {
        apiService.getConfig = originalGetConfig;
    }
});

test('runtime-sync loadSettings schedules a silent refresh while local auth sync is still running', async () => {
    const originalGetConfig = apiService.getConfig;
    const originalSetTimeout = globalThis.setTimeout;
    const originalClearTimeout = globalThis.clearTimeout;
    const timers = [];
    const cleared = [];

    try {
        apiService.getConfig = async () => ({
            success: true,
            api: {
                active_preset: 'default',
                presets: [{ name: 'default', provider_id: 'openai', model: 'gpt-4.1' }],
            },
            bot: {},
            logging: {},
            agent: {},
            services: {},
            local_auth_sync: {
                refreshing: true,
                refreshed_at: 0,
                revision: 0,
                changed_provider_ids: [],
                message: '',
            },
            modelCatalog: { providers: [] },
        });
        globalThis.setTimeout = (callback, delay) => {
            const token = { callback, delay };
            timers.push(token);
            return token;
        };
        globalThis.clearTimeout = (token) => {
            cleared.push(token);
        };

        await withDom(async () => {
            let reloadOptions = null;
            const page = {
                _config: null,
                _modelCatalog: null,
                _providersById: new Map(),
                _configAudit: null,
                _loaded: false,
                _loadingPromise: null,
                _auditPromise: null,
                _auditStatus: 'idle',
                _auditMessage: '',
                _lastConfigVersion: 0,
                _auditRequestId: 0,
                _localAuthSyncState: null,
                _localAuthSyncRefreshTimer: null,
                _localAuthSyncRefreshAttempt: 0,
                _isSaving: false,
                isActive() {
                    return true;
                },
                _shouldRefreshAudit() {
                    return false;
                },
                getState() {
                    return 0;
                },
                $(selector) {
                    if (selector === '#current-config-hero') {
                        return { innerHTML: '' };
                    }
                    return null;
                },
                _fillForm() {},
                _renderHero() {},
                _renderExportRagStatus() {},
                _hideSaveFeedback() {},
                _renderLoadError() {},
                _loadConfigAudit() {},
                _renderUpdatePanel() {},
                _commitSettingsBaseline() {},
                _resetDirtyState() {},
                async loadSettings(options) {
                    reloadOptions = options;
                },
            };

            await loadSettings(page, { silent: true }, {
                loading: 'loading',
                loadFailed: 'load failed',
                noAudit: 'no audit',
            });

            assert.equal(page._localAuthSyncState.refreshing, true);
            assert.equal(page._localAuthSyncRefreshAttempt, 1);
            assert.equal(timers.length, 1);
            assert.equal(timers[0].delay, 600);

            timers[0].callback();
            await Promise.resolve();

            assert.deepEqual(reloadOptions, { silent: true, preserveFeedback: true });
            assert.deepEqual(cleared, []);
        });
    } finally {
        apiService.getConfig = originalGetConfig;
        globalThis.setTimeout = originalSetTimeout;
        globalThis.clearTimeout = originalClearTimeout;
    }
});

test('runtime-sync defers config reload while settings page is inactive', async () => {
    const previousWindow = globalThis.window;
    let changeHandler = null;

    globalThis.window = {
        electronAPI: {
            configSubscribe() {
                return Promise.resolve();
            },
            onConfigChanged(handler) {
                changeHandler = handler;
                return () => {};
            },
        },
        open: () => {},
        setTimeout: globalThis.setTimeout,
        clearTimeout: globalThis.clearTimeout,
    };

    try {
        let loadCalls = 0;
        const page = {
            _removeConfigListener: null,
            _isSaving: false,
            _pendingConfigReload: false,
            isActive() {
                return false;
            },
            async loadSettings() {
                loadCalls += 1;
            },
        };

        watchConfigChanges(page);
        changeHandler?.();

        assert.equal(page._pendingConfigReload, true);
        assert.equal(loadCalls, 0);
    } finally {
        if (previousWindow === undefined) {
            delete globalThis.window;
        } else {
            globalThis.window = previousWindow;
        }
    }
});

test('settings page onEnter reloads when a background config change is pending', async () => {
    const page = new SettingsPage();
    const calls = [];

    page._loaded = true;
    page._pendingConfigReload = true;
    page._handleMainScroll = () => {};
    page._loadWorkspaceBackups = async () => {
        calls.push('backups');
    };
    page.loadSettings = async (options) => {
        calls.push(options);
        page._pendingConfigReload = false;
    };
    page._renderHero = () => {
        calls.push('hero');
    };
    page.getState = () => 0;

    await page.onEnter();

    assert.deepEqual(calls, [
        { preserveFeedback: true },
        'backups',
    ]);
});

test('settings page onEnter reloads when local auth sync is still refreshing', async () => {
    const page = new SettingsPage();
    const calls = [];

    page._loaded = true;
    page._localAuthSyncState = { refreshing: true };
    page._handleMainScroll = () => {};
    page._loadWorkspaceBackups = async () => {
        calls.push('backups');
    };
    page.loadSettings = async (options) => {
        calls.push(options);
        page._localAuthSyncState = { refreshing: false };
    };
    page._renderHero = () => {
        calls.push('hero');
    };
    page.getState = () => 0;

    await page.onEnter();

    assert.deepEqual(calls, [
        { preserveFeedback: true },
        'backups',
    ]);
});

test('settings page clears pending local auth sync refresh when leaving', async () => {
    const originalClearTimeout = globalThis.clearTimeout;
    const cleared = [];
    globalThis.clearTimeout = (handle) => {
        cleared.push(handle);
    };

    try {
        const page = new SettingsPage();
        page._localAuthSyncRefreshTimer = 123;
        page._localAuthSyncRefreshAttempt = 2;

        await page.onLeave();

        assert.deepEqual(cleared, [123]);
        assert.equal(page._localAuthSyncRefreshTimer, null);
        assert.equal(page._localAuthSyncRefreshAttempt, 0);
        assert.equal(page.isActive(), false);
    } finally {
        globalThis.clearTimeout = originalClearTimeout;
    }
});

test('runtime-sync scheduleAutoSave debounces and preserves immediate path', () => {
    const originalSetTimeout = globalThis.setTimeout;
    const originalClearTimeout = globalThis.clearTimeout;
    const previousWindow = globalThis.window;
    const timers = [];
    globalThis.setTimeout = (callback, delay) => {
        const token = { callback, delay };
        timers.push(token);
        return token;
    };
    globalThis.clearTimeout = () => {};
    globalThis.window = {
        electronAPI: {},
        open: () => {},
        setTimeout: globalThis.setTimeout,
        clearTimeout: globalThis.clearTimeout,
    };

    try {
        const calls = [];
        const page = {
            _loaded: true,
            _autoSaveTimer: null,
            _saveSettings(options) {
                calls.push(options);
            },
            _renderSaveFeedback(result) {
                calls.push({ feedback: result.save_state });
            },
        };

        scheduleAutoSave(page);
        assert.equal(timers.length, 1);
        assert.deepEqual(calls, [{ feedback: 'saving' }]);
        timers[0].callback();
        assert.deepEqual(calls, [
            { feedback: 'saving' },
            { silentToast: true },
        ]);

        scheduleAutoSave(page, { immediate: true });
        assert.deepEqual(calls, [
            { feedback: 'saving' },
            { silentToast: true },
            { silentToast: true },
        ]);
        assert.equal(timers[0].delay, 700);
    } finally {
        globalThis.setTimeout = originalSetTimeout;
        globalThis.clearTimeout = originalClearTimeout;
        if (previousWindow === undefined) {
            delete globalThis.window;
        } else {
            globalThis.window = previousWindow;
        }
    }
});

test('backup panel renders backup summary, restore status and eval state', async () => withDom(async ({ document, registerElement }) => {
    const summary = registerElement('settings-backup-summary', document.createElement('div'));
    const evalSummary = registerElement('settings-eval-summary', document.createElement('div'));
    const select = registerElement('settings-backup-select', document.createElement('select'));
    const feedback = registerElement('settings-backup-restore-feedback', document.createElement('div'));
    const list = registerElement('settings-backup-list', document.createElement('div'));

    const page = {
        _backupState: {
            backups: [
                {
                    id: '20260325-quick',
                    mode: 'quick',
                    created_at: 1_700_000_000,
                    size_bytes: 4096,
                    included_files: ['app_config.json', 'chat_memory.db'],
                },
            ],
            summary: {
                latest_quick_backup_at: 1_700_000_000,
                latest_full_backup_at: 1_700_001_000,
                last_restore_result: {
                    success: true,
                    pre_restore_backup: { id: 'pre-restore-1' },
                },
            },
            latestEval: {
                summary: {
                    passed: true,
                    total_cases: 20,
                    retrieval_hit_rate: 0.5,
                },
            },
            restoreFeedback: '',
        },
        $(selector) {
            return document.getElementById(selector.slice(1));
        },
    };

    renderBackupPanel(page);

    assert.equal(summary.textContent.includes('最近快速备份'), true);
    assert.equal(evalSummary.textContent.includes('20'), true);
    assert.equal(select.children.length, 1);
    assert.equal(feedback.textContent.includes('保险备份'), true);
    assert.equal(list.textContent.includes('快速备份'), true);
    assert.equal(list.textContent.includes('20260325-quick'), true);
}));

test('preset-controller keeps modal flow and draft commit behavior stable', async () => withDom(async ({ document, registerElement }) => {
    const modal = document.createElement('div');
    modal.classList.add('modal');
    registerElement('preset-modal', modal);

    const providerSelect = document.createElement('select');
    const originalName = document.createElement('input');
    const nameInput = document.createElement('input');
    const aliasInput = document.createElement('input');
    const embeddingInput = document.createElement('input');
    const keyInput = document.createElement('input');
    const modelSelect = document.createElement('select');
    const modelCustom = document.createElement('input');
    const help = document.createElement('div');
    const helpLink = document.createElement('a');

    registerElement('edit-preset-provider', providerSelect);
    registerElement('edit-preset-original-name', originalName);
    registerElement('edit-preset-name', nameInput);
    registerElement('edit-preset-alias', aliasInput);
    registerElement('edit-preset-embedding-model', embeddingInput);
    registerElement('edit-preset-key', keyInput);
    registerElement('edit-preset-model-select', modelSelect);
    registerElement('edit-preset-model-custom', modelCustom);
    registerElement('api-key-help', help);
    registerElement('api-key-help-link', helpLink);

    const calls = [];
    globalThis.window.electronAPI = {
        openExternal: async () => {},
    };

    const page = {
        _selectedPresetIndex: -1,
        _activePreset: '',
        _presetDrafts: [],
        _providersById: new Map([
            ['openai', {
                id: 'openai',
                label: 'OpenAI',
                base_url: 'https://api.openai.com/v1',
                default_model: 'gpt-4.1',
                allow_empty_key: false,
                api_key_url: 'https://example.com/key',
            }],
        ]),
        _modelCatalog: {
            providers: [{
                id: 'openai',
                label: 'OpenAI',
                base_url: 'https://api.openai.com/v1',
                default_model: 'gpt-4.1',
            }],
        },
        $(selector) {
            return document.getElementById(selector.slice(1));
        },
        _renderPresetList() {
            calls.push('render-list');
        },
        _renderHero() {
            calls.push('render-hero');
        },
        _scheduleAutoSave(options) {
            calls.push(`autosave:${options.immediate}`);
        },
    };

    openPresetModal(page);
    assert.equal(modal.classList.contains('active'), true);
    assert.equal(providerSelect.value, 'openai');

    nameInput.value = 'work';
    aliasInput.value = 'Work';
    modelSelect.value = '__custom__';
    modelCustom.value = 'gpt-4.1';
    keyInput.value = 'secret';

    commitPresetModal(page, {
        presetNameMissing: 'preset name missing',
        presetModelMissing: 'preset model missing',
        presetSaveSuccess: 'preset saved',
    });
    await Promise.resolve();

    assert.equal(page._activePreset, 'work');
    assert.equal(page._presetDrafts.length, 1);
    assert.equal(page._presetDrafts[0].name, 'work');
    assert.equal(page._presetDrafts[0].alias, 'Work');
    assert.equal(page._presetDrafts[0].model, 'gpt-4.1');
    assert.equal(page._presetDrafts[0].api_key, 'secret');
    assert.equal(modal.classList.contains('active'), false);
    assert.deepEqual(calls, [
        'render-list',
        'render-hero',
        'autosave:true',
    ]);
}));

test('preset-controller upgrades legacy Kimi OAuth presets to coding runtime defaults', async () => withDom(async ({ document, registerElement }) => {
    const modal = document.createElement('div');
    modal.classList.add('modal');
    registerElement('preset-modal', modal);

    const providerSelect = document.createElement('select');
    const originalName = document.createElement('input');
    const nameInput = document.createElement('input');
    const aliasInput = document.createElement('input');
    const embeddingInput = document.createElement('input');
    const keyInput = document.createElement('input');
    const modelSelect = document.createElement('select');
    const modelCustom = document.createElement('input');
    const help = document.createElement('div');
    const helpLink = document.createElement('a');
    const authModeApiKey = document.createElement('input');
    const authModeOauth = document.createElement('input');
    const oauthProjectId = document.createElement('input');
    const oauthLocation = document.createElement('input');

    authModeApiKey.type = 'radio';
    authModeOauth.type = 'radio';

    registerElement('edit-preset-provider', providerSelect);
    registerElement('edit-preset-original-name', originalName);
    registerElement('edit-preset-name', nameInput);
    registerElement('edit-preset-alias', aliasInput);
    registerElement('edit-preset-embedding-model', embeddingInput);
    registerElement('edit-preset-key', keyInput);
    registerElement('edit-preset-model-select', modelSelect);
    registerElement('edit-preset-model-custom', modelCustom);
    registerElement('api-key-help', help);
    registerElement('api-key-help-link', helpLink);
    registerElement('edit-preset-auth-mode-api-key', authModeApiKey);
    registerElement('edit-preset-auth-mode-oauth', authModeOauth);
    registerElement('edit-preset-oauth-project-id', oauthProjectId);
    registerElement('edit-preset-oauth-location', oauthLocation);

    const page = {
        _selectedPresetIndex: -1,
        _activePreset: '',
        _presetDrafts: [],
        _providersById: new Map([
            ['kimi', {
                id: 'kimi',
                label: 'Kimi',
                base_url: 'https://api.moonshot.cn/v1',
                default_model: 'kimi-k2-turbo-preview',
                api_key_url: 'https://platform.moonshot.cn/console/api-keys',
                auth_methods: [
                    {
                        id: 'api_key',
                        type: 'api_key',
                        metadata: {
                            recommended_base_url: 'https://api.moonshot.cn/v1',
                            recommended_model: 'kimi-k2-turbo-preview',
                        },
                    },
                    {
                        id: 'kimi_code_oauth',
                        type: 'oauth',
                        provider_id: 'kimi_code_local',
                        metadata: {
                            recommended_base_url: 'https://api.kimi.com/coding/v1',
                            recommended_model: 'kimi-for-coding',
                        },
                    },
                ],
            }],
        ]),
        _modelCatalog: {
            providers: [{
                id: 'kimi',
                label: 'Kimi',
                base_url: 'https://api.moonshot.cn/v1',
                default_model: 'kimi-k2-turbo-preview',
                auth_methods: [
                    {
                        id: 'api_key',
                        type: 'api_key',
                        metadata: {
                            recommended_base_url: 'https://api.moonshot.cn/v1',
                            recommended_model: 'kimi-k2-turbo-preview',
                        },
                    },
                    {
                        id: 'kimi_code_oauth',
                        type: 'oauth',
                        provider_id: 'kimi_code_local',
                        metadata: {
                            recommended_base_url: 'https://api.kimi.com/coding/v1',
                            recommended_model: 'kimi-for-coding',
                        },
                    },
                ],
            }],
        },
        $(selector) {
            return document.getElementById(selector.slice(1));
        },
        _renderPresetList() {},
        _renderHero() {},
        _scheduleAutoSave() {},
    };

    openPresetModal(page);
    providerSelect.value = 'kimi';
    authModeApiKey.checked = false;
    authModeOauth.checked = true;
    nameInput.value = 'kimi-oauth';
    modelSelect.value = '__custom__';
    modelCustom.value = 'kimi-k2-turbo-preview';

    commitPresetModal(page, {
        presetNameMissing: 'preset name missing',
        presetModelMissing: 'preset model missing',
        presetSaveSuccess: 'preset saved',
    });
    await Promise.resolve();

    assert.equal(page._presetDrafts.length, 1);
    assert.equal(page._presetDrafts[0].auth_mode, 'oauth');
    assert.equal(page._presetDrafts[0].oauth_provider, 'kimi_code_local');
    assert.equal(page._presetDrafts[0].base_url, 'https://api.kimi.com/coding/v1');
    assert.equal(page._presetDrafts[0].model, 'kimi-for-coding');
}));

test('preset-controller infers qwen coding plan runtime from coder models in legacy api key presets', async () => withDom(async ({ document, registerElement }) => {
    const modal = document.createElement('div');
    modal.classList.add('modal');
    registerElement('preset-modal', modal);

    const providerSelect = document.createElement('select');
    const originalName = document.createElement('input');
    const nameInput = document.createElement('input');
    const aliasInput = document.createElement('input');
    const embeddingInput = document.createElement('input');
    const keyInput = document.createElement('input');
    const modelSelect = document.createElement('select');
    const modelCustom = document.createElement('input');
    const help = document.createElement('div');
    const helpLink = document.createElement('a');
    const authModeApiKey = document.createElement('input');
    const authModeOauth = document.createElement('input');

    authModeApiKey.type = 'radio';
    authModeOauth.type = 'radio';

    registerElement('edit-preset-provider', providerSelect);
    registerElement('edit-preset-original-name', originalName);
    registerElement('edit-preset-name', nameInput);
    registerElement('edit-preset-alias', aliasInput);
    registerElement('edit-preset-embedding-model', embeddingInput);
    registerElement('edit-preset-key', keyInput);
    registerElement('edit-preset-model-select', modelSelect);
    registerElement('edit-preset-model-custom', modelCustom);
    registerElement('api-key-help', help);
    registerElement('api-key-help-link', helpLink);
    registerElement('edit-preset-auth-mode-api-key', authModeApiKey);
    registerElement('edit-preset-auth-mode-oauth', authModeOauth);

    const qwenProvider = {
        id: 'qwen',
        label: 'Qwen',
        base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        default_model: 'qwen3.5-plus',
        api_key_url: 'https://dashscope.console.aliyun.com/apiKey',
        auth_methods: [
            {
                id: 'api_key',
                type: 'api_key',
                metadata: {
                    recommended_base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
                    recommended_model: 'qwen3.5-plus',
                },
            },
            {
                id: 'coding_plan_api_key',
                type: 'api_key',
                metadata: {
                    recommended_base_url: 'https://coding.dashscope.aliyuncs.com/v1',
                    recommended_model: 'qwen3-coder-next',
                },
            },
        ],
    };

    const page = {
        _selectedPresetIndex: -1,
        _activePreset: '',
        _presetDrafts: [],
        _providersById: new Map([['qwen', qwenProvider]]),
        _modelCatalog: {
            providers: [qwenProvider],
        },
        $(selector) {
            return document.getElementById(selector.slice(1));
        },
        _renderPresetList() {},
        _renderHero() {},
        _scheduleAutoSave() {},
    };

    openPresetModal(page);
    providerSelect.value = 'qwen';
    authModeApiKey.checked = true;
    authModeOauth.checked = false;
    nameInput.value = 'qwen-coder';
    modelSelect.value = '__custom__';
    modelCustom.value = 'qwen3-coder-next';

    commitPresetModal(page, {
        presetNameMissing: 'preset name missing',
        presetModelMissing: 'preset model missing',
        presetSaveSuccess: 'preset saved',
    });
    await Promise.resolve();

    assert.equal(page._presetDrafts.length, 1);
    assert.equal(page._presetDrafts[0].auth_mode, 'api_key');
    assert.equal(page._presetDrafts[0].oauth_provider, '');
    assert.equal(page._presetDrafts[0].base_url, 'https://coding.dashscope.aliyuncs.com/v1');
    assert.equal(page._presetDrafts[0].model, 'qwen3-coder-next');
}));

test('preset-controller defaults legacy GLM api key presets to the coding plan endpoint', async () => withDom(async ({ document, registerElement }) => {
    const modal = document.createElement('div');
    modal.classList.add('modal');
    registerElement('preset-modal', modal);

    const providerSelect = document.createElement('select');
    const originalName = document.createElement('input');
    const nameInput = document.createElement('input');
    const aliasInput = document.createElement('input');
    const embeddingInput = document.createElement('input');
    const keyInput = document.createElement('input');
    const modelSelect = document.createElement('select');
    const modelCustom = document.createElement('input');
    const help = document.createElement('div');
    const helpLink = document.createElement('a');
    const authModeApiKey = document.createElement('input');
    const authModeOauth = document.createElement('input');

    authModeApiKey.type = 'radio';
    authModeOauth.type = 'radio';

    registerElement('edit-preset-provider', providerSelect);
    registerElement('edit-preset-original-name', originalName);
    registerElement('edit-preset-name', nameInput);
    registerElement('edit-preset-alias', aliasInput);
    registerElement('edit-preset-embedding-model', embeddingInput);
    registerElement('edit-preset-key', keyInput);
    registerElement('edit-preset-model-select', modelSelect);
    registerElement('edit-preset-model-custom', modelCustom);
    registerElement('api-key-help', help);
    registerElement('api-key-help-link', helpLink);
    registerElement('edit-preset-auth-mode-api-key', authModeApiKey);
    registerElement('edit-preset-auth-mode-oauth', authModeOauth);

    const zhipuProvider = {
        id: 'zhipu',
        label: 'GLM',
        base_url: 'https://open.bigmodel.cn/api/paas/v4',
        default_model: 'glm-5',
        api_key_url: 'https://open.bigmodel.cn/usercenter/apikeys',
        auth_methods: [
            {
                id: 'api_key',
                type: 'api_key',
                metadata: {
                    recommended_base_url: 'https://open.bigmodel.cn/api/paas/v4',
                    recommended_model: 'glm-5',
                },
            },
            {
                id: 'coding_plan_api_key',
                type: 'api_key',
                metadata: {
                    recommended_base_url: 'https://open.bigmodel.cn/api/coding/paas/v4',
                    recommended_model: 'glm-5',
                },
            },
        ],
    };

    const page = {
        _selectedPresetIndex: -1,
        _activePreset: '',
        _presetDrafts: [],
        _providersById: new Map([['zhipu', zhipuProvider]]),
        _modelCatalog: {
            providers: [zhipuProvider],
        },
        $(selector) {
            return document.getElementById(selector.slice(1));
        },
        _renderPresetList() {},
        _renderHero() {},
        _scheduleAutoSave() {},
    };

    openPresetModal(page);
    providerSelect.value = 'zhipu';
    authModeApiKey.checked = true;
    authModeOauth.checked = false;
    nameInput.value = 'glm-coding';
    modelSelect.value = '__custom__';
    modelCustom.value = 'glm-5';

    commitPresetModal(page, {
        presetNameMissing: 'preset name missing',
        presetModelMissing: 'preset model missing',
        presetSaveSuccess: 'preset saved',
    });
    await Promise.resolve();

    assert.equal(page._presetDrafts.length, 1);
    assert.equal(page._presetDrafts[0].base_url, 'https://open.bigmodel.cn/api/coding/paas/v4');
    assert.equal(page._presetDrafts[0].model, 'glm-5');
}));

function createToastRecorder() {
    const calls = [];
    const push = (type, message) => calls.push({ type, message });
    return {
        calls,
        success(message) {
            push('success', message);
        },
        info(message) {
            push('info', message);
        },
        warning(message) {
            push('warning', message);
        },
        error(message) {
            push('error', message);
        },
        getErrorMessage(error, fallback) {
            return error?.message || fallback;
        },
    };
}

function createClassList() {
    const tokens = new Set();
    return {
        contains(token) {
            return tokens.has(token);
        },
        toggle(token, force) {
            const shouldAdd = force === undefined ? !tokens.has(token) : !!force;
            if (shouldAdd) {
                tokens.add(token);
            } else {
                tokens.delete(token);
            }
            return shouldAdd;
        },
    };
}

test('settings action helper saves config and preserves queued autosave flow', async () => {
    const toastRecorder = createToastRecorder();
    const calls = [];
    const page = {
        _isSaving: false,
        _queuedAutoSave: false,
        _presetDrafts: [{ name: 'default' }],
        _collectPayload(scope) {
            calls.push(`collect:${scope?.title || 'all'}`);
            return { bot: { close_to_tray: true } };
        },
        _setSavingState(isSaving, triggerButton) {
            calls.push(`saving:${isSaving}:${triggerButton?.id || 'none'}`);
            this._isSaving = isSaving;
        },
        async loadSettings(options) {
            calls.push(`load:${options.silent}:${options.preserveFeedback}`);
        },
        _renderHero(highlight) {
            calls.push(`hero:${highlight}`);
        },
        _renderSaveFeedback(result) {
            calls.push(`feedback:${result.success}`);
        },
        _renderExportRagStatus() {
            calls.push('export-rag');
        },
        _scheduleAutoSave(options) {
            calls.push(`autosave:${options.immediate}`);
        },
    };

    await saveSettings(page, {
        scope: { title: '模块A' },
        triggerButton: { id: 'save-button' },
    }, {
        presetMissing: 'missing preset',
        saveFailed: 'save failed',
    }, {
        toast: toastRecorder,
        windowApi: {
            configPatch: async (payload) => ({
                success: true,
                message: 'saved',
                runtime_apply: { message: `patched:${Object.keys(payload).length}` },
            }),
        },
    });

    assert.deepEqual(calls, [
        'collect:模块A',
        'saving:true:save-button',
        'load:true:true',
        'hero:true',
        'feedback:true',
        'export-rag',
        'saving:false:save-button',
    ]);
    assert.deepEqual(toastRecorder.calls, [{ type: 'success', message: 'patched:1' }]);

    const busyPage = {
        _isSaving: true,
        _queuedAutoSave: false,
    };
    await saveSettings(busyPage, {}, {
        presetMissing: 'missing preset',
        saveFailed: 'save failed',
    }, {
        toast: toastRecorder,
    });
    assert.equal(busyPage._queuedAutoSave, true);
});

test('settings action helpers handle preview and updater flows', async () => withDom(async ({ document }) => {
    const previewSummary = document.createElement('div');
    const previewOutput = document.createElement('pre');
    const selectors = {
        '#setting-preview-chat-name': { value: 'Chat A' },
        '#setting-preview-sender': { value: 'Alice' },
        '#setting-preview-relationship': { value: 'friend' },
        '#setting-preview-emotion': { value: 'calm' },
        '#setting-preview-message': { value: 'hello' },
        '#setting-preview-is-group': { checked: true },
        '#settings-preview-summary': previewSummary,
        '#settings-prompt-preview': previewOutput,
    };
    const toastRecorder = createToastRecorder();
    let updateSource = '';
    const page = {
        getState(path) {
            const mapping = {
                'bot.connected': true,
                'updater.readyToInstall': false,
                'updater.enabled': true,
            };
            return mapping[path];
        },
        _collectPayload() {
            return { bot: { reply_mode: 'smart' } };
        },
        _renderUpdatePanel() {
            this.rendered = true;
        },
        $(selector) {
            return selectors[selector] || null;
        },
    };

    await previewPrompt(page, { previewFailed: 'preview failed' }, {
        toast: toastRecorder,
        apiService: {
            previewPrompt: async () => ({
                success: true,
                prompt: 'prompt content',
                summary: { lines: 3, chars: 42 },
            }),
        },
    });
    assert.equal(previewSummary.dataset.state, 'success');
    assert.match(previewSummary.textContent, /3 行/);
    assert.equal(previewOutput.textContent, 'prompt content');

    await checkUpdates(page, { updateFailed: 'update failed' }, {
        toast: toastRecorder,
        updateSource: 'about-page',
        windowApi: {
            checkForUpdates: async ({ source }) => {
                updateSource = source;
                return {
                    success: true,
                    updateAvailable: true,
                };
            },
        },
    });
    assert.equal(page.rendered, true);
    assert.equal(updateSource, 'about-page');

    await openUpdateDownload(page, {
        toast: toastRecorder,
        windowApi: {
            downloadUpdate: async () => ({ success: true, alreadyDownloaded: false }),
        },
    });

    await resetCloseBehavior({ resetCloseSuccess: 'reset ok' }, {
        toast: toastRecorder,
        windowApi: {
            resetCloseBehavior: async () => ({ success: true }),
        },
    });

    assert.deepEqual(toastRecorder.calls, [
        { type: 'success', message: '已发现新版本' },
        { type: 'info', message: '开始下载新版本，请稍候...' },
        { type: 'success', message: 'reset ok' },
    ]);
}));

test('settings page shell binds events and auto save routing stably', async () => withDom(async ({ document, registerElement }) => {
    const controls = new Map();
    [
        'btn-refresh-config',
        'btn-save-settings',
        'btn-preview-prompt',
        'btn-reset-close-behavior',
        'btn-settings-scroll-top',
        'btn-create-quick-backup',
        'btn-create-full-backup',
        'btn-restore-backup-dry-run',
        'btn-restore-backup-apply',
        'btn-cleanup-backup-dry-run',
        'btn-cleanup-backup-apply',
    ].forEach((id) => {
        controls.set(`#${id}`, registerElement(id, document.createElement('button')));
    });
    const rootListeners = {};
    const root = {
        addEventListener(type, handler) {
            rootListeners[type] = handler;
        },
        removeEventListener() {},
    };
    const page = {
        containerId: 'page-settings',
        bindings: [],
        _eventCleanups: [],
        bindEvent(target, type, handler) {
            this.bindings.push({ target, type, handler });
        },
        loadSettings() {
            this.calls.push('load');
        },
        _saveSettings() {
            this.calls.push('save');
        },
        _previewPrompt() {
            this.calls.push('preview');
        },
        _resetCloseBehavior() {
            this.calls.push('reset');
        },
        _scrollToTop() {
            this.calls.push('top');
        },
        _createWorkspaceBackup(mode) {
            this.calls.push(`backup-create:${mode}`);
        },
        _restoreWorkspaceBackup(dryRun) {
            this.calls.push(`backup-restore:${dryRun}`);
        },
        _cleanupWorkspaceBackups(dryRun) {
            this.calls.push(`backup-cleanup:${dryRun}`);
        },
        _scheduleAutoSave(options) {
            this.calls.push(`autosave:${options.immediate}`);
        },
        emit(event, payload) {
            this.calls.push(`${event}:${payload}`);
        },
        calls: [],
        $(selector) {
            return controls.get(selector) || null;
        },
    };

    bindSettingsEvents(page, {
        documentObj: document,
    });
    bindSettingsAutoSave(page, {
        rootElement: root,
    });

    assert.equal(page.bindings.length, 11);
    assert.equal(page._eventCleanups.length, 1);

    page.bindings[0].handler();
    page.bindings[1].handler();
    page.bindings[2].handler();
    page.bindings[3].handler();
    page.bindings[4].handler();
    page.bindings[5].handler();
    page.bindings[6].handler();
    page.bindings[7].handler();
    page.bindings[8].handler();
    page.bindings[9].handler();
    page.bindings[10].handler();
    rootListeners.input({ target: { id: 'setting-group-at-only', tagName: 'INPUT', type: 'checkbox' } });
    rootListeners.change({ target: { id: 'setting-log-level', tagName: 'SELECT' } });
    rootListeners.input({ target: { id: 'unknown-field', tagName: 'INPUT', type: 'text' } });

    assert.deepEqual(page.calls, [
        'load',
        'save',
        'preview',
        'reset',
        'top',
        'backup-create:quick',
        'backup-create:full',
        'backup-restore:true',
        'backup-restore:false',
        'backup-cleanup:true',
        'backup-cleanup:false',
        'autosave:true',
        'autosave:true',
    ]);
}));

test('runtime-sync model summary prefers model auth overview before legacy preset projection', () => {
    const summary = buildModelSummaryView(
        {
            active_provider_id: 'qwen',
            cards: [
                {
                    provider: { id: 'qwen', label: 'Qwen', default_model: 'qwen3-coder-plus' },
                    selected_label: 'Coding Plan API Key',
                    summary: 'API Key 已配置',
                    metadata: {
                        is_active_provider: true,
                        default_model: 'qwen3-coder-plus',
                    },
                },
            ],
        },
        {
            api: {
                active_preset: 'OpenAI',
                presets: [{ name: 'OpenAI', provider_id: 'openai', model: 'gpt-4.1', auth_mode: 'api_key' }],
            },
        },
    );

    assert.deepEqual(summary, {
        title: 'Qwen · qwen3-coder-plus',
        meta: 'Coding Plan API Key · API Key 已配置',
    });
});

test('models page groups shared auth sources by source group and prefers full email display', () => {
    const provider = {
        id: 'google',
        auth_methods: [
            { id: 'google_oauth', type: 'oauth', label: 'Google OAuth' },
            { id: 'gemini_cli_local', type: 'local_import', label: 'Gemini CLI 本机登录' },
            { id: 'api_key', type: 'api_key', label: 'Gemini API Key' },
        ],
    };
    const groups = groupAuthStates(
        {
            auth_states: [
                {
                    method_id: 'google_oauth',
                    status: 'connected',
                    default_selected: true,
                    account_label: 'Google 工作账号',
                    account_email: 'work@example.com',
                    metadata: {
                        profile_id: 'google:google_oauth:work',
                        source_group: {
                            id: 'google_gemini_cli:work@example.com',
                            label: 'Google / Gemini 登录态',
                            kind: 'shared_auth_provider',
                            shared_auth_provider_id: 'google_gemini_cli',
                            account_key: 'work@example.com',
                        },
                    },
                    actions: [{ id: 'set_default_profile' }, { id: 'start_browser_auth' }],
                },
                {
                    method_id: 'gemini_cli_local',
                    status: 'available_to_import',
                    account_label: 'Gemini 本机账号',
                    account_email: 'work@example.com',
                    metadata: {
                        source_group: {
                            id: 'google_gemini_cli:work@example.com',
                            label: 'Google / Gemini 登录态',
                            kind: 'shared_auth_provider',
                            shared_auth_provider_id: 'google_gemini_cli',
                            account_key: 'work@example.com',
                        },
                    },
                    actions: [{ id: 'bind_local_auth' }],
                },
                {
                    method_id: 'google_oauth',
                    status: 'connected',
                    account_label: 'Google 备用账号',
                    account_email: 'other@example.com',
                    metadata: {
                        profile_id: 'google:google_oauth:other',
                        source_group: {
                            id: 'google_gemini_cli:other@example.com',
                            label: 'Google / Gemini 登录态',
                            kind: 'shared_auth_provider',
                            shared_auth_provider_id: 'google_gemini_cli',
                            account_key: 'other@example.com',
                        },
                    },
                    actions: [{ id: 'set_default_profile' }],
                },
            ],
        },
        provider,
    );

    assert.equal(groups.length, 2);
    assert.equal(groups[0].group_label, 'Google / Gemini 登录态');
    assert.equal(groups[0].account_display, 'work@example.com');
    assert.equal(groups[0].default_selected, true);
    assert.deepEqual(
        groups[0].actions.map((item) => item.id),
        ['set_default_profile', 'start_browser_auth', 'bind_local_auth'],
    );
    assert.equal(groups[1].account_display, 'other@example.com');
});

test('models page toggles between full and masked email display', async () => {
    await withMockStorage({}, async ({ state }) => {
        const page = new ModelsPage();
        const maskedEmail = maskEmailAddress('work@example.com');
        page.render = () => {};

        assert.equal(page.renderFilterRow().includes('显示脱敏邮箱'), true);
        assert.equal(page.renderProviderListItem({
            provider: { id: 'openai', label: 'OpenAI' },
            selected_label: 'work@example.com',
            state: 'connected',
            metadata: {},
        }).includes('work@example.com'), true);

        await page.handleButtonAction({
            dataset: {
                modelAuthUi: 'toggle_email_visibility',
            },
        });

        assert.equal(state.get(EMAIL_VISIBILITY_STORAGE_KEY), 'masked');
        assert.equal(page.renderFilterRow().includes('显示完整邮箱'), true);
        assert.equal(page.getSyncDetail({
            metadata: {
                provider_sync: {
                    source_message: '已同步 work@example.com',
                },
            },
        }), `已同步 ${maskedEmail}`);

        const rowMarkup = page.renderWorkbenchAuthRow(
            {},
            { id: 'openai' },
            { id: 'chatgpt_local', label: 'ChatGPT 本机登录' },
            {
                method_id: 'chatgpt_local',
                status: 'following_local_auth',
                actions: [],
            },
            {
                account_display: 'work@example.com',
                grouped_method_labels: ['ChatGPT 本机登录'],
                status: 'following_local_auth',
                actions: [],
            },
        );
        assert.equal(rowMarkup.includes(maskedEmail), true);
        assert.equal(rowMarkup.includes('work@example.com'), false);
    });
});

test('runtime-sync model summary masks auth email when preference is masked', async () => {
    await withMockStorage({
        [EMAIL_VISIBILITY_STORAGE_KEY]: 'masked',
    }, async () => {
        const summary = buildModelSummaryView(
            {
                active_provider_id: 'openai',
                cards: [
                    {
                        provider: { id: 'openai', label: 'OpenAI', default_model: 'gpt-5.4' },
                        selected_label: 'work@example.com',
                        summary: '已连接',
                        metadata: {
                            is_active_provider: true,
                            default_model: 'gpt-5.4',
                        },
                    },
                ],
            },
            null,
        );

        assert.equal(summary.meta.includes(maskEmailAddress('work@example.com')), true);
        assert.equal(summary.meta.includes('work@example.com'), false);
    });
});

test('settings shell keeps workbench structure balanced for section switching', () => {
    const markup = renderSettingsPageShell();
    assert.equal(markup.includes('id="settings-section-nav"'), true);
    assert.equal((markup.match(/<div\b/g) || []).length, (markup.match(/<\/div>/g) || []).length);
});

test('settings shell removes duplicated model summary block from config center', () => {
    const markup = renderSettingsPageShell();
    assert.equal(markup.includes('model-summary-card'), false);
    assert.equal(markup.includes('settings-model-summary-title'), false);
});

test('settings hero stays focused on generic config status instead of model testing', async () => {
    await withDom(async () => {
        const container = document.createElement('div');
        const page = {
            _config: {
                agent: {
                    langsmith_api_key_configured: false,
                },
            },
            _configAudit: {
                version: 3,
                loaded_at: '2026-03-26T10:00:00',
                audit: {
                    unknown_override_paths: ['a'],
                    dormant_paths: ['b', 'c'],
                },
            },
            _auditStatus: 'ready',
            _auditMessage: '',
            _hasPendingChanges: false,
            getState(path) {
                if (path === 'bot.connected') {
                    return true;
                }
                if (path === 'bot.status.config_snapshot.version') {
                    return 9;
                }
                return undefined;
            },
            $(selector) {
                if (selector === '#current-config-hero') {
                    return container;
                }
                return null;
            },
        };

        renderSettingsHero(page);
        const renderedText = String(container.textContent || '');
        const summaryButton = container.querySelector('#btn-open-models');

        assert.equal(renderedText.includes('测试当前连接'), false);
        assert.equal(renderedText.includes('当前运行预设'), false);
        assert.equal(renderedText.includes('API Key'), false);
        assert.equal(renderedText.includes('Ollama'), false);
        assert.equal(renderedText.includes('LangSmith'), true);
        assert.equal(renderedText.includes('前往模型页'), true);
        assert.ok(container.querySelector('#settings-model-summary-title'));
        assert.ok(container.querySelector('#settings-model-summary-meta'));
        assert.ok(summaryButton);
        assert.equal(summaryButton?.textContent, '前往模型页');
    });
});

test('settings model summary button routes back to the models page', async () => {
    await withDom(async () => {
        const summaryButton = document.createElement('button');
        summaryButton.id = 'btn-open-models';

        const calls = [];
        const page = {
            $(selector) {
                if (selector === '#btn-open-models') {
                    return summaryButton;
                }
                return null;
            },
            bindEvent(target, eventName, handler) {
                target.addEventListener(eventName, handler);
            },
            emit(eventName, payload) {
                calls.push({ eventName, payload });
            },
        };

        bindSettingsEvents(page);
        summaryButton.click();

        assert.deepEqual(calls, [
            { eventName: Events.PAGE_CHANGE, payload: 'models' },
        ]);
    });
});

test('settings export center button routes to the exports page', async () => {
    await withDom(async () => {
        const exportButton = document.createElement('button');
        exportButton.id = 'btn-open-export-center';

        const calls = [];
        const page = {
            $(selector) {
                if (selector === '#btn-open-export-center') {
                    return exportButton;
                }
                return null;
            },
            bindEvent(target, eventName, handler) {
                target.addEventListener(eventName, handler);
            },
            emit(eventName, payload) {
                calls.push({ eventName, payload });
            },
        };

        bindSettingsEvents(page);
        exportButton.click();

        assert.deepEqual(calls, [
            { eventName: Events.PAGE_CHANGE, payload: 'exports' },
        ]);
    });
});

test('settings shell exposes common section as the default entry', () => {
    const markup = renderSettingsPageShell();
    assert.equal(markup.includes('data-settings-section="common"'), true);
    assert.equal(markup.includes('data-settings-section="common" aria-pressed="true">常用'), true);
});

test('settings page full payload excludes api preset state after model center split', () => {
    const page = new SettingsPage();
    const selectors = {
        '#setting-self-name': { value: '???' },
    };

    page.$ = (selector) => selectors[selector] || null;

    const payload = page._collectPayload();

    assert.equal(payload.bot?.self_name, '???');
    assert.equal(payload.api, undefined);
});

test('settings page hydrates shared groups and card order for common modules', () => {
    const page = new SettingsPage();
    const makeCard = (title) => ({
        dataset: {},
        style: {},
        querySelector(selector) {
            if (selector === '.settings-card-title') {
                return { textContent: title };
            }
            return null;
        },
    });
    const cards = [
        makeCard('模型与认证'),
        makeCard('备份与恢复'),
        makeCard('白名单管理'),
    ];

    page.$$ = (selector) => selector === '.settings-card' ? cards : [];

    page._hydrateSettingsSections();

    assert.equal(cards[0].dataset.settingsGroup, 'workspace');
    assert.equal(cards[0].dataset.settingsGroups, 'workspace common');
    assert.equal(cards[0].style.order, '10');
    assert.equal(cards[1].dataset.settingsGroups, 'workspace');
    assert.equal(cards[2].dataset.settingsGroups, 'guard common');
});

test('settings page switches section cards and nav state consistently', () => {
    const page = new SettingsPage();
    const workspaceButton = {
        dataset: { settingsSection: 'workspace' },
        classList: createClassList(),
        setAttribute(name, value) {
            this[name] = value;
        },
    };
    const promptButton = {
        dataset: { settingsSection: 'prompt' },
        classList: createClassList(),
        setAttribute(name, value) {
            this[name] = value;
        },
    };
    const workspaceCard = {
        dataset: { settingsGroup: 'workspace' },
        hidden: false,
    };
    const promptCard = {
        dataset: { settingsGroup: 'prompt' },
        hidden: false,
    };

    page.$$ = (selector) => {
        if (selector === '#settings-section-nav [data-settings-section]') {
            return [workspaceButton, promptButton];
        }
        if (selector === '.settings-card') {
            return [workspaceCard, promptCard];
        }
        return [];
    };

    page._setSettingsSection('prompt');

    assert.equal(page._activeSettingsSection, 'prompt');
    assert.equal(workspaceButton.classList.contains('active'), false);
    assert.equal(promptButton.classList.contains('active'), true);
    assert.equal(workspaceButton['aria-pressed'], 'false');
    assert.equal(promptButton['aria-pressed'], 'true');
    assert.equal(workspaceCard.hidden, true);
    assert.equal(promptCard.hidden, false);
});

test('settings page keeps shared cards visible in common and original sections', () => {
    const page = new SettingsPage();
    const commonButton = {
        dataset: { settingsSection: 'common' },
        classList: createClassList(),
        setAttribute(name, value) {
            this[name] = value;
        },
    };
    const botButton = {
        dataset: { settingsSection: 'bot' },
        classList: createClassList(),
        setAttribute(name, value) {
            this[name] = value;
        },
    };
    const sharedCard = {
        dataset: { settingsGroups: 'bot common' },
        hidden: false,
    };
    const guardCard = {
        dataset: { settingsGroups: 'guard' },
        hidden: false,
    };

    page.$$ = (selector) => {
        if (selector === '#settings-section-nav [data-settings-section]') {
            return [commonButton, botButton];
        }
        if (selector === '.settings-card') {
            return [sharedCard, guardCard];
        }
        return [];
    };

    page._setSettingsSection('common');
    assert.equal(sharedCard.hidden, false);
    assert.equal(guardCard.hidden, true);

    page._setSettingsSection('bot');
    assert.equal(sharedCard.hidden, false);
    assert.equal(guardCard.hidden, true);
});

test('models page callback payload parser keeps JSON and wraps plain text safely', () => {
    assert.deepEqual(parseCallbackPayload('{"code":"abc","state":"123"}'), { code: 'abc', state: '123' });
    assert.deepEqual(parseCallbackPayload('plain-code'), { raw_payload: 'plain-code' });
    assert.deepEqual(parseCallbackPayload(''), {});
});

test('models page localizes core actions and switches between wizard and workbench modes', async () => {
    assert.equal(getLocalizedActionLabel('start_browser_auth'), '\u524d\u5f80\u767b\u5f55\u9875');
    assert.equal(getLocalizedActionLabel('set_active_provider'), '\u8bbe\u4e3a\u5f53\u524d\u56de\u590d\u6a21\u578b');
    assert.equal(getLocalizedActionLabel('unknown_action'), 'unknown_action');
    assert.equal(getActionWorkflowKind('start_browser_auth', { type: 'web_session' }), 'browser');
    assert.equal(getActionWorkflowKind('show_session_form', { type: 'web_session' }), 'session');
    assert.equal(getActionWorkflowKind('bind_local_auth', { type: 'web_session' }), 'local');

    assert.equal(resolveCardViewMode({ metadata: { can_set_active_provider: true } }), 'workbench');
    assert.equal(resolveCardViewMode({ metadata: { can_set_active_provider: false } }), 'wizard');

    const page = new ModelsPage();
    page.renderWorkflowModal = () => {};

    await page.openWorkflow({
        kind: 'api_key',
        providerId: 'openai',
        methodId: 'api_key',
    });
    assert.equal(page._activeWorkflow?.kind, 'onboarding');
    assert.equal(page._activeWorkflow?.onboardingType, 'api_key');

    page.markOnboardingSeen('api_key');
    await page.openWorkflow({
        kind: 'api_key',
        providerId: 'openai',
        methodId: 'api_key',
    });
    assert.equal(page._activeWorkflow?.kind, 'api_key');
});

test('models page preserves full auth methods from overview providers and routes doubao browser actions correctly', () => {
    const page = new ModelsPage();
    page.applyModelCatalog({
        providers: [
            {
                id: 'doubao',
                label: 'Doubao',
                models: ['doubao-seed-1-6-flash-250715'],
                auth_methods: [
                    {
                        id: 'api_key',
                        type: 'api_key',
                        label: 'Ark API Key',
                    },
                ],
            },
        ],
    });

    const mergedProvider = page.getProvider('doubao', {
        id: 'doubao',
        label: 'Doubao',
        supported_models: ['doubao-seed-1-8-251228'],
        auth_methods: [
            {
                id: 'api_key',
                type: 'api_key',
                label: 'Ark API Key',
            },
            {
                id: 'doubao_web_session',
                type: 'web_session',
                label: 'Doubao Web Session',
            },
        ],
    });

    assert.deepEqual(
        mergedProvider.auth_methods.map((item) => item.id),
        ['api_key', 'doubao_web_session'],
    );
    assert.deepEqual(
        mergedProvider.models,
        ['doubao-seed-1-6-flash-250715', 'doubao-seed-1-8-251228'],
    );

    const browserButton = page.renderWorkbenchActionButton(
        { id: 'doubao' },
        { id: 'doubao_web_session', type: 'web_session', label: 'Doubao Web Session' },
        { method_id: 'doubao_web_session' },
        { id: 'start_browser_auth' },
    );
    assert.equal(browserButton.includes('data-model-auth-ui="workflow_start_browser"'), true);
    assert.equal(browserButton.includes('data-workflow-kind="session"'), false);

    const googleBrowserButton = page.renderWorkbenchActionButton(
        { id: 'google' },
        {
            id: 'google_oauth',
            type: 'oauth',
            label: 'Google OAuth',
            requires_fields: ['oauth_project_id'],
        },
        { method_id: 'google_oauth' },
        { id: 'start_browser_auth' },
    );
    assert.equal(googleBrowserButton.includes('data-model-auth-ui="open_workflow"'), true);
    assert.equal(googleBrowserButton.includes('data-workflow-kind="browser"'), true);

    const wizardMarkup = page.renderWizardAuthCard(
        {},
        { id: 'doubao' },
        { id: 'doubao_web_session', type: 'web_session', label: 'Doubao Web Session' },
        {
            method_id: 'doubao_web_session',
            status: 'available_to_import',
            actions: [
                { id: 'bind_local_auth' },
                { id: 'show_session_form' },
                { id: 'start_browser_auth' },
            ],
        },
    );
    assert.equal(wizardMarkup.includes('同步本机登录'), true);
    assert.equal(wizardMarkup.includes('导入会话'), true);
    assert.equal(wizardMarkup.includes('前往登录页'), true);
});

test('models page advanced panel renders provider description, local paths and notes', () => {
    const page = new ModelsPage();
    const markup = page.renderAdvancedPanel(
        { metadata: {} },
        {
            id: 'google',
            label: 'Google / Gemini',
            description: '支持从本机 Gemini CLI 配置目录导入、粘贴 JWT 令牌或通过 OAuth 登录来管理 Gemini CLI 账号。',
            metadata: {
                research_summary: '支持从本机 Gemini CLI 配置目录导入、粘贴 JWT 令牌，或通过 Google OAuth 登录来管理 Gemini CLI 账号。',
                local_auth_paths: [
                    '~/.gemini/oauth_creds.json',
                    '$GEMINI_CLI_HOME/.gemini/settings.json',
                ],
                notes: [
                    '权限范围：读取并写入默认 ~/.gemini 或实例目录（$GEMINI_CLI_HOME/.gemini）下的配置文件。',
                    '网络请求范围：仅访问 Google / Gemini 官方接口。',
                ],
            },
            auth_methods: [],
        },
    );

    assert.equal(markup.includes('服务说明'), true);
    assert.equal(markup.includes('本地配置路径'), true);
    assert.equal(markup.includes('补充说明'), true);
    assert.equal(markup.includes('~/.gemini/oauth_creds.json'), true);
    assert.equal(markup.includes('$GEMINI_CLI_HOME/.gemini/settings.json'), true);
});

test('models page browser auth form renders required provider fields inline', () => {
    const page = new ModelsPage();
    const markup = page.renderBrowserAuthForm(
        { metadata: { oauth_project_id: 'demo-project' } },
        { id: 'google' },
        { id: 'google_oauth', label: 'Google OAuth', type: 'oauth', requires_fields: ['oauth_project_id'] },
        { metadata: {} },
    );

    assert.equal(markup.includes('name="oauth_project_id"'), true);
    assert.equal(markup.includes('value="demo-project"'), true);
});

test('models page api key workflow previews coding plan runtime before first save', () => {
    const page = new ModelsPage();
    page.getCardByProviderId = () => ({
        provider: {
            id: 'qwen',
            default_model: 'qwen3.5-plus',
            default_base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
            auth_methods: [
                {
                    id: 'coding_plan_api_key',
                    type: 'api_key',
                    label: 'Coding Plan API Key',
                    metadata: {
                        recommended_model: 'qwen3-coder-next',
                        recommended_base_url: 'https://coding.dashscope.aliyuncs.com/v1',
                    },
                },
            ],
        },
        auth_states: [],
        metadata: {
            default_model: 'qwen3.5-plus',
            default_base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        },
    });
    page.getSelectedCard = () => ({});
    page._activeWorkflow = {
        kind: 'api_key',
        providerId: 'qwen',
        methodId: 'coding_plan_api_key',
    };

    const content = page.getWorkflowContent();

    assert.equal(content.body.includes('qwen3-coder-next'), true);
    assert.equal(content.body.includes('https://coding.dashscope.aliyuncs.com/v1'), true);
    assert.equal(content.body.includes('qwen3.5-plus'), false);
    assert.equal(content.body.includes('https://dashscope.aliyuncs.com/compatible-mode/v1'), false);
});

test('models page browser auth form previews Kimi coding runtime before first OAuth login', () => {
    const page = new ModelsPage();
    const markup = page.renderBrowserAuthForm(
        {
            auth_states: [],
            metadata: {
                default_model: 'kimi-k2-turbo-preview',
                default_base_url: 'https://api.moonshot.cn/v1',
            },
        },
        {
            id: 'kimi',
            default_model: 'kimi-k2-turbo-preview',
            default_base_url: 'https://api.moonshot.cn/v1',
        },
        {
            id: 'kimi_code_oauth',
            label: 'Kimi Code OAuth',
            type: 'oauth',
            metadata: {
                recommended_model: 'kimi-for-coding',
                recommended_base_url: 'https://api.kimi.com/coding/v1',
            },
        },
        { metadata: {} },
    );

    assert.equal(markup.includes('kimi-for-coding'), true);
    assert.equal(markup.includes('https://api.kimi.com/coding/v1'), true);
    assert.equal(markup.includes('kimi-k2-turbo-preview'), false);
    assert.equal(markup.includes('https://api.moonshot.cn/v1'), false);
});

test('models page local auth workflow previews Kimi coding runtime before first local bind', () => {
    const page = new ModelsPage();
    page.getCardByProviderId = () => ({
        provider: {
            id: 'kimi',
            default_model: 'kimi-k2-turbo-preview',
            default_base_url: 'https://api.moonshot.cn/v1',
            auth_methods: [
                {
                    id: 'kimi_code_local',
                    type: 'local_import',
                    label: 'Kimi Code Local',
                    metadata: {
                        recommended_model: 'kimi-for-coding',
                        recommended_base_url: 'https://api.kimi.com/coding/v1',
                    },
                },
            ],
        },
        auth_states: [],
        metadata: {
            default_model: 'kimi-k2-turbo-preview',
            default_base_url: 'https://api.moonshot.cn/v1',
        },
    });
    page.getSelectedCard = () => ({});
    page._activeWorkflow = {
        kind: 'local',
        providerId: 'kimi',
        methodId: 'kimi_code_local',
    };

    const content = page.getWorkflowContent();

    assert.equal(content.body.includes('kimi-for-coding'), true);
    assert.equal(content.body.includes('https://api.kimi.com/coding/v1'), true);
    assert.equal(content.body.includes('kimi-k2-turbo-preview'), false);
    assert.equal(content.body.includes('https://api.moonshot.cn/v1'), false);
});

test('models page browser auth form previews Qwen OAuth runtime before first login', () => {
    const page = new ModelsPage();
    const markup = page.renderBrowserAuthForm(
        {
            auth_states: [],
            metadata: {
                default_model: 'qwen3.5-plus',
                default_base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
            },
        },
        {
            id: 'qwen',
            default_model: 'qwen3.5-plus',
            default_base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        },
        {
            id: 'qwen_oauth',
            label: 'Qwen OAuth',
            type: 'oauth',
            metadata: {
                recommended_model: 'qwen3-coder-plus',
                recommended_base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
            },
        },
        { metadata: {} },
    );

    assert.equal(markup.includes('qwen3-coder-plus'), true);
    assert.equal(markup.includes('qwen3.5-plus'), false);
    assert.equal(markup.includes('https://dashscope.aliyuncs.com/compatible-mode/v1'), true);
});

test('models page browser callback form submits structured payload to the model auth center', async () => {
    const originalFormData = globalThis.FormData;
    const page = new ModelsPage();
    let captured = null;
    globalThis.FormData = class {
        constructor(form) {
            this.map = form._data || {};
        }

        get(name) {
            return this.map[name] ?? null;
        }
    };
    page.runAction = async (action, payload, options) => {
        captured = { action, payload, options };
        return { success: true };
    };
    page.closeWorkflowModal = () => {};

    try {
        await page.handleFormSubmit({
            dataset: {
                modelAuthForm: 'browser_callback',
                providerId: 'qwen',
                methodId: 'qwen_oauth',
                flowId: 'flow-1',
            },
            _data: {
                flow_id: 'flow-1',
                label: 'Qwen OAuth',
                callback_payload: '{"code":"abc"}',
                set_default: 'on',
            },
        });
    } finally {
        globalThis.FormData = originalFormData;
    }

    assert.equal(captured.action, 'complete_browser_auth');
    assert.deepEqual(captured.payload, {
        provider_id: 'qwen',
        method_id: 'qwen_oauth',
        flow_id: 'flow-1',
        label: 'Qwen OAuth',
        callback_payload: { code: 'abc' },
        set_default: true,
    });
});

test('models page renders and submits flowless browser auth continuation via local rescan', async () => {
    const originalFormData = globalThis.FormData;
    const page = new ModelsPage();
    let captured = null;
    globalThis.FormData = class {
        constructor(form) {
            this.map = form._data || {};
        }

        get(name) {
            return this.map[name] ?? null;
        }
    };
    page.runAction = async (action, payload, options) => {
        captured = { action, payload, options };
        return { success: true };
    };
    page.closeWorkflowModal = () => {};

    try {
        const markup = page.renderBrowserAuthForm(
            { selected_method_id: '', selected_label: '' },
            { id: 'doubao' },
            { id: 'doubao_web_session', label: 'Doubao Web Session', type: 'web_session', metadata: {} },
            { metadata: { pending_flow: { started_at: 123, browser_entry_url: 'https://www.doubao.com/' } } },
        );

        assert.equal(markup.includes('Flowless Rescan'), false);
        assert.equal(markup.includes('\u53ef\u9009\u9879'), true);
        assert.equal(markup.includes('__local_rescan__'), true);

        await page.handleFormSubmit({
            dataset: {
                modelAuthForm: 'browser_callback',
                providerId: 'doubao',
                methodId: 'doubao_web_session',
                flowId: '__local_rescan__',
            },
            _data: {
                label: 'Doubao Browser',
                callback_payload: '',
                set_default: 'on',
            },
        });
    } finally {
        globalThis.FormData = originalFormData;
    }

    assert.equal(captured.action, 'complete_browser_auth');
    assert.deepEqual(captured.payload, {
        provider_id: 'doubao',
        method_id: 'doubao_web_session',
        flow_id: '__local_rescan__',
        label: 'Doubao Browser',
        callback_payload: {},
        set_default: true,
    });
});

test('models page browser workflow persists required fields before starting auth', async () => {
    const originalFormData = globalThis.FormData;
    const page = new ModelsPage();
    const calls = [];
    const workflowCalls = [];
    globalThis.FormData = class {
        constructor(form) {
            this.map = form._data || {};
        }

        get(name) {
            return this.map[name] ?? null;
        }
    };
    page.getCardByProviderId = () => ({
        provider: {
            id: 'google',
            auth_methods: [
                { id: 'google_oauth', type: 'oauth', label: 'Google OAuth', requires_fields: ['oauth_project_id'] },
            ],
        },
        auth_states: [],
    });
    page.getSelectedCard = () => ({});
    page.runAction = async (action, payload, options) => {
        calls.push({ action, payload, options });
        return { success: true };
    };
    page.openWorkflow = async (payload) => {
        workflowCalls.push(payload);
    };

    try {
        await page.handleFormSubmit(
            {
                dataset: {
                    modelAuthForm: 'browser_callback',
                    providerId: 'google',
                    methodId: 'google_oauth',
                },
                _data: {
                    oauth_project_id: 'demo-google-project',
                    callback_payload: '',
                },
            },
            {
                dataset: {
                    modelAuthSubmitAction: 'start_browser_auth',
                },
            },
        );
    } finally {
        globalThis.FormData = originalFormData;
    }

    assert.deepEqual(calls, [
        {
            action: 'update_provider_defaults',
            payload: {
                provider_id: 'google',
                oauth_project_id: 'demo-google-project',
            },
            options: {
                preserveSelection: true,
                providerId: 'google',
            },
        },
        {
            action: 'start_browser_auth',
            payload: {
                provider_id: 'google',
                method_id: 'google_oauth',
            },
            options: {
                preserveSelection: true,
                providerId: 'google',
            },
        },
    ]);
    assert.deepEqual(workflowCalls, [
        {
            kind: 'browser',
            providerId: 'google',
            methodId: 'google_oauth',
            skipOnboarding: true,
        },
    ]);
});

test('models page local auth workflow persists required fields before binding', async () => {
    const originalFormData = globalThis.FormData;
    const page = new ModelsPage();
    const calls = [];
    let closeCalls = 0;
    globalThis.FormData = class {
        constructor(form) {
            this.map = form._data || {};
        }

        get(name) {
            return this.map[name] ?? null;
        }
    };
    page.getCardByProviderId = () => ({
        provider: {
            id: 'google',
            auth_methods: [
                { id: 'gemini_cli_local', type: 'local_import', label: 'Gemini CLI 本机登录', requires_fields: ['oauth_project_id'] },
            ],
        },
        auth_states: [],
    });
    page.getSelectedCard = () => ({});
    page.runAction = async (action, payload, options) => {
        calls.push({ action, payload, options });
        return { success: true };
    };
    page.closeWorkflowModal = () => {
        closeCalls += 1;
    };

    try {
        await page.handleFormSubmit(
            {
                dataset: {
                    modelAuthForm: 'local_auth',
                    providerId: 'google',
                    methodId: 'gemini_cli_local',
                },
                _data: {
                    oauth_project_id: 'demo-google-project',
                },
            },
            {
                dataset: {
                    modelAuthSubmitAction: 'bind_local_auth',
                },
            },
        );
    } finally {
        globalThis.FormData = originalFormData;
    }

    assert.deepEqual(calls, [
        {
            action: 'update_provider_defaults',
            payload: {
                provider_id: 'google',
                oauth_project_id: 'demo-google-project',
            },
            options: {
                preserveSelection: true,
                providerId: 'google',
            },
        },
        {
            action: 'bind_local_auth',
            payload: {
                provider_id: 'google',
                method_id: 'gemini_cli_local',
                set_default: true,
            },
            options: {
                preserveSelection: true,
                providerId: 'google',
            },
        },
    ]);
    assert.equal(closeCalls, 1);
});

test('models page api key workflow seeds coding plan defaults before saving the first specialized profile', async () => {
    const originalFormData = globalThis.FormData;
    const page = new ModelsPage();
    const calls = [];
    let closeCalls = 0;
    globalThis.FormData = class {
        constructor(form) {
            this.map = form._data || {};
        }

        get(name) {
            return this.map[name] ?? null;
        }
    };
    page.getCardByProviderId = () => ({
        provider: {
            id: 'qwen',
            default_model: 'qwen3.5-plus',
            default_base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
            auth_methods: [
                {
                    id: 'coding_plan_api_key',
                    type: 'api_key',
                    label: 'Coding Plan API Key',
                    metadata: {
                        recommended_model: 'qwen3-coder-next',
                        recommended_base_url: 'https://coding.dashscope.aliyuncs.com/v1',
                    },
                },
            ],
        },
        auth_states: [],
        metadata: {
            default_model: 'qwen3.5-plus',
            default_base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        },
    });
    page.getSelectedCard = () => ({});
    page.runAction = async (action, payload, options) => {
        calls.push({ action, payload, options });
        return { success: true };
    };
    page.closeWorkflowModal = () => {
        closeCalls += 1;
    };

    try {
        await page.handleFormSubmit({
            dataset: {
                modelAuthForm: 'api_key',
                providerId: 'qwen',
                methodId: 'coding_plan_api_key',
            },
            _data: {
                api_key: 'sk-demo-coding-plan',
                label: 'Coding Plan',
            },
        });
    } finally {
        globalThis.FormData = originalFormData;
    }

    assert.deepEqual(calls, [
        {
            action: 'update_provider_defaults',
            payload: {
                provider_id: 'qwen',
                default_model: 'qwen3-coder-next',
                default_base_url: 'https://coding.dashscope.aliyuncs.com/v1',
            },
            options: {
                preserveSelection: true,
                providerId: 'qwen',
            },
        },
        {
            action: 'save_api_key',
            payload: {
                provider_id: 'qwen',
                method_id: 'coding_plan_api_key',
                label: 'Coding Plan',
                api_key: 'sk-demo-coding-plan',
                set_default: true,
            },
            options: {
                preserveSelection: true,
                providerId: 'qwen',
            },
        },
    ]);
    assert.equal(closeCalls, 1);
});

test('models page browser workflow seeds method-specific runtime defaults before starting first Kimi coding auth', async () => {
    const originalFormData = globalThis.FormData;
    const page = new ModelsPage();
    const calls = [];
    const workflowCalls = [];
    globalThis.FormData = class {
        constructor(form) {
            this.map = form._data || {};
        }

        get(name) {
            return this.map[name] ?? null;
        }
    };
    page.getCardByProviderId = () => ({
        provider: {
            id: 'kimi',
            default_model: 'kimi-k2-turbo-preview',
            default_base_url: 'https://api.moonshot.cn/v1',
            auth_methods: [
                {
                    id: 'kimi_code_oauth',
                    type: 'oauth',
                    label: 'Kimi Code OAuth',
                    metadata: {
                        recommended_model: 'kimi-for-coding',
                        recommended_base_url: 'https://api.kimi.com/coding/v1',
                    },
                },
            ],
        },
        auth_states: [],
        metadata: {
            default_model: 'kimi-k2-turbo-preview',
            default_base_url: 'https://api.moonshot.cn/v1',
        },
    });
    page.getSelectedCard = () => ({});
    page.runAction = async (action, payload, options) => {
        calls.push({ action, payload, options });
        return { success: true };
    };
    page.openWorkflow = async (payload) => {
        workflowCalls.push(payload);
    };

    try {
        await page.handleFormSubmit(
            {
                dataset: {
                    modelAuthForm: 'browser_callback',
                    providerId: 'kimi',
                    methodId: 'kimi_code_oauth',
                },
                _data: {
                    callback_payload: '',
                },
            },
            {
                dataset: {
                    modelAuthSubmitAction: 'start_browser_auth',
                },
            },
        );
    } finally {
        globalThis.FormData = originalFormData;
    }

    assert.deepEqual(calls, [
        {
            action: 'update_provider_defaults',
            payload: {
                provider_id: 'kimi',
                default_model: 'kimi-for-coding',
                default_base_url: 'https://api.kimi.com/coding/v1',
            },
            options: {
                preserveSelection: true,
                providerId: 'kimi',
            },
        },
        {
            action: 'start_browser_auth',
            payload: {
                provider_id: 'kimi',
                method_id: 'kimi_code_oauth',
            },
            options: {
                preserveSelection: true,
                providerId: 'kimi',
            },
        },
    ]);
    assert.deepEqual(workflowCalls, [
        {
            kind: 'browser',
            providerId: 'kimi',
            methodId: 'kimi_code_oauth',
            skipOnboarding: true,
        },
    ]);
});

test('models page browser workflow seeds method-specific runtime defaults before starting first Qwen OAuth auth', async () => {
    const originalFormData = globalThis.FormData;
    const page = new ModelsPage();
    const calls = [];
    const workflowCalls = [];
    globalThis.FormData = class {
        constructor(form) {
            this.map = form._data || {};
        }

        get(name) {
            return this.map[name] ?? null;
        }
    };
    page.getCardByProviderId = () => ({
        provider: {
            id: 'qwen',
            default_model: 'qwen3.5-plus',
            default_base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
            auth_methods: [
                {
                    id: 'qwen_oauth',
                    type: 'oauth',
                    label: 'Qwen OAuth',
                    metadata: {
                        recommended_model: 'qwen3-coder-plus',
                        recommended_base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
                    },
                },
            ],
        },
        auth_states: [],
        metadata: {
            default_model: 'qwen3.5-plus',
            default_base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        },
    });
    page.getSelectedCard = () => ({});
    page.runAction = async (action, payload, options) => {
        calls.push({ action, payload, options });
        return { success: true };
    };
    page.openWorkflow = async (payload) => {
        workflowCalls.push(payload);
    };

    try {
        await page.handleFormSubmit(
            {
                dataset: {
                    modelAuthForm: 'browser_callback',
                    providerId: 'qwen',
                    methodId: 'qwen_oauth',
                },
                _data: {
                    callback_payload: '',
                },
            },
            {
                dataset: {
                    modelAuthSubmitAction: 'start_browser_auth',
                },
            },
        );
    } finally {
        globalThis.FormData = originalFormData;
    }

    assert.deepEqual(calls, [
        {
            action: 'update_provider_defaults',
            payload: {
                provider_id: 'qwen',
                default_model: 'qwen3-coder-plus',
            },
            options: {
                preserveSelection: true,
                providerId: 'qwen',
            },
        },
        {
            action: 'start_browser_auth',
            payload: {
                provider_id: 'qwen',
                method_id: 'qwen_oauth',
            },
            options: {
                preserveSelection: true,
                providerId: 'qwen',
            },
        },
    ]);
    assert.deepEqual(workflowCalls, [
        {
            kind: 'browser',
            providerId: 'qwen',
            methodId: 'qwen_oauth',
            skipOnboarding: true,
        },
    ]);
});

test('models page local auth workflow seeds method-specific runtime defaults before binding first Qwen local profile', async () => {
    const originalFormData = globalThis.FormData;
    const page = new ModelsPage();
    const calls = [];
    let closeCalls = 0;
    globalThis.FormData = class {
        constructor(form) {
            this.map = form._data || {};
        }

        get(name) {
            return this.map[name] ?? null;
        }
    };
    page.getCardByProviderId = () => ({
        provider: {
            id: 'qwen',
            default_model: 'qwen3.5-plus',
            default_base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
            auth_methods: [
                {
                    id: 'qwen_local',
                    type: 'local_import',
                    label: 'Qwen Local',
                    metadata: {
                        recommended_model: 'qwen3-coder-plus',
                        recommended_base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
                    },
                },
            ],
        },
        auth_states: [],
        metadata: {
            default_model: 'qwen3.5-plus',
            default_base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        },
    });
    page.getSelectedCard = () => ({});
    page.runAction = async (action, payload, options) => {
        calls.push({ action, payload, options });
        return { success: true };
    };
    page.closeWorkflowModal = () => {
        closeCalls += 1;
    };

    try {
        await page.handleFormSubmit(
            {
                dataset: {
                    modelAuthForm: 'local_auth',
                    providerId: 'qwen',
                    methodId: 'qwen_local',
                },
                _data: {},
            },
            {
                dataset: {
                    modelAuthSubmitAction: 'bind_local_auth',
                },
            },
        );
    } finally {
        globalThis.FormData = originalFormData;
    }

    assert.deepEqual(calls, [
        {
            action: 'update_provider_defaults',
            payload: {
                provider_id: 'qwen',
                default_model: 'qwen3-coder-plus',
            },
            options: {
                preserveSelection: true,
                providerId: 'qwen',
            },
        },
        {
            action: 'bind_local_auth',
            payload: {
                provider_id: 'qwen',
                method_id: 'qwen_local',
                set_default: true,
            },
            options: {
                preserveSelection: true,
                providerId: 'qwen',
            },
        },
    ]);
    assert.equal(closeCalls, 1);
});

test('models page local auth workflow seeds method-specific runtime defaults before binding first Kimi coding profile', async () => {
    const originalFormData = globalThis.FormData;
    const page = new ModelsPage();
    const calls = [];
    let closeCalls = 0;
    globalThis.FormData = class {
        constructor(form) {
            this.map = form._data || {};
        }

        get(name) {
            return this.map[name] ?? null;
        }
    };
    page.getCardByProviderId = () => ({
        provider: {
            id: 'kimi',
            default_model: 'kimi-k2-turbo-preview',
            default_base_url: 'https://api.moonshot.cn/v1',
            auth_methods: [
                {
                    id: 'kimi_code_local',
                    type: 'local_import',
                    label: 'Kimi Code Local',
                    metadata: {
                        recommended_model: 'kimi-for-coding',
                        recommended_base_url: 'https://api.kimi.com/coding/v1',
                    },
                },
            ],
        },
        auth_states: [],
        metadata: {
            default_model: 'kimi-k2-turbo-preview',
            default_base_url: 'https://api.moonshot.cn/v1',
        },
    });
    page.getSelectedCard = () => ({});
    page.runAction = async (action, payload, options) => {
        calls.push({ action, payload, options });
        return { success: true };
    };
    page.closeWorkflowModal = () => {
        closeCalls += 1;
    };

    try {
        await page.handleFormSubmit(
            {
                dataset: {
                    modelAuthForm: 'local_auth',
                    providerId: 'kimi',
                    methodId: 'kimi_code_local',
                },
                _data: {},
            },
            {
                dataset: {
                    modelAuthSubmitAction: 'bind_local_auth',
                },
            },
        );
    } finally {
        globalThis.FormData = originalFormData;
    }

    assert.deepEqual(calls, [
        {
            action: 'update_provider_defaults',
            payload: {
                provider_id: 'kimi',
                default_model: 'kimi-for-coding',
                default_base_url: 'https://api.kimi.com/coding/v1',
            },
            options: {
                preserveSelection: true,
                providerId: 'kimi',
            },
        },
        {
            action: 'bind_local_auth',
            payload: {
                provider_id: 'kimi',
                method_id: 'kimi_code_local',
                set_default: true,
            },
            options: {
                preserveSelection: true,
                providerId: 'kimi',
            },
        },
    ]);
    assert.equal(closeCalls, 1);
});

test('models page keeps existing effective auth when deciding default selection', () => {
    const page = new ModelsPage();

    assert.equal(page.shouldSetDefaultByDefault({
        auth_states: [
            { metadata: { profile_id: 'openai:api_key:default' } },
        ],
    }), false);
    assert.equal(page.shouldSetDefaultByDefault({
        auth_states: [
            { metadata: {} },
        ],
    }), true);
});

test('models page bind local auth does not override existing effective auth by default', async () => {
    const page = new ModelsPage();
    let captured = null;
    page.getCardByProviderId = () => ({
        auth_states: [
            { metadata: { profile_id: 'openai:api_key:default' } },
        ],
    });
    page.getSelectedCard = () => ({});
    page.runAction = async (action, payload) => {
        captured = { action, payload };
        return { success: true };
    };

    await page.handleButtonAction({
        dataset: {
            modelAuthAction: 'bind_local_auth',
            providerId: 'openai',
            methodId: 'codex_local',
        },
    });

    assert.equal(captured.action, 'bind_local_auth');
    assert.equal(captured.payload.set_default, false);
});

test('models page api key form keeps existing effective auth when set_default is omitted', async () => {
    const originalFormData = globalThis.FormData;
    const page = new ModelsPage();
    let captured = null;
    globalThis.FormData = class {
        constructor(form) {
            this.map = form._data || {};
        }

        get(name) {
            return this.map[name] ?? null;
        }
    };
    page.getCardByProviderId = () => ({
        auth_states: [
            { metadata: { profile_id: 'openai:codex_local:chatgpt' } },
        ],
    });
    page.getSelectedCard = () => ({});
    page.runAction = async (action, payload, options) => {
        captured = { action, payload, options };
        return { success: true };
    };
    page.closeWorkflowModal = () => {};

    try {
        await page.handleFormSubmit({
            dataset: {
                modelAuthForm: 'api_key',
                providerId: 'openai',
                methodId: 'api_key',
            },
            _data: {
                api_key: 'demo-openai-test-key',
                label: 'OpenAI API Key',
            },
        });
    } finally {
        globalThis.FormData = originalFormData;
    }

    assert.equal(captured.action, 'save_api_key');
    assert.equal(captured.payload.set_default, false);
});

test('models page provider model form saves defaults and can immediately switch the active model', async () => {
    const originalFormData = globalThis.FormData;
    const page = new ModelsPage();
    const calls = [];
    let closeCalls = 0;
    globalThis.FormData = class {
        constructor(form) {
            this.map = form._data || {};
        }

        get(name) {
            return this.map[name] ?? null;
        }
    };
    page.runAction = async (action, payload, options) => {
        calls.push({ action, payload, options });
        return { success: true };
    };
    page.closeWorkflowModal = () => {
        closeCalls += 1;
    };

    try {
        await page.handleFormSubmit({
            dataset: {
                modelAuthForm: 'provider_model',
                providerId: 'openai',
            },
            _data: {
                default_model_select: 'gpt-4.1',
                custom_model: '',
            },
        });

        await page.handleFormSubmit(
            {
                dataset: {
                    modelAuthForm: 'workflow_model',
                    providerId: 'qwen',
                },
                _data: {
                    default_model_select: '__custom__',
                    custom_model: 'qwen-max-latest',
                },
            },
            {
                dataset: {
                    modelAuthSubmitAction: 'save_and_activate',
                },
            },
        );
    } finally {
        globalThis.FormData = originalFormData;
    }

    assert.deepEqual(calls, [
        {
            action: 'update_provider_defaults',
            payload: {
                provider_id: 'openai',
                default_model: 'gpt-4.1',
                force_sync_selected_profile: true,
            },
            options: {
                preserveSelection: true,
                providerId: 'openai',
            },
        },
        {
            action: 'update_provider_defaults',
            payload: {
                provider_id: 'qwen',
                default_model: 'qwen-max-latest',
                force_sync_selected_profile: true,
            },
            options: {
                preserveSelection: true,
                providerId: 'qwen',
            },
        },
        {
            action: 'set_active_provider',
            payload: {
                provider_id: 'qwen',
            },
            options: {
                preserveSelection: true,
                providerId: 'qwen',
            },
        },
    ]);
    assert.equal(closeCalls, 1);
});

test('models page prefers saved provider default model when no auth profile is bound', () => {
    const page = new ModelsPage();
    page.applyModelCatalog({
        providers: [
            {
                id: 'openai',
                label: 'OpenAI',
                default_model: 'gpt-5.4-mini',
                models: ['gpt-5.4-mini', 'gpt-4.1'],
                auth_methods: [{ id: 'api_key', type: 'api_key', label: 'API Key' }],
            },
        ],
    });

    const markup = page.renderProviderDetail({
        provider: { id: 'openai', label: 'OpenAI', default_model: 'gpt-5.4-mini', models: ['gpt-5.4-mini', 'gpt-4.1'] },
        state: 'not_configured',
        selected_method_id: 'api_key',
        auth_states: [
            {
                method_id: 'api_key',
                status: 'not_configured',
                metadata: {
                    model: 'gpt-5.4-mini',
                    base_url: 'https://api.openai.com/v1',
                },
            },
        ],
        metadata: {
            default_model: 'gpt-4.1',
            default_base_url: 'https://api.openai.com/v1',
            can_set_active_provider: false,
            is_active_provider: false,
            provider_sync: { code: 'unsupported' },
            provider_health: { code: 'idle', message: '' },
        },
    });

    assert.match(markup, /<option value="gpt-4\.1" selected>/);
});

test('models page keeps overview provider defaults when merging catalog metadata', () => {
    const page = new ModelsPage();
    page.applyModelCatalog({
        providers: [
            {
                id: 'openai',
                label: 'OpenAI',
                default_model: 'gpt-5.4-mini',
                base_url: 'https://api.openai.com/v1',
                auth_methods: [{ id: 'api_key', type: 'api_key', label: 'API Key' }],
            },
        ],
    });

    const merged = page.getProvider('openai', {
        id: 'openai',
        label: 'OpenAI',
        default_model: 'gpt-4.1',
        base_url: 'https://api.openai-proxy.example/v1',
        metadata: { source: 'overview' },
    });

    assert.equal(merged.default_model, 'gpt-4.1');
    assert.equal(merged.base_url, 'https://api.openai-proxy.example/v1');
    assert.equal(merged.metadata?.source, 'overview');
});

test('models page summary counters and dangerous actions stay in the unified flow', async () => {
    assert.deepEqual(
        summarizeCards([
            { state: 'connected' },
            { state: 'following_local_auth' },
            { state: 'available_to_import' },
            { state: 'error' },
        ]),
        { connected: 2, localReady: 2, attention: 1 },
    );

    const page = new ModelsPage();
    let confirmCalls = 0;
    let actionCalls = 0;
    page.confirmAction = async () => {
        confirmCalls += 1;
        return false;
    };
    page.runAction = async () => {
        actionCalls += 1;
    };

    await page.handleButtonAction({
        dataset: {
            modelAuthAction: 'disconnect_profile',
            providerId: 'openai',
            methodId: 'api_key',
            profileId: 'openai:api_key:default',
        },
    });

    assert.equal(confirmCalls, 1);
    assert.equal(actionCalls, 0);
});

test('models page sorts cards by active, ready, local, attention and fallback name', () => {
    const cards = [
        { provider: { id: 'zhipu', label: 'GLM' }, state: 'not_configured', metadata: {} },
        { provider: { id: 'deepseek', label: 'DeepSeek' }, state: 'error', metadata: {} },
        { provider: { id: 'ollama', label: 'Ollama' }, state: 'available_to_import', metadata: {} },
        { provider: { id: 'claude', label: 'Claude' }, state: 'not_configured', metadata: { can_set_active_provider: true } },
        { provider: { id: 'openai', label: 'OpenAI' }, state: 'connected', metadata: { is_active_provider: true, can_set_active_provider: true } },
    ];

    assert.deepEqual(
        sortCardsForDisplay(cards).map((card) => card.provider.id),
        ['openai', 'claude', 'ollama', 'deepseek', 'zhipu'],
    );

    const page = new ModelsPage();
    page._overview = { cards };
    page._listFilter = 'all';
    page._searchQuery = '';

    assert.deepEqual(
        page.getVisibleCards().map((card) => card.provider.id),
        ['openai', 'claude', 'ollama', 'deepseek', 'zhipu'],
    );
});

test('models page falls back to the first sorted visible provider when current selection is filtered out', () => {
    const page = new ModelsPage();
    page.renderWorkflowModal = () => {};
    page._overview = {
        cards: [
            { provider: { id: 'zhipu', label: 'GLM' }, state: 'not_configured', metadata: {} },
            { provider: { id: 'openai', label: 'OpenAI' }, state: 'connected', metadata: { is_active_provider: true, can_set_active_provider: true } },
            { provider: { id: 'claude', label: 'Claude' }, state: 'not_configured', metadata: { can_set_active_provider: true } },
        ],
    };
    page._selectedProviderId = 'zhipu';
    page._listFilter = 'ready';
    page._searchQuery = '';

    const nodes = {
        '#model-auth-hero': { innerHTML: '' },
        '#model-auth-filter-row': { innerHTML: '' },
        '#model-auth-provider-grid': { innerHTML: '' },
        '#model-auth-detail-panel': { innerHTML: '' },
        '#model-auth-sidebar-meta': { textContent: '' },
    };
    page.$ = (selector) => nodes[selector] || null;

    page.render();

    assert.equal(page._selectedProviderId, 'openai');
    assert.match(nodes['#model-auth-provider-grid'].innerHTML, /OpenAI/);
});

test('models page renders compact detail sections with the new fold structure', () => {
    const page = new ModelsPage();
    page.applyModelCatalog({
        providers: [
            {
                id: 'openai',
                label: 'OpenAI',
                models: ['gpt-5.4'],
                auth_methods: [
                    { id: 'api_key', type: 'api_key', label: 'API Key' },
                ],
            },
        ],
    });

    const markup = page.renderProviderDetail({
        provider: { id: 'openai', label: 'OpenAI' },
        state: 'connected',
        selected_label: 'Work API Key',
        auth_states: [
            {
                method_id: 'api_key',
                status: 'connected',
                default_selected: true,
                actions: [{ id: 'show_api_key_form' }],
                metadata: {
                    profile_id: 'openai:api_key:default',
                    runtime_ready: true,
                    model: 'gpt-5.4',
                },
            },
        ],
        metadata: {
            is_active_provider: true,
            can_set_active_provider: true,
            default_model: 'gpt-5.4',
            provider_sync: { code: 'following_local_auth', source_message: '本机已同步' },
            provider_health: { code: 'healthy', message: '连接正常' },
        },
    });

    assert.match(markup, /快速操作/);
    assert.match(markup, /认证方式/);
    assert.match(markup, /运行状态/);
    assert.match(markup, /更多设置/);
    assert.equal(markup.includes('model-center-detail-section model-center-detail-section-primary" open'), true);
});

test('models page summary bar exposes focus and connection actions for the active provider', () => {
    const page = new ModelsPage();
    page._selectedProviderId = 'anthropic';
    page.applyModelCatalog({
        providers: [
            {
                id: 'openai',
                label: 'OpenAI',
                models: ['gpt-5.4'],
                auth_methods: [
                    { id: 'api_key', type: 'api_key', label: 'API Key' },
                ],
            },
        ],
    });

    const cards = [
        {
            provider: { id: 'openai', label: 'OpenAI', default_model: 'gpt-5.4' },
            state: 'connected',
            selected_label: 'Work API Key',
            auth_states: [
                {
                    method_id: 'api_key',
                    status: 'connected',
                    default_selected: true,
                    metadata: {
                        profile_id: 'openai:api_key:default',
                        runtime_ready: true,
                        account_email: 'work@example.com',
                        model: 'gpt-5.4',
                    },
                },
            ],
            metadata: {
                is_active_provider: true,
                can_set_active_provider: true,
                default_model: 'gpt-5.4',
                provider_sync: { code: 'following_local_auth', source_message: '本机已同步' },
                provider_health: { code: 'healthy', message: '连接正常', checked_at: 1_700_000_000 },
            },
        },
    ];

    const markup = page.renderSummaryBar(cards, summarizeCards(cards), cards[0]);

    assert.match(markup, /查看当前服务方/);
    assert.match(markup, /测试当前连接/);
    assert.match(markup, /默认认证/);
    assert.match(markup, /连接健康/);
});
test('models page keeps a current-connection test button for active legacy preset fallback', () => {
    const page = new ModelsPage();

    const card = {
        provider: { id: 'ollama', label: 'Ollama', default_model: 'deepseek-v3.2:cloud' },
        state: 'connected',
        selected_profile_id: '',
        selected_method_id: '',
        selected_label: 'API Key',
        auth_states: [
            {
                method_id: 'api_key',
                status: 'connected',
                actions: [{ id: 'show_api_key_form' }],
                metadata: {
                    runtime_ready: true,
                    model: 'deepseek-v3.2:cloud',
                },
            },
        ],
        metadata: {
            is_active_provider: true,
            can_set_active_provider: false,
            legacy_preset_name: 'Ollama',
            default_model: 'deepseek-v3.2:cloud',
            provider_sync: { code: 'unsupported' },
            provider_health: { code: 'idle', message: '' },
        },
    };

    const summaryMarkup = page.renderSummaryBar([card], summarizeCards([card]), card);
    const detailMarkup = page.renderProviderDetail(card);

    assert.match(summaryMarkup, /测试当前连接/);
    assert.match(detailMarkup, /测试连接/);
    assert.match(summaryMarkup, /data-model-auth-ui="test_current_connection"/);
    assert.equal(page.getHealthSummary(card), '待绑定');
    assert.match(page.getHealthDetail(card), /先测试一次连接|完成认证绑定/);
});

test('models page current connection test falls back to legacy preset probing when no profile is selected', async () => {
    const originalTestConnection = apiService.testConnection;
    const originalToastSuccess = toast.success;
    const originalToastError = toast.error;
    const page = new ModelsPage();
    const calls = [];

    apiService.testConnection = async (presetName) => {
        calls.push(presetName);
        return {
            success: true,
            message: 'Ollama 当前连接测试成功',
        };
    };
    toast.success = (message) => {
        calls.push(`toast:${message}`);
    };
    toast.error = (message) => {
        calls.push(`error:${message}`);
    };
    page.renderFeedback = (message, type = 'success') => {
        calls.push(`feedback:${type}:${message}`);
    };
    page.getCardByProviderId = () => ({
        provider: { id: 'ollama', label: 'Ollama' },
        selected_profile_id: '',
        auth_states: [
            {
                method_id: 'api_key',
                status: 'connected',
                actions: [{ id: 'show_api_key_form' }],
                metadata: {
                    runtime_ready: true,
                },
            },
        ],
        metadata: {
            is_active_provider: true,
            legacy_preset_name: 'Ollama',
            provider_health: { code: 'idle', message: '' },
        },
    });
    page.getSelectedCard = () => ({});

    try {
        await page.handleButtonAction({
            dataset: {
                modelAuthUi: 'test_current_connection',
                providerId: 'ollama',
            },
        });
    } finally {
        apiService.testConnection = originalTestConnection;
        toast.success = originalToastSuccess;
        toast.error = originalToastError;
    }

    assert.deepEqual(calls, [
        'Ollama',
        'feedback:success:Ollama 当前连接测试成功',
        'toast:Ollama 当前连接测试成功',
    ]);
});
