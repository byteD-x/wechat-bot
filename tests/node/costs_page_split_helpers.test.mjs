import test from 'node:test';
import assert from 'node:assert/strict';

import {
    readCostFilters,
    syncCostFilters,
    toCostApiParams,
} from '../../src/renderer/js/pages/costs/filter-sync.js';
import {
    refreshCosts,
    refreshPricingCatalog,
} from '../../src/renderer/js/pages/costs/data-controller.js';
import { toggleCostSession } from '../../src/renderer/js/pages/costs/session-controller.js';
import { bindCostsPage } from '../../src/renderer/js/pages/costs/page-shell.js';
import { renderCostSessions } from '../../src/renderer/js/pages/costs/renderers.js';
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

function createControl(value = '', checked = false) {
    return {
        value,
        checked,
    };
}

function createCostsPage(initialState = {}, selectors = {}) {
    const state = structuredClone(initialState);
    return {
        _filters: {
            period: '30d',
            provider_id: '',
            model: '',
            only_priced: false,
            include_estimated: true,
        },
        _summary: null,
        _sessions: [],
        _details: new Map(),
        _loading: false,
        $: (selector) => selectors[selector] || null,
        getState: (path) => getStateValue(state, path),
        setState: (path, value) => setStateValue(state, path, value),
        isActive: () => true,
        state,
    };
}

test('cost filter helpers keep dom sync and api params stable', () => withDom(({ document }) => {
    const selectors = {
        '#cost-period': createControl('7d'),
        '#cost-provider': createControl('openai'),
        '#cost-model': createControl('gpt-4.1'),
        '#cost-only-priced': createControl('', true),
        '#cost-include-estimated': createControl('', false),
    };
    const page = createCostsPage({}, selectors);

    assert.deepEqual(readCostFilters(page), {
        period: '7d',
        provider_id: 'openai',
        model: 'gpt-4.1',
        only_priced: true,
        include_estimated: false,
    });
    assert.deepEqual(toCostApiParams(page._filters), {
        period: '7d',
        provider_id: 'openai',
        model: 'gpt-4.1',
        only_priced: true,
        include_estimated: false,
    });

    page._filters = {
        period: '30d',
        provider_id: 'anthropic',
        model: 'claude',
        only_priced: false,
        include_estimated: true,
    };
    syncCostFilters(page);

    assert.equal(selectors['#cost-period'].value, '30d');
    assert.equal(selectors['#cost-provider'].value, 'anthropic');
    assert.equal(selectors['#cost-model'].value, 'claude');
    assert.equal(selectors['#cost-only-priced'].checked, false);
    assert.equal(selectors['#cost-include-estimated'].checked, true);
}));

test('cost data helper handles offline reset and online summary render', async () => withDom(async ({ document }) => {
    const selectors = {
        '#cost-period': document.createElement('select'),
        '#cost-provider': document.createElement('select'),
        '#cost-model': document.createElement('select'),
        '#cost-only-priced': document.createElement('input'),
        '#cost-include-estimated': document.createElement('input'),
        '#cost-overview': document.createElement('div'),
        '#cost-models': document.createElement('div'),
        '#cost-sessions': document.createElement('div'),
    };
    selectors['#cost-period'].value = '7d';
    selectors['#cost-provider'].value = 'openai';
    selectors['#cost-model'].value = 'gpt-4.1';
    selectors['#cost-only-priced'].checked = true;
    selectors['#cost-include-estimated'].checked = false;
    const page = createCostsPage({
        bot: { connected: false },
    }, selectors);

    await refreshCosts(page);
    assert.equal(selectors['#cost-overview'].textContent.includes('Python'), true);
    assert.equal(page._sessions.length, 0);

    const toggleCalls = [];
    page.state.bot.connected = true;
    await refreshCosts(page, {
        apiService: {
            getCostSummary: async (params) => ({
                success: true,
                overview: {
                    currency_groups: [{ currency: 'CNY', total_cost: 1.23 }],
                    total_tokens: 300,
                    priced_reply_count: 2,
                    unpriced_reply_count: 1,
                },
                models: [
                    {
                        model: 'gpt-4.1',
                        provider_id: 'openai',
                        prompt_tokens: 100,
                        completion_tokens: 200,
                        total_tokens: 300,
                        currency_groups: [{ currency: 'USD', total_cost: 0.4 }],
                    },
                ],
                options: {
                    providers: ['openai'],
                    models: ['gpt-4.1'],
                },
                params,
            }),
            getCostSessions: async () => ({
                success: true,
                sessions: [
                    {
                        chat_id: 'wxid_1',
                        display_name: 'Alice',
                        last_timestamp: 1_700_000_000,
                        reply_count: 2,
                        prompt_tokens: 100,
                        completion_tokens: 200,
                        total_tokens: 300,
                        priced_reply_count: 1,
                        estimated_reply_count: 0,
                        currency_groups: [{ currency: 'CNY', total_cost: 1.23 }],
                    },
                ],
            }),
        },
        onToggleSession: (chatId) => {
            toggleCalls.push(chatId);
        },
    });

    assert.equal(page._sessions.length, 1);
    assert.equal(selectors['#cost-overview'].children.length, 5);
    assert.equal(selectors['#cost-models'].children.length, 1);
    assert.equal(selectors['#cost-provider'].children.length, 2);
    assert.equal(selectors['#cost-model'].children.length, 2);
    assert.equal(selectors['#cost-sessions'].children.length, 1);

    selectors['#cost-sessions'].children[0].querySelector('.cost-session-trigger').click();
    assert.deepEqual(toggleCalls, ['wxid_1']);
}));

