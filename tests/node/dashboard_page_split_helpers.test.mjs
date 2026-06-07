import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import { Events } from '../../src/renderer/js/core/EventBus.js';
import { getGrowthTaskLabel } from '../../src/renderer/js/pages/dashboard/formatters.js';
import { renderDashboardCost, renderMessages } from '../../src/renderer/js/pages/dashboard/renderers.js';
import {
    confirmAction,
    handleGrowthTaskAction,
    recoverBot,
    restartBot,
    runReadinessAction,
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
    exportDiagnosticsSnapshot,
    handleDashboardSectionTabClick,
    handleReadinessAction,
    handleRefreshStatus,
    openWeChatClient,
} from '../../src/renderer/js/pages/dashboard/page-shell.js';
import {
    buildToolWorkflowSteps,
    runToolWorkflow,
    TOOL_WORKFLOW_TOOLS,
} from '../../src/renderer/js/pages/dashboard/tool-workflow.js';
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

function createToolWorkflowSelectors(document, options = {}) {
    const selectors = {};
    const register = (selector, element) => {
        selectors[selector] = element;
        return element;
    };
    const stepValues = options.stepValues || ['config_audit', 'prompt_preview', 'readiness_check'];
    stepValues.forEach((value, index) => {
        const select = document.createElement('select');
        select.value = value;
        register(`#dashboard-tool-workflow-step-${index + 1}`, select);
    });
    const sample = document.createElement('textarea');
    sample.value = options.sample ?? '你好，帮我确认当前运行准备状态。';
    register('#dashboard-tool-workflow-sample', sample);
    const continueOnError = document.createElement('input');
    continueOnError.checked = !!options.continueOnError;
    register('#dashboard-tool-workflow-continue', continueOnError);
    register('#dashboard-tool-workflow-meta', document.createElement('div'));
    register('#dashboard-tool-workflow-feedback', document.createElement('div'));
    register('#dashboard-tool-workflow-trace', document.createElement('div'));
    register('#btn-tool-workflow-dry-run', createButton(document, 'btn-tool-workflow-dry-run', '先 dry-run'));
    register('#btn-run-tool-workflow', createButton(document, 'btn-run-tool-workflow', '执行工具流'));
    register('#btn-reset-tool-workflow', createButton(document, 'btn-reset-tool-workflow', '恢复默认'));
    return selectors;
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
        _setDashboardSection(section) {
            this.sectionCalls = (this.sectionCalls || []);
            this.sectionCalls.push(section);
        },
        _loadRecentMessages() {
            this.messageLoads = (this.messageLoads || 0) + 1;
            return Promise.resolve();
        },
        ...overrides,
    };
}

