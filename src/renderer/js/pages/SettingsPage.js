import { PageController } from '../core/PageController.js';
import { apiService } from '../services/ApiService.js';
import { toast } from '../services/NotificationService.js';
import { FIELD_META_BY_ID } from './settings/schema.js';
import {
    collectSettingsPayload,
    createElement,
    deepClone,
    fillSettingsForm,
} from './settings/form-codec.js';
import {
    commitPresetModal,
    createDefaultPreset,
    createModelKindBadge,
    fillPresetModal,
    formatModelOptionLabel,
    getActivePresetDraft,
    getEffectivePreset,
    getOllamaBaseUrl,
    getPresetByName,
    getPresetModelMeta,
    getProviderLabel,
    getRuntimePresetDraft,
    handlePresetProviderChange,
    inferOllamaModelKind,
    isOllamaPreset,
    loadOllamaModels,
    openPresetModal,
    populateModelOptions,
    populateProviderOptions,
    removePreset,
    resolveProviderModels,
    runPresetConnectionTest,
    setHeroTestFeedback,
    syncPresetModelInput,
    testPreset,
    testPresetByName,
    togglePresetKeyVisibility,
    updatePresetHelpLink,
    warmOllamaModels,
    closePresetModal,
} from './settings/preset-service.js';
import {
    renderExportRagStatus,
    renderPresetList,
    renderSaveFeedback,
    renderSettingsHero,
    renderUpdatePanel,
} from './settings/renderers.js';

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
        this._auditPromise = null;
        this._auditRequestId = 0;
        this._auditStatus = 'idle';
        this._auditMessage = '';
        this._lastConfigVersion = 0;
        this._isSaving = false;
        this._queuedAutoSave = false;
        this._autoSaveTimer = null;
        this._removeConfigListener = null;
        this._mainContent = null;
        this._scrollTopButton = null;
        this._ollamaModelCache = new Map();
        this._ollamaModelPromise = new Map();
        this._heroTestFeedback = null;
    }

    async onInit() {
        await super.onInit();
        this._bindEvents();
        this._bindAutoSaveEvents();
        this._initModuleSaveButtons();
        this._initScrollControls();
        this._watchUpdaterState();
        this._watchConfigChanges();
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

        this.bindEvent(window, 'keydown', (event) => {
            if (event.key === 'Escape' && document.getElementById('preset-modal')?.classList.contains('active')) {
                this._closePresetModal();
            }
        });
    }

    _bindAutoSaveEvents() {
        const root = document.getElementById(this.containerId);
        if (!root) {
            return;
        }

        const schedule = (event) => {
            const target = event?.target;
            if (!(target instanceof HTMLElement)) {
                return;
            }
            const id = target.id || '';
            if (!FIELD_META_BY_ID.has(id)) {
                return;
            }
            const immediate = target instanceof HTMLInputElement
                ? target.type === 'checkbox'
                : target instanceof HTMLSelectElement;
            this._scheduleAutoSave({ immediate });
        };

        root.addEventListener('input', schedule, true);
        root.addEventListener('change', schedule, true);
    }

    _watchConfigChanges() {
        if (!window.electronAPI?.onConfigChanged || this._removeConfigListener) {
            return;
        }
        const subscription = window.electronAPI.configSubscribe?.();
        if (subscription?.catch) {
            subscription.catch(() => {});
        }
        this._removeConfigListener = window.electronAPI.onConfigChanged(() => {
            if (this._isSaving) {
                return;
            }
            void this.loadSettings({ silent: true, preserveFeedback: true });
        });
    }

    _scheduleAutoSave(options = {}) {
        if (!this._loaded) {
            return;
        }
        const { immediate = false } = options;
        if (this._autoSaveTimer) {
            clearTimeout(this._autoSaveTimer);
            this._autoSaveTimer = null;
        }
        const trigger = () => {
            this._autoSaveTimer = null;
            void this._saveSettings({ silentToast: true });
        };
        if (immediate) {
            trigger();
            return;
        }
        this._renderSaveFeedback({ success: true, save_state: 'saving', message: '保存中...' });
        this._autoSaveTimer = setTimeout(trigger, 700);
    }

    _watchUpdaterState() {
        [
            'updater.enabled', 'updater.checking', 'updater.available', 'updater.currentVersion',
            'updater.latestVersion', 'updater.lastCheckedAt', 'updater.releaseDate', 'updater.error',
            'updater.skippedVersion', 'updater.downloading', 'updater.downloadProgress',
            'updater.readyToInstall', 'updater.downloadedVersion',
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
        this.watchState('bot.connected', () => {
            if (!this._loaded) {
                if (this.isActive()) {
                    this._renderHero();
                }
                return;
            }
            if (!this.getState('bot.connected')) {
                this._auditRequestId += 1;
                this._auditPromise = null;
                this._configAudit = null;
                this._auditStatus = 'offline';
                this._auditMessage = '';
                if (this.isActive()) {
                    this._renderHero();
                }
                return;
            }
            if (this.isActive()) {
                this._renderHero();
            }
            if (this._shouldRefreshAudit()) {
                void this._loadConfigAudit({ silent: true });
            }
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
                const configResult = window.electronAPI?.configGet
                    ? await window.electronAPI.configGet()
                    : await apiService.getConfig();

                if (!configResult?.success) {
                    throw new Error(configResult?.message || TEXT.loadFailed);
                }

                this._config = {
                    api: deepClone(configResult.api || {}),
                    bot: deepClone(configResult.bot || {}),
                    logging: deepClone(configResult.logging || {}),
                    agent: deepClone(configResult.agent || {}),
                    services: deepClone(configResult.services || {}),
                };
                this._modelCatalog = configResult?.modelCatalog || { providers: [] };
                this._providersById = new Map((this._modelCatalog.providers || []).map((provider) => [provider.id, provider]));
                this._presetDrafts = deepClone(this._config.api.presets || []);
                this._activePreset = String(this._config.api.active_preset || '').trim();
                void this._warmOllamaModels();
                const runtimeVersion = Number(this.getState('bot.status.config_snapshot.version') || 0);
                if (!this.getState('bot.connected')) {
                    this._configAudit = null;
                    this._auditStatus = 'offline';
                    this._auditMessage = '';
                } else if (!this._configAudit) {
                    this._auditStatus = 'idle';
                    this._auditMessage = '';
                }
                this._lastConfigVersion = Number(this._configAudit?.version || runtimeVersion || 0);

                this._fillForm();
                this._renderPresetList();
                this._renderHero();
                this._renderUpdatePanel();
                this._renderExportRagStatus();
                if (!preserveFeedback) {
                    this._hideSaveFeedback();
                }
                this._loaded = true;
                if (this._shouldRefreshAudit() || !silent) {
                    void this._loadConfigAudit({ silent: true, force: !silent });
                }
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

    _shouldRefreshAudit() {
        if (!this._loaded || !this.getState('bot.connected')) {
            return false;
        }
        if (this._auditPromise) {
            return false;
        }
        const runtimeVersion = Number(this.getState('bot.status.config_snapshot.version') || 0);
        const auditVersion = Number(this._configAudit?.version || 0);
        return !this._configAudit
            || this._auditStatus === 'idle'
            || this._auditStatus === 'error'
            || (runtimeVersion > 0 && runtimeVersion > auditVersion);
    }

    async _loadConfigAudit(options = {}) {
        if (!this._config || !this._loaded) {
            return null;
        }
        if (!this.getState('bot.connected')) {
            this._auditRequestId += 1;
            this._auditPromise = null;
            this._auditStatus = 'offline';
            this._auditMessage = '';
            if (this.isActive()) {
                this._renderHero();
            }
            return { success: false, message: TEXT.noAudit };
        }

        const { silent = true, force = false } = options;
        if (this._auditPromise && !force) {
            return this._auditPromise;
        }

        const requestId = ++this._auditRequestId;
        this._auditStatus = 'loading';
        this._auditMessage = '';
        if (this.isActive()) {
            this._renderHero();
        }

        this._auditPromise = (async () => {
            try {
                const result = await apiService.getConfigAudit();
                if (requestId !== this._auditRequestId) {
                    return result;
                }
                if (!result?.success) {
                    throw new Error(result?.message || TEXT.noAudit);
                }
                this._configAudit = result;
                this._auditStatus = 'ready';
                this._auditMessage = '';
                this._lastConfigVersion = Number(result.version || this._lastConfigVersion || 0);
                if (this.isActive()) {
                    this._renderHero();
                }
                return result;
            } catch (error) {
                if (requestId !== this._auditRequestId) {
                    return null;
                }
                console.warn('[SettingsPage] audit unavailable:', error);
                this._auditStatus = 'error';
                this._auditMessage = toast.getErrorMessage(error, TEXT.noAudit);
                if (this.isActive()) {
                    this._renderHero();
                }
                if (!silent) {
                    toast.warning(this._auditMessage);
                }
                return { success: false, message: this._auditMessage };
            } finally {
                if (requestId === this._auditRequestId) {
                    this._auditPromise = null;
                }
            }
        })();

        return this._auditPromise;
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
        fillSettingsForm(this, this._config, scope);
    }

    _collectPayload(scope = null) {
        return collectSettingsPayload(this, scope, {
            activePreset: this._activePreset,
            presetDrafts: this._presetDrafts,
        });
    }

    async _saveSettings(options = {}) {
        const { scope = null, triggerButton = null, silentToast = false } = options;
        if (this._isSaving) {
            this._queuedAutoSave = true;
            return;
        }
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
            const result = window.electronAPI?.configPatch
                ? await window.electronAPI.configPatch(payload)
                : await apiService.saveConfig(payload);
            if (!result?.success) {
                throw new Error(result?.message || TEXT.saveFailed);
            }

            await this.loadSettings({ silent: true, preserveFeedback: true });
            this._renderHero(true);
            this._renderSaveFeedback(result);
            this._renderExportRagStatus();
            this._setSavingState(false, triggerButton);
            if (!silentToast) {
                toast.success(result?.runtime_apply?.message || result?.message || '配置已保存');
            }
        } catch (error) {
            console.error('[SettingsPage] save failed:', error);
            this._renderSaveFeedback({ success: false, message: toast.getErrorMessage(error, TEXT.saveFailed) });
            this._setSavingState(false, triggerButton);
            if (!silentToast) {
                toast.error(toast.getErrorMessage(error, TEXT.saveFailed));
            }
        } finally {
            if (this._queuedAutoSave) {
                this._queuedAutoSave = false;
                this._scheduleAutoSave({ immediate: true });
            }
        }
    }

    async _previewPrompt() {
        try {
            if (!this.getState('bot.connected')) {
                throw new Error('预览 Prompt 需要先启动 Python 服务');
            }
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
        const readyToInstall = !!this.getState('updater.readyToInstall');

        if (readyToInstall && window.electronAPI?.installDownloadedUpdate) {
            const result = await window.electronAPI.installDownloadedUpdate();
            if (!result?.success) {
                toast.warning(result?.error || '启动更新安装失败');
                return;
            }
            toast.info('正在退出应用并启动安装程序...');
            return;
        }

        if (window.electronAPI?.downloadUpdate && this.getState('updater.enabled')) {
            const result = await window.electronAPI.downloadUpdate();
            if (!result?.success) {
                toast.warning(result?.error || '下载安装包失败');
                return;
            }
            toast.info(result?.alreadyDownloaded ? '更新安装包已下载完成' : '开始下载更新，请稍候...');
            return;
        }

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

    _getPresetByName(name) {
        return getPresetByName(this, name);
    }

    _getRuntimePresetDraft() {
        return getRuntimePresetDraft(this);
    }

    _getActivePresetDraft() {
        return getActivePresetDraft(this);
    }

    _getEffectivePreset() {
        return getEffectivePreset(this);
    }

    _getProviderLabel(providerId) {
        return getProviderLabel(this, providerId);
    }

    _isOllamaPreset(preset) {
        return isOllamaPreset(preset);
    }

    _inferOllamaModelKind(modelName) {
        return inferOllamaModelKind(modelName);
    }

    _getPresetModelMeta(preset, overrideModel = '') {
        return getPresetModelMeta(this, preset, overrideModel);
    }

    _createModelKindBadge(meta, extraClassName = '') {
        return createModelKindBadge(meta, extraClassName);
    }

    _setHeroTestFeedback(presetName, state, message) {
        setHeroTestFeedback(this, presetName, state, message);
    }

    _getOllamaBaseUrl(providerOrPreset) {
        return getOllamaBaseUrl(providerOrPreset);
    }

    async _loadOllamaModels(baseUrl) {
        return loadOllamaModels(this, baseUrl);
    }

    async _warmOllamaModels() {
        await warmOllamaModels(this);
    }

    _formatModelOptionLabel(providerId, modelName) {
        return formatModelOptionLabel(providerId, modelName);
    }

    _renderHero(highlight = false) {
        renderSettingsHero(this, highlight);
    }

    _renderPresetList() {
        renderPresetList(this);
    }

    async _testPresetByName(presetName, detailElement = null) {
        await testPresetByName(this, presetName, detailElement);
    }

    async _runPresetConnectionTest(preset, detailElement) {
        await runPresetConnectionTest(this, preset, detailElement);
    }

    async _testPreset(index, detailElement) {
        await testPreset(this, index, detailElement);
    }

    _removePreset(index) {
        removePreset(this, index);
    }

    _openPresetModal(index = -1) {
        openPresetModal(this, index);
    }

    _closePresetModal() {
        closePresetModal(this);
    }

    _createDefaultPreset() {
        return createDefaultPreset(this);
    }

    _populateProviderOptions(selectedId) {
        populateProviderOptions(this, selectedId);
    }

    _fillPresetModal(preset) {
        fillPresetModal(this, preset);
    }

    async _handlePresetProviderChange() {
        await handlePresetProviderChange(this);
    }

    async _resolveProviderModels(provider) {
        return resolveProviderModels(this, provider);
    }

    async _populateModelOptions(providerId, selectedModel) {
        await populateModelOptions(this, providerId, selectedModel);
    }

    _syncPresetModelInput() {
        syncPresetModelInput(this);
    }

    _updatePresetHelpLink(providerId) {
        updatePresetHelpLink(this, providerId);
    }

    _togglePresetKeyVisibility() {
        togglePresetKeyVisibility(this);
    }

    _commitPresetModal() {
        commitPresetModal(this, TEXT);
    }

    _renderUpdatePanel() {
        renderUpdatePanel(this);
    }

    _renderSaveFeedback(result) {
        renderSaveFeedback(this, result, TEXT.saveFailed);
    }

    _hideSaveFeedback() {
        if (this.$('#config-save-feedback')) {
            this.$('#config-save-feedback').hidden = true;
        }
    }

    _renderExportRagStatus() {
        renderExportRagStatus(this);
    }
}

export default SettingsPage;
