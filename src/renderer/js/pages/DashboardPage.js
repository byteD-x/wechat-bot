/**
 * 仪表盘页面控制器
 */

import { PageController } from '../core/PageController.js';
import { Events } from '../core/EventBus.js';
import { apiService } from '../services/ApiService.js';
import { toast } from '../services/NotificationService.js';
import {
    formatCurrencyGroups,
    formatCurrencyValue,
    formatDurationMs,
    formatDurationSec,
    formatGrowthTimestamp,
    formatLatency,
    formatMemory,
    formatNumber,
    formatPercent,
    formatQueue,
    formatStartupUpdatedAt,
    formatTime,
    formatTimingLabel,
    formatTokens,
    getGrowthBatchReason,
    getGrowthModeLabel,
    getGrowthTaskLabel,
    getStartupStageLabel,
} from './dashboard/formatters.js';
import {
    createCompactEmpty,
    createGrowthTaskActionButton,
    renderDashboardCost,
    renderDiagnostics,
    renderGrowthTasks,
    renderHealthCheckItem,
    renderHealthMetrics,
    renderIdlePanel,
    renderMessages,
    renderRetrieval,
    renderStartupState,
    syncStartupMeta,
} from './dashboard/renderers.js';

export class DashboardPage extends PageController {
    constructor() {
        super('DashboardPage', 'page-dashboard');
        this._lastStats = null;
        this._recentMessages = [];
        this._lastCostFetchAt = 0;
        this._idleRenderTimer = null;
        this._dashboardCost = {
            today: null,
            recent: null,
        };
    }

    async onInit() {
        await super.onInit();
        this._bindEvents();
        this.listenEvent(Events.MESSAGE_RECEIVED, (message) => {
            this._appendRecentMessage(message);
        });
    }

    async onEnter() {
        await super.onEnter();
        this._startIdleTimer();
        this._updateBotUI();

        const status = this.getState('bot.status');
        if (status) {
            this.updateStats(status);
        }

        if (!this.getState('bot.connected')) {
            this._clearOfflineData();
            return;
        }

        await Promise.all([
            this._loadRecentMessages(),
            this._refreshDashboardCost(true),
        ]);
    }

    async onLeave() {
        this._stopIdleTimer();
        await super.onLeave();
    }

    async onDestroy() {
        this._stopIdleTimer();
        await super.onDestroy();
    }

    _bindEvents() {
        this.bindEvent('#btn-toggle-bot', 'click', () => this._toggleBot());
        this.bindEvent('#btn-toggle-growth', 'click', () => this._toggleGrowth());
        this.bindEvent('#growth-task-queue', 'click', (event) => this._handleGrowthTaskAction(event));
        this.bindEvent('#btn-pause', 'click', () => this._togglePause());
        this.bindEvent('#btn-restart', 'click', () => this._restartBot());
        this.bindEvent('#btn-recover-bot', 'click', () => this._recoverBot());
        this.bindEvent('#btn-open-costs', 'click', () => this.emit(Events.PAGE_CHANGE, 'costs'));
        this.bindEvent('#btn-view-logs', 'click', () => this.emit(Events.PAGE_CHANGE, 'logs'));
        this.bindEvent('#btn-view-all-messages', 'click', () => this.emit(Events.PAGE_CHANGE, 'messages'));
        this.bindEvent('#backend-idle-panel', 'click', (event) => this._handleIdleActionClick(event));

        this.bindEvent('#btn-refresh-status', 'click', () => {
            if (this._getIdleState().state === 'stopped_by_idle') {
                void this._wakeBackend();
                return;
            }
            this.emit(Events.BOT_STATUS_CHANGE, {});
            toast.success('已触发状态刷新');
            void this._refreshDashboardCost(true);
        });

        this.bindEvent('#btn-minimize-tray', 'click', () => {
            window.electronAPI?.minimizeToTray();
        });

        this.bindEvent('#btn-open-wechat', 'click', async () => {
            try {
                if (window.electronAPI?.openWeChat) {
                    await window.electronAPI.openWeChat();
                    toast.success('正在打开微信客户端...');
                } else {
                    toast.info('请手动打开微信客户端');
                }
            } catch (error) {
                console.error('[DashboardPage] 打开微信失败:', error);
                if (String(error?.message || '').includes('No handler registered')) {
                    toast.error('请重启应用后重试');
                } else {
                    toast.error('打开微信客户端失败');
                }
            }
        });

        const updateIfActive = () => {
            if (this.isActive()) {
                this._updateBotUI();
            }
        };
        this.watchState('bot.status', updateIfActive);
        this.watchState('bot.running', updateIfActive);
        this.watchState('bot.paused', updateIfActive);
        this.watchState('backend.idle', updateIfActive);
        this.watchState('bot.connected', (connected) => {
            if (!this.isActive()) {
                return;
            }
            this._updateBotUI();
            if (!connected) {
                this._clearOfflineData();
                return;
            }
            void this._loadRecentMessages();
            void this._refreshDashboardCost(true);
        });
    }

