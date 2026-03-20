import test from 'node:test';
import assert from 'node:assert/strict';

import {
    checkUpdates,
    openUpdateDownload,
    previewPrompt,
    resetCloseBehavior,
    saveSettings,
} from '../../src/renderer/js/pages/settings/action-controller.js';
import {
    bindSettingsAutoSave,
    bindSettingsEvents,
} from '../../src/renderer/js/pages/settings/page-shell.js';
import {
    loadSettings,
    scheduleAutoSave,
    shouldRefreshAudit,
} from '../../src/renderer/js/pages/settings/runtime-sync.js';
import {
    commitPresetModal,
    openPresetModal,
} from '../../src/renderer/js/pages/settings/preset-controller.js';
import { apiService } from '../../src/renderer/js/services/ApiService.js';
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
                providers: [{ id: 'openai', label: 'OpenAI', default_model: 'gpt-4.1' }],
            },
        });

        await withDom(async () => {
            const calls = [];
            const page = {
                _config: null,
                _configAudit: null,
                _modelCatalog: null,
                _providersById: new Map(),
                _presetDrafts: [],
                _activePreset: '',
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
                _renderPresetList() {
                    calls.push('preset-list');
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
                _warmOllamaModels() {
                    calls.push('warm-models');
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
            assert.equal(page._activePreset, 'default');
            assert.equal(page._presetDrafts.length, 1);
            assert.equal(page._providersById.get('openai')?.label, 'OpenAI');
            assert.equal(page._lastConfigVersion, 4);
            assert.deepEqual(calls, [
                'warm-models',
                'fill',
                'preset-list',
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
    const providerSelect = {
        listeners: {},
        addEventListener(type, handler) {
            this.listeners[type] = handler;
        },
    };
    const modelSelect = {
        listeners: {},
        addEventListener(type, handler) {
            this.listeners[type] = handler;
        },
    };
    const modal = registerElement('preset-modal', document.createElement('div'));
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
        _checkUpdates() {
            this.calls.push('check');
        },
        _openUpdateDownload() {
            this.calls.push('download');
        },
        _resetCloseBehavior() {
            this.calls.push('reset');
        },
        _scrollToTop() {
            this.calls.push('top');
        },
        _openPresetModal() {
            this.calls.push('open-modal');
        },
        _closePresetModal() {
            this.calls.push('close-modal');
        },
        _commitPresetModal() {
            this.calls.push('commit-modal');
        },
        _togglePresetKeyVisibility() {
            this.calls.push('toggle-key');
        },
        _handlePresetProviderChange() {
            this.calls.push('provider-change');
        },
        _syncPresetModelInput() {
            this.calls.push('model-sync');
        },
        _scheduleAutoSave(options) {
            this.calls.push(`autosave:${options.immediate}`);
        },
        calls: [],
        $(selector) {
            return {
                '#edit-preset-provider': providerSelect,
                '#edit-preset-model-select': modelSelect,
            }[selector] || null;
        },
    };

    bindSettingsEvents(page, {
        documentObj: document,
        windowObj: {},
    });
    bindSettingsAutoSave(page, {
        rootElement: root,
    });

    assert.equal(page.bindings.length, 11);
    assert.equal(page._eventCleanups.length, 1);

    page.bindings[0].handler();
    page.bindings[1].handler();
    page.bindings[2].handler();
    providerSelect.listeners.change();
    modelSelect.listeners.change();
    modal.classList.add('active');
    page.bindings.at(-1).handler({ key: 'Escape' });
    rootListeners.input({ target: { id: 'setting-group-at-only', tagName: 'INPUT', type: 'checkbox' } });
    rootListeners.change({ target: { id: 'setting-log-level', tagName: 'SELECT' } });
    rootListeners.input({ target: { id: 'unknown-field', tagName: 'INPUT', type: 'text' } });

    assert.deepEqual(page.calls, [
        'load',
        'save',
        'preview',
        'provider-change',
        'model-sync',
        'close-modal',
        'autosave:true',
        'autosave:true',
    ]);
}));
