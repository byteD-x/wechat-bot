/**
 * 微信AI助手渲染进程入口。
 */

if (typeof window.dragEvent === 'undefined') {
    window.dragEvent = window.DragEvent;
}

import { stateManager, eventBus, Events } from './core/index.js';
import { apiService, notificationService } from './services/index.js';
import { DashboardPage, MessagesPage, SettingsPage, LogsPage } from './pages/index.js';

class App {
    constructor() {
        this.pages = {
            dashboard: new DashboardPage(),
            messages: new MessagesPage(),
            settings: new SettingsPage(),
            logs: new LogsPage()
        };

        this.currentPage = null;
        this._statusTimer = null;
        this._statusRefreshing = false;
        this._statusFailureCount = 0;
        this._statusBaseIntervalMs = 5000;
        this._statusMaxIntervalMs = 30000;
        this._backendStartAttempted = false;
        this._statusPausedByVisibility = false;
        this._lastStatusSignature = null;
        this._lastUpdateToastVersion = '';
        this._removeUpdateListener = null;
        this._eventSource = null;
    }

    async init() {
        console.log('[App] 正在初始化...');

        await apiService.init();
        notificationService.init();

        await this._setupVersion();
        await this._setupUpdater();

        this._bindGlobalEvents();
        this._bindKeyboardShortcuts();
        this._setupCloseChoiceModal();

        for (const page of Object.values(this.pages)) {
            await page.onInit();
        }

        await this._checkBackendConnection();
        await this._refreshStatus();
        this._connectSSE();
        await this._switchPage('dashboard');
        this._startStatusRefresh();

        console.log('[App] 初始化完成');
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

        if (!connected && window.electronAPI?.startBackend && !this._backendStartAttempted) {
            this._backendStartAttempted = true;
            this._startBackendWithFeedback();
        }
    }

    async _startBackendWithFeedback() {
        try {
            notificationService.info('后端未连接，正在尝试启动...');
            await window.electronAPI.startBackend();
            await new Promise(resolve => setTimeout(resolve, 1200));
            await this._checkBackendConnection();

            if (!stateManager.get('bot.connected')) {
                notificationService.error('后端启动失败，请检查环境或日志');
            } else {
                notificationService.success('后端已连接');
            }
        } catch (error) {
            console.error('[App] 启动后端失败:', error);
            notificationService.error('后端启动失败，请检查环境或日志');
        }
    }

    _bindGlobalEvents() {
        document.querySelectorAll('.nav-item').forEach(item => {
            item.addEventListener('click', (event) => {
                event.preventDefault();
                this._switchPage(item.dataset.page);
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
            if (!window.electronAPI?.startBackend || stateManager.get('bot.connected')) {
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
            this._switchPage(pageName);
        });

        eventBus.on(Events.BOT_STATUS_CHANGE, () => {
            this._refreshStatus();
        });

        document.addEventListener('visibilitychange', () => {
            if (document.hidden) {
                this._statusPausedByVisibility = true;
                this._scheduleNextStatusRefresh(null);
            } else if (this._statusPausedByVisibility) {
                this._statusPausedByVisibility = false;
                this._scheduleNextStatusRefresh(0);
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
                this._switchPage('messages');
                return;
            }
            if (key === '3') {
                event.preventDefault();
                this._switchPage('settings');
                return;
            }
            if (key === '4') {
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
            console.error('[App] 快捷键重启失败:', error);
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
        if (!result?.success && stateManager.get('updater.available')) {
            notificationService.warning('未找到 GitHub Releases 下载地址。');
        }
    }

    async _switchPage(pageName) {
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

        if (this.currentPage) {
            await this.currentPage.onEnter();
        }

        console.log(`[App] 切换到页面: ${pageName}`);
    }

    async _refreshStatus() {
        if (this._statusRefreshing) {
            return;
        }

        this._statusRefreshing = true;
        try {
            const status = await apiService.getStatus();
            this._applyStatus(status, { connected: true });
            this._statusFailureCount = 0;
        } catch (error) {
            console.error('[App] 刷新状态失败:', error);
            stateManager.set('bot.connected', false);
            this._updateConnectionStatus();
            this._statusFailureCount += 1;
        } finally {
            this._statusRefreshing = false;
            this._scheduleNextStatusRefresh(this._getNextStatusIntervalMs());
        }
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

        const statusSignature = JSON.stringify(status);
        if (this.pages.dashboard && statusSignature !== this._lastStatusSignature) {
            this.pages.dashboard.updateStats(status);
            this._lastStatusSignature = statusSignature;
        }

        this._updateConnectionStatus();
    }

    _connectSSE() {
        if (this._eventSource) {
            return;
        }
        this._eventSource = apiService.connectSSE(
            (payload) => this._handleRealtimeEvent(payload),
            () => {
                stateManager.set('bot.connected', false);
                this._updateConnectionStatus();
            }
        );
    }

    _handleRealtimeEvent(payload) {
        if (!payload || typeof payload !== 'object') {
            return;
        }
        if (payload.type === 'status_change' && payload.data) {
            this._applyStatus(payload.data, { connected: true });
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
        if (startupActive && this._statusFailureCount <= 0) {
            return 400;
        }

        if (this._statusFailureCount <= 0) {
            return this._statusBaseIntervalMs;
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
        const connected = stateManager.get('bot.connected');
        const running = stateManager.get('bot.running');
        const paused = stateManager.get('bot.paused');

        if (!connected) {
            dot.className = 'status-dot offline';
            label.textContent = '未连接';
        } else if (running) {
            if (paused) {
                dot.className = 'status-dot warning';
                label.textContent = '已暂停';
            } else {
                dot.className = 'status-dot online';
                label.textContent = '运行中';
            }
        } else {
            dot.className = 'status-dot offline';
            label.textContent = '已停止';
        }
    }

    _startStatusRefresh() {
        this._scheduleNextStatusRefresh(0);
    }

    _scheduleNextStatusRefresh(delayMs) {
        if (this._statusTimer) {
            clearTimeout(this._statusTimer);
            this._statusTimer = null;
        }

        if (delayMs === null || document.hidden) {
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
