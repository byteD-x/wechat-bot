/**
 * 微信AI助手渲染进程入口。
 */

if (typeof window.dragEvent === 'undefined') {
    window.dragEvent = window.DragEvent;
}

import { stateManager, eventBus, Events } from './core/index.js';
import { apiService, notificationService } from './services/index.js';
import { DashboardPage, CostsPage, MessagesPage, SettingsPage, LogsPage, AboutPage } from './pages/index.js';

const DEFAULT_IDLE_DELAY_MS = 15 * 60 * 1000;
const AUTO_WAKE_PAGES = new Set(['dashboard', 'costs', 'messages', 'logs']);

class App {
    constructor() {
        this.pages = {
            dashboard: new DashboardPage(),
            costs: new CostsPage(),
            messages: new MessagesPage(),
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
        this._statusPausedByVisibility = false;
        this._lastUpdateToastVersion = '';
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

        await this._runInitStep('_setupVersion', () => this._setupVersion());
        await this._runInitStep('_setupUpdater', () => this._setupUpdater());

        this._bindGlobalEvents();
        this._bindKeyboardShortcuts();
        this._setupCloseChoiceModal();

        for (const [pageName, page] of Object.entries(this.pages)) {
            await this._runInitStep(`${pageName}.onInit`, () => page.onInit());
        }

        await this._runInitStep('_ensureLightweightBackend', () => this._ensureLightweightBackend());
        await this._runInitStep('_checkBackendConnection', () => this._checkBackendConnection());
        await this._runInitStep('_refreshStatus', () => this._refreshStatus());
        await this._runInitStep('_connectSSE', () => this._connectSSE());
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
        const delayMs = Number(idleState?.delayMs || DEFAULT_IDLE_DELAY_MS);
        const remainingMs = Number(idleState?.remainingMs ?? delayMs);
        return {
            state: String(idleState?.state || 'active').trim() || 'active',
            delayMs: Number.isFinite(delayMs) && delayMs > 0 ? delayMs : DEFAULT_IDLE_DELAY_MS,
            remainingMs: Number.isFinite(remainingMs) ? Math.max(0, Math.floor(remainingMs)) : DEFAULT_IDLE_DELAY_MS,
            reason: String(idleState?.reason || '').trim(),
            updatedAt: Number.isFinite(Number(idleState?.updatedAt))
                ? Number(idleState.updatedAt)
                : Date.now(),
        };
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
            'updater.error': updateState.error || ''
        });

        this._updateVersionText();
        this._updateSidebarUpdateBadge();