    _handleIdleActionClick(event) {
        const target = event?.target;
        if (!(target instanceof Element)) {
            return;
        }

        const button = target.closest('button');
        if (!button || button.disabled || button.hidden) {
            return;
        }

        if (button.id === 'btn-cancel-idle-shutdown') {
            event.preventDefault();
            event.stopPropagation();
            toast.info('正在处理自动停机设置...');
            void this._cancelIdleShutdown();
            return;
        }

        if (button.id === 'btn-wake-backend') {
            event.preventDefault();
            event.stopPropagation();
            toast.info('正在尝试唤醒后端服务...');
            void this._wakeBackend();
        }
    }

    async _toggleBot() {
        const btn = this.$('#btn-toggle-bot');
        const btnText = btn?.querySelector('span');
        if (!btn) {
            return;
        }

        btn.disabled = true;

        try {
            const isRunning = !!this.getState('bot.running');

            if (isRunning) {
                if (btnText) {
                    btnText.textContent = '停止中...';
                }
                const result = window.electronAPI?.runtimeStopBot
                    ? await window.electronAPI.runtimeStopBot()
                    : await apiService.stopBot();
                toast.show(
                    result?.message || (result?.success ? '机器人已停止' : '停止机器人失败'),
                    result?.success ? 'success' : 'error'
                );
            } else {
                const accepted = await this._ensureGrowthEnablePrompt();
                if (!accepted) {
                    return;
                }
                if (btnText) {
                    btnText.textContent = '启动中...';
                }

                const prevStatus = this.getState('bot.status');
                const base = prevStatus && typeof prevStatus === 'object' ? prevStatus : {};
                this.setState('bot.status', {
                    ...base,
                    startup: {
                        stage: 'starting',
                        message: '正在启动机器人...',
                        progress: 0,
                        active: true,
                        updated_at: Date.now() / 1000
                    }
                });

                const result = window.electronAPI?.runtimeStartBot
                    ? await window.electronAPI.runtimeStartBot()
                    : await apiService.startBot();
                toast.show(
                    result?.message || (result?.success ? '机器人启动中' : '启动机器人失败'),
                    result?.success ? 'success' : 'error'
                );
            }

            this.emit(Events.BOT_STATUS_CHANGE, {});
            setTimeout(() => this.emit(Events.BOT_STATUS_CHANGE, {}), 1000);
        } catch (error) {
            toast.error(toast.getErrorMessage(error, '启动机器人失败'));
        } finally {
            btn.disabled = false;
        }
    }

