import test from 'node:test';
import assert from 'node:assert/strict';

import { getGrowthTaskLabel } from '../../src/renderer/js/pages/dashboard/formatters.js';
import { renderDashboardCost, renderMessages } from '../../src/renderer/js/pages/dashboard/renderers.js';
import {
    confirmAction,
    handleGrowthTaskAction,
    restartBot,
    toggleBot,
} from '../../src/renderer/js/pages/dashboard/actions.js';
import {
    applyStatusSnapshot,
    cancelIdleShutdown,
    getIdleRemainingMs,
    getIdleState,
    startIdleTimer,
    stopIdleTimer,
    wakeBackend,
} from '../../src/renderer/js/pages/dashboard/runtime-controller.js';
import {
    appendRecentMessage,
    clearOfflineData,
    loadRecentMessages,
    refreshDashboardCost,
} from '../../src/renderer/js/pages/dashboard/data-loader.js';
import {
    updateBotUI,
    updateStats,
} from '../../src/renderer/js/pages/dashboard/status-presenter.js';
import {
    bindDashboardEvents,
    handleRefreshStatus,
    openWeChatClient,
} from '../../src/renderer/js/pages/dashboard/page-shell.js';
import { installDomStub } from './dom-stub.mjs';

async function withDom(run) {
    const env = installDomStub();
    try {
        return await run(env);
    } finally {
        env.restore();
    }
}

function createToastRecorder() {
    const calls = [];
    const push = (type, message, level) => calls.push({ type, message, level });
    return {
        calls,
        show(message, level) {
            push('show', message, level);
        },
        success(message) {
            push('success', message);
        },
        info(message) {
            push('info', message);
        },
        warning(message) {
            push('warning', message);
        },
        error(message) {
            push('error', message);
        },
        getErrorMessage(error, fallback) {
            return error?.message || fallback;
        },
    };
}

function setStateValue(target, path, value) {
    const parts = String(path || '').split('.').filter(Boolean);
    let cursor = target;
    while (parts.length > 1) {
        const key = parts.shift();
        if (!cursor[key] || typeof cursor[key] !== 'object') {
            cursor[key] = {};
        }
        cursor = cursor[key];
    }
    cursor[parts[0]] = value;
}

function getStateValue(target, path) {
    return String(path || '')
        .split('.')
        .filter(Boolean)
        .reduce((cursor, key) => (cursor && key in cursor ? cursor[key] : undefined), target);
}

function createButton(document, id, label = '') {
    const button = document.createElement('button');
    button.id = id;
    const span = document.createElement('span');
    span.textContent = label;
    button.appendChild(span);
    return button;
}

function createGrowthActionButton(document, action, taskType) {
    const button = document.createElement('button');
    button.dataset.growthAction = action;
    button.dataset.taskType = taskType;
    button.closest = (selector) => selector === '[data-growth-action]' ? button : null;
    return button;
}

function createBotState(document) {
    const wrap = document.createElement('div');
    const dot = document.createElement('span');
    dot.className = 'bot-state-dot';
    const text = document.createElement('span');
    text.className = 'bot-state-text';
    wrap.appendChild(dot);
    wrap.appendChild(text);
    return wrap;
}

function createToggleButton(document, id, label) {
    const button = document.createElement('button');
    button.id = id;
    button.className = 'btn btn-primary';
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
    svg.appendChild(use);
    const span = document.createElement('span');
    span.textContent = label;
    button.appendChild(svg);
    button.appendChild(span);
    return button;
}

function createDashboardPage(initialState = {}, selectors = {}) {
    const state = structuredClone(initialState);
    const emitted = [];
    const page = {
        _recentMessages: [],
        _dashboardCost: {
            today: null,
            recent: null,
        },
        _lastCostFetchAt: 0,
        _idleRenderTimer: null,
        _idlePanelRenders: 0,
        _botUiUpdates: 0,
        $: (selector) => selectors[selector] || null,
        getState: (path) => getStateValue(state, path),
        setState: (path, value) => setStateValue(state, path, value),
        emit: (event, payload) => emitted.push({ event, payload }),
        isActive: () => true,
        _renderMessages: (container, messages) => renderMessages(container, messages),
        _renderDashboardCost: () => renderDashboardCost(page, page._dashboardCost),
        _renderIdlePanel: () => {
            page._idlePanelRenders += 1;
        },
        _updateBotUI: () => {
            page._botUiUpdates += 1;
        },
        _getGrowthTaskLabel: (taskType) => getGrowthTaskLabel(taskType),
        state,
        emitted,
    };
    return page;
}

