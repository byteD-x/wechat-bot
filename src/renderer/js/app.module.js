/**
 * 微信 AI 助手渲染进程入口。
 */

if (typeof window !== 'undefined' && typeof window.dragEvent === 'undefined') {
    window.dragEvent = window.DragEvent;
}

import { stateManager, eventBus, Events } from './core/index.js';
import { apiService, notificationService } from './services/index.js';
import { DashboardPage, CostsPage, MessagesPage, ModelsPage, SettingsPage, LogsPage, AboutPage } from './pages/index.js';
import { renderAppFrame } from './app-shell/frame.js';
import {
    buildDisconnectedStatus,
    buildUpdateBadgeState,
    buildVersionText,
    getConnectionStatusView,
    normalizeRuntimeIdleState,
    renderUpdateModalContent,
} from './app/ui-helpers.js';
import {
    buildUnavailableReadinessReport,
    getReadinessBlockingChecks,
    normalizeReadinessReport,
    shouldCompleteFirstRun,
    shouldShowFirstRunGuide,
} from './app/readiness-helpers.js';

const DEFAULT_IDLE_DELAY_MS = 15 * 60 * 1000;
const AUTO_WAKE_PAGES = new Set(['dashboard', 'costs', 'messages', 'models', 'logs']);

function ensureAppFrame() {
    if (typeof document === 'undefined' || !document.body || document.body.dataset.appFrameReady === 'true') {
        return;
    }
    document.body.classList.add('no-select');
    document.body.innerHTML = renderAppFrame();
    document.body.dataset.appFrameReady = 'true';
}

ensureAppFrame();

class App {
    constructor() {
        this.pages = {
            dashboard: new DashboardPage(),
            costs: new CostsPage(),
            messages: new MessagesPage(),
            models: new ModelsPage(),
            settings: new SettingsPage(),
            logs: new LogsPage(),
            about: new AboutPage()
        };

        this.currentPage = null;
        this._statusTimer = null;
        this._statusRefreshing = false;
        this._statusFailureCount = 0;
        this._statusBaseIntervalMs = 5000;
        this._statusMaxIntervalMs = 30000;
        this._backendStartAttempted = false;
        this._readinessRefreshing = false;
        this._lastReadinessRefreshAt = 0;
        this._readinessMinIntervalMs = 8000;
        this._statusPausedByVisibility = false;
        this._lastUpdateToastVersion = '';
        this._lastUpdateModalVersion = '';
        this._confirmModalResolver = null;
        this._removeUpdateListener = null;
        this._removeRuntimeIdleListener = null;
        this._eventSource = null;
        this._sseReconnectTimer = null;
        this._sseReconnectAttempt = 0;
    }

    async init() {
        console.log('[App] 正在初始化...');

        notificationService.init();
        await this._runInitStep('apiService.init', () => apiService.init());
        await this._runInitStep('_setupRuntimeIdleState', () => this._setupRuntimeIdleState());
        await this._runInitStep('_loadFirstRunState', () => this._loadFirstRunState());

        await this._runInitStep('_setupVersion', () => this._setupVersion());
        await this._runInitStep('_setupUpdater', () => this._setupUpdater());

        this._bindGlobalEvents();
        this._bindKeyboardShortcuts();
        this._setupCloseChoiceModal();
        this._setupConfirmModal();
        this._setupUpdateModal();
        this._setupFirstRunGuide();

        for (const [pageName, page] of Object.entries(this.pages)) {
            await this._runInitStep(`${pageName}.onInit`, () => page.onInit());
        }

        await this._runInitStep('_ensureLightweightBackend', () => this._ensureLightweightBackend());
        await this._runInitStep('_checkBackendConnection', () => this._checkBackendConnection());
        await this._runInitStep('_refreshStatus', () => this._refreshStatus());
        await this._runInitStep('_switchPage', () => this._switchPage('dashboard', { source: 'init' }));
        this._startStatusRefresh();
        console.log('[App] 初始化完成');

    }

    async _runInitStep(stepName, fn) {
        try {
            return await fn();
        } catch (error) {
            console.error(`[App] 初始化步骤失败: ${stepName}`, error);
            notificationService.error(`初始化步骤失败：${stepName}`);
            return null;
        }
    }

    async _setupVersion() {
        if (!window.electronAPI?.getAppVersion) {
            return;
        }

        const version = await window.electronAPI.getAppVersion();
        stateManager.set('updater.currentVersion', version);
        this._updateVersionText();
    }

    async _setupUpdater() {
        if (!window.electronAPI?.getUpdateState) {
            this._updateSidebarUpdateBadge();
            return;
        }

        const initialState = await window.electronAPI.getUpdateState();
        this._applyUpdateState(initialState, { silent: true });
        this._maybePromptForUpdate({ forceReadyToInstall: true });

        this._removeUpdateListener = window.electronAPI.onUpdateStateChanged?.((nextState) => {
            this._applyUpdateState(nextState);
        }) || null;
    }

    async _setupRuntimeIdleState() {
        if (window.electronAPI?.getRuntimeIdleState) {
            try {
                const initialState = await window.electronAPI.getRuntimeIdleState();
                this._applyRuntimeIdleState(initialState, { silent: true });
            } catch (error) {
                console.warn('[App] load runtime idle state failed:', error);
            }
        }

        if (window.electronAPI?.onRuntimeIdleStateChanged) {
            this._removeRuntimeIdleListener = window.electronAPI.onRuntimeIdleStateChanged((nextState) => {
                this._applyRuntimeIdleState(nextState);
            }) || null;
        }
    }