    async _toggleGrowth() {
        const button = this.$('#btn-toggle-growth');
        const buttonText = button?.querySelector('span') || button;
        if (!button) {
            return;
        }

        button.disabled = true;
        try {
            const status = this.getState('bot.status') || {};
            const growthRunning = !!status.growth_running;
            if (growthRunning) {
                const accepted = await this._ensureGrowthDisablePrompt();
                if (!accepted) {
                    return;
                }
                if (buttonText) {
                    buttonText.textContent = '停止中...';
                }
                const result = window.electronAPI?.runtimeStopGrowth
                    ? await window.electronAPI.runtimeStopGrowth()
                    : await apiService.request?.('/api/growth/stop', { method: 'POST' });
                toast.show(
                    result?.message || (result?.success ? '成长任务已停止' : '停止成长任务失败'),
                    result?.success ? 'success' : 'error'
                );
            } else {
                if (buttonText) {
                    buttonText.textContent = '启动中...';
                }
                const result = window.electronAPI?.runtimeStartGrowth
                    ? await window.electronAPI.runtimeStartGrowth()
                    : await apiService.request?.('/api/growth/start', { method: 'POST' });
                toast.show(
                    result?.message || (result?.success ? '成长任务已启动' : '启动成长任务失败'),
                    result?.success ? 'success' : 'error'
                );
            }

            this.emit(Events.BOT_STATUS_CHANGE, {});
            setTimeout(() => this.emit(Events.BOT_STATUS_CHANGE, {}), 1000);
        } catch (error) {
            toast.error(toast.getErrorMessage(error, '成长任务操作失败'));
        } finally {
            button.disabled = false;
            this._updateBotUI();
        }
    }

    async _handleGrowthTaskAction(event) {
        const button = event?.target?.closest?.('[data-growth-action]');
        if (!button) {
            return;
        }

        const taskType = String(button.dataset.taskType || '').trim();
        const action = String(button.dataset.growthAction || '').trim();
        if (!taskType || !action) {
            return;
        }

        if (action === 'clear') {
            const accepted = await this._confirmAction({
                kicker: '队列操作',
                title: '确认清空成长任务队列',
                subtitle: '该操作会立即移除当前等待执行的任务。',
                message: `确认清空“${this._getGrowthTaskLabel(taskType)}”队列吗？`,
                confirmText: '确认清空',
            });
            if (!accepted) {
                return;
            }
        }

        button.disabled = true;
        try {
            await this._runGrowthTaskAction(taskType, action);
            this.emit(Events.BOT_STATUS_CHANGE, {});
            setTimeout(() => this.emit(Events.BOT_STATUS_CHANGE, {}), 400);
        } catch (error) {
            toast.error(toast.getErrorMessage(error, '成长任务操作失败'));
        } finally {
            button.disabled = false;
        }
    }

    async _runGrowthTaskAction(taskType, action) {
        const label = this._getGrowthTaskLabel(taskType);
        let result = null;

        if (action === 'run') {
            result = await apiService.runGrowthTaskNow(taskType);
            toast.show(result?.message || `已触发 ${label} 立即执行`, result?.success ? 'success' : 'error');
            return result;
        }

        if (action === 'clear') {
            result = await apiService.clearGrowthTask(taskType);
            toast.show(result?.message || `已清空 ${label} 队列`, result?.success ? 'success' : 'error');
            return result;
        }

        if (action === 'pause') {
            result = await apiService.pauseGrowthTask(taskType);
            toast.show(result?.message || `已暂停 ${label}`, result?.success ? 'success' : 'error');
            return result;
        }

        if (action === 'resume') {
            result = await apiService.resumeGrowthTask(taskType);
            toast.show(result?.message || `已恢复 ${label}`, result?.success ? 'success' : 'error');
            return result;
        }

        throw new Error(`unsupported_growth_action:${action}`);
    }

    async _ensureGrowthEnablePrompt() {
        if (!window.electronAPI?.getGrowthPromptState || !window.electronAPI?.markGrowthPromptSeen) {
            return true;
        }
        const promptState = await window.electronAPI.getGrowthPromptState();
        if (promptState?.enableCostSeen) {
            return true;
        }
        const accepted = await this._confirmAction({
            kicker: '启动提醒',
            title: '确认启动机器人',
            subtitle: '成长任务会随机器人一起启动。',
            message: '启动机器人会自动开启成长任务，并持续消耗模型额度用于后台整理记忆、画像和语料。确认继续吗？',
            confirmText: '确认启动',
        });
        if (!accepted) {
            return false;
        }
        await window.electronAPI.markGrowthPromptSeen('enable-cost');
        return true;
    }

