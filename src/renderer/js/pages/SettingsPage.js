import { PageController } from '../core/PageController.js';
import {
    collectSettingsPayload,
    fillSettingsForm,
} from './settings/form-codec.js';
import {
    formatBackupSize,
    getBackupModeMeta,
    renderBackupPanel,
} from './settings/backup-panel.js';
import {
    previewPrompt,
    resetCloseBehavior,
    saveSettings,
} from './settings/action-controller.js';
import {
    handleMainScroll,
    hideSaveFeedback,
    initModuleSaveButtons,
    initScrollControls,
    renderHero,
    renderLoadError,
    renderPageExportRagStatus,
    renderPageSaveFeedback,
    scrollToTop,
    setSavingState,
} from './settings/page-chrome.js';
import {
    bindSettingsAutoSave,
    bindSettingsEvents,
} from './settings/page-shell.js';
import { FIELD_META_BY_ID } from './settings/schema.js';
import { apiService } from '../services/ApiService.js';
import { toast } from '../services/NotificationService.js';
import {
    clearPendingLocalAuthSyncRefresh,
    loadConfigAudit,
    loadSettings,
    maybeRefreshForRuntimeConfigChange,
    shouldRefreshAudit,
    watchConfigChanges,
    watchUpdaterState,
} from './settings/runtime-sync.js';
import { renderSettingsPageShell } from '../app-shell/pages/index.js';

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

function serializeSettingsPayload(payload) {
    return JSON.stringify(payload || {});
}

const SETTINGS_CARD_META = new Map([
    ['模型与认证', { groups: ['workspace', 'common'], order: 10 }],
    ['机器人设置', { groups: ['bot', 'common'], order: 20 }],
    ['系统提示', { groups: ['prompt', 'common'], order: 30 }],
    ['提示词预览', { groups: ['prompt'], order: 40 }],
    ['记忆与上下文', { groups: ['memory', 'common'], order: 50 }],
    ['群聊与发送', { groups: ['delivery', 'common'], order: 60 }],
    ['白名单管理', { groups: ['guard', 'common'], order: 70 }],
    ['表情与语音', { groups: ['bot'], order: 80 }],
    ['微信连接与传输', { groups: ['bot'], order: 90 }],
    ['备份与恢复', { groups: ['workspace'], order: 100 }],
    ['轮询与延迟', { groups: ['delivery'], order: 110 }],
    ['合并与发送', { groups: ['delivery'], order: 120 }],
    ['智能分段', { groups: ['delivery'], order: 130 }],
    ['向量记忆与 RAG', { groups: ['memory'], order: 140 }],
    ['热更新与重连', { groups: ['workspace'], order: 150 }],
    ['控制命令', { groups: ['delivery'], order: 160 }],
    ['静默时段与限额', { groups: ['guard'], order: 170 }],
    ['过滤与白名单', { groups: ['guard'], order: 175 }],
    ['过滤规则', { groups: ['guard'], order: 180 }],
    ['定时静默', { groups: ['guard'], order: 190 }],
    ['成长与画像', { groups: ['quality'], order: 200 }],
    ['用量监控', { groups: ['guard'], order: 210 }],
    ['个性化', { groups: ['quality'], order: 220 }],
    ['情感识别', { groups: ['quality'], order: 230 }],
    ['LangChain Runtime', { groups: ['quality'], order: 240 }],
    ['日志与调试', { groups: ['quality'], order: 250 }],
    ['日志设置', { groups: ['quality'], order: 250 }],
    ['关闭行为', { groups: ['workspace'], order: 260 }],
]);

function resolveSettingsCardMeta(title = '') {
    const matched = SETTINGS_CARD_META.get(String(title || '').trim());
    if (matched) {
        return {
            groups: [...matched.groups],
            order: matched.order,
        };
    }
    return {
        groups: ['quality'],
        order: 999,
    };
}

function getSettingsCardGroups(card) {
    return String(card?.dataset?.settingsGroups || card?.dataset?.settingsGroup || '')
        .split(/[\s,]+/)
        .map((item) => item.trim())
        .filter(Boolean);
}

