import { PageController } from '../core/PageController.js';
import {
    collectSettingsPayload,
    fillSettingsForm,
} from './settings/form-codec.js';
import {
    previewPrompt,
    resetCloseBehavior,
    saveSettings,
} from './settings/action-controller.js';
import {
    closePresetModal,
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
} from './settings/preset-controller.js';
import {
    handleMainScroll,
    hideSaveFeedback,
    initModuleSaveButtons,
    initScrollControls,
    renderHero,
    renderLoadError,
    renderPageExportRagStatus,
    renderPageSaveFeedback,
    renderPresetCards,
    scrollToTop,
    setSavingState,
} from './settings/page-chrome.js';
import {
    bindSettingsAutoSave,
    bindSettingsEvents,
} from './settings/page-shell.js';
import {
    loadConfigAudit,
    loadSettings,
    maybeRefreshForRuntimeConfigChange,
    scheduleAutoSave,
    shouldRefreshAudit,
    watchConfigChanges,
    watchUpdaterState,
} from './settings/runtime-sync.js';

const TEXT = {
    loading: '加载设置中...',
    loadFailed: '加载设置失败',
    saveFailed: '保存设置失败',
    previewFailed: '预览 Prompt 失败',
    updateFailed: '检查更新失败',
    resetCloseSuccess: '已恢复默认关闭行为',
    presetMissing: '当前配置中没有可用的 API 预设',
    presetNameMissing: '预设名称不能为空',
    presetModelMissing: '请选择或填写模型名称',
    presetSaveSuccess: '预设已保存，相关配置会在下次保存设置后生效',
    noAudit: '当前没有可用的配置审计信息',
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
        bindSettingsEvents(this);
        bindSettingsAutoSave(this);
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
        }
    }

    _watchConfigChanges() {
        watchConfigChanges(this);
    }

    _scheduleAutoSave(options = {}) {
        scheduleAutoSave(this, options);
    }

    _watchUpdaterState() {
        watchUpdaterState(this);
    }

    async loadSettings(options = {}) {
        return loadSettings(this, options, TEXT);
    }

    _shouldRefreshAudit() {
        return shouldRefreshAudit(this);
    }

    async _loadConfigAudit(options = {}) {
        return loadConfigAudit(this, options, TEXT);
    }

    _initModuleSaveButtons() {
        initModuleSaveButtons(this);
    }

    _initScrollControls() {
        initScrollControls(this);
    }

    _handleMainScroll() {
        handleMainScroll(this);
    }

    _scrollToTop() {
        scrollToTop(this);
    }

    _maybeRefreshForRuntimeConfigChange() {
        maybeRefreshForRuntimeConfigChange(this);
    }

    _setSavingState(isSaving, triggerButton = null) {
        setSavingState(this, isSaving, triggerButton);
    }

    _renderLoadError(message) {
        renderLoadError(this, message);
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
        await saveSettings(this, options, TEXT);
    }

    async _previewPrompt() {
        await previewPrompt(this, TEXT);
    }

    async _resetCloseBehavior() {
        await resetCloseBehavior(TEXT);
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
        return isOllamaPreset(this, preset);
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
        renderHero(this, highlight);
    }

    _renderPresetList() {
        renderPresetCards(this);
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

    _renderSaveFeedback(result) {
        renderPageSaveFeedback(this, result, TEXT.saveFailed);
    }

    _hideSaveFeedback() {
        hideSaveFeedback(this);
    }

    _renderExportRagStatus() {
        renderPageExportRagStatus(this);
    }
}

export default SettingsPage;