    async _ensureGrowthDisablePrompt() {
        if (!window.electronAPI?.getGrowthPromptState || !window.electronAPI?.markGrowthPromptSeen) {
            return true;
        }
        const promptState = await window.electronAPI.getGrowthPromptState();
        if (promptState?.disableRiskSeen) {
            return true;
        }
        const accepted = await this._confirmAction({
            kicker: '风险提示',
            title: '确认关闭成长任务',
            subtitle: '关闭后不会影响当前界面操作，但会影响后续回复质量的成长链路。',
            message: '关闭成长任务后，后台记忆整理、画像更新和语料增量处理都会暂停，可能影响后续回复质量。确认继续吗？',
            confirmText: '确认关闭',
        });
        if (!accepted) {
            return false;
        }
        await window.electronAPI.markGrowthPromptSeen('disable-risk');
        return true;
    }

    async _confirmAction(options) {
        if (typeof window.appConfirm === 'function') {
            return window.appConfirm(options);
        }
        return window.confirm(String(options?.message || '确认是否继续？'));
    }

    _startIdleTimer() {
        if (this._idleRenderTimer) {
            return;
        }
        this._idleRenderTimer = setInterval(() => {
            if (this.isActive()) {
                this._renderIdlePanel();
            }
        }, 1000);
    }

    _stopIdleTimer() {
        if (!this._idleRenderTimer) {
            return;
        }
        clearInterval(this._idleRenderTimer);
        this._idleRenderTimer = null;
    }

    _getIdleState() {
        return this.getState('backend.idle') || {
            state: 'active',
            delayMs: 15 * 60 * 1000,
            remainingMs: 15 * 60 * 1000,
            reason: '',
            updatedAt: Date.now(),
        };
    }

    _getIdleRemainingMs(idleState = this._getIdleState()) {
        if (!idleState || idleState.state !== 'countdown') {
            return Math.max(0, Number(idleState?.remainingMs || 0));
        }
        const updatedAt = Number(idleState.updatedAt || Date.now());
        const elapsed = Math.max(0, Date.now() - updatedAt);
        return Math.max(0, Number(idleState.remainingMs || 0) - elapsed);
    }

    _formatDurationMs(value) {
        return formatDurationMs(value);
    }

    async _cancelIdleShutdown() {
        const currentIdleState = this._getIdleState();
        if (currentIdleState.state === 'active') {
            toast.info('当前没有进行中的自动停机计时');
            return;
        }
        if (currentIdleState.state === 'stopped_by_idle') {
            toast.info('后端已经休眠，可以直接点击立即唤醒');
            return;
        }
        if (!window.electronAPI?.runtimeCancelIdleShutdown) {
            toast.warning('当前版本不支持取消自动停机，请重启应用后重试');
            return;
        }
        try {
            const result = await window.electronAPI.runtimeCancelIdleShutdown();
            const idleState = result?.idle_state || (
                window.electronAPI?.getRuntimeIdleState
                    ? await window.electronAPI.getRuntimeIdleState()
                    : null
            );
            if (idleState) {
                this.setState('backend.idle', idleState);
            }
            this._renderIdlePanel();
            this.emit(Events.BOT_STATUS_CHANGE, { force: true });
            toast.success('已重置本轮后端休眠计时');
        } catch (error) {
            toast.error(toast.getErrorMessage(error, '取消自动停机失败'));
        }
    }