test('dashboard stylesheet keeps the overview stage on a two-column desktop grid', () => {
    const css = readFileSync(new URL('../../src/renderer/css/pages/dashboard.css', import.meta.url), 'utf8');
    assert.match(css, /\.dashboard-stage-grid\s*\{\s*grid-template-columns:\s*minmax\(0,\s*1\.08fr\)\s+minmax\(360px,\s*0\.92fr\);/s);
    assert.equal(
        /\.dashboard-stage-grid\s*\{\s*grid-template-columns:\s*repeat\(3,\s*minmax\(0,\s*1fr\)\);/s.test(css),
        false,
    );
});

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
    const toolCalls = [];
    const page = createBindingPage({
        _renderToolWorkflowPanel() {
            toolCalls.push('watch-render');
        },
    });
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
        refreshDashboardStability: async (_target, force) => {
            page.stabilityCalls = (page.stabilityCalls || []);
            page.stabilityCalls.push(force);
        },
        renderToolWorkflowPanel: () => {
            toolCalls.push('tool-render');
        },
        resetToolWorkflow: () => {
            toolCalls.push('tool-reset');
        },
        runToolWorkflow: (_target, options) => {
            toolCalls.push(`tool-run:${!!options?.dryRun}`);
        },
    });

    assert.equal(page.bindings.length, 24);
    assert.equal(page.watchers.length, 6);

    const refreshBinding = page.bindings.find((item) => item.selector === '#btn-refresh-status');
    assert.ok(refreshBinding);
    refreshBinding.handler();
    assert.equal(page.emitted.length, 1);
    assert.deepEqual(page.emitted[0].payload, { force: true, refreshReadiness: true });
    assert.deepEqual(page.refreshCalls, [true]);

    const connectedWatcher = page.watchers.find((item) => item.path === 'bot.connected');
    assert.ok(connectedWatcher);
    connectedWatcher.handler(false);
    assert.equal(page.updateUiCalls, 1);
    assert.equal(page.clearCalls, 1);
    assert.equal(toolCalls.filter((item) => item === 'watch-render').length, 1);

    connectedWatcher.handler(true);
    assert.equal(page.messageLoads, 1);
    assert.deepEqual(page.refreshCalls, [true, true]);
    assert.deepEqual(page.stabilityCalls, [true, true]);
    assert.equal(toolCalls.filter((item) => item === 'watch-render').length, 2);

    const readinessWatcher = page.watchers.find((item) => item.path === 'readiness.report');
    assert.ok(readinessWatcher);

    const sectionBinding = page.bindings.find((item) => item.selector === '#dashboard-section-tabs');
    assert.ok(sectionBinding);
    sectionBinding.handler({
        target: {
            closest(selector) {
                if (selector !== '[data-dashboard-section-button]') {
                    return null;
                }
                return {
                    dataset: {
                        dashboardSectionButton: 'messages',
                    },
                };
            },
        },
    });
    assert.deepEqual(page.sectionCalls, ['messages']);

    page.bindings.find((item) => item.selector === '#btn-tool-workflow-dry-run')?.handler();
    page.bindings.find((item) => item.selector === '#btn-run-tool-workflow')?.handler();
    page.bindings.find((item) => item.selector === '#btn-reset-tool-workflow')?.handler();
    [
        '#dashboard-tool-workflow-step-1',
        '#dashboard-tool-workflow-step-2',
        '#dashboard-tool-workflow-step-3',
        '#dashboard-tool-workflow-continue',
        '#dashboard-tool-workflow-sample',
    ].forEach((selector) => {
        page.bindings.find((item) => item.selector === selector)?.handler();
    });
    assert.equal(toolCalls.includes('tool-run:true'), true);
    assert.equal(toolCalls.includes('tool-run:false'), true);
    assert.equal(toolCalls.includes('tool-reset'), true);
    assert.equal(toolCalls.filter((item) => item === 'tool-render').length, 5);
});

test('dashboard tool workflow helper builds whitelisted dry-run payload and renders trace', async () => withDom(async ({ document }) => {
    const selectors = createToolWorkflowSelectors(document, {
        stepValues: ['shell_exec', 'prompt_preview', ''],
        sample: '请检查当前配置状态',
        continueOnError: true,
    });
    const page = createDashboardPage({ bot: { connected: true } }, selectors);
    const toast = createToastRecorder();
    const calls = [];

    assert.deepEqual(buildToolWorkflowSteps(page).map((item) => item.tool), ['prompt_preview']);

    const result = await runToolWorkflow(page, { dryRun: true }, {
        toast,
        apiService: {
            runToolWorkflow: async (payload) => {
                calls.push(payload);
                return {
                    success: true,
                    trace: [
                        {
                            index: 1,
                            tool: 'prompt_preview',
                            status: 'skipped',
                            duration_ms: 0.2,
                            attempts: 0,
                            retry_count: 0,
                            output: { dry_run: true },
                        },
                    ],
                };
            },
        },
    });

    assert.equal(result.success, true);
    assert.equal(calls[0].dry_run, true);
    assert.equal(calls[0].steps.length, 1);
    assert.equal(calls[0].steps[0].tool, 'prompt_preview');
    assert.equal(calls[0].steps[0].continue_on_error, true);
    assert.equal(calls[0].steps[0].payload.sample.message, '请检查当前配置状态');
    assert.equal(JSON.stringify(calls[0]).includes('shell_exec'), false);
    assert.equal(selectors['#dashboard-tool-workflow-feedback'].dataset.state, 'success');
    assert.equal(selectors['#dashboard-tool-workflow-trace'].textContent.includes('dry-run 已跳过真实执行'), true);
    assert.equal(toast.calls.at(-1)?.type, 'success');
}));