    _normalizeRuntimeIdleState(idleState = {}) {
        return normalizeRuntimeIdleState(idleState, DEFAULT_IDLE_DELAY_MS);
    }

    _applyRuntimeIdleState(idleState, options = {}) {
        const nextState = this._normalizeRuntimeIdleState(idleState);
        stateManager.set('backend.idle', nextState);

        if (nextState.state === 'stopped_by_idle') {
            const previousStatus = stateManager.get('bot.status');
            this._clearSSEReconnectTimer();
            this._closeSSE();
            this._applyDisconnectedRuntimeState(previousStatus, { idleState: nextState });
            this._scheduleNextStatusRefresh(null);
        }
        this._updateConnectionStatus();
    }

    _getRuntimeIdleState() {
        return stateManager.get('backend.idle') || this._normalizeRuntimeIdleState();
    }

    _isIdleStopped() {
        return this._getRuntimeIdleState().state === 'stopped_by_idle';
    }

    async _reportRuntimeStatus(status) {
        if (!window.electronAPI?.runtimeReportStatus || !status || typeof status !== 'object') {
            return;
        }
        try {
            const result = await window.electronAPI.runtimeReportStatus({
                botRunning: !!(status.bot_running ?? status.running),
                growthRunning: !!status.growth_running,
            });
            if (result?.idle_state) {
                this._applyRuntimeIdleState(result.idle_state, { silent: true });
            }
        } catch (error) {
            console.warn('[App] report runtime status failed:', error);
        }
    }

    _applyUpdateState(updateState, options = {}) {
        if (!updateState || typeof updateState !== 'object') {
            return;
        }

        const previousAvailable = stateManager.get('updater.available');
        const previousVersion = stateManager.get('updater.latestVersion');

        stateManager.batchUpdate({
            'updater.enabled': !!updateState.enabled,
            'updater.checking': !!updateState.checking,
            'updater.available': !!updateState.available,
            'updater.currentVersion': updateState.currentVersion || stateManager.get('updater.currentVersion') || '',
            'updater.latestVersion': updateState.latestVersion || '',
            'updater.lastCheckedAt': updateState.lastCheckedAt || '',
            'updater.releaseDate': updateState.releaseDate || '',
            'updater.downloadUrl': updateState.downloadUrl || '',
            'updater.releasePageUrl': updateState.releasePageUrl || '',
            'updater.notes': Array.isArray(updateState.notes) ? updateState.notes : [],
            'updater.error': updateState.error || '',
            'updater.skippedVersion': updateState.skippedVersion || '',
            'updater.downloading': !!updateState.downloading,
            'updater.downloadProgress': Number(updateState.downloadProgress || 0),
            'updater.readyToInstall': !!updateState.readyToInstall,
            'updater.downloadedVersion': updateState.downloadedVersion || '',
            'updater.downloadedInstallerPath': updateState.downloadedInstallerPath || ''
        });

        this._updateVersionText();
        this._updateSidebarUpdateBadge();
        this._renderUpdateModal();

        const nextVersion = updateState.latestVersion || '';
        if (
            updateState.available &&
            (!previousAvailable || previousVersion !== nextVersion) &&
            !options.silent &&
            this._lastUpdateToastVersion !== nextVersion
        ) {
            this._lastUpdateToastVersion = nextVersion;
            notificationService.info(`发现新版本 v${nextVersion}，可在关于页下载更新。`, 5000);
        }

        this._maybePromptForUpdate(options);
    }

    _updateVersionText() {
        const versionElem = document.getElementById('version-text');
        if (!versionElem) {
            return;
        }
        versionElem.textContent = buildVersionText({
            currentVersion: stateManager.get('updater.currentVersion') || '--',
            checking: !!stateManager.get('updater.checking'),
            available: !!stateManager.get('updater.available'),
            latestVersion: stateManager.get('updater.latestVersion') || '',
            enabled: !!stateManager.get('updater.enabled'),
            downloading: !!stateManager.get('updater.downloading'),
            downloadProgress: Number(stateManager.get('updater.downloadProgress') || 0),
            readyToInstall: !!stateManager.get('updater.readyToInstall'),
        });
    }
    _updateSidebarUpdateBadge() {
        const badge = document.getElementById('update-badge');
        if (!badge) {
            return;
        }
        const nextState = buildUpdateBadgeState({
            available: !!stateManager.get('updater.available'),
            latestVersion: stateManager.get('updater.latestVersion') || '',
            checking: !!stateManager.get('updater.checking'),
            downloading: !!stateManager.get('updater.downloading'),
            downloadProgress: Number(stateManager.get('updater.downloadProgress') || 0),
            readyToInstall: !!stateManager.get('updater.readyToInstall'),
        });
        badge.hidden = nextState.hidden;
        badge.textContent = nextState.text;
        badge.disabled = nextState.disabled;
    }
    async _checkBackendConnection() {
        let connected = false;

        if (window.electronAPI?.checkBackend) {
            connected = await window.electronAPI.checkBackend();
        } else {
            try {
                await apiService.getStatus();
                connected = true;
            } catch {
                connected = false;
            }
        }

        stateManager.set('bot.connected', connected);
        this._updateConnectionStatus();
    }

