import test from 'node:test';
import assert from 'node:assert/strict';

import { renderModelsPageShell } from '../../src/renderer/js/app-shell/pages/models.js';
import ModelsPage, { summarizeCards } from '../../src/renderer/js/pages/ModelsPage.js';
import { apiService } from '../../src/renderer/js/services/ApiService.js';
import { toast } from '../../src/renderer/js/services/NotificationService.js';

test('models page shell frames the beginner path before provider details load', () => {
    const markup = renderModelsPageShell();

    assert.match(markup, /按推荐路径接通认证、测试连接，再切换当前回复模型。/);
});

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
                    profile_id: ['openai', 'api_key', 'default'].join(':'),
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

test('models page renders the recommended beginner auth path before advanced auth choices', () => {
    const page = new ModelsPage();
    const card = {
        provider: {
            id: 'openai',
            label: 'OpenAI / Codex / ChatGPT',
            default_model: 'gpt-5.4-mini',
            auth_methods: [
                {
                    id: 'api_key',
                    type: 'api_key',
                    label: 'API Key',
                    description: '直接使用 OpenAI Platform API Key。',
                },
                {
                    id: 'codex_local',
                    type: 'local_import',
                    label: 'Codex / ChatGPT 本机登录',
                    description: '同步本机的 Codex / ChatGPT 登录态，并持续跟随它。',
                },
            ],
            default_auth_order: ['codex_local', 'api_key'],
        },
        state: 'available_to_import',
        auth_states: [
            {
                method_id: 'api_key',
                status: 'not_configured',
                actions: [{ id: 'show_api_key_form' }],
                detail: '填入 API Key 后即可使用。',
                metadata: {},
            },
            {
                method_id: 'codex_local',
                status: 'available_to_import',
                actions: [{ id: 'bind_local_auth' }, { id: 'start_browser_auth' }],
                detail: '检测到本机登录，可直接同步。',
                metadata: {},
            },
        ],
        metadata: {
            is_active_provider: false,
            can_set_active_provider: false,
            active_provider_reason: '请先配置一组支持运行时调用的认证，再把这家服务方设为当前回复模型。',
            default_model: 'gpt-5.4-mini',
            provider_sync: { code: 'available_to_import', source_message: '检测到本机登录' },
            provider_health: { code: 'idle', message: '' },
        },
    };

    const groups = page.getAuthGroupsForDisplay(card, card.provider);
    const detailMarkup = page.renderProviderDetail(card);

    assert.equal(groups[0].method_id, 'codex_local');
    assert.match(detailMarkup, /推荐默认：Codex \/ ChatGPT 本机登录/);
    assert.match(detailMarkup, /推荐默认/);
    assert.match(detailMarkup, /推荐已有本机登录的用户；默认跟随本机凭据刷新。/);
    assert.match(detailMarkup, /连接通过后再设为当前回复模型/);
});

test('models page explains activation impact before switching providers', () => {
    const page = new ModelsPage();
    const detailMarkup = page.renderProviderDetail({
        provider: {
            id: 'qwen',
            label: 'Qwen',
            default_model: 'qwen3-coder-plus',
            auth_methods: [{ id: 'api_key', type: 'api_key', label: 'API Key' }],
            default_auth_order: ['api_key'],
        },
        state: 'connected',
        selected_label: 'Work API Key',
        auth_states: [
            {
                method_id: 'api_key',
                status: 'connected',
                default_selected: true,
                actions: [{ id: 'test_profile' }],
                metadata: {
                    profile_id: ['qwen', 'api_key', 'default'].join(':'),
                    runtime_ready: true,
                    model: 'qwen3-coder-plus',
                },
            },
        ],
        metadata: {
            is_active_provider: false,
            can_set_active_provider: true,
            default_model: 'qwen3-coder-plus',
            provider_sync: { code: 'unsupported' },
            provider_health: { code: 'healthy', message: '连接正常' },
        },
    });

    assert.match(detailMarkup, /下一步：切换为当前回复模型/);
    assert.match(detailMarkup, /切换后，后续自动回复会使用这家服务方的默认模型和默认认证。/);
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

test('models page reports profile connection test failures from model auth overview health', async () => {
    const originalRunModelAuthAction = apiService.runModelAuthAction;
    const originalToastSuccess = toast.success;
    const originalToastError = toast.error;
    const calls = [];

    apiService.runModelAuthAction = async () => ({
        message: '连接检查已完成。',
        overview: {
            active_provider_id: 'openai',
            cards: [
                {
                    provider: { id: 'openai', label: 'OpenAI' },
                    state: 'connected',
                    auth_states: [
                        {
                            method_id: 'api_key',
                            status: 'connected',
                            actions: [{ id: 'test_profile' }],
                            metadata: {
                                profile_id: ['openai', 'api_key', 'default'].join(':'),
                                runtime_ready: true,
                            },
                        },
                    ],
                    metadata: {
                        is_active_provider: true,
                        can_set_active_provider: true,
                        provider_health: {
                            code: 'warning',
                            message: '401 invalid API key',
                        },
                    },
                },
            ],
        },
    });
    toast.success = (message) => {
        calls.push(`success:${message}`);
    };
    toast.error = (message) => {
        calls.push(`error:${message}`);
    };

    try {
        const page = new ModelsPage();
        page._isActive = true;
        page.applyOverview({
            active_provider_id: 'openai',
            cards: [
                {
                    provider: { id: 'openai', label: 'OpenAI' },
                    auth_states: [
                        {
                            method_id: 'api_key',
                            status: 'connected',
                            actions: [{ id: 'test_profile' }],
                            metadata: {
                                profile_id: ['openai', 'api_key', 'default'].join(':'),
                                runtime_ready: true,
                            },
                        },
                    ],
                    metadata: {
                        is_active_provider: true,
                        can_set_active_provider: true,
                        provider_health: { code: 'not_checked', message: '' },
                    },
                },
            ],
        });
        page.render = () => {
            calls.push('render');
        };
        page.renderFeedback = (message, type = 'success') => {
            calls.push(`feedback:${type}:${message}`);
        };

        await page.handleButtonAction({
            dataset: {
                modelAuthUi: 'test_current_connection',
                providerId: 'openai',
            },
        });
    } finally {
        apiService.runModelAuthAction = originalRunModelAuthAction;
        toast.success = originalToastSuccess;
        toast.error = originalToastError;
    }

    assert.deepEqual(calls, [
        'render',
        'feedback:error:连接检查未通过：401 invalid API key。请检查默认认证、模型和接口地址后重试。',
        'error:连接检查未通过：401 invalid API key。请检查默认认证、模型和接口地址后重试。',
    ]);
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
