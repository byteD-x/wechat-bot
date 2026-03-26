import test from 'node:test';
import assert from 'node:assert/strict';

import {
    readCostFilters,
    syncCostFilters,
    toCostApiParams,
} from '../../src/renderer/js/pages/costs/filter-sync.js';
import {
    exportCostReviewQueue,
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
            preset: '',
            review_reason: '',
            suggested_action: '',
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

test('cost filter helpers keep review_reason in sync', () => withDom(() => {
    const selectors = {
        '#cost-period': createControl('7d'),
        '#cost-provider': createControl('openai'),
        '#cost-model': createControl('gpt-4.1'),
        '#cost-preset': createControl('default'),
        '#cost-review-reason': createControl('retrieval_weak'),
        '#cost-suggested-action': createControl('tune_retrieval_threshold'),
        '#cost-only-priced': createControl('', true),
        '#cost-include-estimated': createControl('', false),
    };
    const page = createCostsPage({}, selectors);

    assert.deepEqual(readCostFilters(page), {
        period: '7d',
        provider_id: 'openai',
        model: 'gpt-4.1',
        preset: 'default',
        review_reason: 'retrieval_weak',
        suggested_action: 'tune_retrieval_threshold',
        only_priced: true,
        include_estimated: false,
    });
    assert.deepEqual(toCostApiParams(page._filters), {
        period: '7d',
        provider_id: 'openai',
        model: 'gpt-4.1',
        preset: 'default',
        review_reason: 'retrieval_weak',
        suggested_action: 'tune_retrieval_threshold',
        only_priced: true,
        include_estimated: false,
    });

    page._filters = {
        period: '30d',
        provider_id: 'anthropic',
        model: 'claude',
        preset: 'prod',
        review_reason: 'reply_too_short',
        suggested_action: 'review_prompt_constraints',
        only_priced: false,
        include_estimated: true,
    };
    syncCostFilters(page);

    assert.equal(selectors['#cost-period'].value, '30d');
    assert.equal(selectors['#cost-provider'].value, 'anthropic');
    assert.equal(selectors['#cost-model'].value, 'claude');
    assert.equal(selectors['#cost-preset'].value, 'prod');
    assert.equal(selectors['#cost-review-reason'].value, 'reply_too_short');
    assert.equal(selectors['#cost-suggested-action'].value, 'review_prompt_constraints');
    assert.equal(selectors['#cost-only-priced'].checked, false);
    assert.equal(selectors['#cost-include-estimated'].checked, true);
}));

test('cost data helper renders review_reason filter options', async () => withDom(async ({ document }) => {
    const selectors = {
        '#cost-period': document.createElement('select'),
        '#cost-provider': document.createElement('select'),
        '#cost-model': document.createElement('select'),
        '#cost-preset': document.createElement('select'),
        '#cost-review-reason': document.createElement('select'),
        '#cost-suggested-action': document.createElement('select'),
        '#cost-only-priced': document.createElement('input'),
        '#cost-include-estimated': document.createElement('input'),
        '#cost-overview': document.createElement('div'),
        '#cost-models': document.createElement('div'),
        '#cost-review-list': document.createElement('div'),
        '#cost-sessions': document.createElement('div'),
    };
    selectors['#cost-period'].value = '7d';
    selectors['#cost-provider'].value = 'openai';
    selectors['#cost-model'].value = 'gpt-4.1';
    selectors['#cost-preset'].value = 'default';
    selectors['#cost-review-reason'].value = 'retrieval_weak';
    selectors['#cost-suggested-action'].value = 'tune_retrieval_threshold';
    selectors['#cost-only-priced'].checked = true;
    selectors['#cost-include-estimated'].checked = false;

    const page = createCostsPage({
        bot: { connected: true },
    }, selectors);

    await refreshCosts(page, {
        apiService: {
            getCostSummary: async (params) => {
                assert.deepEqual(params, {
                    period: '7d',
                    provider_id: 'openai',
                    model: 'gpt-4.1',
                    preset: 'default',
                    review_reason: 'retrieval_weak',
                    suggested_action: 'tune_retrieval_threshold',
                    only_priced: true,
                    include_estimated: false,
                });
                return {
                    success: true,
                    overview: {
                        currency_groups: [{ currency: 'USD', total_cost: 0.12 }],
                        total_tokens: 300,
                        priced_reply_count: 2,
                        unpriced_reply_count: 0,
                        helpful_count: 1,
                        unhelpful_count: 1,
                        feedback_coverage: 100,
                    },
                    models: [{
                        model: 'gpt-4.1',
                        provider_id: 'openai',
                        prompt_tokens: 100,
                        completion_tokens: 200,
                        total_tokens: 300,
                        currency_groups: [{ currency: 'USD', total_cost: 0.12 }],
                    }],
                    options: {
                        providers: ['openai'],
                        models: ['gpt-4.1'],
                        presets: ['default'],
                        review_reasons: ['retrieval_weak'],
                        suggested_actions: ['tune_retrieval_threshold'],
                    },
                    review_playbook: {
                        total_items: 1,
                        top_action: 'tune_retrieval_threshold',
                        actions: [{
                            action: 'tune_retrieval_threshold',
                            count: 1,
                            review_reasons: ['retrieval_weak'],
                            guidance: {
                                summary: 'check retrieval threshold first',
                            },
                        }],
                    },
                    review_queue: [{
                        chat_id: 'wxid_1',
                        display_name: 'Alice',
                        model: 'gpt-4.1',
                        timestamp: 1_700_000_000,
                        provider_id: 'openai',
                        preset: 'default',
                        review_reason: 'retrieval_weak',
                        suggested_action: 'tune_retrieval_threshold',
                        action_guidance: {
                            summary: 'check retrieval threshold first',
                        },
                        reply_preview: 'needs more evidence',
                        user_preview: 'explain the result',
                        retrieval: { augmented: true, runtime_hit_count: 1 },
                        cost: { total_cost: 0.12 },
                        currency: 'USD',
                    }],
                };
            },
            getCostSessions: async () => ({
                success: true,
                sessions: [{
                    chat_id: 'wxid_1',
                    display_name: 'Alice',
                    last_timestamp: 1_700_000_000,
                    reply_count: 1,
                    prompt_tokens: 100,
                    completion_tokens: 200,
                    total_tokens: 300,
                    priced_reply_count: 1,
                    estimated_reply_count: 0,
                    helpful_count: 0,
                    unhelpful_count: 1,
                    currency_groups: [{ currency: 'USD', total_cost: 0.12 }],
                }],
            }),
        },
        onToggleSession: () => {},
    });

    assert.equal(page._sessions.length, 1);
    assert.equal(selectors['#cost-review-reason'].children.length, 2);
    assert.equal(selectors['#cost-suggested-action'].children.length, 2);
    assert.match(selectors['#cost-review-list'].textContent, /调整检索阈值或召回数/);
    assert.match(selectors['#cost-review-list'].textContent, /check retrieval threshold first/);
    assert.match(selectors['#cost-review-list'].textContent, /needs more evidence/);
    let clickedAction = '';
    page._applySuggestedActionFilter = (action) => {
        clickedAction = action;
    };
    selectors['#cost-review-list'].querySelector('.cost-reply-metric').click();
    assert.equal(clickedAction, 'tune_retrieval_threshold');
}));

test('cost pricing helper handles offline notice and partial refresh result', async () => {
    const toastRecorder = createToastRecorder();
    const page = createCostsPage({
        bot: { connected: false },
    });

    await refreshPricingCatalog(page, {
        toast: toastRecorder,
    });
    assert.equal(toastRecorder.calls[0].type, 'info');

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

test('cost review export helper passes review_reason filter', async () => withDom(async ({ document }) => {
    const selectors = {
        '#cost-period': document.createElement('select'),
        '#cost-provider': document.createElement('select'),
        '#cost-model': document.createElement('select'),
        '#cost-preset': document.createElement('select'),
        '#cost-review-reason': document.createElement('select'),
        '#cost-suggested-action': document.createElement('select'),
        '#cost-only-priced': document.createElement('input'),
        '#cost-include-estimated': document.createElement('input'),
    };
    selectors['#cost-period'].value = '7d';
    selectors['#cost-provider'].value = 'openai';
    selectors['#cost-model'].value = 'gpt-4.1';
    selectors['#cost-preset'].value = 'default';
    selectors['#cost-review-reason'].value = 'retrieval_weak';
    selectors['#cost-suggested-action'].value = 'tune_retrieval_threshold';
    selectors['#cost-only-priced'].checked = true;
    selectors['#cost-include-estimated'].checked = false;

    const page = createCostsPage({
        bot: { connected: true },
    }, selectors);
    const toastRecorder = createToastRecorder();
    const createdUrls = [];
    const originalBlob = globalThis.Blob;
    const originalUrl = globalThis.URL;
    globalThis.Blob = class FakeBlob {
        constructor(parts, options = {}) {
            this.parts = parts;
            this.type = options.type;
        }
    };
    globalThis.URL = {
        createObjectURL(blob) {
            createdUrls.push(blob);
            return 'blob:cost-review';
        },
        revokeObjectURL() {},
    };

    try {
        await exportCostReviewQueue(page, {
            toast: toastRecorder,
            apiService: {
                exportCostReviewQueue: async (params) => {
                    assert.deepEqual(params, {
                        period: '7d',
                        provider_id: 'openai',
                        model: 'gpt-4.1',
                        preset: 'default',
                        review_reason: 'retrieval_weak',
                        suggested_action: 'tune_retrieval_threshold',
                        only_priced: true,
                        include_estimated: false,
                    });
                    return {
                        success: true,
                        total: 1,
                        items: [{
                            id: 1,
                            review_reason: 'retrieval_weak',
                            suggested_action: 'tune_retrieval_threshold',
                            reply_text: 'needs review',
                        }],
                    };
                },
            },
        });
    } finally {
        globalThis.Blob = originalBlob;
        globalThis.URL = originalUrl;
    }

    assert.equal(createdUrls.length, 1);
    assert.equal(toastRecorder.calls.at(-1).type, 'success');
    assert.match(toastRecorder.calls.at(-1).message, /reason retrieval_weak/);
}));

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
        preset: '',
        review_reason: '',
        suggested_action: '',
        only_priced: false,
        include_estimated: true,
    };

    renderCostSessions(page, [{
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
    }], () => {});

    const item = selectors['#cost-sessions'].children[0];
    const detail = item.querySelector('.cost-session-detail');
    const trigger = item.querySelector('.cost-session-trigger');

    let detailRequestCount = 0;
    await toggleCostSession(page, 'wxid_1', item, {
        apiService: {
            getCostSessionDetails: async (_chatId, params) => {
                detailRequestCount += 1;
                assert.equal(params.review_reason, '');
                assert.equal(params.suggested_action, '');
                return {
                    success: true,
                    records: [{
                        model: 'gpt-4.1',
                        timestamp: 1_700_000_000,
                        tokens: { user: 10, reply: 20, total: 30 },
                        pricing_available: true,
                        currency: 'USD',
                        cost: { total_cost: 0.2, input_cost: 0.08, output_cost: 0.12 },
                        provider_id: 'openai',
                        preset: 'default',
                        review_reason: 'retrieval_weak',
                        suggested_action: 'tune_retrieval_threshold',
                        reply_quality: { feedback: 'unhelpful' },
                        retrieval: { augmented: true, runtime_hit_count: 2 },
                        user_preview: 'needs context',
                        reply_preview: 'ok',
                    }],
                };
            },
        },
        toast: createToastRecorder(),
    });

    assert.equal(detail.hidden, false);
    assert.equal(detailRequestCount, 1);
    assert.match(detail.textContent, /gpt-4\.1/);
    assert.match(detail.textContent, /needs context/);

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

test('cost page shell binds review_reason refresh flow', async () => {
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
        exportCostReviewQueue: async () => {
            calls.push('export');
        },
        refreshPricingCatalog: async () => {
            calls.push('pricing');
        },
    });

    assert.equal(page.bindings.length, 12);
    assert.equal(page.watchers.length, 1);

    await page.bindings[0].handler();
    await page.bindings[1].handler();
    await page.bindings[2].handler();
    await page.bindings[3].handler();
    await page.bindings[9].handler();
    await page.watchers[0].handler(true);

    assert.deepEqual(calls, ['refresh', 'pricing', 'export', 'refresh', 'refresh', 'refresh']);
});