    async _wakeBackend() {
        const currentIdleState = this._getIdleState();
        if (this.getState('bot.connected') && currentIdleState.state === 'active') {
            toast.info('后端当前已经在线，无需额外唤醒');
            return;
        }
        try {
            if (window.electronAPI?.runtimeEnsureService) {
                await window.electronAPI.runtimeEnsureService();
            } else if (window.electronAPI?.startBackend) {
                await window.electronAPI.startBackend();
            } else {
                toast.warning('当前版本不支持立即唤醒，请重启应用后重试');
                return;
            }

            if (window.electronAPI?.getRuntimeIdleState) {
                const idleState = await window.electronAPI.getRuntimeIdleState();
                this.setState('backend.idle', idleState);
            }

            try {
                const status = await apiService.getStatus();
                this._applyStatusSnapshot(status);
            } catch (error) {
                console.warn('[DashboardPage] wake backend status refresh failed:', error);
            }

            this.emit(Events.BOT_STATUS_CHANGE, { force: true });
            setTimeout(() => this.emit(Events.BOT_STATUS_CHANGE, { force: true }), 600);
            this.emit(Events.BOT_STATUS_CHANGE, {});
            setTimeout(() => this.emit(Events.BOT_STATUS_CHANGE, {}), 600);
            toast.success('后端已唤醒');
        } catch (error) {
            toast.error(toast.getErrorMessage(error, '唤醒后端失败'));
        }
    }

    _applyStatusSnapshot(status) {
        if (!status || typeof status !== 'object') {
            return;
        }

        this.setState('bot.connected', true);
        this.setState('bot.running', !!status.running);
        this.setState('bot.paused', !!status.is_paused);
        this.setState('bot.status', status);
        this._updateBotUI();
    }

    async _togglePause() {
        try {
            const isPaused = !!this.getState('bot.paused');
            const result = isPaused
                ? await apiService.resumeBot()
                : await apiService.pauseBot();

            toast.show(
                result?.message || (result?.success ? '操作成功' : '操作失败'),
                result?.success ? 'success' : 'error'
            );
            this.emit(Events.BOT_STATUS_CHANGE, {});
        } catch (error) {
            toast.error(toast.getErrorMessage(error, '暂停/恢复失败'));
        }
    }

    async _restartBot() {
        try {
            toast.info('正在重启机器人...');
            const result = await apiService.restartBot();
            toast.show(
                result?.message || (result?.success ? '机器人正在重启' : '重启机器人失败'),
                result?.success ? 'success' : 'error'
            );
            this.emit(Events.BOT_STATUS_CHANGE, {});
            setTimeout(() => this.emit(Events.BOT_STATUS_CHANGE, {}), 2000);
        } catch (error) {
            toast.error(toast.getErrorMessage(error, '重启机器人失败'));
        }
    }

    async _recoverBot() {
        try {
            toast.info('正在尝试恢复机器人...');
            const result = await apiService.recoverBot();
            toast.show(
                result?.message || (result?.success ? '机器人恢复中' : '恢复机器人失败'),
                result?.success ? 'success' : 'error'
            );
            this.emit(Events.BOT_STATUS_CHANGE, {});
            setTimeout(() => this.emit(Events.BOT_STATUS_CHANGE, {}), 1500);
        } catch (error) {
            toast.error(toast.getErrorMessage(error, '恢复机器人失败'));
        }
    }