    async _ensureLightweightBackend() {
        if (this._backendStartAttempted) {
            return;
        }

        let connected = false;
        try {
            if (window.electronAPI?.checkBackend) {
                connected = await window.electronAPI.checkBackend();
            } else {
                await apiService.getStatus();
                connected = true;
            }
        } catch {
            connected = false;
        }

        if (connected) {
            this._backendStartAttempted = true;
            return;
        }

        if (!window.electronAPI?.runtimeEnsureService && !window.electronAPI?.startBackend) {
            return;
        }

        this._backendStartAttempted = true;

        try {
            if (window.electronAPI?.runtimeEnsureService) {
                await window.electronAPI.runtimeEnsureService();
            } else {
                await window.electronAPI.startBackend();
            }
        } catch (error) {
            console.warn('[App] lightweight backend bootstrap failed:', error);
        }
    }

    async _startBackendWithFeedback() {
        try {
            notificationService.info('正在启动 Python 服务...');
            await this._wakeBackend();

            if (!stateManager.get('bot.connected')) {
                notificationService.error('Python 服务启动失败，请检查环境或日志');
            } else {
                notificationService.success('Python 服务已连接');
            }
        } catch (error) {
            console.error('[App] backend start failed:', error);
            notificationService.error('Python 服务启动失败，请检查环境或日志');
        }
    }

    async _wakeBackend() {
        if (window.electronAPI?.runtimeEnsureService) {
            await window.electronAPI.runtimeEnsureService();
        } else if (window.electronAPI?.startBackend) {
            await window.electronAPI.startBackend();
        }

        if (window.electronAPI?.getRuntimeIdleState) {
            try {
                const idleState = await window.electronAPI.getRuntimeIdleState();
                this._applyRuntimeIdleState(idleState, { silent: true });
            } catch (error) {
                console.warn('[App] refresh runtime idle state failed:', error);
            }
        }

        await this._refreshStatus({ force: true });
        this._connectSSE();
    }

    async _ensureBackendForPage(pageName, options = {}) {
        const source = String(options?.source || '').trim();
        if (
            source === 'init'
            || !AUTO_WAKE_PAGES.has(pageName)
            || stateManager.get('bot.connected')
            || !this._isIdleStopped()
        ) {
            return;
        }

        try {
            await this._wakeBackend();
        } catch (error) {
            console.warn(`[App] wake backend for page failed: ${pageName}`, error);
        }
    }

    _bindGlobalEvents() {
        document.querySelectorAll('.nav-item').forEach(item => {
            item.addEventListener('click', (event) => {
                event.preventDefault();
                this._switchPage(item.dataset.page, { source: 'nav' });
            });
        });

        document.getElementById('btn-minimize')?.addEventListener('click', () => {
            window.electronAPI?.minimizeWindow();
        });

        document.getElementById('btn-maximize')?.addEventListener('click', () => {
            window.electronAPI?.maximizeWindow();
        });

        document.getElementById('btn-close')?.addEventListener('click', () => {
            window.electronAPI?.closeWindow();
        });

        document.getElementById('status-badge')?.addEventListener('click', () => {
            if (
                !(window.electronAPI?.runtimeEnsureService || window.electronAPI?.startBackend)
                || stateManager.get('bot.connected')
            ) {
                return;
            }
            this._startBackendWithFeedback();
        });

        document.getElementById('update-badge')?.addEventListener('click', async () => {
            if (stateManager.get('updater.available') || stateManager.get('updater.readyToInstall')) {
                this._openUpdateModal();
                return;
            }
            await this._switchPage('about', { source: 'update-badge' });
        });

        if (window.electronAPI?.onTrayAction) {
            window.electronAPI.onTrayAction((action) => {
                if (action === 'start-bot' && !stateManager.get('bot.running')) {
                    eventBus.emit(Events.BOT_START, {});
                } else if (action === 'stop-bot' && stateManager.get('bot.running')) {
                    eventBus.emit(Events.BOT_STOP, {});
                }
            });
        }

        eventBus.on(Events.PAGE_CHANGE, pageName => {
            this._switchPage(pageName, { source: 'event' });
        });

        eventBus.on(Events.BOT_STATUS_CHANGE, (options = {}) => {
            this._refreshStatus(options);
        });

        document.addEventListener('visibilitychange', () => {
            if (document.hidden) {
                this._statusPausedByVisibility = true;
                this._scheduleNextStatusRefresh(null);
            } else if (this._statusPausedByVisibility) {
                this._statusPausedByVisibility = false;
                if (!this._isIdleStopped()) {
                    this._scheduleNextStatusRefresh(0);
                }
            }
        });
    }

    _bindKeyboardShortcuts() {
        window.addEventListener('keydown', (event) => {
            if (event.defaultPrevented || event.isComposing) {
                return;
            }

            const key = String(event.key || '').toLowerCase();
            const ctrlOrMeta = event.ctrlKey || event.metaKey;

            if (key === 'f5') {
                event.preventDefault();
                notificationService.info('正在刷新状态...');
                this._refreshStatus();
                return;
            }

            if (!ctrlOrMeta || this._isEditableTarget(event.target)) {
                return;
            }

            if (key === '1') {
                event.preventDefault();
                this._switchPage('dashboard');
                return;
            }
            if (key === '2') {
                event.preventDefault();
                this._switchPage('costs');
                return;
            }
            if (key === '3') {
                event.preventDefault();
                this._switchPage('messages');
                return;
            }
            if (key === '4') {
                event.preventDefault();
                this._switchPage('models');
                return;
            }
            if (key === '5') {
                event.preventDefault();
                this._switchPage('settings');
                return;
            }
            if (key === '6') {
                event.preventDefault();
                this._switchPage('logs');
                return;
            }
            if (key === 'r') {
                event.preventDefault();
                void this._restartBotFromShortcut();
                return;
            }
            if (key === 'q') {
                event.preventDefault();
                window.electronAPI?.closeWindow();
            }
        });
    }