export class SettingsPage extends PageController {
    constructor() {
        super('SettingsPage', 'page-settings');
        this._config = null;
        this._configAudit = null;
        this._loaded = false;
        this._loadingPromise = null;
        this._auditPromise = null;
        this._auditRequestId = 0;
        this._auditStatus = 'idle';
        this._auditMessage = '';
        this._lastConfigVersion = 0;
        this._localAuthSyncState = null;
        this._localAuthSyncRefreshTimer = null;
        this._localAuthSyncRefreshAttempt = 0;
        this._pendingConfigReload = false;
        this._isSaving = false;
        this._queuedAutoSave = false;
        this._autoSaveTimer = null;
        this._removeConfigListener = null;
        this._mainContent = null;
        this._scrollTopButton = null;
        this._backupState = {
            backups: [],
            summary: {},
            latestEval: null,
            restoreFeedback: '',
            dataControlFeedback: '',
            supportedDataControlScopes: [],
            backupBusy: false,
            dataControlBusy: false,
            dataControlDryRunScope: '',
        };
        this._backupPromise = null;
        this._activeSettingsSection = 'common';
        this._hasPendingChanges = false;
        this._baselineSettingsPayload = serializeSettingsPayload({});
        this._baselineCardPayloads = new Map();
    }

    async onInit() {
        await super.onInit();
        const container = this.container || (typeof document !== 'undefined' ? this.getContainer() : null);
        if (container) {
            container.innerHTML = renderSettingsPageShell();
        }
        this._hydrateSettingsSections();
        bindSettingsEvents(this);
        bindSettingsAutoSave(this);
        this._initModuleSaveButtons();
        this._renderWorkbenchState();
        this._setSettingsSection(this._activeSettingsSection);
        this._initScrollControls();
        this._watchUpdaterState();
        this._watchConfigChanges();
    }

    async onEnter() {
        await super.onEnter();
        this._handleMainScroll();
        const runtimeVersion = Number(this.getState('bot.status.config_snapshot.version') || 0);
        if (
            this._pendingConfigReload
            || !this._loaded
            || (runtimeVersion && runtimeVersion > this._lastConfigVersion)
            || this._localAuthSyncState?.refreshing
        ) {
            await this.loadSettings({ preserveFeedback: true });
        } else {
            this._renderHero();
        }
        await this._loadWorkspaceBackups({ silent: true });
    }

    async onLeave() {
        clearPendingLocalAuthSyncRefresh(this);
        await super.onLeave();
    }

    async onDestroy() {
        clearPendingLocalAuthSyncRefresh(this);
        await super.onDestroy();
    }

    _watchConfigChanges() {
        watchConfigChanges(this);
    }

    _scheduleAutoSave(options = {}) {
        this._trackPendingChanges(options);
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
        this._renderWorkbenchState();
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
        this._renderWorkbenchState();
    }

    _renderLoadError(message) {
        renderLoadError(this, message);
    }

    _fillForm(scope = null) {
        fillSettingsForm(this, this._config, scope);
    }