function createBindingPage(overrides = {}) {
    const bindings = [];
    const watchers = [];
    return {
        bindings,
        watchers,
        bindEvent(selector, type, handler) {
            bindings.push({ selector, type, handler });
        },
        watchState(path, handler) {
            watchers.push({ path, handler });
        },
        emit(event, payload) {
            (this.emitted || (this.emitted = [])).push({ event, payload });
        },
        isActive() {
            return true;
        },
        _getIdleState() {
            return { state: 'active' };
        },
        _wakeBackend() {
            this.wakeCalls = (this.wakeCalls || 0) + 1;
        },
        _refreshDashboardCost(force) {
            this.refreshCalls = (this.refreshCalls || []);
            this.refreshCalls.push(force);
            return Promise.resolve();
        },
        _updateBotUI() {
            this.updateUiCalls = (this.updateUiCalls || 0) + 1;
        },
        _clearOfflineData() {
            this.clearCalls = (this.clearCalls || 0) + 1;
        },
        _loadRecentMessages() {
            this.messageLoads = (this.messageLoads || 0) + 1;
            return Promise.resolve();
        },
        ...overrides,
    };
}

test('dashboard actions helper toggles bot start and records startup status', async () => withDom(async ({ document }) => {
    const toggleButton = createButton(document, 'btn-toggle-bot', '启动机器人');
    const page = createDashboardPage({
        bot: {
            running: false,
            status: {},
        },
    }, {
        '#btn-toggle-bot': toggleButton,
    });
    const toast = createToastRecorder();
    let started = 0;

    await toggleBot(page, {
        toast,
        windowApi: {
            runtimeStartBot: async () => {
                started += 1;
                return { success: true, message: '机器人启动中' };
            },
        },
    });

    assert.equal(started, 1);
    assert.equal(page.state.bot.status.startup.stage, 'starting');
    assert.equal(toggleButton.disabled, false);
    assert.equal(toast.calls.at(-1)?.message, '机器人启动中');
    assert.equal(page.emitted.length >= 1, true);
}));

test('dashboard actions helper handles growth task confirmation and restart flow', async () => withDom(async ({ document }) => {
    const eventButton = createGrowthActionButton(document, 'clear', 'emotion');
    const page = createDashboardPage();
    const toast = createToastRecorder();
    const cleared = [];
    let confirmed = 0;

    await handleGrowthTaskAction(page, {
        target: eventButton,
    }, {
        toast,
        confirmAction: async () => {
            confirmed += 1;
            return true;
        },
        apiService: {
            clearGrowthTask: async (taskType) => {
                cleared.push(taskType);
                return { success: true, message: '已清空队列' };
            },
        },
    });

    assert.equal(confirmed, 1);
    assert.deepEqual(cleared, ['emotion']);
    assert.equal(eventButton.disabled, false);
    assert.equal(toast.calls.at(-1)?.message, '已清空队列');

    await restartBot(page, {
        toast,
        apiService: {
            restartBot: async () => ({ success: true, message: '机器人正在重启' }),
        },
    });
    assert.equal(toast.calls.some((item) => item.message === '正在重启机器人...'), true);
}));

test('dashboard action confirm helper falls back to injected confirm function', async () => {
    const accepted = await confirmAction({ message: '继续吗？' }, {
        confirmAction: async (options) => options.message === '继续吗？',
    });
    assert.equal(accepted, true);
});