    _isEditableTarget(target) {
        if (!(target instanceof HTMLElement)) {
            return false;
        }
        if (target.isContentEditable) {
            return true;
        }
        const tagName = target.tagName;
        return tagName === 'INPUT' || tagName === 'TEXTAREA' || tagName === 'SELECT';
    }

    async _restartBotFromShortcut() {
        try {
            notificationService.info('正在重启机器人...');
            const result = await apiService.restartBot();
            notificationService.show(result.message, result.success ? 'success' : 'error');
            await this._refreshStatus();
        } catch (error) {
            notificationService.error('快捷键重启失败');

        }
    }

    _setupCloseChoiceModal() {
        const modal = document.getElementById('close-choice-modal');
        const btnClose = document.getElementById('btn-close-choice-modal');
        const remember = document.getElementById('close-choice-remember');
        const btnMinimize = document.getElementById('btn-close-choice-minimize');
        const btnQuit = document.getElementById('btn-close-choice-quit');
        const statusText = document.getElementById('close-choice-status');

        if (!modal || !window.electronAPI?.onAppCloseDialog) {
            return;
        }

        const openModal = () => {
            if (remember) {
                remember.checked = false;
            }

            const running = stateManager.get('bot.running');
            const paused = stateManager.get('bot.paused');
            if (statusText) {
                if (!running) {
                    statusText.textContent = '机器人已停止';
                } else if (paused) {
                    statusText.textContent = '机器人已暂停';
                } else {
                    statusText.textContent = '机器人运行中';
                }
            }

            modal.classList.add('active');
        };

        const closeModal = () => {
            modal.classList.remove('active');
        };

        window.electronAPI.onAppCloseDialog(() => {
            openModal();
        });

        btnClose?.addEventListener('click', closeModal);

        modal.addEventListener('click', (event) => {
            if (event.target === modal) {
                closeModal();
            }
        });

        window.addEventListener('keydown', (event) => {
            if (event.key === 'Escape' && modal.classList.contains('active')) {
                closeModal();
            }
        });

        btnMinimize?.addEventListener('click', async () => {
            const keep = !!remember?.checked;
            closeModal();
            await window.electronAPI.confirmCloseAction('minimize', keep);
        });

        btnQuit?.addEventListener('click', async () => {
            const keep = !!remember?.checked;
            closeModal();
            await window.electronAPI.confirmCloseAction('quit', keep);
        });
    }

    _setupConfirmModal() {
        const modal = document.getElementById('confirm-modal');
        const btnClose = document.getElementById('btn-close-confirm-modal');
        const btnCancel = document.getElementById('btn-confirm-modal-cancel');
        const btnConfirm = document.getElementById('btn-confirm-modal-confirm');
        if (!modal || !btnCancel || !btnConfirm) {
            return;
        }

        const closeWith = (accepted) => {
            modal.classList.remove('active');
            if (this._confirmModalResolver) {
                const resolver = this._confirmModalResolver;
                this._confirmModalResolver = null;
                resolver(Boolean(accepted));
            }
        };

        modal.addEventListener('click', (event) => {
            if (event.target === modal) {
                closeWith(false);
            }
        });

        btnClose?.addEventListener('click', () => closeWith(false));
        btnCancel.addEventListener('click', () => closeWith(false));
        btnConfirm.addEventListener('click', () => closeWith(true));

        window.addEventListener('keydown', (event) => {
            if (event.key === 'Escape' && modal.classList.contains('active')) {
                closeWith(false);
            }
        });

        window.appConfirm = (options = {}) => {
            const title = String(options.title || '确认操作').trim();
            const message = String(options.message || '确认是否继续？').trim();
            const kicker = String(options.kicker || '操作确认').trim();
            const subtitle = String(options.subtitle || '').trim();
            const confirmText = String(options.confirmText || '确认').trim();
            const cancelText = String(options.cancelText || '取消').trim();

            const kickerElem = document.getElementById('confirm-modal-kicker');
            const titleElem = document.getElementById('confirm-modal-title');
            const subtitleElem = document.getElementById('confirm-modal-subtitle');
            const messageElem = document.getElementById('confirm-modal-message');

            if (kickerElem) {
                kickerElem.textContent = kicker;
            }
            if (titleElem) {
                titleElem.textContent = title;
            }
            if (subtitleElem) {
                subtitleElem.textContent = subtitle || '请确认是否继续执行当前操作。';
            }
            if (messageElem) {
                messageElem.textContent = message;
            }
            btnCancel.textContent = cancelText;
            btnConfirm.textContent = confirmText;

            if (this._confirmModalResolver) {
                this._confirmModalResolver(false);
                this._confirmModalResolver = null;
            }

            modal.classList.add('active');
            return new Promise((resolve) => {
                this._confirmModalResolver = resolve;
            });
        };
    }