    _updateBotUI() {
        const connected = !!this.getState('bot.connected');
        const isRunning = !!this.getState('bot.running');
        const isPaused = !!this.getState('bot.paused');
        const status = this.getState('bot.status') || {};
        const idleState = this._getIdleState();
        const startupActive = !!status?.startup?.active;
        const growthRunning = !!status?.growth_running;
        const isIdleStandby = idleState.state === 'standby' || idleState.state === 'countdown';
        const isIdleStopped = idleState.state === 'stopped_by_idle';

        const stateElem = this.$('#bot-state');
        if (stateElem) {
            const dot = stateElem.querySelector('.bot-state-dot');
            const text = stateElem.querySelector('.bot-state-text');
            let stateText = '机器人未启动';
            let dotClass = 'bot-state-dot ready';

            if (!connected && isIdleStopped) {
                stateText = '后端已休眠';
                dotClass = 'bot-state-dot sleeping';
            } else if (!connected) {
                stateText = '服务未连接';
                dotClass = 'bot-state-dot offline';
            } else if (isRunning && isPaused) {
                stateText = '已暂停';
                dotClass = 'bot-state-dot paused';
            } else if (isRunning) {
                stateText = '运行中';
                dotClass = 'bot-state-dot online';
            } else if (startupActive) {
                stateText = '启动中';
                dotClass = 'bot-state-dot starting';
            } else if (isIdleStandby) {
                stateText = '后端待机中';
                dotClass = 'bot-state-dot standby';
            }

            if (dot) {
                dot.className = dotClass;
            }
            if (text) {
                text.textContent = stateText;
            }
        }

        const pauseBtn = this.$('#btn-pause');
        const pauseText = pauseBtn?.querySelector('span');
        if (pauseBtn) {
            pauseBtn.disabled = !connected || !isRunning;
        }
        if (pauseText) {
            pauseText.textContent = isPaused ? '继续运行' : '暂停';
        }

        const restartBtn = this.$('#btn-restart');
        if (restartBtn) {
            restartBtn.disabled = !connected || (!isRunning && !startupActive);
        }

        const toggleBtn = this.$('#btn-toggle-bot');
        if (toggleBtn) {
            const icon = toggleBtn.querySelector('svg use');
            const text = toggleBtn.querySelector('span');

            if (connected && (isRunning || startupActive)) {
                if (text) {
                    text.textContent = startupActive && !isRunning ? '启动中...' : '停止机器人';
                }
                icon?.setAttribute('href', '#icon-square');
                toggleBtn.classList.remove('btn-primary');
                toggleBtn.classList.add('btn-secondary');
            } else {
                if (text) {
                    text.textContent = '启动机器人';
                }
                icon?.setAttribute('href', '#icon-play');
                toggleBtn.classList.remove('btn-secondary');
                toggleBtn.classList.add('btn-primary');
            }
        }

        const growthEnabled = !!status?.growth_enabled;
        const backlogCount = Number(status?.background_backlog_count || 0);
        const growthStatus = this.$('#growth-task-status');
        const growthBacklog = this.$('#growth-task-backlog');
        const growthQueue = this.$('#growth-task-queue');
        const growthBatch = this.$('#growth-task-batch');
        const growthNext = this.$('#growth-task-next');
        const growthError = this.$('#growth-task-error');
        const growthButton = this.$('#btn-toggle-growth');
        const growthButtonText = growthButton?.querySelector('span') || growthButton;
        if (growthStatus) {
            if (!connected && isIdleStopped) {
                growthStatus.textContent = '后端已休眠';
            } else if (!connected) {
                growthStatus.textContent = '服务未连接';
            } else {
                growthStatus.textContent = growthRunning
                    ? '运行中'
                    : (growthEnabled ? '已启用，等待启动' : '未启动');
            }
        }
        if (growthBacklog) {
            growthBacklog.textContent = connected
                ? `待处理任务 ${this._formatNumber(backlogCount)}`
                : '待处理任务 --';
        }
        this._renderGrowthTasks(connected, status, {
            queueElement: growthQueue,
            batchElement: growthBatch,
            nextElement: growthNext,
            errorElement: growthError,
        });
        if (growthButtonText) {
            growthButtonText.textContent = growthRunning ? '停止成长任务' : '启动成长任务';
        }

        this._renderIdlePanel({
            connected,
            isRunning,
            growthRunning,
            startupActive,
            idleState,
        });
        this._renderStartupState(status.startup);
        this._syncStartupMeta(status.startup);
        this._renderDiagnostics(status.diagnostics);
    }

    _renderIdlePanel(context = {}) {
        renderIdlePanel(this, context, {
            getIdleState: () => this._getIdleState(),
            getIdleRemainingMs: (idleState) => this._getIdleRemainingMs(idleState),
            formatDurationMs: (value) => this._formatDurationMs(value),
        });
    }