test('dashboard page shell binds events and watchers with stable side effects', async () => {
    const page = createBindingPage();
    bindDashboardEvents(page, {
        toast: createToastRecorder(),
        windowApi: {},
        getIdleState: () => ({ state: 'active' }),
        updateBotUI: () => {
            page.updateUiCalls = (page.updateUiCalls || 0) + 1;
        },
        clearOfflineData: () => {
            page.clearCalls = (page.clearCalls || 0) + 1;
        },
        loadRecentMessages: async () => {
            page.messageLoads = (page.messageLoads || 0) + 1;
        },
        refreshDashboardCost: async (_target, force) => {
            page.refreshCalls = (page.refreshCalls || []);
            page.refreshCalls.push(force);
        },
    });

    assert.equal(page.bindings.length, 13);
    assert.equal(page.watchers.length, 5);

    const refreshBinding = page.bindings.find((item) => item.selector === '#btn-refresh-status');
    assert.ok(refreshBinding);
    refreshBinding.handler();
    assert.equal(page.emitted.length, 1);
    assert.deepEqual(page.refreshCalls, [true]);

    const connectedWatcher = page.watchers.find((item) => item.path === 'bot.connected');
    assert.ok(connectedWatcher);
    connectedWatcher.handler(false);
    assert.equal(page.updateUiCalls, 1);
    assert.equal(page.clearCalls, 1);

    connectedWatcher.handler(true);
    assert.equal(page.messageLoads, 1);
    assert.deepEqual(page.refreshCalls, [true, true]);
});

test('dashboard page shell handles refresh wake-up and wechat open feedback', async () => {
    const toast = createToastRecorder();
    const page = createBindingPage();

    handleRefreshStatus(page, {
        toast,
        getIdleState: () => ({ state: 'stopped_by_idle' }),
        wakeBackend: () => {
            page.wakeCalls = (page.wakeCalls || 0) + 1;
        },
    });
    assert.equal(page.wakeCalls, 1);
    assert.equal(page.emitted, undefined);

    await openWeChatClient({
        toast,
        windowApi: {
            openWeChat: async () => {},
        },
    });
    assert.equal(toast.calls.at(-1)?.message, '正在打开微信客户端...');

    await openWeChatClient({ toast, windowApi: {} });
    assert.equal(toast.calls.at(-1)?.message, '请手动打开微信客户端');
});

test('dashboard runtime helper manages idle timer and wake flow', async () => {
    const page = createDashboardPage({
        bot: {
            connected: false,
            running: false,
            paused: false,
            status: {},
        },
        backend: {
            idle: {
                state: 'countdown',
                remainingMs: 30000,
                updatedAt: Date.now() - 500,
            },
        },
    });
    const toast = createToastRecorder();
    const timers = [];
    const clearedTimers = [];
    const originalSetInterval = globalThis.setInterval;
    const originalClearInterval = globalThis.clearInterval;
    globalThis.setInterval = (_handler, _delay) => {
        timers.push(true);
        return 123;
    };
    globalThis.clearInterval = (value) => {
        clearedTimers.push(value);
    };

    try {
        startIdleTimer(page);
        assert.equal(page._idleRenderTimer, 123);
        assert.equal(timers.length, 1);
        stopIdleTimer(page);
        assert.equal(page._idleRenderTimer, null);
        assert.deepEqual(clearedTimers, [123]);
    } finally {
        globalThis.setInterval = originalSetInterval;
        globalThis.clearInterval = originalClearInterval;
    }

    await cancelIdleShutdown(page, {
        toast,
        windowApi: {
            runtimeCancelIdleShutdown: async () => ({
                idle_state: {
                    state: 'active',
                    remainingMs: 0,
                    updatedAt: Date.now(),
                },
            }),
        },
    });
    assert.equal(page.state.backend.idle.state, 'active');
    assert.equal(page._idlePanelRenders, 1);

    await wakeBackend(page, {
        toast,
        windowApi: {
            runtimeEnsureService: async () => {},
            getRuntimeIdleState: async () => ({
                state: 'active',
                remainingMs: 0,
                updatedAt: Date.now(),
            }),
        },
        apiService: {
            getStatus: async () => ({
                running: true,
                is_paused: false,
                startup: null,
            }),
        },
        updateBotUI: () => {
            page._botUiUpdates += 1;
        },
    });
    assert.equal(page.state.bot.connected, true);
    assert.equal(page.state.bot.running, true);
    assert.equal(page._botUiUpdates >= 1, true);
    assert.equal(toast.calls.at(-1)?.message, '后端已唤醒');
});

test('dashboard runtime helper exposes stable idle state helpers', () => {
    const page = {
        getState(path) {
            if (path === 'backend.idle') {
                return {
                    state: 'countdown',
                    remainingMs: 3000,
                    updatedAt: Date.now() - 1000,
                };
            }
            return null;
        },
    };

    const state = getIdleState(page);
    assert.equal(state.state, 'countdown');
    assert.equal(getIdleRemainingMs(page, state) <= 3000, true);
});

