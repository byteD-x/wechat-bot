import {
    formatCurrencyGroups,
    formatDurationSec,
    formatGrowthTimestamp,
    formatNumber,
    formatPercent,
    formatQueue,
    formatLatency,
    formatMemory,
    formatReplyQualitySummary,
    formatStartupMeta,
    formatTime,
    formatTimingLabel,
    formatTokens,
    getGrowthBatchReason,
    getGrowthModeLabel,
    getGrowthTaskLabel,
} from './formatters.js';

function createSvgIcon(href) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'icon');
    const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
    use.setAttribute('href', href);
    use.setAttributeNS('http://www.w3.org/1999/xlink', 'href', href);
    svg.appendChild(use);
    return svg;
}

export function createCompactEmpty(text) {
    const wrap = document.createElement('div');
    wrap.className = 'empty-state compact-empty';

    const label = document.createElement('span');
    label.className = 'empty-state-text';
    label.textContent = text;

    wrap.appendChild(label);
    return wrap;
}

export function createGrowthTaskActionButton(taskType, action, label) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'btn btn-secondary btn-xs';
    button.dataset.growthAction = String(action || '');
    button.dataset.taskType = String(taskType || '');
    button.textContent = String(label || '');
    return button;
}

export function renderHealthCheckItem(page, elementId, check) {
    const item = page.$(`#${elementId}`);
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

export function renderIdlePanel(page, context = {}, helpers = {}) {
    const panel = page.$('#backend-idle-panel');
    const title = page.$('#backend-idle-title');
    const detail = page.$('#backend-idle-detail');
    const meta = page.$('#backend-idle-meta');
    const cancelButton = page.$('#btn-cancel-idle-shutdown');
    const wakeButton = page.$('#btn-wake-backend');
    if (!panel || !title || !detail || !meta || !cancelButton || !wakeButton) {
        return;
    }

    const idleState = context.idleState || helpers.getIdleState?.();
    const connected = context.connected ?? !!page.getState('bot.connected');
    const isRunning = context.isRunning ?? !!page.getState('bot.running');
    const growthRunning = context.growthRunning ?? !!((page.getState('bot.status') || {}).growth_running);
    const startupActive = context.startupActive ?? !!((page.getState('bot.status') || {}).startup?.active);

    const shouldShow = (
        idleState?.state === 'standby'
        || idleState?.state === 'countdown'
        || idleState?.state === 'stopped_by_idle'
    ) && !isRunning && !growthRunning && !startupActive;

    panel.hidden = !shouldShow;
    cancelButton.hidden = true;
    wakeButton.hidden = true;
    if (!shouldShow) {
        return;
    }

    const delayMs = Number(idleState?.delayMs || 15 * 60 * 1000);
    const remainingMs = helpers.getIdleRemainingMs
        ? helpers.getIdleRemainingMs(idleState)
        : Math.max(0, Number(idleState?.remainingMs || 0));
    const formatDurationMs = helpers.formatDurationMs || String;
    const countdownPaused = idleState?.state === 'standby' && remainingMs > 0 && remainingMs < delayMs;

    if (idleState?.state === 'stopped_by_idle') {
        title.textContent = '后端已休眠';
        detail.textContent = '后端已因空闲自动停止。切换到消息、日志、成本页，或点击下方按钮即可按需唤醒。';
        meta.textContent = '当前不会自动重连，需由页面切换或显式操作恢复。';
        wakeButton.hidden = false;
        return;
    }

    if (idleState?.state === 'countdown') {
        title.textContent = '后端休眠倒计时中';
        detail.textContent = `主窗口当前不可见，后端将在 ${formatDurationMs(remainingMs)} 后自动休眠。`;
        meta.textContent = '点击“取消自动停机”会把本轮倒计时重置为 15 分钟。';
        cancelButton.hidden = false;
        return;
    }

    if (countdownPaused) {
        title.textContent = '休眠倒计时已暂停';
        detail.textContent = `主窗口当前可见，自动休眠已暂停，剩余 ${formatDurationMs(remainingMs)}。再次隐藏到托盘后将继续计时。`;
        meta.textContent = '点击“取消自动停机”会重置本轮 15 分钟计时。';
        cancelButton.hidden = false;
        return;
    }

    title.textContent = connected ? '后端待机中' : '等待后端恢复';
    detail.textContent = '机器人和成长任务都已停止。隐藏到托盘后，将开始 15 分钟自动休眠倒计时。';
    meta.textContent = `自动休眠时长：${formatDurationMs(delayMs)}`;
}

export function renderMessages(container, messages) {
    container.textContent = '';

    if (!messages || messages.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'empty-state';
        empty.appendChild(createSvgIcon('#icon-inbox'));

        const text = document.createElement('span');
        text.className = 'empty-state-text';
        text.textContent = '暂无消息记录';

        empty.appendChild(text);
        container.appendChild(empty);
        return;
    }

    const frag = document.createDocumentFragment();
    messages.forEach((msg, index) => {
        const isSelf = !!msg.is_self;
        const sender = msg.sender || (isSelf ? 'AI 助手' : '用户');
        const time = formatTime(msg.timestamp);
        const content = msg.content || msg.text || '';

        const item = document.createElement('div');
        item.className = `message-item ${isSelf ? 'is-self' : 'is-user'}`;
        item.style.animationDelay = `${index * 0.05}s`;

        const avatar = document.createElement('div');
        avatar.className = 'message-avatar';
        avatar.appendChild(createSvgIcon(isSelf ? '#icon-bot' : '#icon-user'));

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

export function renderGrowthTasks(connected, status, elements = {}) {
    const {
        queueElement,
        batchElement,
        nextElement,
        errorElement,
    } = elements;

    if (queueElement) {
        queueElement.textContent = '';

        if (!connected) {
            const empty = document.createElement('span');
            empty.className = 'growth-task-empty';
            empty.textContent = '服务未连接';
            queueElement.appendChild(empty);
        } else {
            const pausedTaskTypes = new Set(status?.paused_growth_task_types || []);
            const taskEntries = Object.entries(status?.background_backlog_by_task || {})
                .map(([taskType, count]) => [taskType, Number(count || 0)])
                .filter(([taskType, count]) => count > 0 || pausedTaskTypes.has(taskType))
                .sort((left, right) => right[1] - left[1]);

            if (taskEntries.length === 0) {
                const pendingTasks = Number(status?.growth_tasks_pending || 0);
                const empty = document.createElement('span');
                empty.className = 'growth-task-empty';
                empty.textContent = pendingTasks > 0 ? '有任务正在执行，当前队列为空' : '当前没有排队任务';
                queueElement.appendChild(empty);
            } else {
                const fragment = document.createDocumentFragment();
                taskEntries.forEach(([taskType, count]) => {
                    const row = document.createElement('div');
                    row.className = 'growth-task-row';

                    const meta = document.createElement('div');
                    meta.className = 'growth-task-row-meta';

                    const title = document.createElement('div');
                    title.className = 'growth-task-row-title';
                    title.textContent = getGrowthTaskLabel(taskType);

                    if (pausedTaskTypes.has(taskType)) {
                        const badge = document.createElement('span');
                        badge.className = 'growth-task-badge paused';
                        badge.textContent = '已暂停';
                        title.appendChild(badge);
                    }

                    const detail = document.createElement('div');
                    detail.className = 'growth-task-row-detail';
                    detail.textContent = `排队 ${formatNumber(count)}`;

                    meta.appendChild(title);
                    meta.appendChild(detail);

                    const actions = document.createElement('div');
                    actions.className = 'growth-task-actions';
                    actions.appendChild(createGrowthTaskActionButton(taskType, 'run', '立即执行'));
                    actions.appendChild(
                        createGrowthTaskActionButton(
                            taskType,
                            pausedTaskTypes.has(taskType) ? 'resume' : 'pause',
                            pausedTaskTypes.has(taskType) ? '恢复' : '暂停',
                        )
                    );
                    actions.appendChild(createGrowthTaskActionButton(taskType, 'clear', '清空队列'));

                    row.appendChild(meta);
                    row.appendChild(actions);
                    fragment.appendChild(row);
                });
                queueElement.appendChild(fragment);
            }
        }
    }

    if (batchElement) {
        if (!connected) {
            batchElement.textContent = '最近批次 --';
        } else {
            const batch = status?.last_background_batch || {};
            const hasBatch = Object.keys(batch).length > 0;
            if (!hasBatch) {
                batchElement.textContent = '最近批次：暂无执行记录';
            } else {
                const completed = Number(batch.completed || 0);
                const failed = Number(batch.failed || 0);
                const batchTime = formatGrowthTimestamp(batch.finished_at || batch.started_at);
                const reason = getGrowthBatchReason(batch.reason);
                const mode = getGrowthModeLabel(status?.growth_mode);
                const trigger = batch.trigger === 'manual' ? '手动触发' : '定时批处理';
                const segments = [
                    `最近批次：完成 ${formatNumber(completed)}`,
                    `失败 ${formatNumber(failed)}`,
                ];
                segments.push(trigger);
                if (batchTime !== '--') {
                    segments.push(batchTime);
                }
                if (mode) {
                    segments.push(mode);
                }
                if (reason) {
                    segments.push(reason);
                }
                batchElement.textContent = segments.join(' · ');
            }
        }
    }

    if (nextElement) {
        if (!connected) {
            nextElement.textContent = '下次批处理 --';
        } else {
            const nextBatchAt = formatGrowthTimestamp(status?.next_background_batch_at);
            nextElement.textContent = nextBatchAt === '--'
                ? '下次批处理：等待调度'
                : `下次批处理：${nextBatchAt}`;
        }
    }

    if (errorElement) {
        const errorText = connected ? String(status?.last_growth_error || '').trim() : '';
        errorElement.hidden = !errorText;
        errorElement.textContent = errorText ? `最近异常：${errorText}` : '';
    }
}

export function renderDashboardCost(page, dashboardCost) {
    const todayElem = page.$('#stat-today-cost');
    const summaryElem = page.$('#dashboard-cost-summary');
    const modelsElem = page.$('#dashboard-cost-top-models');
    if (!todayElem || !summaryElem || !modelsElem) {
        return;
    }

    const todayOverview = dashboardCost?.today?.overview || {};
    const recentOverview = dashboardCost?.recent?.overview || {};
    const recentModels = Array.isArray(dashboardCost?.recent?.models)
        ? [...dashboardCost.recent.models]
            .sort((left, right) => Number(right.total_tokens || 0) - Number(left.total_tokens || 0))
            .slice(0, 3)
        : [];

    todayElem.textContent = formatCurrencyGroups(todayOverview.currency_groups) || '--';

    const summaryItems = [
        {
            label: '近 30 天总金额',
            value: formatCurrencyGroups(recentOverview.currency_groups) || '待定价',
        },
        {
            label: '近 30 天总 Token',
            value: formatNumber(recentOverview.total_tokens || 0),
        },
        {
            label: '已定价回复',
            value: formatNumber(recentOverview.priced_reply_count || 0),
        },
    ];

    summaryElem.textContent = '';
    const summaryFragment = document.createDocumentFragment();
    summaryItems.forEach((item) => {
        const block = document.createElement('div');
        block.className = 'dashboard-cost-stat';

        const label = document.createElement('span');
        label.className = 'dashboard-cost-label';
        label.textContent = item.label;

        const value = document.createElement('strong');
        value.className = 'dashboard-cost-value';
        value.textContent = item.value;

        block.appendChild(label);
        block.appendChild(value);
        summaryFragment.appendChild(block);
    });
    summaryElem.appendChild(summaryFragment);

    modelsElem.textContent = '';
    if (recentModels.length === 0) {
        modelsElem.appendChild(createCompactEmpty('暂无成本模型数据'));
        return;
    }

    const listFragment = document.createDocumentFragment();
    recentModels.forEach((item) => {
        const row = document.createElement('div');
        row.className = 'dashboard-model-item';

        const main = document.createElement('div');
        main.className = 'dashboard-model-main';

        const title = document.createElement('strong');
        title.textContent = item.model || '--';

        const meta = document.createElement('span');
        meta.textContent = `${item.provider_id || '--'} · ${formatTokens(item.total_tokens || 0)}`;

        const cost = document.createElement('span');
        cost.className = 'dashboard-model-cost';
        cost.textContent = formatCurrencyGroups(item.currency_groups) || '待定价';

        main.appendChild(title);
        main.appendChild(meta);
        row.appendChild(main);
        row.appendChild(cost);
        listFragment.appendChild(row);
    });
    modelsElem.appendChild(listFragment);
}

export function renderStartupState(page, startup) {
    const panel = page.$('#bot-startup-panel');
    const label = page.$('#bot-startup-label');
    const progress = page.$('#bot-startup-progress');
    const meta = page.$('#bot-startup-meta');
    if (!panel || !label || !progress || !meta) {
        return;
    }

    const active = !!startup?.active;
    panel.hidden = !active;
    if (!active) {
        return;
    }

    const progressValue = Number(startup?.progress || 0);
    label.textContent = startup?.message || '正在启动机器人...';
    progress.style.width = `${Math.max(0, Math.min(progressValue, 100))}%`;
    meta.textContent = formatStartupMeta(startup);
}

export function syncStartupMeta(page, startup) {
    const meta = page.$('#bot-startup-meta');
    if (!meta || !startup?.active) {
        return;
    }

    meta.textContent = formatStartupMeta(startup);
}

export function renderDiagnostics(page, diagnostics) {
    const panel = page.$('#bot-diagnostics');
    const title = page.$('#bot-diagnostics-title');
    const detail = page.$('#bot-diagnostics-detail');
    const list = page.$('#bot-diagnostics-list');
    const action = page.$('#btn-recover-bot');
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

export function renderHealthMetrics(
    page,
    metrics = {},
    checks = {},
    mergeFeedback = null,
    replyQuality = null
) {
    const cpuElem = page.$('#health-cpu');
    const memoryElem = page.$('#health-memory');
    const queueElem = page.$('#health-queue');
    const latencyElem = page.$('#health-latency');
    const warningElem = page.$('#health-warning');
    const mergeElem = page.$('#health-merge-feedback');
    if (!cpuElem || !memoryElem || !queueElem || !latencyElem || !warningElem || !mergeElem) {
        return;
    }

    cpuElem.textContent = formatPercent(metrics.cpu_percent);
    memoryElem.textContent = formatMemory(
        metrics.process_memory_mb,
        metrics.system_memory_percent
    );
    queueElem.textContent = formatQueue(
        metrics.pending_tasks,
        metrics.merge_pending_chats,
        metrics.merge_pending_messages
    );
    latencyElem.textContent = formatLatency(metrics.ai_latency_ms);
    warningElem.hidden = !metrics.warning;
    warningElem.textContent = metrics.warning || '';
    const feedbackParts = [];
    if (mergeFeedback?.status_text) {
        feedbackParts.push(mergeFeedback.status_text);
    } else {
        feedbackParts.push('消息合并状态：未激活');
    }
    if (replyQuality) {
        feedbackParts.push(formatReplyQualitySummary(replyQuality));
    }
    mergeElem.textContent = feedbackParts.join(' | ');
    mergeElem.dataset.active = mergeFeedback?.active ? 'true' : 'false';

    renderHealthCheckItem(page, 'health-ai', checks.ai);
    renderHealthCheckItem(page, 'health-wechat', checks.wechat);
    renderHealthCheckItem(page, 'health-db', checks.database);
}

export function renderRetrieval(page, retrieverStats = {}, timings = {}, exportRag = null) {
    const vectorEl = page.$('#retrieval-vector');
    const exportEl = page.$('#retrieval-export');
    const topkEl = page.$('#retrieval-topk');
    const thresholdEl = page.$('#retrieval-threshold');
    const rerankEl = page.$('#retrieval-rerank');
    const hitsEl = page.$('#retrieval-hits');
    const timingsGrid = page.$('#retrieval-timings');
    const timingsEmpty = page.$('#retrieval-timings-empty');

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
            ? formatNumber(Number(hits))
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

        span.textContent = formatTimingLabel(key);
        strong.textContent = formatDurationSec(Number(normalized[key]));
        cell.appendChild(span);
        cell.appendChild(strong);
        frag.appendChild(cell);
    });

    timingsGrid.appendChild(frag);
}