    _setupUpdateModal() {
        const modal = document.getElementById('update-modal');
        const btnClose = document.getElementById('btn-close-update-modal');
        const btnSkip = document.getElementById('btn-update-modal-skip');
        const btnAction = document.getElementById('btn-update-modal-action');
        if (!modal) {
            return;
        }

        const closeModal = () => {
            modal.classList.remove('active');
        };

        modal.addEventListener('click', (event) => {
            if (event.target === modal) {
                closeModal();
            }
        });

        btnClose?.addEventListener('click', closeModal);

        window.addEventListener('keydown', (event) => {
            if (event.key === 'Escape' && modal.classList.contains('active')) {
                closeModal();
            }
        });

        btnSkip?.addEventListener('click', async () => {
            if (!window.electronAPI?.skipUpdateVersion) {
                return;
            }
            const latestVersion = stateManager.get('updater.latestVersion');
            if (!latestVersion) {
                return;
            }
            const result = await window.electronAPI.skipUpdateVersion(latestVersion);
            if (!result?.success) {
                notificationService.warning(result?.error || '跳过版本失败');
                return;
            }
            notificationService.info(`已跳过 v${latestVersion}`);
            closeModal();
        });

        btnAction?.addEventListener('click', async () => {
            if (stateManager.get('updater.readyToInstall')) {
                await this._installDownloadedUpdate();
                return;
            }
            await this._downloadUpdate();
        });

        this._renderUpdateModal();
    }

    _openUpdateModal() {
        const modal = document.getElementById('update-modal');
        if (!modal) {
            return;
        }
        this._renderUpdateModal();
        modal.classList.add('active');
    }

    _maybePromptForUpdate(options = {}) {
        const latestVersion = stateManager.get('updater.latestVersion');
        const skippedVersion = stateManager.get('updater.skippedVersion');
        const readyToInstall = stateManager.get('updater.readyToInstall');
        const available = stateManager.get('updater.available');

        if (readyToInstall && latestVersion) {
            this._lastUpdateModalVersion = latestVersion;
            this._openUpdateModal();
            return;
        }

        if (!available || !latestVersion || latestVersion === skippedVersion) {
            return;
        }

        if (options.silent && !options.forceReadyToInstall) {
            return;
        }

        if (this._lastUpdateModalVersion === latestVersion) {
            return;
        }

        this._lastUpdateModalVersion = latestVersion;
        this._openUpdateModal();
    }

    _renderUpdateModal() {
        renderUpdateModalContent({
            currentVersion: stateManager.get('updater.currentVersion') || '--',
            latestVersion: stateManager.get('updater.latestVersion') || '',
            releaseDate: stateManager.get('updater.releaseDate'),
            lastCheckedAt: stateManager.get('updater.lastCheckedAt'),
            error: stateManager.get('updater.error'),
            readyToInstall: !!stateManager.get('updater.readyToInstall'),
            downloading: !!stateManager.get('updater.downloading'),
            downloadProgress: Number(stateManager.get('updater.downloadProgress') || 0),
            available: !!stateManager.get('updater.available'),
            notes: Array.isArray(stateManager.get('updater.notes')) ? stateManager.get('updater.notes') : [],
        }, {
            statusText: document.getElementById('update-modal-status'),
            meta: document.getElementById('update-modal-meta'),
            notes: document.getElementById('update-modal-notes'),
            progress: document.getElementById('update-modal-progress'),
            progressFill: document.getElementById('update-modal-progress-fill'),
            progressText: document.getElementById('update-modal-progress-text'),
            btnSkip: document.getElementById('btn-update-modal-skip'),
            btnAction: document.getElementById('btn-update-modal-action'),
        });
    }

    async _loadFirstRunState() {
        let firstRunPending = false;
        if (window.electronAPI?.isFirstRun) {
            try {
                firstRunPending = !!(await window.electronAPI.isFirstRun());
            } catch (error) {
                console.warn('[App] load first run state failed:', error);
            }
        }

        stateManager.batchUpdate({
            'readiness.firstRunPending': firstRunPending,
            'readiness.firstRunGuideDismissed': false,
        });
    }

    _setupFirstRunGuide() {
        const modal = document.getElementById('first-run-modal');
        const btnClose = document.getElementById('btn-close-first-run-modal');
        const btnLater = document.getElementById('btn-first-run-later');
        const btnRetry = document.getElementById('btn-first-run-retry');
        const btnSettings = document.getElementById('btn-first-run-settings');
        if (!modal) {
            return;
        }

        const closeModal = () => {
            modal.classList.remove('active');
            stateManager.set('readiness.firstRunGuideDismissed', true);
        };

        modal.addEventListener('click', (event) => {
            if (event.target === modal) {
                closeModal();
                return;
            }
            const button = event.target?.closest?.('[data-readiness-action]');
            if (!button) {
                return;
            }
            event.preventDefault?.();
            event.stopPropagation?.();
            void this._handleReadinessAction(button.dataset.readinessAction);
        });

        btnClose?.addEventListener('click', closeModal);
        btnLater?.addEventListener('click', closeModal);
        btnRetry?.addEventListener('click', () => {
            void this._handleReadinessAction('retry');
        });
        btnSettings?.addEventListener('click', () => {
            void this._handleReadinessAction('open_settings');
        });

        window.addEventListener('keydown', (event) => {
            if (event.key === 'Escape' && modal.classList.contains('active')) {
                closeModal();
            }
        });
    }