    _clearOfflineData() {
        this._recentMessages = [];
        this._dashboardCost = {
            today: null,
            recent: null,
        };

        const container = this.$('#recent-messages');
        if (container) {
            this._renderMessages(container, this._recentMessages);
        }
        this._renderDashboardCost();
    }

    async _loadRecentMessages() {
        if (!this.getState('bot.connected')) {
            this._clearOfflineData();
            return;
        }

        try {
            const result = await apiService.getMessages({ limit: 5, offset: 0 });
            const container = this.$('#recent-messages');
            if (result?.success && Array.isArray(result.messages) && container) {
                this._recentMessages = [...result.messages].reverse();
                this._renderMessages(container, this._recentMessages);
            }
        } catch (error) {
            console.error('[DashboardPage] 加载最近消息失败:', error);
        }
    }

    _appendRecentMessage(message) {
        if (!message) {
            return;
        }
        const container = this.$('#recent-messages');
        if (!container) {
            return;
        }

        const normalized = {
            sender: message.sender,
            content: message.content,
            text: message.text,
            timestamp: message.timestamp,
            is_self: message.direction === 'outgoing'
        };

        this._recentMessages = [...this._recentMessages, normalized].slice(-5);
        this._renderMessages(container, this._recentMessages);
    }

    _renderMessages(container, messages) {
        renderMessages(container, messages);
    }

    _formatTime(timestamp) {
        return formatTime(timestamp);
    }

    _getGrowthTaskLabel(taskType) {
        return getGrowthTaskLabel(taskType);
    }

    _getGrowthModeLabel(mode) {
        return getGrowthModeLabel(mode);
    }

    _getGrowthBatchReason(reason) {
        return getGrowthBatchReason(reason);
    }

    _formatGrowthTimestamp(value) {
        return formatGrowthTimestamp(value);
    }

    _createGrowthTaskActionButton(taskType, action, label) {
        return createGrowthTaskActionButton(taskType, action, label);
    }

    _renderGrowthTasks(connected, status, elements = {}) {
        renderGrowthTasks(connected, status, elements);
    }

    updateStats(stats) {
        const nextStats = {
            uptime: stats.uptime || '--',
            today_replies: stats.today_replies ?? 0,
            today_tokens: stats.today_tokens ?? 0,
            total_replies: stats.total_replies ?? 0,
            transport_backend: stats.transport_backend || '--',
            wechat_version: stats.wechat_version || '--',
            silent_mode: stats.silent_mode !== false,
            transport_warning: stats.transport_warning || '',
            startup: stats.startup || null,
            diagnostics: stats.diagnostics || null,
            system_metrics: stats.system_metrics || {},
            health_checks: stats.health_checks || {},
            merge_feedback: stats.merge_feedback || null,
            retriever_stats: stats.retriever_stats || {},
            runtime_timings: stats.runtime_timings || {},
            export_rag: stats.export_rag || null,
        };

        const uptimeElem = this.$('#stat-uptime');
        const todayRepliesElem = this.$('#stat-today-replies');
        const todayTokensElem = this.$('#stat-today-tokens');
        const totalRepliesElem = this.$('#stat-total-replies');
        const transportBackendElem = this.$('#bot-transport-backend');
        const transportVersionElem = this.$('#bot-transport-version');
        const transportWarningElem = this.$('#bot-transport-warning');

        if (uptimeElem) {
            uptimeElem.textContent = nextStats.uptime;
        }
        if (todayRepliesElem) {
            todayRepliesElem.textContent = this._formatNumber(nextStats.today_replies);
        }
        if (todayTokensElem) {
            todayTokensElem.textContent = this._formatTokens(nextStats.today_tokens);
        }
        if (totalRepliesElem) {
            totalRepliesElem.textContent = this._formatNumber(nextStats.total_replies);
        }
        if (transportBackendElem) {
            const modeText = nextStats.silent_mode ? '静默模式' : '标准模式';
            transportBackendElem.textContent = `后端: ${nextStats.transport_backend} (${modeText})`;
        }
        if (transportVersionElem) {
            transportVersionElem.textContent = `微信: ${nextStats.wechat_version}`;
        }
        if (transportWarningElem) {
            transportWarningElem.hidden = !nextStats.transport_warning;
            transportWarningElem.textContent = nextStats.transport_warning || '';
        }

        this._renderStartupState(nextStats.startup);
        this._syncStartupMeta(nextStats.startup);
        this._renderDiagnostics(nextStats.diagnostics);
        this._renderHealthMetrics(
            nextStats.system_metrics,
            nextStats.health_checks,
            nextStats.merge_feedback
        );
        this._renderRetrieval(
            nextStats.retriever_stats,
            nextStats.runtime_timings,
            nextStats.export_rag
        );
        void this._refreshDashboardCost();

        this._lastStats = nextStats;
    }