test('dashboard runtime helper applies status snapshot to page state', () => {
    const state = {};
    let updated = 0;
    const page = {
        setState(path, value) {
            setStateValue(state, path, value);
        },
        _updateBotUI() {
            updated += 1;
        },
    };

    applyStatusSnapshot(page, {
        running: true,
        is_paused: true,
        startup: { active: false },
    }, {
        updateBotUI: () => {
            updated += 1;
        },
    });

    assert.equal(state.bot.connected, true);
    assert.equal(state.bot.running, true);
    assert.equal(state.bot.paused, true);
    assert.equal(updated, 1);
});

test('dashboard status presenter maps bot and growth state into dashboard controls', async () => withDom(async ({ document }) => {
    const selectors = {
        '#bot-state': createBotState(document),
        '#btn-pause': createButton(document, 'btn-pause', '暂停'),
        '#btn-restart': createButton(document, 'btn-restart', '重启'),
        '#btn-toggle-bot': createToggleButton(document, 'btn-toggle-bot', '启动机器人'),
        '#growth-task-status': document.createElement('div'),
        '#growth-task-backlog': document.createElement('div'),
        '#growth-task-queue': document.createElement('div'),
        '#growth-task-batch': document.createElement('div'),
        '#growth-task-next': document.createElement('div'),
        '#growth-task-error': document.createElement('div'),
        '#btn-toggle-growth': createButton(document, 'btn-toggle-growth', '启动成长任务'),
    };
    let idlePanelContext = null;
    let startupArg = null;
    let startupMetaArg = null;
    let diagnosticsArg = null;
    let growthRenderArgs = null;
    const page = {
        $: (selector) => selectors[selector] || null,
        getState(path) {
            return getStateValue({
                bot: {
                    connected: true,
                    running: true,
                    paused: false,
                    status: {
                        growth_running: true,
                        growth_enabled: true,
                        background_backlog_count: 8,
                        startup: { active: false },
                        diagnostics: { level: 'warning' },
                    },
                },
            }, path);
        },
    };

    updateBotUI(page, {
        formatNumber: (value) => String(value),
        renderGrowthTasks: (...args) => {
            growthRenderArgs = args;
        },
        renderIdlePanel: (_page, context) => {
            idlePanelContext = context;
        },
        renderStartupState: (_page, startup) => {
            startupArg = startup;
        },
        syncStartupMeta: (_page, startup) => {
            startupMetaArg = startup;
        },
        renderDiagnostics: (_page, diagnostics) => {
            diagnosticsArg = diagnostics;
        },
    });

    assert.equal(selectors['#bot-state'].querySelector('.bot-state-text')?.textContent, '运行中');
    assert.equal(selectors['#bot-state'].querySelector('.bot-state-dot')?.className, 'bot-state-dot online');
    assert.equal(selectors['#btn-pause'].disabled, false);
    assert.equal(selectors['#btn-toggle-bot'].querySelector('span')?.textContent, '停止机器人');
    assert.equal(selectors['#btn-toggle-growth'].querySelector('span')?.textContent, '停止成长任务');
    assert.equal(selectors['#growth-task-status'].textContent, '运行中');
    assert.equal(selectors['#growth-task-backlog'].textContent, '待处理任务 8');
    assert.equal(growthRenderArgs?.[0], true);
    assert.equal(idlePanelContext?.connected, true);
    assert.deepEqual(startupArg, { active: false });
    assert.deepEqual(startupMetaArg, { active: false });
    assert.deepEqual(diagnosticsArg, { level: 'warning' });
}));