    _renderFirstRunGuide(report = stateManager.get('readiness.report')) {
        const modal = document.getElementById('first-run-modal');
        const title = document.getElementById('first-run-title');
        const subtitle = document.getElementById('first-run-subtitle');
        const summary = document.getElementById('first-run-summary');
        const list = document.getElementById('first-run-check-list');
        const settingsButton = document.getElementById('btn-first-run-settings');
        if (!modal || !title || !subtitle || !summary || !list || !settingsButton) {
            return;
        }

        const normalized = normalizeReadinessReport(report);
        const visible = shouldShowFirstRunGuide({
            firstRunPending: !!stateManager.get('readiness.firstRunPending'),
            dismissed: !!stateManager.get('readiness.firstRunGuideDismissed'),
            report: normalized,
        });

        if (!visible) {
            modal.classList.remove('active');
            return;
        }

        const blockingChecks = getReadinessBlockingChecks(normalized, {
            onlyFirstRun: true,
            limit: 6,
        });

        title.textContent = normalized.summary.title;
        subtitle.textContent = normalized.summary.detail;
        summary.textContent = blockingChecks.length > 0
            ? `先完成这 ${blockingChecks.length} 项，应用就更接近“开箱即用”。`
            : '先补齐下面的阻塞项，再启动机器人会更稳妥。';
        settingsButton.hidden = !blockingChecks.some((check) => check.action === 'open_settings');

        list.textContent = '';
        blockingChecks.forEach((check) => {
            const item = document.createElement('li');
            item.className = 'first-run-check-item';
            item.dataset.status = check.status;

            const copy = document.createElement('div');
            copy.className = 'first-run-check-copy';

            const label = document.createElement('strong');
            label.className = 'first-run-check-label';
            label.textContent = check.label;

            const message = document.createElement('div');
            message.className = 'first-run-check-message';
            message.textContent = check.message;

            copy.appendChild(label);
            copy.appendChild(message);

            if (check.hint) {
                const hint = document.createElement('div');
                hint.className = 'first-run-check-hint';
                hint.textContent = check.hint;
                copy.appendChild(hint);
            }

            item.appendChild(copy);

            if (check.action) {
                const action = document.createElement('button');
                action.type = 'button';
                action.className = 'btn btn-secondary btn-sm';
                action.dataset.readinessAction = check.action;
                action.textContent = check.actionLabel;
                item.appendChild(action);
            }

            list.appendChild(item);
        });

        modal.classList.add('active');
    }

    async _markFirstRunComplete(report) {
        const normalized = normalizeReadinessReport(report);
        if (!shouldCompleteFirstRun({
            firstRunPending: stateManager.get('readiness.firstRunPending'),
            report: normalized,
        })) {
            return;
        }

        try {
            await window.electronAPI?.setFirstRunComplete?.();
        } catch (error) {
            console.warn('[App] mark first run complete failed:', error);
        }

        stateManager.batchUpdate({
            'readiness.firstRunPending': false,
            'readiness.firstRunGuideDismissed': false,
        });
        document.getElementById('first-run-modal')?.classList.remove('active');
    }

    async _refreshReadiness(options = {}) {
        if (this._readinessRefreshing) {
            return stateManager.get('readiness.report');
        }

        const force = !!options.force;
        const now = Date.now();
        const cachedReport = stateManager.get('readiness.report');
        if (
            !force
            && cachedReport
            && (now - this._lastReadinessRefreshAt) < this._readinessMinIntervalMs
        ) {
            this._renderFirstRunGuide(cachedReport);
            return cachedReport;
        }

        this._readinessRefreshing = true;
        stateManager.set('readiness.loading', true);
        try {
            const report = normalizeReadinessReport(await apiService.getReadiness(force));
            this._lastReadinessRefreshAt = now;
            stateManager.batchUpdate({
                'readiness.report': report,
                'readiness.error': '',
                'readiness.lastCheckedAt': report.checkedAt,
                'readiness.loading': false,
            });
            await this._markFirstRunComplete(report);
            this._renderFirstRunGuide(report);
            return report;
        } catch (error) {
            const report = buildUnavailableReadinessReport(error?.message || '');
            stateManager.batchUpdate({
                'readiness.report': report,
                'readiness.error': error?.message || '',
                'readiness.loading': false,
            });
            this._renderFirstRunGuide(report);
            return report;
        } finally {
            this._readinessRefreshing = false;
        }
    }

