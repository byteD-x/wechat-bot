import test from 'node:test';
import assert from 'node:assert/strict';

import {
    applyFilters,
    clearLogs,
    copyLogs,
    exportLogs,
    refreshLogs,
} from '../../src/renderer/js/pages/logs/data-controller.js';
import {
    bindLogsEvents,
    syncLogsPageOptions,
} from '../../src/renderer/js/pages/logs/page-shell.js';
import {
    clearRefreshTimer,
    scrollToBottom,
    setupAutoRefresh,
    syncOptionState,
    updateWrapState,
} from '../../src/renderer/js/pages/logs/runtime-controller.js';
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
    const push = (type, message) => calls.push({ type, message });
    return {
        calls,
        success(message) {
            push('success', message);
        },
        info(message) {
            push('info', message);
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

function createLogsPage(initialState = {}, selectors = {}) {
    const state = structuredClone(initialState);
    const emitted = [];
    return {
        _allLogs: [],
        _visibleLogs: [],
        _lineCount: 500,
        _keyword: '',
        _level: '',
        _refreshTimer: null,
        $: (selector) => selectors[selector] || null,
        getState: (path) => getStateValue(state, path),
        setState: (path, value) => setStateValue(state, path, value),
        emit: (event, payload) => emitted.push({ event, payload }),
        isActive: () => true,
        state,
        emitted,
    };
}

function createInteractiveControl(initial = '') {
    return {
        value: initial,
        checked: false,
        listeners: {},
        addEventListener(type, handler) {
            this.listeners[type] = handler;
        },
    };
}

test('logs runtime helpers sync options, wrap state and auto refresh timer', async () => withDom(async ({ document }) => {
    const wrapContainer = document.createElement('div');
    wrapContainer.className = 'log-container';
    const selectors = {
        '#setting-auto-scroll': document.createElement('input'),
        '#setting-auto-refresh': document.createElement('input'),
        '#setting-wrap': document.createElement('input'),
        '.log-container': wrapContainer,
        '#log-content': document.createElement('div'),
    };
    selectors['#log-content'].scrollHeight = 180;
    const page = createLogsPage({
        logs: {
            autoScroll: true,
            autoRefresh: false,
            wrap: true,
        },
        bot: {
            connected: true,
        },
    }, selectors);

    syncOptionState(page);
    assert.equal(selectors['#setting-auto-scroll'].checked, true);
    assert.equal(selectors['#setting-auto-refresh'].checked, false);
    assert.equal(wrapContainer.classList.contains('wrap'), true);

    updateWrapState(page, false);
    assert.equal(wrapContainer.classList.contains('wrap'), false);

    scrollToBottom(page);
    assert.equal(selectors['#log-content'].scrollTop, 180);

    const timers = [];
    const cleared = [];
    setupAutoRefresh(page, {
        setIntervalFn: (_handler, _delay) => {
            timers.push(true);
            return 42;
        },
        refreshLogs: async () => {},
    });
    assert.equal(page.state.intervals.logs, null);

    page.setState('logs.autoRefresh', true);
    setupAutoRefresh(page, {
        setIntervalFn: (_handler, _delay) => {
            timers.push(true);
            return 99;
        },
        refreshLogs: async () => {},
    });
    assert.equal(page._refreshTimer, 99);
    assert.equal(page.state.intervals.logs, 99);
    clearRefreshTimer(page, {
        clearIntervalFn: (value) => {
            cleared.push(value);
        },
    });
    assert.deepEqual(cleared, [99]);
    assert.equal(page.state.intervals.logs, null);
}));

test('logs data helpers refresh, filter and clear logs stably', async () => withDom(async ({ document }) => {
    const selectors = {
        '#log-content': document.createElement('div'),
        '#log-count': document.createElement('div'),
        '#log-visible-count': document.createElement('div'),
        '#log-updated': document.createElement('div'),
    };
    const page = createLogsPage({
        bot: { connected: true },
        logs: { autoScroll: false },
    }, selectors);
    const toast = createToastRecorder();

    await refreshLogs(page, {}, {
        toast,
        apiService: {
            getLogs: async () => ({
                success: true,
                logs: [
                    '[INFO] keep first',
                    '[ERROR] boom happened',
                    '127.0.0.1 GET /api/logs 1.1 200 10 20',
                ],
            }),
        },
    });

    assert.equal(page._allLogs.length, 3);
    assert.equal(page._visibleLogs.length, 2);
    assert.equal(selectors['#log-count'].textContent, '3 行');
    assert.equal(selectors['#log-visible-count'].textContent, '2 匹配');
    assert.equal(page.emitted.length, 1);

    page._keyword = 'boom';
    page._level = 'error';
    applyFilters(page);
    assert.equal(page._visibleLogs.length, 1);
    assert.match(selectors['#log-content'].textContent, /boom/i);

    await clearLogs(page, {
        toast,
        apiService: {
            clearLogs: async () => ({ success: true, message: '日志已清空' }),
        },
    });
    assert.equal(page._allLogs.length, 0);
    assert.equal(page._visibleLogs.length, 0);
    assert.equal(toast.calls.at(-1)?.message, '日志已清空');
}));

test('logs data helpers support copy and export flows', async () => withDom(async ({ document }) => {
    const page = createLogsPage({}, {
        '#log-content': document.createElement('div'),
    });
    page._visibleLogs = ['line 1', 'line 2'];
    const toast = createToastRecorder();
    const clipboardWrites = [];
    const exports = [];

    await copyLogs(page, {
        toast,
        navigatorObj: {
            clipboard: {
                writeText: async (value) => {
                    clipboardWrites.push(value);
                },
            },
        },
    });
    assert.deepEqual(clipboardWrites, ['line 1\nline 2']);
    assert.equal(toast.calls.at(-1)?.message, '日志已复制到剪贴板');

    exportLogs(page, {
        toast,
        downloadLogTextFile: (filename, content) => {
            exports.push({ filename, content });
        },
        nowFn: () => 123,
    });
    assert.equal(exports[0].filename, 'wechat-ai-assistant-logs-123.log');
    assert.equal(exports[0].content, 'line 1\nline 2');
}));

test('logs page shell binds controls and watcher side effects stably', async () => {
    const searchInput = createInteractiveControl();
    const levelSelect = createInteractiveControl();
    const lineSelect = createInteractiveControl('200');
    const autoScroll = createInteractiveControl();
    const autoRefresh = createInteractiveControl();
    const wrap = createInteractiveControl();
    const page = {
        bindings: [],
        watchers: [],
        state: {},
        bindEvent(selector, type, handler) {
            this.bindings.push({ selector, type, handler });
        },
        watchState(path, handler) {
            this.watchers.push({ path, handler });
        },
        $(selector) {
            return {
                '#log-search': searchInput,
                '#log-level': levelSelect,
                '#log-lines': lineSelect,
                '#setting-auto-scroll': autoScroll,
                '#setting-auto-refresh': autoRefresh,
                '#setting-wrap': wrap,
            }[selector] || null;
        },
        setState(path, value) {
            setStateValue(this.state, path, value);
        },
        isActive() {
            return true;
        },
    };
    const calls = [];

    bindLogsEvents(page, {
        refreshLogs: async (_page, options = {}) => {
            calls.push(['refresh', options]);
        },
        clearLogs: async () => {
            calls.push(['clear']);
        },
        copyLogs: async () => {
            calls.push(['copy']);
        },
        exportLogs: () => {
            calls.push(['export']);
        },
        applyFilters: () => {
            calls.push(['filter', page._keyword, page._level]);
        },
        setupAutoRefresh: () => {
            calls.push(['setup']);
        },
        scrollToBottom: () => {
            calls.push(['scroll']);
        },
        updateWrapState: (_page, enabled) => {
            calls.push(['wrap', enabled]);
        },
    });

    assert.equal(page.bindings.length, 5);
    assert.equal(page.watchers.length, 1);

    searchInput.value = 'Err';
    searchInput.listeners.input();
    levelSelect.value = 'ERROR';
    levelSelect.listeners.change();
    lineSelect.listeners.change();
    autoScroll.checked = true;
    autoScroll.listeners.change();
    autoRefresh.checked = false;
    autoRefresh.listeners.change();
    wrap.checked = true;
    wrap.listeners.change();

    assert.deepEqual(calls[0], ['filter', 'err', undefined]);
    assert.deepEqual(calls[1], ['filter', 'err', 'error']);
    assert.deepEqual(calls[2], ['refresh', {}]);
    assert.deepEqual(calls[3], ['scroll']);
    assert.deepEqual(calls[4], ['setup']);
    assert.deepEqual(calls[5], ['wrap', true]);

    const refreshBtn = page.bindings.find((item) => item.selector === '#btn-refresh-logs');
    const clearBtn = page.bindings.find((item) => item.selector === '#btn-clear-logs');
    const copyBtn = page.bindings.find((item) => item.selector === '#btn-copy-logs');
    const exportBtn = page.bindings.find((item) => item.selector === '#btn-export-logs');
    await refreshBtn.handler();
    await clearBtn.handler();
    await copyBtn.handler();
    exportBtn.handler();
    assert.equal(calls.some((item) => item[0] === 'clear'), true);
    assert.equal(calls.some((item) => item[0] === 'copy'), true);
    assert.equal(calls.some((item) => item[0] === 'export'), true);

    const connectedWatcher = page.watchers[0];
    connectedWatcher.handler(true);
    assert.equal(calls.some((item) => item[0] === 'setup'), true);
    assert.equal(calls.some((item) => item[0] === 'refresh' && item[1]?.silent === true), true);
});

test('logs page shell sync helper delegates to runtime sync', () => {
    let synced = 0;
    syncLogsPageOptions({}, {
        syncOptionState: () => {
            synced += 1;
        },
    });
    assert.equal(synced, 1);
});