test('dashboard tool workflow helper supports readonly observability tools with summaries', async () => withDom(async ({ document }) => {
    const selectors = createToolWorkflowSelectors(document, {
        stepValues: ['eval_latest', 'cost_summary', 'shell_exec'],
    });
    const page = createDashboardPage({ bot: { connected: true } }, selectors);
    const toast = createToastRecorder();
    let captured = null;

    assert.deepEqual(
        TOOL_WORKFLOW_TOOLS.map((item) => item.value),
        ['config_audit', 'prompt_preview', 'readiness_check', 'eval_latest', 'cost_summary'],
    );
    assert.deepEqual(buildToolWorkflowSteps(page), [
        { tool: 'eval_latest', payload: {} },
        { tool: 'cost_summary', payload: {} },
    ]);

    const result = await runToolWorkflow(page, {}, {
        toast,
        apiService: {
            runToolWorkflow: async (payload) => {
                captured = payload;
                return {
                    success: true,
                    trace: [
                        {
                            index: 1,
                            tool: 'eval_latest',
                            status: 'ok',
                            duration_ms: 1.2,
                            attempts: 1,
                            retry_count: 0,
                            output: {
                                has_report: true,
                                summary: { total_cases: 12, passed: true },
                                regression_count: 1,
                                cases: [{ id: 'should-not-leak' }],
                            },
                        },
                        {
                            index: 2,
                            tool: 'cost_summary',
                            status: 'ok',
                            duration_ms: 2.4,
                            attempts: 1,
                            retry_count: 0,
                            output: {
                                overview: {
                                    reply_count: 3,
                                    total_tokens: 420,
                                    currency_groups: [{ currency: 'USD', total_cost: 0.18 }],
                                },
                                model_count: 2,
                                review_queue_count: 1,
                                review_queue: [{ reply_preview: 'should-not-leak' }],
                            },
                        },
                    ],
                };
            },
        },
    });

    const traceText = selectors['#dashboard-tool-workflow-trace'].textContent;
    assert.equal(result.success, true);
    assert.deepEqual(captured.steps.map((item) => item.tool), ['eval_latest', 'cost_summary']);
    assert.equal(JSON.stringify(captured).includes('shell_exec'), false);
    assert.equal(traceText.includes('最新评测：12 个用例，通过，回归 1 项'), true);
    assert.equal(traceText.includes('成本摘要：回复 3 条，Token 420，模型 2 个，复核 1 条，USD 0.1800'), true);
    assert.equal(traceText.includes('should-not-leak'), false);
    assert.equal(toast.calls.at(-1)?.type, 'success');
}));

test('dashboard tool workflow helper preserves single-step failure trace and advice', async () => withDom(async ({ document }) => {
    const selectors = createToolWorkflowSelectors(document, {
        stepValues: ['prompt_preview', '', ''],
        sample: '',
    });
    const page = createDashboardPage({ bot: { connected: true } }, selectors);
    const toast = createToastRecorder();
    const error = new Error('bad workflow');
    error.code = 'bad_workflow';
    error.data = {
        code: 'bad_workflow',
        message: '工具流未完成',
        trace: [
            {
                index: 1,
                tool: 'prompt_preview',
                status: 'error',
                duration_ms: 1.5,
                attempts: 1,
                retry_count: 0,
                error_type: 'schema_validation',
                error: 'payload.sample.message is required',
            },
        ],
    };

    const result = await runToolWorkflow(page, {}, {
        toast,
        apiService: {
            runToolWorkflow: async () => {
                throw error;
            },
        },
    });

    assert.equal(result.success, false);
    assert.equal(result.trace[0].status, 'error');
    assert.equal(selectors['#dashboard-tool-workflow-feedback'].dataset.state, 'warning');
    assert.equal(selectors['#dashboard-tool-workflow-trace'].querySelector('.tool-workflow-trace-item')?.className.includes('is-error'), true);
    assert.equal(selectors['#dashboard-tool-workflow-trace'].textContent.includes('schema_validation'), true);
    assert.equal(selectors['#dashboard-tool-workflow-trace'].textContent.includes('检查示例消息'), true);
    assert.equal(toast.calls.at(-1)?.message, '工具流未完成');
}));