    _collectPayload(scope = null) {
        const nextScope = scope
            ? { ...scope, includeApiPresets: false }
            : { includeApiPresets: false };
        return collectSettingsPayload(this, nextScope);
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

    _renderHero(highlight = false) {
        renderHero(this, highlight);
        this._renderWorkbenchState();
    }

    _renderSaveFeedback(result) {
        renderPageSaveFeedback(this, result, TEXT.saveFailed);
        this._renderWorkbenchState();
    }

    _hideSaveFeedback() {
        hideSaveFeedback(this);
        this._renderWorkbenchState();
    }

    _renderExportRagStatus() {
        renderPageExportRagStatus(this);
    }

    _renderBackupPanel() {
        renderBackupPanel(this);
    }

    _syncDataControlScopeOptions(scopes = []) {
        const select = this.$('#settings-data-control-scope');
        if (!select || typeof document === 'undefined' || typeof document.createElement !== 'function') {
            return;
        }
        const normalized = Array.from(
            new Set(
                (Array.isArray(scopes) ? scopes : [])
                    .map((item) => String(item || '').trim())
                    .filter(Boolean),
            ),
        );
        const previousValue = String(select.value || '').trim();
        select.textContent = '';

        const placeholder = document.createElement('option');
        placeholder.value = '';
        placeholder.textContent = normalized.length ? '请选择清理范围' : '暂无可清理范围';
        select.appendChild(placeholder);

        normalized.forEach((scope) => {
            const option = document.createElement('option');
            option.value = scope;
            option.textContent = scope;
            select.appendChild(option);
        });

        if (normalized.includes(previousValue)) {
            select.value = previousValue;
        } else {
            select.value = '';
        }
        if (this._backupState.dataControlDryRunScope && !normalized.includes(this._backupState.dataControlDryRunScope)) {
            this._backupState.dataControlDryRunScope = '';
        }
    }

    _buildDataControlFailureMessage(error, fallback) {
        const baseMessage = toast.getErrorMessage(error, fallback);
        const payload = (error && typeof error === 'object') ? error.data : null;
        const failedTargets = Array.isArray(payload?.failed_targets) ? payload.failed_targets : [];
        if (!failedTargets.length) {
            return baseMessage;
        }
        const details = failedTargets
            .slice(0, 3)
            .map((item) => String(item?.relative_path || item?.path || '').trim())
            .filter(Boolean)
            .join(', ');
        return details
            ? `${baseMessage}（失败 ${failedTargets.length} 项：${details}）`
            : `${baseMessage}（失败 ${failedTargets.length} 项）`;
    }

    async _loadWorkspaceBackups(options = {}) {
        const { silent = false } = options;
        if (this._backupPromise) {
            return this._backupPromise;
        }

        this._backupPromise = (async () => {
            try {
                const [backupsResult, evalResult, dataControlsResult] = await Promise.all([
                    apiService.getBackups(10),
                    apiService.getLatestEvalReport(),
                    apiService.getDataControls().catch(() => null),
                ]);
                const supportedDataControlScopes = Array.isArray(dataControlsResult?.supported_scopes)
                    ? dataControlsResult.supported_scopes
                    : (this._backupState.supportedDataControlScopes || []);
                this._backupState = {
                    backups: Array.isArray(backupsResult?.backups) ? backupsResult.backups : [],
                    summary: backupsResult?.summary || {},
                    latestEval: evalResult?.report || null,
                    restoreFeedback: this._backupState.restoreFeedback || '',
                    dataControlFeedback: this._backupState.dataControlFeedback || '',
                    supportedDataControlScopes,
                    backupBusy: !!this._backupState.backupBusy,
                    dataControlBusy: !!this._backupState.dataControlBusy,
                    dataControlDryRunScope: this._backupState.dataControlDryRunScope || '',
                };
                this._syncDataControlScopeOptions(supportedDataControlScopes);
                this._renderBackupPanel();
                return this._backupState;
            } catch (error) {
                if (!silent) {
                    toast.error(toast.getErrorMessage(error, '加载备份信息失败'));
                }
                this._backupState = {
                    backups: [],
                    summary: {},
                    latestEval: null,
                    restoreFeedback: '加载备份信息失败',
                    dataControlFeedback: this._backupState.dataControlFeedback || '',
                    supportedDataControlScopes: this._backupState.supportedDataControlScopes || [],
                    backupBusy: !!this._backupState.backupBusy,
                    dataControlBusy: !!this._backupState.dataControlBusy,
                    dataControlDryRunScope: this._backupState.dataControlDryRunScope || '',
                };
                this._syncDataControlScopeOptions(this._backupState.supportedDataControlScopes || []);
                this._renderBackupPanel();
                return this._backupState;
            } finally {
                this._backupPromise = null;
            }
        })();

        return this._backupPromise;
    }

    async _createWorkspaceBackup(mode) {
        if (this._backupState.backupBusy) {
            toast.info('备份任务执行中，请稍候...');
            return;
        }
        this._backupState.backupBusy = true;
        this._backupState.restoreFeedback = '正在创建备份，请稍候...';
        this._renderBackupPanel();
        try {
            const result = await apiService.createBackup(mode);
            if (!result?.success) {
                throw new Error(result?.message || '创建备份失败');
            }
            const meta = getBackupModeMeta(mode, result?.backup?.id);
            this._backupState.restoreFeedback = `已保存一份${meta.label}，可以在下方时间点列表里找到它。`;
            this._renderBackupPanel();
            toast.success(`已保存一份${meta.label}`);
            await this._loadWorkspaceBackups({ silent: true });
        } catch (error) {
            toast.error(toast.getErrorMessage(error, '创建备份失败'));
        } finally {
            this._backupState.backupBusy = false;
            this._renderBackupPanel();
        }
    }

    async _restoreWorkspaceBackup(dryRun = false) {
        if (this._backupState.backupBusy) {
            toast.info('备份任务执行中，请稍候...');
            return;
        }
        const backupId = String(this.$('#settings-backup-select')?.value || '').trim();
        if (!backupId) {
            toast.info('请先选择一个可恢复时间点');
            return;
        }
        this._backupState.backupBusy = true;
        this._backupState.restoreFeedback = dryRun ? '正在检查备份完整性...' : '正在执行备份恢复...';
        this._renderBackupPanel();

        try {
            const requestRestore = async (allowLegacyUnverified = false) => apiService.restoreBackup({
                backup_id: backupId,
                dry_run: !!dryRun,
                ...(allowLegacyUnverified ? { allow_legacy_unverified: true } : {}),
            });
            const detectLegacyBlocked = (error) => {
                const plan = (error && typeof error === 'object') ? error?.data?.plan : null;
                const message = String((error && typeof error === 'object') ? error?.message || '' : '').toLowerCase();
                return !!(plan?.legacy_unverified || message.includes('allow_legacy_unverified'));
            };

            let legacyOptIn = false;
            let result;
            try {
                result = await requestRestore(false);
            } catch (error) {
                if (!detectLegacyBlocked(error)) {
                    throw error;
                }
                const confirmLegacyRestore = typeof window !== 'undefined' && typeof window.confirm === 'function'
                    ? window.confirm('该历史备份缺少校验摘要，无法进行完整性校验。是否继续恢复？')
                    : false;
                if (!confirmLegacyRestore) {
                    const message = '已取消恢复：该历史备份缺少校验摘要。';
                    this._backupState.restoreFeedback = message;
                    this._renderBackupPanel();
                    toast.info(message);
                    return;
                }
                legacyOptIn = true;
                result = await requestRestore(true);
            }
            if (!result?.success && !dryRun) {
                throw new Error(result?.message || '恢复备份失败');
            }

            if (dryRun) {
                const plan = result?.plan || {};
                this._backupState.restoreFeedback = legacyOptIn
                    ? `检查完成，本次预计会恢复 ${plan.included_files?.length || 0} 个文件。该备份缺少校验摘要，应用恢复时将按确认继续。`
                    : `检查完成，本次预计会恢复 ${plan.included_files?.length || 0} 个文件。`;
                toast.success('恢复检查完成');
            } else {
                const authChecks = result?.auth_restore_checks || {};
                const warningCount = Number(authChecks?.warning_count || 0);
                this._backupState.restoreFeedback = warningCount > 0
                    ? `已恢复到所选时间点，保险备份：${result?.pre_restore_backup?.id || '--'}，认证告警 ${warningCount} 项`
                    : `已恢复到所选时间点，保险备份：${result?.pre_restore_backup?.id || '--'}`;
                toast.success('已恢复到所选时间点');
                if (warningCount > 0) {
                    toast.warning(`恢复后检测到 ${warningCount} 项认证风险，请在模型认证中心检查`);
                }
                if (legacyOptIn) {
                    toast.warning('本次恢复使用了 legacy 模式（缺少校验摘要）。建议立即创建一份新备份。');
                }
                await this.loadSettings({ silent: true, preserveFeedback: true });
            }

            this._renderBackupPanel();
            await this._loadWorkspaceBackups({ silent: true });
        } catch (error) {
            const message = toast.getErrorMessage(error, '恢复备份失败');
            this._backupState.restoreFeedback = message;
            this._renderBackupPanel();
            toast.error(message);
        } finally {
            this._backupState.backupBusy = false;
            this._renderBackupPanel();
        }
    }

    async _cleanupWorkspaceBackups(dryRun = true) {
        if (this._backupState.backupBusy) {
            toast.info('备份任务执行中，请稍候...');
            return;
        }
        this._backupState.backupBusy = true;
        this._backupState.restoreFeedback = dryRun ? '正在检查可清理备份...' : '正在清理旧备份...';
        this._renderBackupPanel();
        try {
            const result = await apiService.cleanupBackups({
                dry_run: !!dryRun,
            });
            if (!result?.success) {
                throw new Error(result?.message || '清理旧备份失败');
            }

            const sizeText = dryRun
                ? formatBackupSize(result?.reclaimable_bytes)
                : formatBackupSize(result?.reclaimed_bytes);
            this._backupState.restoreFeedback = dryRun
                ? `已检查可清理的旧备份，共 ${result?.candidate_count || 0} 份，预计可释放 ${sizeText}。`
                : `已清理 ${result?.deleted_count || 0} 份旧备份，已释放 ${sizeText}。`;
            this._renderBackupPanel();
            await this._loadWorkspaceBackups({ silent: true });
            toast.success(dryRun ? '旧备份检查完成' : '旧备份清理完成');
        } catch (error) {
            const message = toast.getErrorMessage(error, '清理旧备份失败');
            this._backupState.restoreFeedback = message;
            this._renderBackupPanel();
            toast.error(message);
        } finally {
            this._backupState.backupBusy = false;
            this._renderBackupPanel();
        }
    }

    async _runDataControls(dryRun = true) {
        if (this._backupState.dataControlBusy || this._backupState.backupBusy) {
            return;
        }

        const selectedScope = String(this.$('#settings-data-control-scope')?.value || '').trim();
        if (!selectedScope) {
            const message = '请先选择清理范围';
            this._backupState.dataControlFeedback = message;
            this._renderBackupPanel();
            toast.info(message);
            return;
        }

        if (!dryRun) {
            if (this._backupState.dataControlDryRunScope !== selectedScope) {
                const message = '请先对当前范围执行一次检查，再执行清理';
                this._backupState.dataControlFeedback = message;
                this._renderBackupPanel();
                toast.info(message);
                return;
            }
            const botRunning = !!this.getState('bot.running');
            const growthRunning = !!this.getState('bot.status.growth_running');
            if (botRunning || growthRunning) {
                const runningServices = [
                    botRunning ? '机器人' : '',
                    growthRunning ? '成长任务' : '',
                ].filter(Boolean).join('、');
                const message = `请先停止${runningServices}后再执行数据清理`;
                this._backupState.dataControlFeedback = message;
                this._renderBackupPanel();
                toast.info(message);
                return;
            }
            const confirmApply = typeof window !== 'undefined' && typeof window.confirm === 'function'
                ? window.confirm(`确认要清理 ${selectedScope} 范围的数据吗？该操作不可撤销。`)
                : true;
            if (!confirmApply) {
                return;
            }
        }

        this._backupState.dataControlBusy = true;
        this._backupState.dataControlFeedback = dryRun ? `正在检查 ${selectedScope} ...` : `正在清理 ${selectedScope} ...`;
        this._renderBackupPanel();
        try {
            const result = await apiService.clearDataControls({
                scopes: [selectedScope],
                dry_run: !!dryRun,
            });
            if (!result?.success) {
                throw new Error(result?.message || 'data cleanup failed');
            }

            const sizeText = dryRun
                ? formatBackupSize(result?.reclaimable_bytes)
                : formatBackupSize(result?.reclaimed_bytes);
            this._backupState.dataControlFeedback = dryRun
                ? `检查完成：${selectedScope} 可清理 ${result?.existing_target_count || 0} 项，预计释放 ${sizeText}`
                : `清理完成：${selectedScope} 已删除 ${result?.deleted_count || 0} 项，释放 ${sizeText}`;
            this._backupState.dataControlDryRunScope = dryRun ? selectedScope : '';
            this._renderBackupPanel();
            toast.success(dryRun ? '数据清理检查完成' : '数据清理已执行');
        } catch (error) {
            const message = this._buildDataControlFailureMessage(error, '数据清理失败');
            this._backupState.dataControlFeedback = message;
            this._backupState.dataControlDryRunScope = '';
            this._renderBackupPanel();
            toast.error(message);
        } finally {
            this._backupState.dataControlBusy = false;
            this._renderBackupPanel();
        }
        return;
    }

    _hydrateSettingsSections() {
        this.$$('.settings-card').forEach((card) => {
            const title = String(card.querySelector('.settings-card-title')?.textContent || '').trim();
            const meta = resolveSettingsCardMeta(title);
            card.dataset.settingsGroup = meta.groups[0] || 'quality';
            card.dataset.settingsGroups = meta.groups.join(' ');
            if (card.style) {
                card.style.order = String(meta.order);
            }
        });
    }

    _setSettingsSection(section = 'all') {
        const normalized = String(section || 'all').trim() || 'all';
        this._activeSettingsSection = normalized;

        this.$$('#settings-section-nav [data-settings-section]').forEach((button) => {
            const active = button.dataset.settingsSection === normalized;
            button.classList.toggle('active', active);
            button.setAttribute('aria-pressed', active ? 'true' : 'false');
        });

        this.$$('.settings-card').forEach((card) => {
            const groups = getSettingsCardGroups(card);
            const visible = normalized === 'all' || groups.includes(normalized);
            card.hidden = !visible;
        });

        this._scrollToTop();
    }

    _getCardScopeMeta(card) {
        if (!card) {
            return null;
        }
        const ids = new Set(
            Array.from(card.querySelectorAll('[id]'))
                .map((element) => element.id)
                .filter((id) => FIELD_META_BY_ID.has(id)),
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
            title: String(card.querySelector('.settings-card-title')?.textContent || '').trim() || '当前模块',
            ids,
            sections,
            includeApiPresets,
        };
    }

    _captureBaselinePayloads() {
        this._baselineSettingsPayload = serializeSettingsPayload(this._collectPayload());
        this._baselineCardPayloads = new Map();
        this.$$('.settings-card').forEach((card, index) => {
            const cardKey = card.dataset.settingsCardKey || String(index);
            const scope = this._getCardScopeMeta(card);
            card.dataset.settingsCardKey = cardKey;
            if (!scope) {
                return;
            }
            this._baselineCardPayloads.set(cardKey, serializeSettingsPayload(this._collectPayload(scope)));
        });
    }

    _resetDirtyState() {
        this._hasPendingChanges = false;
        this.$$('.settings-card.is-dirty').forEach((card) => card.classList.remove('is-dirty'));
        if (this._loaded && this._config) {
            this._captureBaselinePayloads();
        }
        this._renderWorkbenchState();
    }

    _trackPendingChanges(options = {}) {
        if (!this._loaded || !this._config) {
            return;
        }
        if (!this._baselineCardPayloads.size) {
            this._captureBaselinePayloads();
        }

        const payload = this._collectPayload();
        this._hasPendingChanges = serializeSettingsPayload(payload) !== this._baselineSettingsPayload;

        this.$$('.settings-card').forEach((card, index) => {
            const cardKey = card.dataset.settingsCardKey || String(index);
            const scope = this._getCardScopeMeta(card);
            if (!scope) {
                card.classList.remove('is-dirty');
                return;
            }
            card.dataset.settingsCardKey = cardKey;
            const currentPayload = serializeSettingsPayload(this._collectPayload(scope));
            const baselinePayload = this._baselineCardPayloads.get(cardKey) || serializeSettingsPayload({});
            card.classList.toggle('is-dirty', currentPayload !== baselinePayload);
        });

        this._renderWorkbenchState();
    }

    _renderWorkbenchState() {
        const dirtyStatus = this.$('#settings-dirty-status');
        const capabilityStatus = this.$('#settings-capability-status');
        const connected = !!this.getState('bot.connected');
        const previewButton = this.$('#btn-preview-prompt');
        const saveButton = this.$('#btn-save-settings');

        if (dirtyStatus) {
            if (this._isSaving) {
                dirtyStatus.textContent = '正在写入配置...';
                dirtyStatus.dataset.state = 'saving';
            } else if (this._hasPendingChanges) {
                dirtyStatus.textContent = '有未保存改动';
                dirtyStatus.dataset.state = 'warning';
            } else {
                dirtyStatus.textContent = '当前内容已同步';
                dirtyStatus.dataset.state = 'ready';
            }
        }

        if (capabilityStatus) {
            capabilityStatus.textContent = connected
                ? '已连接 Python 服务，可预览 Prompt 并检查运行状态'
                : '未连接 Python 服务，预览与运行检查暂不可用';
            capabilityStatus.dataset.state = connected ? 'ready' : 'warning';
        }

        if (previewButton) {
            previewButton.disabled = !connected;
            previewButton.title = connected ? '生成当前设置下的最终 Prompt 预览' : '请先连接 Python 服务后再预览';
        }

        if (saveButton && !this._isSaving) {
            saveButton.disabled = !this._hasPendingChanges;
        }

        this.$$('.settings-card').forEach((card) => {
            const button = card.querySelector('[data-card-save-button]');
            if (!button || this._isSaving) {
                return;
            }
            button.disabled = !card.classList.contains('is-dirty');
        });
    }
}

export default SettingsPage;