test('dashboard status presenter updates summary stats and delegates detailed panels', async () => withDom(async ({ document }) => {
    const selectors = {
        '#stat-uptime': document.createElement('div'),
        '#stat-today-replies': document.createElement('div'),
        '#stat-today-tokens': document.createElement('div'),
        '#stat-total-replies': document.createElement('div'),
        '#bot-transport-backend': document.createElement('div'),
        '#bot-transport-version': document.createElement('div'),
        '#bot-transport-warning': document.createElement('div'),
    };
    const calls = [];
    const page = {
        _lastStats: null,
        $: (selector) => selectors[selector] || null,
    };

    updateStats(page, {
        uptime: '1h',
        today_replies: 12,
        today_tokens: 345,
        total_replies: 67,
        transport_backend: 'wcferry',
        wechat_version: '3.9.0',
        transport_warning: '连接波动',
        startup: { active: true },
        diagnostics: { level: 'warning' },
        system_metrics: { cpu_percent: 10 },
        health_checks: { ai: { status: 'ok' } },
        merge_feedback: { active: true },
        retriever_stats: { top_k: 8 },
        runtime_timings: { invoke_sec: 1.2 },
        export_rag: { enabled: true },
    }, {
        formatNumber: (value) => `N${value}`,
        formatTokens: (value) => `T${value}`,
        renderStartupState: (_page, value) => {
            calls.push(['startup', value]);
        },
        syncStartupMeta: (_page, value) => {
            calls.push(['startupMeta', value]);
        },
        renderDiagnostics: (_page, value) => {
            calls.push(['diagnostics', value]);
        },
        renderHealthMetrics: (_page, metrics, checks, mergeFeedback) => {
            calls.push(['health', metrics, checks, mergeFeedback]);
        },
        renderRetrieval: (_page, stats, timings, exportRag) => {
            calls.push(['retrieval', stats, timings, exportRag]);
        },
        refreshDashboardCost: () => {
            calls.push(['cost']);
            return Promise.resolve();
        },
    });

    assert.equal(selectors['#stat-uptime'].textContent, '1h');
    assert.equal(selectors['#stat-today-replies'].textContent, 'N12');
    assert.equal(selectors['#stat-today-tokens'].textContent, 'T345');
    assert.equal(selectors['#stat-total-replies'].textContent, 'N67');
    assert.equal(selectors['#bot-transport-backend'].textContent, '后端: wcferry (静默模式)');
    assert.equal(selectors['#bot-transport-version'].textContent, '微信: 3.9.0');
    assert.equal(selectors['#bot-transport-warning'].hidden, false);
    assert.equal(selectors['#bot-transport-warning'].textContent, '连接波动');
    assert.equal(calls.some((entry) => entry[0] === 'health'), true);
    assert.equal(calls.some((entry) => entry[0] === 'retrieval'), true);
    assert.equal(calls.some((entry) => entry[0] === 'cost'), true);
    assert.equal(page._lastStats.transport_backend, 'wcferry');
}));

test('dashboard data helper loads messages, appends recent data and refreshes cost', async () => withDom(async ({ document }) => {
    const recentMessages = document.createElement('div');
    const todayCost = document.createElement('div');
    const summary = document.createElement('div');
    const models = document.createElement('div');
    const page = createDashboardPage({
        bot: {
            connected: true,
        },
    }, {
        '#recent-messages': recentMessages,
        '#stat-today-cost': todayCost,
        '#dashboard-cost-summary': summary,
        '#dashboard-cost-top-models': models,
    });

    await loadRecentMessages(page, {
        apiService: {
            getMessages: async () => ({
                success: true,
                messages: [
                    { sender: 'A', content: '一', timestamp: 1 },
                    { sender: 'B', content: '二', timestamp: 2 },
                ],
            }),
        },
    });
    assert.equal(page._recentMessages.length, 2);
    assert.equal(recentMessages.children.length, 2);

    appendRecentMessage(page, {
        sender: 'C',
        content: '三',
        timestamp: 3,
        direction: 'outgoing',
    });
    assert.equal(page._recentMessages.at(-1).is_self, true);

    await refreshDashboardCost(page, true, {
        apiService: {
            getCostSummary: async ({ period }) => period === 'today'
                ? {
                    success: true,
                    overview: {
                        currency_groups: [{ currency: 'CNY', total_cost: 2.5 }],
                    },
                }
                : {
                    success: true,
                    overview: {
                        currency_groups: [{ currency: 'USD', total_cost: 6.8 }],
                        total_tokens: 2000,
                        priced_reply_count: 4,
                    },
                    models: [
                        {
                            model: 'gpt-4.1',
                            provider_id: 'openai',
                            total_tokens: 2000,
                            currency_groups: [{ currency: 'USD', total_cost: 6.8 }],
                        },
                    ],
                },
        },
    });

    assert.equal(todayCost.textContent.includes('2.5000'), true);
    assert.equal(summary.children.length, 3);
    assert.equal(models.children.length, 1);

    clearOfflineData(page);
    assert.equal(page._recentMessages.length, 0);
    assert.equal(page._dashboardCost.today, null);
}));