    async _refreshDashboardCost(force = false) {
        if (!this.getState('bot.connected')) {
            this._dashboardCost = {
                today: null,
                recent: null,
            };
            this._renderDashboardCost();
            return;
        }

        const now = Date.now();
        if (!force && now - this._lastCostFetchAt < 15000) {
            return;
        }
        this._lastCostFetchAt = now;

        try {
            const [today, recent] = await Promise.all([
                apiService.getCostSummary({
                    period: 'today',
                    include_estimated: true,
                }),
                apiService.getCostSummary({
                    period: '30d',
                    include_estimated: true,
                }),
            ]);

            if (today?.success) {
                this._dashboardCost.today = today;
            }
            if (recent?.success) {
                this._dashboardCost.recent = recent;
            }

            this._renderDashboardCost();
        } catch (error) {
            console.error('[DashboardPage] 加载成本概览失败:', error);
        }
    }

    _renderDashboardCost() {
        renderDashboardCost(this, this._dashboardCost);
    }

    _createCompactEmpty(text) {
        return createCompactEmpty(text);
    }

    _renderStartupState(startup) {
        renderStartupState(this, startup);
    }

    _syncStartupMeta(startup) {
        syncStartupMeta(this, startup);
    }

    _renderDiagnostics(diagnostics) {
        renderDiagnostics(this, diagnostics);
    }

    _renderHealthMetrics(metrics = {}, checks = {}, mergeFeedback = null) {
        renderHealthMetrics(this, metrics, checks, mergeFeedback);
    }

    _renderHealthCheckItem(elementId, check) {
        renderHealthCheckItem(this, elementId, check);
    }

    _renderRetrieval(retrieverStats = {}, timings = {}, exportRag = null) {
        renderRetrieval(this, retrieverStats, timings, exportRag);
    }

    _formatDurationSec(value) {
        return formatDurationSec(value);
    }

    _formatTimingLabel(key) {
        return formatTimingLabel(key);
    }

    _getStartupStageLabel(stage) {
        return getStartupStageLabel(stage);
    }

    _formatStartupUpdatedAt(timestamp) {
        return formatStartupUpdatedAt(timestamp);
    }

    _formatPercent(value) {
        return formatPercent(value);
    }

    _formatMemory(processMemory, systemPercent) {
        return formatMemory(processMemory, systemPercent);
    }

    _formatQueue(pendingTasks, pendingChats, pendingMessages) {
        return formatQueue(pendingTasks, pendingChats, pendingMessages);
    }

    _formatLatency(value) {
        return formatLatency(value);
    }

    _formatNumber(value) {
        return formatNumber(value);
    }

    _formatTokens(value) {
        return formatTokens(value);
    }

    _formatCurrencyGroups(groups) {
        return formatCurrencyGroups(groups);
    }

    _formatCurrencyValue(currency, amount) {
        return formatCurrencyValue(currency, amount);
    }
}

export default DashboardPage;
