import test from 'node:test';
import assert from 'node:assert/strict';

import ModelsPage, { summarizeCards } from '../../src/renderer/js/pages/ModelsPage.js';
import { apiService } from '../../src/renderer/js/services/ApiService.js';
import { toast } from '../../src/renderer/js/services/NotificationService.js';

test('models page falls back to another testable auth state when the selected one has no runtime profile', () => {
    const page = new ModelsPage();
    page.applyModelCatalog({
        providers: [
            {
                id: 'openai',
                label: 'OpenAI',
                models: ['gpt-5.4'],
                auth_methods: [
                    { id: 'api_key', type: 'api_key', label: 'API Key' },
                    { id: 'oauth', type: 'oauth', label: 'OAuth' },
                ],
            },
        ],
    });

    const card = {
        provider: { id: 'openai', label: 'OpenAI', default_model: 'gpt-5.4' },
        state: 'connected',
        selected_label: '当前认证',
        auth_states: [
            {
                method_id: 'oauth',
                status: 'connected',
                default_selected: true,
                actions: [{ id: 'show_api_key_form' }],
                metadata: {},
            },
            {
                method_id: 'api_key',
                status: 'connected',
                actions: [{ id: 'test_profile' }],
                metadata: {
                    profile_id: 'openai:api_key:default',
                    runtime_ready: true,
                    model: 'gpt-5.4',
                },
            },
        ],
        metadata: {
            is_active_provider: true,
            can_set_active_provider: true,
            default_model: 'gpt-5.4',
            provider_sync: { code: 'following_local_auth', source_message: '本机已同步' },
            provider_health: { code: 'healthy', message: '连接正常' },
        },
    };

    const summaryMarkup = page.renderSummaryBar([card], summarizeCards([card]), card);
    const detailMarkup = page.renderProviderDetail(card);

    assert.match(summaryMarkup, /测试当前连接/);
    assert.match(detailMarkup, /测试连接/);
    assert.match(summaryMarkup, /data-model-auth-ui="test_current_connection"/);
    assert.match(detailMarkup, /data-model-auth-action="test_profile"/);
});

test('models page still renders set-active button when provider is not ready', () => {
    const page = new ModelsPage();
    page.applyModelCatalog({
        providers: [
            {
                id: 'ollama',
                label: 'Ollama',
                models: ['qwen3'],
                auth_methods: [
                    { id: 'api_key', type: 'api_key', label: 'API Key' },
                ],
            },
        ],
    });

    const detailMarkup = page.renderProviderDetail({
        provider: { id: 'ollama', label: 'Ollama', default_model: 'qwen3' },
        state: 'not_configured',
        selected_label: '',
        auth_states: [],
        metadata: {
            is_active_provider: false,
            can_set_active_provider: false,
            active_provider_reason: 'Need auth first',
            default_model: 'qwen3',
            provider_sync: { code: 'not_detected', source_message: '' },
            provider_health: { code: 'idle', message: '' },
        },
    });

    assert.match(detailMarkup, /data-model-auth-action="set_active_provider"/);
    assert.match(detailMarkup, /disabled/);
    assert.match(detailMarkup, /Need auth first/);
});

test('models page localizes legacy english runtime health details', () => {
    const page = new ModelsPage();
    const card = {
        metadata: {
            provider_health: {
                code: 'blocked',
                message: 'A local auth source was detected, but it cannot be projected into runtime requests yet.',
            },
            provider_sync: {
                code: 'following_local_auth',
                source_message: 'Detected local authorization source',
            },
        },
    };

    assert.equal(page.getHealthDetail(card), '已检测到本机认证来源，但暂时还不能直接用于运行时请求。');
    assert.equal(page.getSyncDetail(card), '已检测到本机授权来源。');
});

