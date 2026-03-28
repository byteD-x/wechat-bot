/**
 * WeChat AI Assistant frontend application entry.
 */

if (typeof window !== 'undefined' && typeof window.dragEvent === 'undefined') {
    window.dragEvent = window.DragEvent;
}

import { stateManager, eventBus, Events } from './core/index.js';
import { apiService, notificationService } from './services/index.js';
import { DashboardPage, CostsPage, MessagesPage, ExportCenterPage, ModelsPage, SettingsPage, LogsPage, AboutPage } from './pages/index.js';
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
import { setupGlobalButtonFeedback } from './app/button-feedback.js';

const DEFAULT_IDLE_DELAY_MS = 15 * 60 * 1000;
const AUTO_WAKE_PAGES = new Set(['dashboard', 'costs', 'messages', 'exports', 'models', 'logs']);
const RUNTIME_READONLY_PAGE_MESSAGES = Object.freeze({
    costs: '机器人未启动：当前仅可查看成本数据，操作已禁用。',
    messages: '机器人未启动：当前仅可查看消息数据，操作已禁用。',
    exports: '机器人未启动：当前仅可查看导出设置，操作已禁用。',
});

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
            exports: new ExportCenterPage(),
            models: new ModelsPage(),
            settings: new SettingsPage(),
            logs: new LogsPage(),
            about: new AboutPage()
        };

        this.currentPage = null;
        this._pageSwitchSeq = 0;
        this._statusTimer = null;
        this._statusRefreshing = false;
        this._statusFailureCount = 0;
        this._statusBaseIntervalMs = 5000;
        this._statusMaxIntervalMs = 30000;
        this._lastStatusSuccessAt = 0;
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
        this._sseFailureCount = 0;
        this._sseFailureWindowStartedAt = 0;
        this._sseFailureWindowMs = 30000;
        this._sseFailureThreshold = 4;
        this._sseDisableBaseMs = 15000;
        this._sseDisableMaxMs = 120000;
        this._sseDisabledUntil = 0;
        this._sseDegradedNotifiedAt = 0;
        this._pageSwitchInProgress = false;
        this._restartInFlight = false;
        this._lastRestartAt = 0;
        this._restartFollowupTimers = new Set();
    }

    async init() {
        console.log('[App] initializing application...');

        notificationService.init();
        if (typeof document !== 'undefined') {
            setupGlobalButtonFeedback(document);
        }
        await this._runInitStep('apiService.init', () => apiService.init());
        await this._runInitStep('_setupRuntimeIdleState', () => this._setupRuntimeIdleState());
        await this._runInitStep('_loadFirstRunState', () => this._loadFirstRunState());

        await this._runInitStep('_setupVersion', () => this._setupVersion());
        await this._runInitStep('_setupUpdater', () => this._setupUpdater());

        this._setupCloseChoiceModal();
        this._setupConfirmModal();
        this._setupUpdateModal();
        this._setupFirstRunGuide();

        for (const [pageName, page] of Object.entries(this.pages)) {
            await this._runInitStep(`${pageName}.onInit`, () => page.onInit());
        }
        this._bindGlobalEvents();
        this._bindKeyboardShortcuts();

        await this._runInitStep('_ensureLightweightBackend', () => this._ensureLightweightBackend());
        await this._runInitStep('_checkBackendConnection', () => this._checkBackendConnection());
        await this._runInitStep('_refreshStatus', () => this._refreshStatus());
        const initialPage = stateManager.get('currentPage') || 'dashboard';
        await this._runInitStep('_switchPage', () => this._switchPage(initialPage, { source: 'init' }));
        this._syncRuntimeReadonlyPages();
        this._startStatusRefresh();
        console.log('[App] initialized');

    }

    async _runInitStep(stepName, fn) {
        try {
            return await fn();
        } catch (error) {
            console.error(`[App] initialization step failed: ${stepName}`, error);
            notificationService.error(`Initialization step failed: ${stepName}`);
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
            'updater.downloadedInstallerPath': updateState.downloadedInstallerPath || '',
            'updater.downloadedInstallerSha256': updateState.downloadedInstallerSha256 || '',
            'updater.checksumAssetUrl': updateState.checksumAssetUrl || '',
            'updater.checksumExpected': updateState.checksumExpected || '',
            'updater.checksumActual': updateState.checksumActual || '',
            'updater.checksumVerified': !!updateState.checksumVerified,
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
            notificationService.info(`Update available: v${nextVersion}`, 5000);
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
            notificationService.info('Starting Python backend service...');
            await this._wakeBackend();

            if (!stateManager.get('bot.connected')) {
                notificationService.error('Python backend failed to start.');
            } else {
                notificationService.success('Python backend started.');
            }
        } catch (error) {
            console.error('[App] backend start failed:', error);
            notificationService.error('Python backend failed to start.');
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
                notificationService.info('Refreshing runtime status...');
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
            if (key === '7') {
                event.preventDefault();
                this._switchPage('about');
                return;
            }
            if (key === '8') {
                event.preventDefault();
                this._switchPage('exports');
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

    _clearRestartFollowupTimers() {
        this._restartFollowupTimers.forEach((timer) => clearTimeout(timer));
        this._restartFollowupTimers.clear();
    }

    _scheduleRestartHealthChecks(delays = [1200, 3000, 6000]) {
        this._clearRestartFollowupTimers();
        delays.forEach((delayMs) => {
            const timer = setTimeout(() => {
                this._restartFollowupTimers.delete(timer);
                void this._refreshStatus({ force: true, refreshReadiness: true });
            }, Math.max(0, Number(delayMs) || 0));
            this._restartFollowupTimers.add(timer);
        });
    }

    async _restartBotFromShortcut() {
        if (this._restartInFlight) {
            notificationService.info('A restart is already in progress...');
            return;
        }
        const now = Date.now();
        if ((now - this._lastRestartAt) < 2500) {
            notificationService.warning('Restart was triggered recently. Please wait a moment.');
            return;
        }

        this._restartInFlight = true;
        this._lastRestartAt = now;
        try {
            notificationService.info('Restarting bot service...');
            this._clearSSEReconnectTimer();
            this._closeSSE();
            const result = await apiService.restartBot();
            notificationService.show(
                result?.message || (result?.success ? 'Bot restart completed' : 'Bot restart failed'),
                result?.success ? 'success' : 'error'
            );
            await this._refreshStatus({ force: true, refreshReadiness: true });
            this._scheduleRestartHealthChecks();
        } catch (error) {
            const code = String(error?.code || '').toLowerCase();
            if (code === 'timeout' || code === 'network' || code === 'network_error') {
                notificationService.warning('Restart command timed out. Verifying service health automatically...');
                this._scheduleRestartHealthChecks([800, 2000, 4500, 8000]);
                return;
            }
            notificationService.error('Restart failed. Please retry.');
        } finally {
            this._restartInFlight = false;
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
                    statusText.textContent = 'Bot is stopped.';
                } else if (paused) {
                    statusText.textContent = 'Bot is paused.';
                } else {
                    statusText.textContent = 'Bot is running.';
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
            const title = String(options.title || 'Confirm action').trim();
            const message = String(options.message || 'Please confirm this action.').trim();
            const kicker = String(options.kicker || 'Please confirm').trim();
            const subtitle = String(options.subtitle || '').trim();
            const confirmText = String(options.confirmText || 'Confirm').trim();
            const cancelText = String(options.cancelText || 'Cancel').trim();

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
                subtitleElem.textContent = subtitle || 'This action cannot be undone.';
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
            btnSkip.disabled = true;
            try {
                const result = await window.electronAPI.skipUpdateVersion(latestVersion);
                if (!result?.success) {
                    const errorText = String(result?.error || '').trim();
                    if (/(sha256|checksum|sha256sums)/i.test(errorText)) {
                        await this._openUpdateDownload();
                        notificationService.info('Checksum metadata missing, opening release page.');
                        return;
                    }
                    notificationService.warning(result?.error || 'Skip update failed.');
                    return;
                }
                notificationService.info(`Skipped version v${latestVersion}`);
                closeModal();
            } catch (error) {
                notificationService.error('Failed to skip this version.');
            } finally {
                btnSkip.disabled = false;
            }
        });

        btnAction?.addEventListener('click', async () => {
            btnAction.disabled = true;
            try {
                if (stateManager.get('updater.readyToInstall')) {
                    await this._installDownloadedUpdate();
                    return;
                }
                await this._downloadUpdate();
            } catch (error) {
                notificationService.error('Update operation failed.');
            } finally {
                btnAction.disabled = false;
            }
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
            ? `开箱即用检查还有 ${blockingChecks.length} 项待处理。`
            : 'All required checks are complete. You can continue.';
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
            notificationService.info('Switched to settings page. Complete setup and retry.');
            return;
        }

        if (normalizedAction === 'open_wechat') {
            try {
                if (window.electronAPI?.openWeChat) {
                    const result = await window.electronAPI.openWeChat();
                    if (result?.success) {
                        modal?.classList.remove('active');
                        stateManager.set('readiness.firstRunGuideDismissed', true);
                        notificationService.success(result?.message || 'WeChat client opened');
                    } else {
                        stateManager.set('readiness.firstRunGuideDismissed', false);
                        modal?.classList.add('active');
                        notificationService.error(result?.error || result?.message || 'Failed to open WeChat client');
                    }
                } else {
                    stateManager.set('readiness.firstRunGuideDismissed', false);
                    modal?.classList.add('active');
                    notificationService.info('Please open and sign in to WeChat manually.');
                }
            } catch (error) {
                stateManager.set('readiness.firstRunGuideDismissed', false);
                modal?.classList.add('active');
                notificationService.error('Failed to open WeChat client');
            }
            await this._refreshStatus({ force: true, refreshReadiness: true });
            return;
        }

        if (normalizedAction === 'restart_as_admin') {
            modal?.classList.remove('active');
            stateManager.set('readiness.firstRunGuideDismissed', true);
            if (!window.electronAPI?.restartAppAsAdmin) {
                notificationService.warning('This environment does not support automatic admin relaunch.');
                return;
            }

            try {
                const result = await window.electronAPI.restartAppAsAdmin();
                if (result?.success) {
                    notificationService.success(result.message || 'Relaunching app with administrator privileges...');
                    return;
                }
                if (result?.canceled) {
                    notificationService.info(result.message || 'Admin restart was canceled');
                    return;
                }
                notificationService.error(result?.message || 'Admin restart failed');
            } catch (error) {
                notificationService.error('Admin restart failed');
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
            notificationService.warning('Diagnostics snapshot export is not supported in this environment.');
            return;
        }

        try {
            const result = await window.electronAPI.exportDiagnosticsSnapshot();
            if (result?.success) {
                notificationService.success(result.message || 'Diagnostics snapshot exported.');
                return;
            }
            if (!result?.canceled) {
                notificationService.error(result?.message || 'Failed to export diagnostics snapshot.');
            }
        } catch (error) {
            notificationService.error('Failed to export diagnostics snapshot.');
        }
    }

    async _downloadUpdate() {
        try {
            if (window.electronAPI?.downloadUpdate) {
                const result = await window.electronAPI.downloadUpdate();
                if (!result?.success) {
                    const errorMessage = result?.error || 'Failed to download installer';
                    if (this._shouldFallbackToReleasePage(errorMessage) && window.electronAPI?.openUpdateDownload) {
                        const openResult = await window.electronAPI.openUpdateDownload();
                        if (openResult?.success) {
                            notificationService.info('Checksum metadata missing. Opened release page for full installer.');
                            return;
                        }
                    }
                    notificationService.warning(errorMessage);
                    return;
                }
                if (result?.alreadyDownloaded) {
                    notificationService.info('Update installer already downloaded.');
                } else {
                    notificationService.info('Downloading installer package...');
                }
                this._openUpdateModal();
                return;
            }
            await this._openUpdateDownload();
        } catch (error) {
            notificationService.error('Failed to download installer, please retry later.');
        }
    }

    _shouldFallbackToReleasePage(errorMessage = '') {
        const normalized = String(errorMessage || '').trim();
        if (!normalized) {
            return false;
        }
        return /(sha256|checksum|SHA256SUMS)/i.test(normalized);
    }

    async _installDownloadedUpdate() {
        try {
            if (!window.electronAPI?.installDownloadedUpdate) {
                notificationService.warning('Installing updates is not supported in this environment.');
                return;
            }

            const result = await window.electronAPI.installDownloadedUpdate();
            if (!result?.success) {
                notificationService.warning(result?.error || 'Failed to start update installation.');
                return;
            }
            notificationService.info('Launching update installer. Application will close shortly.');
        } catch (error) {
            notificationService.error('Failed to launch update installer.');
        }
    }

    async _openUpdateDownload() {
        try {
            if (!window.electronAPI?.openUpdateDownload) {
                return;
            }

            const result = await window.electronAPI.openUpdateDownload();
            if (!result?.success) {
                notificationService.warning('GitHub Releases URL not found.');
            }
        } catch (error) {
            notificationService.warning('Failed to open download page, please retry later.');
        }
    }

    async _switchPage(pageName, options = {}) {
        const requestedPageName = String(pageName || '').trim();
        let nextPageName = requestedPageName;
        if (!this.pages[nextPageName]) {
            if (String(options?.source || '').trim() === 'init') {
                nextPageName = 'dashboard';
            } else {
                notificationService.warning(`Page not found: ${requestedPageName || 'unknown'}`);
                return;
            }
        }
        const nextPage = this.pages[nextPageName];
        if (!nextPage) {
            return;
        }

        if (
            this.currentPage === nextPage
            && stateManager.get('currentPage') === nextPageName
            && typeof nextPage.isActive === 'function'
            && nextPage.isActive()
            && !this._pageSwitchInProgress
        ) {
            return;
        }

        const switchToken = (this._pageSwitchSeq || 0) + 1;
        this._pageSwitchSeq = switchToken;
        this._pageSwitchInProgress = true;
        const previousPage = this.currentPage;
        const previousPageName = this.pages[stateManager.get('currentPage')]
            ? String(stateManager.get('currentPage'))
            : (Object.entries(this.pages).find(([, page]) => page === previousPage)?.[0] || 'dashboard');

        try {
            if (previousPage && previousPage !== nextPage) {
                await previousPage.onLeave();
                if (switchToken !== this._pageSwitchSeq) {
                    return;
                }
            }

            if (!this._syncPageVisibility(nextPageName)) {
                throw new Error(`missing page container: page-${nextPageName}`);
            }

            stateManager.set('currentPage', nextPageName);
            this.currentPage = nextPage;

            await this._ensureBackendForPage(nextPageName, options);
            if (switchToken !== this._pageSwitchSeq) {
                return;
            }

            if (this.currentPage === nextPage) {
                await nextPage.onEnter();
                if (switchToken !== this._pageSwitchSeq) {
                    return;
                }
            }

            this._syncRuntimeReadonlyPages();
            console.log(`[App] switched to page: ${nextPageName}`);
        } catch (error) {
            console.error(`[App] switch page failed: ${nextPageName}`, error);
            notificationService.error(`Failed to switch page: ${nextPageName}`);
            if (this.pages[previousPageName]) {
                this._syncPageVisibility(previousPageName);
                stateManager.set('currentPage', previousPageName);
                this.currentPage = this.pages[previousPageName];
                try {
                    if (previousPage && previousPage !== nextPage) {
                        await this.pages[previousPageName].onEnter();
                    }
                } catch (rollbackError) {
                    console.error(`[App] rollback onEnter failed: ${previousPageName}`, rollbackError);
                }
            }
        } finally {
            if (switchToken === this._pageSwitchSeq) {
                this._pageSwitchInProgress = false;
            }
        }
    }

    _syncPageVisibility(pageName) {
        if (typeof document === 'undefined') {
            return false;
        }
        document.querySelectorAll('.nav-item').forEach(item => {
            item.classList.toggle('active', item.dataset.page === pageName);
        });

        let hasTargetPage = false;
        document.querySelectorAll('.page').forEach(page => {
            const isTarget = page.id === `page-${pageName}`;
            if (isTarget) {
                hasTargetPage = true;
            }
            page.classList.toggle('active', isTarget);
        });
        return hasTargetPage;
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
            this._lastStatusSuccessAt = Date.now();
        } catch (error) {
            if (!this._isIdleStopped()) {
                console.error('[App] status refresh failed', error);
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
        this._syncRuntimeReadonlyPages();
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
        this._syncRuntimeReadonlyPages();

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
        if (this._isSSECircuitOpen()) {
            this._scheduleSSEReconnect();
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
        this._resetSSEFailureState();
        stateManager.set('bot.connected', true);
        this._updateConnectionStatus();
    }

    _handleSSEError(err) {
        if (!this._isIdleStopped()) {
            console.warn('[App] SSE connection error', err);
        }
        const status = stateManager.get('bot.status') || {};
        const shouldReconnect = !!(
            status.running ||
            status.growth_running ||
            status?.startup?.active
        );
        const now = Date.now();
        const circuitOpened = this._registerSSEFailure(now);
        const recentStatusHealthy = (now - this._lastStatusSuccessAt) <= 15000;

        this._closeSSE();
        void apiService.refreshSseTicket({ force: true });
        if (!recentStatusHealthy) {
            this._applyDisconnectedRuntimeState(status, { idleState: this._getRuntimeIdleState() });
        }
        if (shouldReconnect && !this._isIdleStopped()) {
            if (circuitOpened) {
                const cooldownMs = Math.max(0, this._sseDisabledUntil - now);
                this._scheduleNextStatusRefresh(Math.min(3000, Math.max(1200, cooldownMs)));
                if ((now - this._sseDegradedNotifiedAt) > 30000) {
                    notificationService.warning('Realtime channel is unstable. Switched to polling temporarily.');
                    this._sseDegradedNotifiedAt = now;
                }
            }
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

        const now = Date.now();
        if (this._isSSECircuitOpen(now)) {
            const wait = Math.max(500, this._sseDisabledUntil - now);
            const jitter = Math.floor(Math.random() * 500);
            this._sseReconnectTimer = setTimeout(() => {
                this._sseReconnectTimer = null;
                this._connectSSE();
            }, wait + jitter);
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

    _isSSECircuitOpen(now = Date.now()) {
        return this._sseDisabledUntil > now;
    }

    _resetSSEFailureState() {
        this._sseFailureCount = 0;
        this._sseFailureWindowStartedAt = 0;
        this._sseDisabledUntil = 0;
    }

    _registerSSEFailure(now = Date.now()) {
        if (!this._sseFailureWindowStartedAt || (now - this._sseFailureWindowStartedAt) > this._sseFailureWindowMs) {
            this._sseFailureWindowStartedAt = now;
            this._sseFailureCount = 1;
        } else {
            this._sseFailureCount += 1;
        }

        if (this._sseFailureCount < this._sseFailureThreshold) {
            return false;
        }

        const overflow = Math.max(0, this._sseFailureCount - this._sseFailureThreshold);
        const cooldown = Math.min(
            this._sseDisableMaxMs,
            this._sseDisableBaseMs * Math.pow(2, Math.min(3, overflow))
        );
        this._sseDisabledUntil = Math.max(this._sseDisabledUntil, now + cooldown);
        return true;
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

    _syncRuntimeReadonlyPages() {
        if (typeof document === 'undefined') {
            return;
        }
        const isRunning = !!stateManager.get('bot.running');
        const shouldLock = !isRunning;
        const navRoot = (document && document.body && typeof document.body.querySelectorAll === 'function')
            ? document.body
            : document;
        const navItems = Array.from(
            typeof navRoot?.querySelectorAll === 'function' ? navRoot.querySelectorAll('.nav-item') : []
        );
        const navItemByPage = new Map(
            navItems.map((item) => [String(item?.dataset?.page || '').trim(), item])
        );

        Object.entries(RUNTIME_READONLY_PAGE_MESSAGES).forEach(([pageName, message]) => {
            const container = document.getElementById(`page-${pageName}`);
            if (!container) {
                return;
            }
            const markerSelector = '.runtime-readonly-note';
            const marker = container.querySelector(markerSelector);
            const navItem = navItemByPage.get(pageName);
            container.classList.toggle('runtime-readonly', shouldLock);
            container.setAttribute('data-runtime-readonly', shouldLock ? 'true' : 'false');
            container.setAttribute('aria-disabled', shouldLock ? 'true' : 'false');
            if (navItem) {
                navItem.classList.toggle('is-readonly-route', shouldLock);
                navItem.setAttribute('data-runtime-readonly', shouldLock ? 'true' : 'false');
                if (shouldLock) {
                    navItem.setAttribute('data-runtime-badge', 'READ-ONLY');
                    navItem.setAttribute('title', String(message || '当前页面为只读模式。'));
                } else {
                    navItem.removeAttribute('data-runtime-badge');
                    navItem.removeAttribute('title');
                }
            }

            if (!shouldLock) {
                marker?.remove();
                return;
            }

            const note = marker || document.createElement('div');
            note.className = 'runtime-readonly-note';
            note.textContent = String(message || '机器人未启动：当前页面处于只读模式。');
            if (!marker) {
                if (typeof container.insertBefore === 'function') {
                    container.insertBefore(note, container.firstChild || null);
                } else {
                    container.appendChild(note);
                }
            }
        });
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
        ensureAppFrame();
        const app = new App();
        await app.init();

        const allowDebugGlobals = String(window.location?.search || '').includes('debug_globals=1');
        if (allowDebugGlobals) {
            window.__app = app;
            window.__state = stateManager;
            window.__events = eventBus;
        }
    });
}