test('dashboard tool workflow helper renders continue_on_error multi-step trace', async () => withDom(async ({ document }) => {
    const selectors = createToolWorkflowSelectors(document, {
        stepValues: ['config_audit', 'readiness_check', ''],
        continueOnError: true,
    });
    const page = createDashboardPage({ bot: { connected: true } }, selectors);
    const toast = createToastRecorder();
    let captured = null;

    const result = await runToolWorkflow(page, {}, {
        toast,
        apiService: {
            runToolWorkflow: async (payload) => {
                captured = payload;
                return {
                    success: false,
                    message: '部分步骤失败',
                    trace: [
                        {
                            index: 1,
                            tool: 'config_audit',
                            status: 'error',
                            duration_ms: 3,
                            attempts: 1,
                            retry_count: 0,
                            error_type: 'timeout',
                            error: 'tool timed out after 5000 ms',
                        },
                        {
                            index: 2,
                            tool: 'readiness_check',
                            status: 'ok',
                            duration_ms: 4,
                            attempts: 1,
                            retry_count: 1,
                            output: { ready: true, blockingCount: 0 },
                        },
                    ],
                };
            },
        },
    });

    assert.equal(result.success, false);
    assert.deepEqual(captured.steps.map((item) => item.continue_on_error), [true, true]);
    assert.equal(selectors['#dashboard-tool-workflow-feedback'].dataset.state, 'warning');
    assert.equal(selectors['#dashboard-tool-workflow-trace'].querySelectorAll('.tool-workflow-trace-item').length, 2);
    assert.equal(selectors['#dashboard-tool-workflow-trace'].textContent.includes('timeout'), true);
    assert.equal(selectors['#dashboard-tool-workflow-trace'].textContent.includes('已就绪'), true);
    assert.equal(toast.calls.at(-1)?.message, '部分步骤失败');
}));

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

test('dashboard page shell routes readiness actions and snapshot export', async () => {
    const toast = createToastRecorder();
    const page = createBindingPage();

    await handleReadinessAction(page, 'open_settings', { toast });
    assert.deepEqual(page.emitted?.[0], { event: Events.PAGE_CHANGE, payload: 'settings' });

    await handleReadinessAction(page, 'open_wechat', {
        toast,
        windowApi: {
            openWeChat: async () => {},
        },
    });
    assert.equal(
        page.emitted.some((entry) => entry.event === Events.BOT_STATUS_CHANGE),
        true
    );

    await exportDiagnosticsSnapshot({
        toast,
        windowApi: {
            exportDiagnosticsSnapshot: async () => ({
                success: true,
                message: '诊断快照已导出',
            }),
        },
    });
    assert.equal(toast.calls.at(-1)?.message, '诊断快照已导出');
});

test('dashboard page shell ignores invalid section tab clicks', () => {
    const page = createBindingPage();
    handleDashboardSectionTabClick(page, {
        target: {
            closest() {
                return null;
            },
        },
    });
    assert.equal(page.sectionCalls, undefined);
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

test('dashboard runtime helper falls back to full UI refresh when idle renderer is missing', async () => {
    const page = createDashboardPage({
        backend: {
            idle: {
                state: 'countdown',
                remainingMs: 10000,
                updatedAt: Date.now(),
            },
        },
    });
    const toast = createToastRecorder();
    delete page._renderIdlePanel;

    await cancelIdleShutdown(page, {
        toast,
        updateBotUI: () => {
            page._botUiUpdates += 1;
        },
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
    assert.equal(page._botUiUpdates, 1);
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
        getState(path) {
            if (path === 'readiness.report') {
                return {
                    ready: false,
                    blockingCount: 1,
                    checks: [],
                    summary: {
                        title: '还有 1 项准备未完成',
                        detail: '请先处理阻塞项。',
                    },
                };
            }
            return undefined;
        },
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
        reply_quality: { success_rate: 75, attempted: 4 },
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
        renderHealthMetrics: (_page, metrics, checks, mergeFeedback, replyQuality) => {
            calls.push(['health', metrics, checks, mergeFeedback, replyQuality]);
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
    assert.deepEqual(calls.find((entry) => entry[0] === 'health')?.[4], {
        success_rate: 75,
        attempted: 4,
    });
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