test('cost pricing helper handles offline notice and partial refresh result', async () => {
    const toastRecorder = createToastRecorder();
    const page = createCostsPage({
        bot: { connected: false },
    });

    await refreshPricingCatalog(page, {
        toast: toastRecorder,
    });
    assert.deepEqual(toastRecorder.calls[0], {
        type: 'info',
        message: '请先启动 Python 服务后查看成本数据',
    });

    page.state.bot.connected = true;
    let refreshCount = 0;
    await refreshPricingCatalog(page, {
        toast: toastRecorder,
        apiService: {
            refreshPricing: async () => ({
                success: true,
                results: {
                    openai: { success: false, message: 'timeout' },
                    anthropic: { success: true },
                },
            }),
        },
        refreshCosts: async () => {
            refreshCount += 1;
        },
    });

    assert.equal(refreshCount, 1);
    assert.equal(toastRecorder.calls.at(-1).type, 'warning');
    assert.match(toastRecorder.calls.at(-1).message, /openai: timeout/);
});

test('cost session helper caches detail result and renders error fallback', async () => withDom(async ({ document }) => {
    const selectors = {
        '#cost-sessions': document.createElement('div'),
    };
    const page = createCostsPage({
        bot: { connected: true },
    }, selectors);
    page._filters = {
        period: '30d',
        provider_id: '',
        model: '',
        only_priced: false,
        include_estimated: true,
    };

    renderCostSessions(page, [
        {
            chat_id: 'wxid_1',
            display_name: 'Alice',
            last_timestamp: 1_700_000_000,
            reply_count: 3,
            prompt_tokens: 100,
            completion_tokens: 50,
            total_tokens: 150,
            priced_reply_count: 1,
            estimated_reply_count: 0,
            currency_groups: [{ currency: 'USD', total_cost: 0.5 }],
        },
    ], () => {});

    const item = selectors['#cost-sessions'].children[0];
    const detail = item.querySelector('.cost-session-detail');
    const trigger = item.querySelector('.cost-session-trigger');
    let detailRequestCount = 0;
    await toggleCostSession(page, 'wxid_1', item, {
        apiService: {
            getCostSessionDetails: async () => {
                detailRequestCount += 1;
                return {
                    success: true,
                    records: [
                        {
                            model: 'gpt-4.1',
                            timestamp: 1_700_000_000,
                            tokens: { user: 10, reply: 20, total: 30 },
                            pricing_available: true,
                            currency: 'USD',
                            cost: { total_cost: 0.2, input_cost: 0.08, output_cost: 0.12 },
                            provider_id: 'openai',
                            preset: 'default',
                            reply_preview: 'ok',
                        },
                    ],
                };
            },
        },
        toast: createToastRecorder(),
    });

    assert.equal(detail.hidden, false);
    assert.equal(detailRequestCount, 1);
    assert.match(detail.textContent, /gpt-4\.1/);

    await toggleCostSession(page, 'wxid_1', item, {
        apiService: {
            getCostSessionDetails: async () => {
                detailRequestCount += 1;
                return { success: true, records: [] };
            },
        },
        toast: createToastRecorder(),
    });
    assert.equal(detail.hidden, true);

    await toggleCostSession(page, 'wxid_1', item, {
        apiService: {
            getCostSessionDetails: async () => {
                detailRequestCount += 1;
                return { success: true, records: [] };
            },
        },
        toast: createToastRecorder(),
    });
    assert.equal(detailRequestCount, 1);

    let focused = 0;
    trigger.focus = () => {
        focused += 1;
    };
    page._details.clear();
    item.classList.remove('is-open');
    detail.hidden = true;
    trigger.setAttribute('aria-expanded', 'false');
    await toggleCostSession(page, 'wxid_1', item, {
        apiService: {
            getCostSessionDetails: async () => ({
                success: false,
                message: 'bad detail',
            }),
        },
        toast: createToastRecorder(),
    });

    assert.equal(focused, 1);
    assert.match(detail.textContent, /bad detail/);
}));

test('cost page shell binds refresh flows and watcher side effects', async () => {
    const page = {
        bindings: [],
        watchers: [],
        bindEvent(target, type, handler) {
            this.bindings.push({ target, type, handler });
        },
        watchState(path, handler) {
            this.watchers.push({ path, handler });
        },
        isActive() {
            return true;
        },
    };
    const calls = [];

    bindCostsPage(page, {
        refreshCosts: async () => {
            calls.push('refresh');
        },
        refreshPricingCatalog: async () => {
            calls.push('pricing');
        },
    });

    assert.equal(page.bindings.length, 7);
    assert.equal(page.watchers.length, 1);

    await page.bindings[0].handler();
    await page.bindings[1].handler();
    await page.bindings[2].handler();
    await page.bindings[5].handler();
    await page.watchers[0].handler(true);

    assert.deepEqual(calls, ['refresh', 'pricing', 'refresh', 'refresh', 'refresh']);
});