test('models page keeps the user selected provider when a slow save resolves late', async () => {
    const originalRunModelAuthAction = apiService.runModelAuthAction;
    const originalToastSuccess = toast.success;
    const originalToastError = toast.error;
    let resolveAction = null;

    apiService.runModelAuthAction = async () => (
        new Promise((resolve) => {
            resolveAction = resolve;
        })
    );
    toast.success = () => {};
    toast.error = () => {};

    try {
        const page = new ModelsPage();
        page._isActive = true;
        page.applyOverview({
            active_provider_id: 'openai',
            cards: [
                { provider: { id: 'openai', label: 'OpenAI' } },
                { provider: { id: 'google', label: 'Google' } },
            ],
        });
        page._selectedProviderId = 'openai';
        let renderCount = 0;
        page.render = () => {
            renderCount += 1;
        };
        page.renderFeedback = () => {};

        const pending = page.runAction(
            'update_provider_defaults',
            { provider_id: 'openai' },
            { preserveSelection: true, providerId: 'openai' },
        );

        page._selectedProviderId = 'google';
        resolveAction?.({
            message: 'saved',
            overview: {
                active_provider_id: 'openai',
                cards: [
                    { provider: { id: 'openai', label: 'OpenAI' } },
                    { provider: { id: 'google', label: 'Google' } },
                ],
            },
        });

        await pending;

        assert.equal(page._selectedProviderId, 'google');
        assert.equal(renderCount, 1);
    } finally {
        apiService.runModelAuthAction = originalRunModelAuthAction;
        toast.success = originalToastSuccess;
        toast.error = originalToastError;
    }
});

test('models page schedules a silent refresh while local auth sync is still running', async () => {
    const originalGetModelAuthOverview = apiService.getModelAuthOverview;
    const originalGetModelCatalog = apiService.getModelCatalog;
    const originalSetTimeout = globalThis.setTimeout;
    const originalClearTimeout = globalThis.clearTimeout;
    const scheduled = [];
    const cleared = [];

    apiService.getModelAuthOverview = async () => ({
        overview: {
            active_provider_id: 'openai',
            cards: [
                { provider: { id: 'openai', label: 'OpenAI' } },
            ],
            local_auth_sync: {
                refreshing: true,
                refreshed_at: 0,
                revision: 0,
                changed_provider_ids: [],
                message: '',
            },
        },
    });
    apiService.getModelCatalog = async () => ({
        providers: [
            { id: 'openai', label: 'OpenAI', models: ['gpt-5.4'] },
        ],
    });
    globalThis.setTimeout = (fn, delay) => {
        scheduled.push({ fn, delay });
        return scheduled.length;
    };
    globalThis.clearTimeout = (handle) => {
        cleared.push(handle);
    };

    try {
        const page = new ModelsPage();
        page._isActive = true;
        page.render = () => {};
        page._ensureProviderModels = async () => {};

        await page.loadOverview({ preserveSelection: true });

        assert.equal(scheduled.length, 1);
        assert.equal(scheduled[0].delay, 600);
        assert.equal(page._localAuthSyncRefreshAttempt, 1);

        let refreshOptions = null;
        page.loadOverview = async (options = {}) => {
            refreshOptions = options;
        };

        scheduled[0].fn();
        await Promise.resolve();

        assert.deepEqual(refreshOptions, { preserveSelection: true });
        assert.deepEqual(cleared, []);
    } finally {
        apiService.getModelAuthOverview = originalGetModelAuthOverview;
        apiService.getModelCatalog = originalGetModelCatalog;
        globalThis.setTimeout = originalSetTimeout;
        globalThis.clearTimeout = originalClearTimeout;
    }
});

test('models page clears pending silent refresh when leaving the page', async () => {
    const originalClearTimeout = globalThis.clearTimeout;
    const cleared = [];
    globalThis.clearTimeout = (handle) => {
        cleared.push(handle);
    };

    try {
        const page = new ModelsPage();
        page._isActive = true;
        page._localAuthSyncRefreshTimer = 42;
        page._localAuthSyncRefreshAttempt = 3;

        await page.onLeave();

        assert.deepEqual(cleared, [42]);
        assert.equal(page._localAuthSyncRefreshTimer, null);
        assert.equal(page._localAuthSyncRefreshAttempt, 0);
        assert.equal(page.isActive(), false);
    } finally {
        globalThis.clearTimeout = originalClearTimeout;
    }
});
