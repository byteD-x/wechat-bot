import {
    formatDurationMs,
    formatNumber,
    formatTokens,
} from './formatters.js';
import {
    renderDiagnostics,
    renderGrowthTasks,
    renderHealthMetrics,
    renderIdlePanel,
    renderReadiness,
    renderRetrieval,
    renderStabilitySummary,
    renderStartupState,
    syncStartupMeta,
} from './renderers.js';
import { refreshDashboardCost, refreshDashboardStability } from './data-loader.js';

function resolveDeps(deps = {}) {
    return {
        formatDurationMs: deps.formatDurationMs || formatDurationMs,
        formatNumber: deps.formatNumber || formatNumber,
        formatTokens: deps.formatTokens || formatTokens,
        renderDiagnostics: deps.renderDiagnostics || renderDiagnostics,
        renderGrowthTasks: deps.renderGrowthTasks || renderGrowthTasks,
        renderHealthMetrics: deps.renderHealthMetrics || renderHealthMetrics,
        renderIdlePanel: deps.renderIdlePanel || renderIdlePanel,
        renderReadiness: deps.renderReadiness || renderReadiness,
        renderRetrieval: deps.renderRetrieval || renderRetrieval,
        renderStabilitySummary: deps.renderStabilitySummary || renderStabilitySummary,
        renderStartupState: deps.renderStartupState || renderStartupState,
        syncStartupMeta: deps.syncStartupMeta || syncStartupMeta,
        refreshDashboardCost: deps.refreshDashboardCost || refreshDashboardCost,
        refreshDashboardStability: deps.refreshDashboardStability || refreshDashboardStability,
    };
}

function getIdleState(page) {
    return page.getState('backend.idle') || {
        state: 'active',
        delayMs: 15 * 60 * 1000,
        remainingMs: 15 * 60 * 1000,
        reason: '',
        updatedAt: Date.now(),
    };
}

function getIdleRemainingMs(idleState = getIdleState(this)) {
    if (!idleState || idleState.state !== 'countdown') {
        return Math.max(0, Number(idleState?.remainingMs || 0));
    }
    const updatedAt = Number(idleState.updatedAt || Date.now());
    const elapsed = Math.max(0, Date.now() - updatedAt);
    return Math.max(0, Number(idleState.remainingMs || 0) - elapsed);
}

export function updateBotUI(page, deps = {}) {
    const helper = resolveDeps(deps);
    const connected = !!page.getState('bot.connected');
    const isRunning = !!page.getState('bot.running');
    const isPaused = !!page.getState('bot.paused');
    const status = page.getState('bot.status') || {};
    const idleState = getIdleState(page);
    const startupActive = !!status?.startup?.active;
    const growthRunning = !!status?.growth_running;
    const isIdleStandby = idleState.state === 'standby' || idleState.state === 'countdown';
    const isIdleStopped = idleState.state === 'stopped_by_idle';

    const stateElem = page.$('#bot-state');
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

    const pauseBtn = page.$('#btn-pause');
    const pauseText = pauseBtn?.querySelector('span');
    if (pauseBtn) {
        pauseBtn.disabled = !connected || !isRunning;
    }
    if (pauseText) {
        pauseText.textContent = isPaused ? '继续运行' : '暂停';
    }

    const restartBtn = page.$('#btn-restart');
    if (restartBtn) {
        restartBtn.disabled = !connected || (!isRunning && !startupActive);
    }

    const toggleBtn = page.$('#btn-toggle-bot');
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
    const growthStatus = page.$('#growth-task-status');
    const growthBacklog = page.$('#growth-task-backlog');
    const growthQueue = page.$('#growth-task-queue');
    const growthBatch = page.$('#growth-task-batch');
    const growthNext = page.$('#growth-task-next');
    const growthError = page.$('#growth-task-error');
    const growthButton = page.$('#btn-toggle-growth');
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
            ? `待处理任务 ${helper.formatNumber(backlogCount)}`
            : '待处理任务 --';
    }
    helper.renderGrowthTasks(connected, status, {
        queueElement: growthQueue,
        batchElement: growthBatch,
        nextElement: growthNext,
        errorElement: growthError,
    });
    if (growthButtonText) {
        growthButtonText.textContent = growthRunning ? '停止成长任务' : '启动成长任务';
    }

    helper.renderIdlePanel(page, {
        connected,
        isRunning,
        growthRunning,
        startupActive,
        idleState,
    }, {
        getIdleState: () => getIdleState(page),
        getIdleRemainingMs: (state) => getIdleRemainingMs.call(page, state),
        formatDurationMs: helper.formatDurationMs,
    });
    helper.renderStartupState(page, status.startup);
    helper.syncStartupMeta(page, status.startup);
    helper.renderReadiness(page, page.getState('readiness.report'));
    helper.renderDiagnostics(page, status.diagnostics);
}

export function updateStats(page, stats, deps = {}) {
    const helper = resolveDeps(deps);
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
        pending_replies: stats.pending_replies || null,
        reply_quality: stats.reply_quality || null,
        retriever_stats: stats.retriever_stats || {},
        runtime_timings: stats.runtime_timings || {},
        export_rag: stats.export_rag || null,
    };

    const uptimeElem = page.$('#stat-uptime');
    const todayRepliesElem = page.$('#stat-today-replies');
    const todayTokensElem = page.$('#stat-today-tokens');
    const totalRepliesElem = page.$('#stat-total-replies');
    const transportBackendElem = page.$('#bot-transport-backend');
    const transportVersionElem = page.$('#bot-transport-version');
    const transportWarningElem = page.$('#bot-transport-warning');

    if (uptimeElem) {
        uptimeElem.textContent = nextStats.uptime;
    }
    if (todayRepliesElem) {
        todayRepliesElem.textContent = helper.formatNumber(nextStats.today_replies);
    }
    if (todayTokensElem) {
        todayTokensElem.textContent = helper.formatTokens(nextStats.today_tokens);
    }
    if (totalRepliesElem) {
        totalRepliesElem.textContent = helper.formatNumber(nextStats.total_replies);
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

    helper.renderStartupState(page, nextStats.startup);
    helper.syncStartupMeta(page, nextStats.startup);
    helper.renderReadiness(page, page.getState('readiness.report'));
    helper.renderDiagnostics(page, nextStats.diagnostics);
    helper.renderHealthMetrics(
        page,
        nextStats.system_metrics,
        nextStats.health_checks,
        nextStats.merge_feedback,
        nextStats.reply_quality
    );
    helper.renderRetrieval(
        page,
        nextStats.retriever_stats,
        nextStats.runtime_timings,
        nextStats.export_rag
    );
    helper.renderStabilitySummary(
        page,
        nextStats.pending_replies,
        page._stability || {},
    );
    void helper.refreshDashboardCost(page);
    void helper.refreshDashboardStability(page);

    page._lastStats = nextStats;
}