        const nextVersion = updateState.latestVersion || '';
        if (
            updateState.available &&
            (!previousAvailable || previousVersion !== nextVersion) &&
            !options.silent &&
            this._lastUpdateToastVersion !== nextVersion
        ) {
            this._lastUpdateToastVersion = nextVersion;
            notificationService.info(`发现新版本 v${nextVersion}，可在设置页下载更新。`, 5000);
        }
    }

    _updateVersionText() {
        const versionElem = document.getElementById('version-text');
        if (!versionElem) {
            return;
        }

        const currentVersion = stateManager.get('updater.currentVersion') || '--';
        const checking = stateManager.get('updater.checking');
        const available = stateManager.get('updater.available');
        const latestVersion = stateManager.get('updater.latestVersion');
        const enabled = stateManager.get('updater.enabled');

        let suffix = '';
        if (checking) {
            suffix = ' · 检查更新中';
        } else if (available && latestVersion) {
            suffix = ` · 可更新到 v${latestVersion}`;
        } else if (enabled) {
            suffix = ' · 已启用更新检查';
        }

        versionElem.textContent = `v${currentVersion}${suffix}`;
    }

    _updateSidebarUpdateBadge() {
        const badge = document.getElementById('update-badge');
        if (!badge) {
            return;
        }

        const available = stateManager.get('updater.available');
        const latestVersion = stateManager.get('updater.latestVersion');
        const checking = stateManager.get('updater.checking');

        if (available && latestVersion) {
            badge.hidden = false;
            badge.textContent = `新版本 v${latestVersion}`;
            badge.disabled = false;
            return;
        }

        if (checking) {
            badge.hidden = false;
            badge.textContent = '检查更新中...';
            badge.disabled = true;
            return;
        }

        badge.hidden = true;
        badge.disabled = false;
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
            await this._openUpdateDownload();
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
                this._switchPage('settings');
                return;
            }
            if (key === '5') {
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
            this._statusRefreshing = false;
            this._scheduleNextStatusRefresh(this._getNextStatusIntervalMs());
        }
    }

    _buildDisconnectedStatus(previousStatus = null, options = {}) {
        const baseStatus = previousStatus && typeof previousStatus === 'object'
            ? previousStatus
            : {};
        const previousStartup = baseStatus.startup && typeof baseStatus.startup === 'object'
            ? baseStatus.startup
            : {};
        const idleState = options?.idleState || this._getRuntimeIdleState();
        const isIdleStopped = idleState?.state === 'stopped_by_idle';
        const disconnectedMessage = isIdleStopped ? '后端已休眠' : '服务未启动';

        return {
            ...baseStatus,
            service_running: false,
            running: false,
            bot_running: false,
            growth_running: false,
            growth_enabled: false,
            is_paused: false,
            background_backlog_count: 0,
            last_background_batch: null,
            diagnostics: null,
            startup: {
                ...previousStartup,
                stage: 'stopped',
                message: disconnectedMessage,
                progress: 0,
                active: false,
                updated_at: Date.now() / 1000,
            },
        };
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
            console.warn('[App] SSE 连接异常，准备重连', err);
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
        const connected = !!stateManager.get('bot.connected');
        const running = !!stateManager.get('bot.running');
        const paused = !!stateManager.get('bot.paused');
        const status = stateManager.get('bot.status');
        const idleState = this._getRuntimeIdleState();
        const startupActive = !!(status && typeof status === 'object' && status?.startup?.active);
        const growthRunning = !!(status && typeof status === 'object' && status?.growth_running);
        const serviceRunning = !!(status && typeof status === 'object' && status?.service_running);
        const isIdleStandby = idleState.state === 'standby' || idleState.state === 'countdown';
        const isIdleStopped = idleState.state === 'stopped_by_idle';

        let labelText = '服务已就绪';
        let dotClass = 'status-dot offline';
        let titleText = 'Python 服务已启动，机器人未启动';

        if (!connected && isIdleStopped) {
            labelText = '后端已休眠';
            dotClass = 'status-dot sleeping';
            titleText = 'Python 服务已因空闲自动休眠，点击唤醒';
        } else if (!connected) {
            labelText = '服务未连接';
            dotClass = 'status-dot offline';
            titleText = (window.electronAPI?.runtimeEnsureService || window.electronAPI?.startBackend)
                ? 'Python 服务未连接，点击启动'
                : 'Python 服务未连接';
        } else if (!running && startupActive) {
            labelText = '机器人启动中';
            dotClass = 'status-dot warning';
            titleText = 'Python 服务已启动，机器人正在启动';
        } else if (running) {
            if (paused) {
                labelText = '机器人已暂停';
                dotClass = 'status-dot warning';
                titleText = 'Python 服务已启动，机器人当前处于暂停状态';
            } else {
                labelText = '机器人运行中';
                dotClass = 'status-dot online';
                titleText = 'Python 服务已启动，机器人正在运行';
            }
        } else if (growthRunning) {
            labelText = '成长任务运行中';
            dotClass = 'status-dot online';
            titleText = 'Python 服务已启动，成长任务正在运行';
        } else if (isIdleStandby) {
            labelText = '后端待机中';
            dotClass = 'status-dot standby';
            titleText = 'Python 服务在线，隐藏到托盘后会进入自动休眠倒计时';
        } else if (serviceRunning || connected) {
            labelText = '服务已就绪';
            dotClass = 'status-dot ready';
            titleText = 'Python 服务已启动，机器人未启动';
        }

        if (label) {
            label.textContent = labelText;
        }
        if (dot) {
            dot.className = dotClass;
        }
        badge.title = titleText;
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

document.addEventListener('DOMContentLoaded', async () => {
    const app = new App();
    await app.init();

    window.__app = app;
    window.__state = stateManager;
    window.__events = eventBus;
});
