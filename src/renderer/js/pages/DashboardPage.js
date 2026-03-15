/**
 * 仪表盘页面控制器
 */

import { PageController } from '../core/PageController.js';
import { Events } from '../core/EventBus.js';
import { apiService } from '../services/ApiService.js';
import { toast } from '../services/NotificationService.js';

export class DashboardPage extends PageController {
    constructor() {
        super('DashboardPage', 'page-dashboard');
        this._lastStats = null;
    }

    async onInit() {
        await super.onInit();
        this._bindEvents();
    }

    async onEnter() {
        await super.onEnter();
        this._updateBotUI();
        const status = this.getState('bot.status');
        if (status) {
            this.updateStats(status);
        }
    }

    // ═══════════════════════════════════════════════════════════════════════
    //                           事件绑定
    // ═══════════════════════════════════════════════════════════════════════

    _bindEvents() {
        // 启动/停止按钮
        this.bindEvent('#btn-toggle-bot', 'click', () => this._toggleBot());

        // 暂停按钮
        this.bindEvent('#btn-pause', 'click', () => this._togglePause());

        // 重启按钮
        this.bindEvent('#btn-restart', 'click', () => this._restartBot());
        this.bindEvent('#btn-recover-bot', 'click', () => this._recoverBot());

        // 快捷操作
        this.bindEvent('#btn-open-wechat', 'click', async () => {
            try {
                if (window.electronAPI && window.electronAPI.openWeChat) {
                    await window.electronAPI.openWeChat();
                    toast.success('正在打开微信...');
                } else {
                    toast.info('请手动打开微信客户端');
                }
            } catch (e) {
                console.error('打开微信失败:', e);
                if (e.message && e.message.includes('No handler registered')) {
                    toast.error('请重启应用以应用最新更改');
                } else {
                    toast.error('打开微信失败，请手动打开');
                }
            }
        });

        this.bindEvent('#btn-view-logs', 'click', () => {
            this.emit(Events.PAGE_CHANGE, 'logs');
        });

        this.bindEvent('#btn-refresh-status', 'click', async () => {
            this.emit(Events.BOT_STATUS_CHANGE, {});
            toast.success('状态已刷新');
        });

        this.bindEvent('#btn-minimize-tray', 'click', () => {
            window.electronAPI?.minimizeToTray();
        });

        // 监听状态变化
        this.watchState('bot.*', () => this._updateBotUI());
    }

    // ═══════════════════════════════════════════════════════════════════════
    //                           机器人控制
    // ═══════════════════════════════════════════════════════════════════════

    async _toggleBot() {
        const btn = this.$('#btn-toggle-bot');
        const btnText = btn?.querySelector('span');
        if (!btn) return;

        btn.disabled = true;

        try {
            const isRunning = this.getState('bot.running');
            if (isRunning) {
                btnText.textContent = '停止中...';
                const result = await apiService.stopBot();
                toast.show(result.message, result.success ? 'success' : 'error');
            } else {
                btnText.textContent = '启动中...';
                const result = await apiService.startBot();
                toast.show(result.message, result.success ? 'success' : 'error');
            }

            // 延迟触发状态刷新
            setTimeout(() => this.emit(Events.BOT_STATUS_CHANGE, {}), 1000);
        } catch (error) {
            toast.error(toast.getErrorMessage(error, '操作失败'));
        } finally {
            btn.disabled = false;
        }
    }

    async _togglePause() {
        try {
            const isPaused = this.getState('bot.paused');
            if (isPaused) {
                const result = await apiService.resumeBot();
                toast.show(result.message, result.success ? 'success' : 'error');
            } else {
                const result = await apiService.pauseBot();
                toast.show(result.message, result.success ? 'success' : 'error');
            }

            this.emit(Events.BOT_STATUS_CHANGE, {});
        } catch (error) {
            toast.error(toast.getErrorMessage(error, '操作失败'));
        }
    }

    async _restartBot() {
        try {
            toast.info('正在重启机器人...');
            const result = await apiService.restartBot();
            toast.show(result.message, result.success ? 'success' : 'error');

            setTimeout(() => this.emit(Events.BOT_STATUS_CHANGE, {}), 2000);
        } catch (error) {
            toast.error(toast.getErrorMessage(error, '重启失败'));
        }
    }

    async _recoverBot() {
        try {
            toast.info('正在尝试恢复机器人...');
            const result = await apiService.recoverBot();
            toast.show(result.message, result.success ? 'success' : 'error');
            setTimeout(() => this.emit(Events.BOT_STATUS_CHANGE, {}), 1500);
        } catch (error) {
            toast.error(toast.getErrorMessage(error, '恢复失败'));
        }
    }