    async _handleReadinessAction(action) {
        const normalizedAction = String(action || '').trim();
        if (!normalizedAction) {
            return;
        }
        const modal = document.getElementById('first-run-modal');

        if (normalizedAction === 'open_settings') {
            modal?.classList.remove('active');
            stateManager.set('readiness.firstRunGuideDismissed', true);
            await this._switchPage('settings', { source: 'readiness' });
            notificationService.info('已切换到设置页，请补齐配置后再回来重新检查。');
            return;
        }

        if (normalizedAction === 'open_wechat') {
            modal?.classList.remove('active');
            stateManager.set('readiness.firstRunGuideDismissed', true);
            try {
                if (window.electronAPI?.openWeChat) {
                    await window.electronAPI.openWeChat();
                    notificationService.success('正在打开微信客户端...');
                } else {
                    notificationService.info('请先手动打开并登录微信客户端。');
                }
            } catch (error) {
                notificationService.error('打开微信客户端失败');
            }
            await this._refreshStatus({ force: true, refreshReadiness: true });
            return;
        }

        if (normalizedAction === 'restart_as_admin') {
            modal?.classList.remove('active');
            stateManager.set('readiness.firstRunGuideDismissed', true);
            if (!window.electronAPI?.restartAppAsAdmin) {
                notificationService.warning('当前环境暂不支持自动提权重启，请手动以管理员身份重新启动应用。');
                return;
            }

            try {
                const result = await window.electronAPI.restartAppAsAdmin();
                if (result?.success) {
                    notificationService.success(result.message || '正在以管理员身份重新启动应用...');
                    return;
                }
                if (result?.canceled) {
                    notificationService.info(result.message || '已取消管理员权限授权');
                    return;
                }
                notificationService.error(result?.message || '管理员重启失败');
            } catch (error) {
                notificationService.error('管理员重启失败');
            }
            return;
        }

        if (normalizedAction === 'retry') {
            modal?.classList.remove('active');
            stateManager.set('readiness.firstRunGuideDismissed', false);
            await this._refreshStatus({ force: true, refreshReadiness: true });
            return;
        }

        modal?.classList.remove('active');
        stateManager.set('readiness.firstRunGuideDismissed', false);
        await this._refreshStatus({ force: true, refreshReadiness: true });
    }

    async _exportDiagnosticsSnapshot() {
        if (!window.electronAPI?.exportDiagnosticsSnapshot) {
            notificationService.warning('当前版本暂不支持导出诊断快照。');
            return;
        }

        try {
            const result = await window.electronAPI.exportDiagnosticsSnapshot();
            if (result?.success) {
                notificationService.success(result.message || '诊断快照已导出');
                return;
            }
            if (!result?.canceled) {
                notificationService.error(result?.message || '导出诊断快照失败');
            }
        } catch (error) {
            notificationService.error('导出诊断快照失败');
        }
    }

    async _downloadUpdate() {
        if (window.electronAPI?.downloadUpdate) {
            const result = await window.electronAPI.downloadUpdate();
            if (!result?.success) {
                notificationService.warning(result?.error || '下载安装包失败');
                return;
            }
            if (result?.alreadyDownloaded) {
                notificationService.info('更新安装包已下载完成');
            } else {
                notificationService.info('开始下载更新，请稍候...');
            }
            this._openUpdateModal();
            return;
        }
        await this._openUpdateDownload();
    }

    async _installDownloadedUpdate() {
        if (!window.electronAPI?.installDownloadedUpdate) {
            notificationService.warning('当前环境不支持安装更新');
            return;
        }

        const result = await window.electronAPI.installDownloadedUpdate();
        if (!result?.success) {
            notificationService.warning(result?.error || '启动更新安装失败');
            return;
        }
        notificationService.info('正在退出应用并启动安装程序...');
    }

    async _openUpdateDownload() {
        if (!window.electronAPI?.openUpdateDownload) {
            return;
        }

        const result = await window.electronAPI.openUpdateDownload();
        if (!result?.success) {
            notificationService.warning('未找到 GitHub Releases 下载地址。');
        }
    }

    async _switchPage(pageName, options = {}) {
        if (this.currentPage) {
            await this.currentPage.onLeave();
        }

        document.querySelectorAll('.nav-item').forEach(item => {
            item.classList.toggle('active', item.dataset.page === pageName);
        });

        document.querySelectorAll('.page').forEach(page => {
            page.classList.toggle('active', page.id === `page-${pageName}`);
        });

        stateManager.set('currentPage', pageName);
        this.currentPage = this.pages[pageName];

        await this._ensureBackendForPage(pageName, options);

        if (this.currentPage) {
            await this.currentPage.onEnter();
        }

        console.log(`[App] 切换到页面: ${pageName}`);
    }

    async _refreshStatus(options = {}) {
        if (this._isIdleStopped() && !options.force) {
            this._scheduleNextStatusRefresh(null);
            return;
        }

        if (this._statusRefreshing) {
            return;
        }

        this._statusRefreshing = true;
        try {
            const status = await apiService.getStatus();
            this._applyStatus(status, { connected: true });
            void this._reportRuntimeStatus(status);
            this._statusFailureCount = 0;
        } catch (error) {
            if (!this._isIdleStopped()) {
                console.error('[App] 刷新状态失败:', error);
            }
            const previousStatus = stateManager.get('bot.status');
            this._closeSSE();
            this._applyDisconnectedRuntimeState(previousStatus, { idleState: this._getRuntimeIdleState() });
            this._statusFailureCount += 1;
        } finally {
            if (options.refreshReadiness !== false) {
                await this._refreshReadiness({ force: !!options.force });
            }
            this._statusRefreshing = false;
            this._scheduleNextStatusRefresh(this._getNextStatusIntervalMs());
        }
    }

    _buildDisconnectedStatus(previousStatus = null, options = {}) {
        return buildDisconnectedStatus(previousStatus, options?.idleState || this._getRuntimeIdleState());
    }
    _applyDisconnectedRuntimeState(previousStatus = null, options = {}) {
        stateManager.batchUpdate({
            'bot.connected': false,
            'bot.running': false,
            'bot.paused': false,
            'bot.status': this._buildDisconnectedStatus(previousStatus, options),
        });
        this._updateConnectionStatus();
    }

