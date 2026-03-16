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
        this._recentMessages = [];
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
        this._updateBotUI();

        const status = this.getState('bot.status');
        if (status) {
            this.updateStats(status);
        }

        await this._loadRecentMessages();
    }

    _bindEvents() {
        this.bindEvent('#btn-toggle-bot', 'click', () => this._toggleBot());
        this.bindEvent('#btn-pause', 'click', () => this._togglePause());
        this.bindEvent('#btn-restart', 'click', () => this._restartBot());
        this.bindEvent('#btn-recover-bot', 'click', () => this._recoverBot());
        this.bindEvent('#btn-view-logs', 'click', () => this.emit(Events.PAGE_CHANGE, 'logs'));
        this.bindEvent('#btn-view-all-messages', 'click', () => this.emit(Events.PAGE_CHANGE, 'messages'));

        this.bindEvent('#btn-refresh-status', 'click', () => {
            this.emit(Events.BOT_STATUS_CHANGE, {});
            toast.success('已触发状态刷新');
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
        this.watchState('bot.connected', updateIfActive);
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
                const result = await apiService.stopBot();
                toast.show(
                    result?.message || (result?.success ? '机器人已停止' : '停止机器人失败'),
                    result?.success ? 'success' : 'error'
                );
            } else {
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

                const result = await apiService.startBot();
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
        const isRunning = !!this.getState('bot.running');
        const isPaused = !!this.getState('bot.paused');
        const status = this.getState('bot.status') || {};
        const startupActive = !!status?.startup?.active;

        const stateElem = this.$('#bot-state');
        if (stateElem) {
            const dot = stateElem.querySelector('.bot-state-dot');
            const text = stateElem.querySelector('.bot-state-text');
            let stateText = '已停止';
            let dotClass = 'bot-state-dot offline';

            if (isRunning && isPaused) {
                stateText = '已暂停';
                dotClass = 'bot-state-dot paused';
            } else if (isRunning) {
                stateText = '运行中';
                dotClass = 'bot-state-dot online';
            } else if (startupActive) {
                stateText = '启动中';
                dotClass = 'bot-state-dot starting';
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
            pauseBtn.disabled = !isRunning;
        }
        if (pauseText) {
            pauseText.textContent = isPaused ? '继续运行' : '暂停';
        }

        const restartBtn = this.$('#btn-restart');
        if (restartBtn) {
            restartBtn.disabled = !isRunning && !startupActive;
        }

        const toggleBtn = this.$('#btn-toggle-bot');
        if (toggleBtn) {
            const icon = toggleBtn.querySelector('svg use');
            const text = toggleBtn.querySelector('span');

            if (isRunning || startupActive) {
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

        this._renderStartupState(status.startup);
        this._syncStartupMeta(status.startup);
        this._renderDiagnostics(status.diagnostics);
    }

    async _loadRecentMessages() {
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
        container.textContent = '';

        if (!messages || messages.length === 0) {
            const empty = document.createElement('div');
            empty.className = 'empty-state';

            const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
            svg.setAttribute('class', 'icon');
            const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
            use.setAttribute('href', '#icon-inbox');
            use.setAttributeNS('http://www.w3.org/1999/xlink', 'href', '#icon-inbox');
            svg.appendChild(use);

            const text = document.createElement('span');
            text.className = 'empty-state-text';
            text.textContent = '暂无消息记录';

            empty.appendChild(svg);
            empty.appendChild(text);
            container.appendChild(empty);
            return;
        }

        const frag = document.createDocumentFragment();
        messages.forEach((msg, index) => {
            const isSelf = !!msg.is_self;
            const sender = msg.sender || (isSelf ? 'AI 助手' : '用户');
            const time = this._formatTime(msg.timestamp);
            const content = msg.content || msg.text || '';

            const item = document.createElement('div');
            item.className = `message-item ${isSelf ? 'is-self' : 'is-user'}`;
            item.style.animationDelay = `${index * 0.05}s`;

            const avatar = document.createElement('div');
            avatar.className = 'message-avatar';
            const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
            svg.setAttribute('class', 'icon');
            const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
            const href = isSelf ? '#icon-bot' : '#icon-user';
            use.setAttribute('href', href);
            use.setAttributeNS('http://www.w3.org/1999/xlink', 'href', href);
            svg.appendChild(use);
            avatar.appendChild(svg);

            const body = document.createElement('div');
            body.className = 'message-body';

            const meta = document.createElement('div');
            meta.className = 'message-meta';

            const senderEl = document.createElement('span');
            senderEl.className = 'message-sender';
            senderEl.textContent = String(sender);

            const timeEl = document.createElement('span');
            timeEl.className = 'message-time';
            timeEl.textContent = String(time);

            const textEl = document.createElement('div');
            textEl.className = 'message-text';
            textEl.textContent = String(content);

            meta.appendChild(senderEl);
            meta.appendChild(timeEl);
            body.appendChild(meta);
            body.appendChild(textEl);
            item.appendChild(avatar);
            item.appendChild(body);
            frag.appendChild(item);
        });

        container.appendChild(frag);
    }

    _formatTime(timestamp) {
        if (!timestamp) {
            return '';
        }

        const raw = Number(timestamp);
        const date = new Date(raw > 1e12 ? raw : raw * 1000);
        if (Number.isNaN(date.getTime())) {
            return '';
        }

        const now = new Date();
        if (date.toDateString() === now.toDateString()) {
            return date.toLocaleTimeString('zh-CN', {
                hour: '2-digit',
                minute: '2-digit'
            });
        }

        return date.toLocaleString('zh-CN', {
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit'
        });
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
        const updatedAt = this._formatStartupUpdatedAt(startup?.updated_at);

        label.textContent = startup?.message || '正在启动机器人...';
        progress.style.width = `${Math.max(0, Math.min(progressValue, 100))}%`;
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
            list.textContent = '';
            return;
        }

        panel.hidden = false;
        panel.dataset.level = diagnostics.level || 'warning';
        title.textContent = diagnostics.title || '运行诊断';
        detail.textContent = diagnostics.detail || '检测到需要关注的运行状态。';
        list.textContent = '';

        if (Array.isArray(diagnostics.suggestions)) {
            const frag = document.createDocumentFragment();
            diagnostics.suggestions.forEach((item) => {
                const li = document.createElement('li');
                li.textContent = String(item ?? '');
                frag.appendChild(li);
            });
            list.appendChild(frag);
        }

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
        memoryElem.textContent = this._formatMemory(
            metrics.process_memory_mb,
            metrics.system_memory_percent
        );
        queueElem.textContent = this._formatQueue(
            metrics.pending_tasks,
            metrics.merge_pending_chats,
            metrics.merge_pending_messages
        );
        latencyElem.textContent = this._formatLatency(metrics.ai_latency_ms);
        warningElem.hidden = !metrics.warning;
        warningElem.textContent = metrics.warning || '';
        mergeElem.textContent = mergeFeedback?.status_text || '消息合并状态：未激活';
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
        const level = ['healthy', 'warning', 'error'].includes(check?.level)
            ? check.level
            : 'warning';

        item.dataset.level = level;
        item.dataset.status = check?.status || 'unknown';
        if (text) {
            text.textContent = check?.message || '未检测';
        }
    }

    _renderRetrieval(retrieverStats = {}, timings = {}, exportRag = null) {
        const vectorEl = this.$('#retrieval-vector');
        const exportEl = this.$('#retrieval-export');
        const topkEl = this.$('#retrieval-topk');
        const thresholdEl = this.$('#retrieval-threshold');
        const rerankEl = this.$('#retrieval-rerank');
        const hitsEl = this.$('#retrieval-hits');
        const timingsGrid = this.$('#retrieval-timings');
        const timingsEmpty = this.$('#retrieval-timings-empty');

        if (vectorEl) {
            const enabled = exportRag?.vector_memory_enabled;
            const ready = exportRag?.vector_memory_ready;
            if (enabled === true) {
                vectorEl.textContent = ready === false ? '初始化中' : '已启用';
            } else if (enabled === false) {
                vectorEl.textContent = '未启用';
            } else {
                vectorEl.textContent = '--';
            }
        }

        if (exportEl) {
            const enabled = exportRag?.enabled;
            exportEl.textContent = enabled === true ? '已启用' : enabled === false ? '关闭' : '--';
        }

        if (topkEl) {
            const value = retrieverStats?.top_k;
            topkEl.textContent = Number.isFinite(Number(value)) ? String(value) : '--';
        }

        if (thresholdEl) {
            const value = retrieverStats?.score_threshold;
            thresholdEl.textContent =
                value === undefined || value === null || Number.isNaN(Number(value))
                    ? '--'
                    : String(value);
        }

        if (rerankEl) {
            const backend = String(
                retrieverStats?.rerank_backend || retrieverStats?.rerank_mode || '--'
            );
            const configured = retrieverStats?.cross_encoder_configured;
            const fallbacks = retrieverStats?.rerank_fallbacks;
            let text = backend;
            if (backend === 'cross_encoder' && configured === false) {
                text = `${backend} (未配置)`;
            }
            if (Number.isFinite(Number(fallbacks)) && Number(fallbacks) > 0) {
                text = `${text} (回退 ${fallbacks})`;
            }
            rerankEl.textContent = text;
        }

        if (hitsEl) {
            const hits = retrieverStats?.hits;
            hitsEl.textContent = Number.isFinite(Number(hits))
                ? this._formatNumber(Number(hits))
                : '--';
        }

        if (!timingsGrid || !timingsEmpty) {
            return;
        }

        const normalized = timings && typeof timings === 'object' ? timings : {};
        const primaryOrder = [
            'prepare_total_sec',
            'load_context_sec',
            'build_prompt_sec',
            'invoke_sec',
            'stream_sec'
        ];
        const primaryKeys = primaryOrder.filter((key) => Number.isFinite(Number(normalized[key])));
        const extraKeys = Object.keys(normalized)
            .filter((key) => !primaryOrder.includes(key))
            .filter((key) => Number.isFinite(Number(normalized[key])))
            .slice(0, 6);
        const keys = [...primaryKeys, ...extraKeys];

        timingsGrid.textContent = '';
        if (keys.length === 0) {
            timingsEmpty.hidden = false;
            return;
        }
        timingsEmpty.hidden = true;

        const frag = document.createDocumentFragment();
        keys.forEach((key) => {
            const cell = document.createElement('div');
            const span = document.createElement('span');
            const strong = document.createElement('strong');

            span.textContent = this._formatTimingLabel(key);
            strong.textContent = this._formatDurationSec(Number(normalized[key]));
            cell.appendChild(span);
            cell.appendChild(strong);
            frag.appendChild(cell);
        });

        timingsGrid.appendChild(frag);
    }

    _formatDurationSec(value) {
        const sec = Number(value);
        if (!Number.isFinite(sec) || sec <= 0) {
            return '--';
        }

        const ms = sec * 1000;
        if (ms < 1000) {
            return `${Math.round(ms)} ms`;
        }
        if (ms < 10000) {
            return `${(ms / 1000).toFixed(2)} s`;
        }
        return `${(ms / 1000).toFixed(1)} s`;
    }

    _formatTimingLabel(key) {
        const map = {
            prepare_total_sec: '总准备耗时',
            load_context_sec: '加载上下文',
            build_prompt_sec: '构建提示词',
            invoke_sec: '调用模型',
            stream_sec: '流式输出',
        };
        return map[key] || String(key || '');
    }

    _getStartupStageLabel(stage) {
        const stageMap = {
            loading_config: '加载配置',
            init_memory: '准备记忆',
            init_ai: '初始化 AI',
            connect_wechat: '连接微信',
            ready: '启动完成',
            failed: '启动失败',
            idle: '等待启动',
            stopped: '已停止',
            starting: '启动中',
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
        const processText =
            processMemory === undefined || processMemory === null || Number.isNaN(Number(processMemory))
                ? '--'
                : `${Number(processMemory).toFixed(0)} MB`;
        const systemText =
            systemPercent === undefined || systemPercent === null || Number.isNaN(Number(systemPercent))
                ? '--'
                : `${Number(systemPercent).toFixed(0)}%`;
        return `${processText} / ${systemText}`;
    }

    _formatQueue(pendingTasks, pendingChats, pendingMessages) {
        const tasks = Number.isFinite(Number(pendingTasks)) ? Number(pendingTasks) : 0;
        const chats = Number.isFinite(Number(pendingChats)) ? Number(pendingChats) : 0;
        const messages = Number.isFinite(Number(pendingMessages)) ? Number(pendingMessages) : 0;
        return `${tasks} 个任务 / ${chats} 个会话 / ${messages} 条消息`;
    }

    _formatLatency(value) {
        if (value === undefined || value === null || Number.isNaN(Number(value)) || Number(value) <= 0) {
            return '--';
        }
        return `${Math.round(Number(value))} ms`;
    }

    _formatNumber(value) {
        if (value === undefined || value === null) {
            return '0';
        }
        return Number(value).toLocaleString('zh-CN');
    }

    _formatTokens(value) {
        const num = Number(value || 0);
        if (!Number.isFinite(num) || num <= 0) {
            return '0';
        }
        if (num < 1000) {
            return String(num);
        }
        if (num < 1000000) {
            return `${(num / 1000).toFixed(1)}K`;
        }
        return `${(num / 1000000).toFixed(1)}M`;
    }
}

export default DashboardPage;