    // ═══════════════════════════════════════════════════════════════════════
    //                           UI 更新
    // ═══════════════════════════════════════════════════════════════════════

    _updateBotUI() {
        const isRunning = this.getState('bot.running');
        const isPaused = this.getState('bot.paused');
        const status = this.getState('bot.status') || {};

        // 更新机器人状态显示
        const stateElem = this.$('#bot-state');
        if (stateElem) {
            const dot = stateElem.querySelector('.bot-state-dot');
            const text = stateElem.querySelector('.bot-state-text');

            if (isRunning) {
                if (isPaused) {
                    dot.className = 'bot-state-dot paused';
                    text.textContent = '已暂停';
                } else {
                    dot.className = 'bot-state-dot online';
                    text.textContent = '运行中';
                }
            } else {
                dot.className = 'bot-state-dot offline';
                text.textContent = '离线';
            }
        }

        // 更新暂停按钮文本
        const pauseBtn = this.$('#btn-pause');
        const pauseText = pauseBtn?.querySelector('span');
        if (pauseText) {
            pauseText.textContent = isPaused ? '恢复' : '暂停';
        }

        // 更新切换按钮
        const toggleBtn = this.$('#btn-toggle-bot');
        if (toggleBtn) {
            const icon = toggleBtn.querySelector('svg use');
            const text = toggleBtn.querySelector('span');

            if (isRunning) {
                text.textContent = '停止机器人';
                icon?.setAttribute('href', '#icon-square');
                toggleBtn.classList.remove('btn-primary');
                toggleBtn.classList.add('btn-secondary');
            } else {
                text.textContent = '启动机器人';
                icon?.setAttribute('href', '#icon-play');
                toggleBtn.classList.remove('btn-secondary');
                toggleBtn.classList.add('btn-primary');
            }
        }

        this._renderStartupState(status.startup);
        this._syncStartupMeta(status.startup);
        this._renderDiagnostics(status.diagnostics);
    }

    // ═══════════════════════════════════════════════════════════════════════
    //                           消息加载
    // ═══════════════════════════════════════════════════════════════════════