    _applyStatus(status, options = {}) {
        if (!status || typeof status !== 'object') {
            return;
        }
        stateManager.batchUpdate({
            'bot.running': !!status.running,
            'bot.paused': !!status.is_paused,
            'bot.connected': options.connected !== false,
            'bot.status': status
        });

        if (this.pages.dashboard && this.pages.dashboard.isActive()) {
            this.pages.dashboard.updateStats(status);
        }

        if (options.connected !== false) {
            this._connectSSE();
        }
        this._updateConnectionStatus();
    }

    _connectSSE() {
        if (this._eventSource || !stateManager.get('bot.connected') || this._isIdleStopped()) {
            return;
        }
        this._eventSource = apiService.connectSSE(
            (payload) => this._handleRealtimeEvent(payload),
            (err) => this._handleSSEError(err),
            () => this._handleSSEOpen()
        );
    }

    _handleSSEOpen() {
        this._clearSSEReconnectTimer();
        this._sseReconnectAttempt = 0;
        stateManager.set('bot.connected', true);
        this._updateConnectionStatus();
    }

    _handleSSEError(err) {
        if (!this._isIdleStopped()) {
            console.warn('[App] SSE 连接异常，准备重连:', err);
        }
        const status = stateManager.get('bot.status') || {};
        const shouldReconnect = !!(
            status.running ||
            status.growth_running ||
            status?.startup?.active
        );

        this._closeSSE();
        this._applyDisconnectedRuntimeState(status, { idleState: this._getRuntimeIdleState() });
        if (shouldReconnect && !this._isIdleStopped()) {
            this._scheduleSSEReconnect();
        }
    }

    _closeSSE() {
        if (!this._eventSource) {
            return;
        }
        try {
            this._eventSource.close();
        } catch (_) {
            // ignore
        }
        this._eventSource = null;
    }

    _clearSSEReconnectTimer() {
        if (!this._sseReconnectTimer) {
            return;
        }
        clearTimeout(this._sseReconnectTimer);
        this._sseReconnectTimer = null;
    }

    _scheduleSSEReconnect() {
        if (this._sseReconnectTimer) {
            return;
        }

        const attempt = Math.min(this._sseReconnectAttempt, 6);
        const baseDelay = Math.min(15000, 1000 * Math.pow(2, attempt));
        const jitter = Math.floor(Math.random() * 300);
        const delay = baseDelay + jitter;
        this._sseReconnectAttempt = attempt + 1;

        this._sseReconnectTimer = setTimeout(() => {
            this._sseReconnectTimer = null;
            this._connectSSE();
        }, delay);
    }

    _handleRealtimeEvent(payload) {
        if (!payload || typeof payload !== 'object') {
            return;
        }
        if (payload.type === 'heartbeat') {
            stateManager.set('bot.connected', true);
            this._updateConnectionStatus();
            return;
        }
        if (payload.type === 'status_change' && payload.data) {
            this._applyStatus(payload.data, { connected: true });
            void this._reportRuntimeStatus(payload.data);
            return;
        }
        if (payload.type === 'message' && payload.data) {
            stateManager.set('bot.connected', true);
            this._updateConnectionStatus();
            eventBus.emit(Events.MESSAGE_RECEIVED, payload.data);
        }
    }

    _getNextStatusIntervalMs() {
        const startupActive = !!stateManager.get('bot.status.startup.active');
        const currentPage = stateManager.get('currentPage') || 'dashboard';
        const dashboardActive = currentPage === 'dashboard';
        if (startupActive && this._statusFailureCount <= 0) {
            return dashboardActive ? 800 : 2000;
        }

        if (this._statusFailureCount <= 0) {
            return dashboardActive ? this._statusBaseIntervalMs : 15000;
        }

        const backoff = this._statusBaseIntervalMs * Math.pow(2, this._statusFailureCount);
        const jitter = Math.floor(Math.random() * 500);
        return Math.min(this._statusMaxIntervalMs, backoff + jitter);
    }

    _updateConnectionStatus() {
        const badge = document.getElementById('status-badge');
        if (!badge) {
            return;
        }
        const dot = badge.querySelector('.status-dot');
        const label = badge.querySelector('.status-label');
        const nextView = getConnectionStatusView({
            connected: !!stateManager.get('bot.connected'),
            running: !!stateManager.get('bot.running'),
            paused: !!stateManager.get('bot.paused'),
            status: stateManager.get('bot.status'),
            idleState: this._getRuntimeIdleState(),
            canWake: !!(window.electronAPI?.runtimeEnsureService || window.electronAPI?.startBackend),
        });
        if (label) {
            label.textContent = nextView.labelText;
        }
        if (dot) {
            dot.className = nextView.dotClass;
        }
        badge.title = nextView.titleText;
    }
    _startStatusRefresh() {
        this._scheduleNextStatusRefresh(0);
    }

    _scheduleNextStatusRefresh(delayMs) {
        if (this._statusTimer) {
            clearTimeout(this._statusTimer);
            this._statusTimer = null;
        }

        if (delayMs === null || document.hidden || this._isIdleStopped()) {
            return;
        }

        this._statusTimer = setTimeout(() => this._refreshStatus(), delayMs);
    }
}

export { App };

if (typeof document !== 'undefined' && typeof document.addEventListener === 'function') {
    document.addEventListener('DOMContentLoaded', async () => {
        const app = new App();
        await app.init();

        window.__app = app;
        window.__state = stateManager;
        window.__events = eventBus;
    });
}