    async _loadRecentMessages() {
        try {
            const result = await apiService.getMessages({ limit: 5, offset: 0 });
            const container = this.$('#recent-messages');

            if (result.success && result.messages && container) {
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
            timestamp: message.timestamp,
            is_self: message.direction === 'outgoing'
        };
        this._recentMessages = [...this._recentMessages, normalized].slice(-5);
        this._renderMessages(container, this._recentMessages);
    }

    _renderMessages(container, messages) {
        if (!messages || messages.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <svg class="icon"><use href="#icon-inbox"/></svg>
                    <span class="empty-state-text">暂无消息记录</span>
                </div>
            `;
            return;
        }

        container.innerHTML = messages.map((msg, index) => {
            const icon = msg.is_self
                ? '<svg class="icon"><use href="#icon-bot"/></svg>'
                : '<svg class="icon"><use href="#icon-user"/></svg>';
            const sender = msg.sender || (msg.is_self ? 'AI助手' : '用户');
            const time = this._formatTime(msg.timestamp);
            const text = this._escapeHtml(msg.content || msg.text || '');
            const roleClass = msg.is_self ? 'is-self' : 'is-user';

            return `
                <div class="message-item ${roleClass}" style="animation-delay: ${index * 0.05}s">
                    <div class="message-avatar">${icon}</div>
                    <div class="message-body">
                        <div class="message-meta">
                            <span class="message-sender">${sender}</span>
                            <span class="message-time">${time}</span>
                        </div>
                        <div class="message-text">${text}</div>
                    </div>
                </div>
            `;
        }).join('');
    }

    _formatTime(timestamp) {
        if (!timestamp) return '';
        const date = new Date(timestamp * 1000);
        const now = new Date();

        if (date.toDateString() === now.toDateString()) {
            return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
        }

        return date.toLocaleString('zh-CN', {
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit'
        });
    }

    _escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    /**
     * 更新统计数据
     */
    updateStats(stats) {
        const nextStats = {
            uptime: stats.uptime || '--',
            today_replies: stats.today_replies ?? 0,
            today_tokens: stats.today_tokens ?? 0,
            total_replies: stats.total_replies ?? 0,
            transport_backend: stats.transport_backend || 'compat_ui',
            wechat_version: stats.wechat_version || '--',
            compat_mode: !!stats.compat_mode,
            transport_warning: stats.transport_warning || '',
            startup: stats.startup || null,
            diagnostics: stats.diagnostics || null,
            system_metrics: stats.system_metrics || {},
            health_checks: stats.health_checks || {},
            merge_feedback: stats.merge_feedback || null,
        };
        const uptimeElem = this.$('#stat-uptime');
        const todayRepliesElem = this.$('#stat-today-replies');
        const todayTokensElem = this.$('#stat-today-tokens');
        const totalRepliesElem = this.$('#stat-total-replies');
        const transportBackendElem = this.$('#bot-transport-backend');
        const transportVersionElem = this.$('#bot-transport-version');
        const transportWarningElem = this.$('#bot-transport-warning');

        if (!this._lastStats || this._lastStats.uptime !== nextStats.uptime) {
            if (uptimeElem) uptimeElem.textContent = nextStats.uptime;
        }
        if (!this._lastStats || this._lastStats.today_replies !== nextStats.today_replies) {
            if (todayRepliesElem) todayRepliesElem.textContent = this._formatNumber(nextStats.today_replies);
        }
        if (!this._lastStats || this._lastStats.today_tokens !== nextStats.today_tokens) {
            if (todayTokensElem) todayTokensElem.textContent = this._formatTokens(nextStats.today_tokens);
        }
        if (!this._lastStats || this._lastStats.total_replies !== nextStats.total_replies) {
            if (totalRepliesElem) totalRepliesElem.textContent = this._formatNumber(nextStats.total_replies);
        }
        if (!this._lastStats || this._lastStats.transport_backend !== nextStats.transport_backend || this._lastStats.compat_mode !== nextStats.compat_mode) {
            if (transportBackendElem) {
                const modeText = nextStats.compat_mode ? '兼容模式' : '静默模式';
                transportBackendElem.textContent = `后端: ${nextStats.transport_backend} (${modeText})`;
            }
        }
        if (!this._lastStats || this._lastStats.wechat_version !== nextStats.wechat_version) {
            if (transportVersionElem) transportVersionElem.textContent = `微信: ${nextStats.wechat_version}`;
        }
        if (!this._lastStats || this._lastStats.transport_warning !== nextStats.transport_warning) {
            if (transportWarningElem) {
                transportWarningElem.hidden = !nextStats.transport_warning;
                transportWarningElem.textContent = nextStats.transport_warning || '';
            }
        }

        this._renderStartupState(nextStats.startup);
        this._syncStartupMeta(nextStats.startup);
        this._renderDiagnostics(nextStats.diagnostics);
        this._renderHealthMetrics(nextStats.system_metrics, nextStats.health_checks, nextStats.merge_feedback);

        this._lastStats = nextStats;
    }

    _renderStartupState(startup) {
        const panel = this.$('#bot-startup-panel');
        const label = this.$('#bot-startup-label');
        const progress = this.$('#bot-startup-progress');
        const meta = this.$('#bot-startup-meta');
        if (!panel || !label || !progress || !meta) {
            return;
        }

        const active = !!startup?.active;
        panel.hidden = !active;
        if (!active) {
            return;
        }

        const progressValue = Number(startup?.progress || 0);
        const stageLabel = this._getStartupStageLabel(startup?.stage);
        label.textContent = startup?.message || '正在启动机器人...';
        progress.style.width = `${Math.max(0, Math.min(progressValue, 100))}%`;
        const updatedAt = this._formatStartupUpdatedAt(startup?.updated_at);
        meta.textContent = updatedAt
            ? `${progressValue}% · ${stageLabel} · ${updatedAt}`
            : `${progressValue}% · ${stageLabel}`;
    }

    _syncStartupMeta(startup) {
        const meta = this.$('#bot-startup-meta');
        if (!meta || !startup?.active) {
            return;
        }
        const progressValue = Number(startup?.progress || 0);
        const stageLabel = this._getStartupStageLabel(startup?.stage);
        const updatedAt = this._formatStartupUpdatedAt(startup?.updated_at);
        meta.textContent = updatedAt
            ? `${progressValue}% · ${stageLabel} · ${updatedAt}`
            : `${progressValue}% · ${stageLabel}`;
    }

    _renderDiagnostics(diagnostics) {
        const panel = this.$('#bot-diagnostics');
        const title = this.$('#bot-diagnostics-title');
        const detail = this.$('#bot-diagnostics-detail');
        const list = this.$('#bot-diagnostics-list');
        const action = this.$('#btn-recover-bot');
        if (!panel || !title || !detail || !list || !action) {
            return;
        }

        if (!diagnostics) {
            panel.hidden = true;
            list.innerHTML = '';
            return;
        }

        panel.hidden = false;
        panel.dataset.level = diagnostics.level || 'warning';
        title.textContent = diagnostics.title || '运行诊断';
        detail.textContent = diagnostics.detail || '检测到需要关注的运行状态。';
        list.innerHTML = Array.isArray(diagnostics.suggestions)
            ? diagnostics.suggestions.map(item => `<li>${this._escapeHtml(item)}</li>`).join('')
            : '';
        action.hidden = !diagnostics.recoverable;
        action.textContent = diagnostics.action_label || '一键恢复';
    }

    _renderHealthMetrics(metrics = {}, checks = {}, mergeFeedback = null) {
        const cpuElem = this.$('#health-cpu');
        const memoryElem = this.$('#health-memory');
        const queueElem = this.$('#health-queue');
        const latencyElem = this.$('#health-latency');
        const warningElem = this.$('#health-warning');
        const mergeElem = this.$('#health-merge-feedback');
        if (!cpuElem || !memoryElem || !queueElem || !latencyElem || !warningElem || !mergeElem) {
            return;
        }

        cpuElem.textContent = this._formatPercent(metrics.cpu_percent);
        memoryElem.textContent = this._formatMemory(metrics.process_memory_mb, metrics.system_memory_percent);
        queueElem.textContent = this._formatQueue(metrics.pending_tasks, metrics.merge_pending_chats, metrics.merge_pending_messages);
        latencyElem.textContent = this._formatLatency(metrics.ai_latency_ms);

        warningElem.hidden = !metrics.warning;
        warningElem.textContent = metrics.warning || '';

        const mergeText = mergeFeedback?.status_text || '消息合并状态：未激活';
        mergeElem.textContent = mergeText;
        mergeElem.dataset.active = mergeFeedback?.active ? 'true' : 'false';

        this._renderHealthCheckItem('health-ai', checks.ai);
        this._renderHealthCheckItem('health-wechat', checks.wechat);
        this._renderHealthCheckItem('health-db', checks.database);
    }

    _renderHealthCheckItem(elementId, check) {
        const item = this.$(`#${elementId}`);
        if (!item) {
            return;
        }
        const text = item.querySelector('.health-check-text');
        const level = ['healthy', 'warning', 'error'].includes(check?.level) ? check.level : 'warning';
        item.dataset.level = level;
        item.dataset.status = check?.status || 'unknown';
        if (text) {
            text.textContent = check?.message || '未检测';
        }
    }

    _getStartupStageLabel(stage) {
        const stageMap = {
            loading_config: '读取配置',
            init_memory: '准备记忆库',
            init_ai: '检查 AI',
            connect_wechat: '连接微信',
            ready: '启动完成',
            failed: '启动失败',
            idle: '等待启动'
        };
        return stageMap[stage] || `当前阶段: ${stage || 'starting'}`;
    }

    _formatStartupUpdatedAt(timestamp) {
        const value = Number(timestamp || 0);
        if (!Number.isFinite(value) || value <= 0) {
            return '';
        }
        return `更新于 ${new Date(value * 1000).toLocaleTimeString('zh-CN', {
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        })}`;
    }

    _formatPercent(value) {
        if (value === undefined || value === null || Number.isNaN(Number(value))) {
            return '--';
        }
        return `${Number(value).toFixed(1)}%`;
    }

    _formatMemory(processMemory, systemPercent) {
        const processText = processMemory === undefined || processMemory === null || Number.isNaN(Number(processMemory))
            ? '--'
            : `${Number(processMemory).toFixed(0)} MB`;
        const systemText = systemPercent === undefined || systemPercent === null || Number.isNaN(Number(systemPercent))
            ? '--'
            : `${Number(systemPercent).toFixed(0)}%`;
        return `${processText} / ${systemText}`;
    }

    _formatQueue(pendingTasks, pendingChats, pendingMessages) {
        const tasks = Number.isFinite(Number(pendingTasks)) ? Number(pendingTasks) : 0;
        const chats = Number.isFinite(Number(pendingChats)) ? Number(pendingChats) : 0;
        const messages = Number.isFinite(Number(pendingMessages)) ? Number(pendingMessages) : 0;
        return `${tasks} 任务 / ${chats} 会话 / ${messages} 条`;
    }

    _formatLatency(value) {
        if (value === undefined || value === null || Number.isNaN(Number(value)) || Number(value) <= 0) {
            return '--';
        }
        return `${Math.round(Number(value))} ms`;
    }

    _formatNumber(value) {
        if (value === undefined || value === null) return '0';
        return value.toLocaleString('zh-CN');
    }

    _formatTokens(value) {
        if (!value || value < 1000) return value || '0';
        if (value < 1000000) return (value / 1000).toFixed(1) + 'K';
        return (value / 1000000).toFixed(1) + 'M';
    }
}

export default DashboardPage;
