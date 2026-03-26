import test from 'node:test';
import assert from 'node:assert/strict';

import {
    buildMessageDetail,
    renderMessageSummary,
} from '../../src/renderer/js/pages/messages/renderers.js';
import {
    formatCostGroups,
    formatCurrencyValue,
} from '../../src/renderer/js/pages/costs/formatters.js';
import {
    renderCostSessionDetails,
    renderCostSessions,
    renderCostReviewQueue,
} from '../../src/renderer/js/pages/costs/renderers.js';
import {
    formatLogDisplayLine,
    parseLogEntry,
} from '../../src/renderer/js/pages/logs/formatters.js';
import {
    renderLogList,
    updateLogMeta,
} from '../../src/renderer/js/pages/logs/renderers.js';
import {
    buildDisconnectedStatus,
    buildUpdateBadgeState,
    buildVersionText,
    getConnectionStatusView,
    normalizeRuntimeIdleState,
    renderUpdateModalContent,
} from '../../src/renderer/js/app/ui-helpers.js';
import {
    buildUnavailableReadinessReport,
    getReadinessBlockingChecks,
    normalizeReadinessReport,
    shouldCompleteFirstRun,
    shouldShowFirstRunGuide,
} from '../../src/renderer/js/app/readiness-helpers.js';
import {
    getRecoveryButtonModel,
    pickSuggestedSelfHealAction,
} from '../../src/renderer/js/app/self-heal.js';
import { App } from '../../src/renderer/js/app.module.js';
import { stateManager } from '../../src/renderer/js/core/StateManager.js';
import { apiService } from '../../src/renderer/js/services/ApiService.js';
import {
    renderPresetList,
    renderSaveFeedback,
    renderSettingsHero,
    renderUpdatePanel,
} from '../../src/renderer/js/pages/settings/renderers.js';
import { AboutPage } from '../../src/renderer/js/pages/AboutPage.js';
import { installDomStub } from './dom-stub.mjs';

function withDom(run) {
    const env = installDomStub();
    try {
        run(env);
    } finally {
        env.restore();
    }
}

function resetReadinessState() {
    stateManager.batchUpdate({
        'readiness.report': null,
        'readiness.loading': false,
        'readiness.error': '',
        'readiness.lastCheckedAt': 0,
        'readiness.firstRunPending': false,
        'readiness.firstRunGuideDismissed': false,
        'currentPage': 'dashboard',
    });
}

test('message renderer keeps summary and detail rendering stable', () => withDom(({ document, createPage }) => {
    const selectors = {
        '#message-filter-summary': document.createElement('div'),
        '#message-total-count': document.createElement('div'),
    };
    const page = createPage(selectors);

    renderMessageSummary(page, {
        selectedChatId: 'wxid_123',
        searchKeyword: 'hello',
        messageCount: 2,
        total: 5,
    });

    assert.match(selectors['#message-filter-summary'].textContent, /wxid_123/);
    assert.match(selectors['#message-filter-summary'].textContent, /hello/);
    assert.equal(selectors['#message-total-count'].textContent, '2/5 条');

    const detail = buildMessageDetail({
        sender: 'Alice',
        wx_id: 'wxid_123',
        timestamp: 1_700_000_000,
        is_self: false,
        msg_type: 'text',
        content: 'hello world',
    });
    assert.equal(detail.className, 'detail-group');
    assert.match(detail.textContent, /Alice/);
    assert.match(detail.textContent, /hello world/);
}));

test('cost helpers render sessions and details consistently', () => withDom(({ document, createPage }) => {
    assert.equal(formatCurrencyValue('CNY', 1.23), '¥1.2300');
    assert.equal(
        formatCostGroups([
            { currency: 'CNY', total_cost: 1.23 },
            { currency: 'USD', total_cost: 0.5 },
        ]),
        '¥1.2300 / $0.500000'
    );

    const selectors = {
        '#cost-sessions': document.createElement('div'),
    };
    const page = createPage(selectors);

    renderCostSessions(page, [
        {
            chat_id: 'wxid_123',
            display_name: 'Alice',
            last_timestamp: 1_700_000_000,
            reply_count: 3,
            prompt_tokens: 100,
            completion_tokens: 50,
            total_tokens: 150,
            priced_reply_count: 2,
            estimated_reply_count: 1,
            helpful_count: 1,
            unhelpful_count: 1,
            currency_groups: [{ currency: 'CNY', total_cost: 1.2 }],
        },
    ], () => {});

    assert.equal(selectors['#cost-sessions'].children.length, 1);
    assert.match(selectors['#cost-sessions'].children[0].textContent, /Alice/);
    assert.match(selectors['#cost-sessions'].children[0].textContent, /没帮助/);

    const detail = document.createElement('div');
    renderCostSessionDetails(detail, [
        {
            model: 'gpt-4.1',
            timestamp: 1_700_000_000,
            tokens: { user: 10, reply: 20, total: 30 },
            pricing_available: true,
            currency: 'USD',
            cost: { total_cost: 0.2, input_cost: 0.08, output_cost: 0.12 },
            provider_id: 'openai',
            preset: 'default',
            reply_quality: { feedback: 'unhelpful' },
            retrieval: { augmented: true, runtime_hit_count: 2 },
            user_preview: '上一条用户消息',
            reply_preview: 'ok',
        },
    ]);

    assert.equal(detail.children.length, 1);
    assert.match(detail.textContent, /gpt-4\.1/);
    assert.match(detail.textContent, /openai/);
    assert.match(detail.textContent, /上一条用户消息/);
    assert.match(detail.textContent, /没帮助/);

    selectors['#cost-review-list'] = document.createElement('div');
    renderCostReviewQueue(page, [
        {
            chat_id: 'wxid_123',
            display_name: 'Alice',
            model: 'gpt-4.1',
            timestamp: 1_700_000_000,
            provider_id: 'openai',
            preset: 'default',
            reply_preview: '需要复盘的回复',
            user_preview: '用户原始问题',
            retrieval: { augmented: true, runtime_hit_count: 2 },
            cost: { total_cost: 0.2 },
            currency: 'USD',
        },
    ]);
    assert.match(selectors['#cost-review-list'].textContent, /需要复盘的回复/);
    assert.match(selectors['#cost-review-list'].textContent, /用户原始问题/);
}));

test('log helpers summarize structured lines and update renderer meta', () => withDom(({ document, createPage }) => {
    const entry = parseLogEntry('[SEND.SUCCESS] chat=alice | sender=bob | duration_ms=123');
    assert.equal(entry.level, 'send');
    assert.match(entry.summary, /发送成功/);
    assert.match(entry.context, /alice/);
    assert.match(entry.context, /bob/);
    assert.match(formatLogDisplayLine(entry), /发送成功/);

    const selectors = {
        '#log-content': document.createElement('div'),
        '#log-count': document.createElement('div'),
        '#log-visible-count': document.createElement('div'),
        '#log-updated': document.createElement('div'),
    };
    const page = createPage(selectors);
    renderLogList(page, ['line1', 'line2'], ['[AI.REPLY_READY]']);
    updateLogMeta(page, 2, 1);

    assert.equal(selectors['#log-content'].children.length, 1);
    assert.equal(selectors['#log-count'].textContent, '2 行');
    assert.equal(selectors['#log-visible-count'].textContent, '1 匹配');
    assert.notEqual(selectors['#log-updated'].textContent, '--');
}));

test('app ui helpers keep updater and connection states deterministic', () => withDom(({ document }) => {
    const idleState = normalizeRuntimeIdleState({ state: 'countdown', remainingMs: 1000 }, 5_000);
    assert.equal(idleState.state, 'countdown');
    assert.equal(idleState.delayMs, 5_000);
    assert.equal(idleState.remainingMs, 1_000);
    assert.equal(idleState.reason, '');
    assert.equal(typeof idleState.updatedAt, 'number');

    assert.equal(
        buildVersionText({
            currentVersion: '1.0.0',
            checking: false,
            available: true,
            latestVersion: '1.1.0',
            enabled: true,
            downloading: false,
            downloadProgress: 0,
            readyToInstall: false,
        }),
        'v1.0.0 · 可更新到 v1.1.0'
    );

    assert.deepEqual(
        buildUpdateBadgeState({
            readyToInstall: false,
            downloading: true,
            downloadProgress: 42,
            available: true,
            latestVersion: '1.1.0',
            checking: false,
        }),
        {
            hidden: false,
            text: '下载 42%',
            disabled: true,
        }
    );

    const disconnected = buildDisconnectedStatus(
        { startup: { stage: 'booting' } },
        { state: 'stopped_by_idle' },
        1_700_000_000_000
    );
    assert.equal(disconnected.running, false);
    assert.equal(disconnected.startup.message, '后端已休眠');

    const view = getConnectionStatusView({
        connected: false,
        running: false,
        paused: false,
        status: {},
        idleState: { state: 'stopped_by_idle' },
        canWake: true,
    });
    assert.equal(view.labelText, '后端已休眠');
    assert.equal(view.dotClass, 'status-dot sleeping');

    const statusText = document.createElement('div');
    const meta = document.createElement('div');
    const notes = document.createElement('ul');
    const progress = document.createElement('div');
    const progressFill = document.createElement('div');
    const progressText = document.createElement('div');
    const btnSkip = document.createElement('button');
    const btnAction = document.createElement('button');

    renderUpdateModalContent({
        currentVersion: '1.0.0',
        latestVersion: '1.1.0',
        releaseDate: '2025-01-01T00:00:00Z',
        lastCheckedAt: '2025-01-02T00:00:00Z',
        error: '',
        readyToInstall: false,
        downloading: true,
        downloadProgress: 60,
        available: true,
        notes: ['fix bug'],
    }, {
        statusText,
        meta,
        notes,
        progress,
        progressFill,
        progressText,
        btnSkip,
        btnAction,
    });

    assert.match(statusText.textContent, /1\.1\.0/);
    assert.match(meta.textContent, /1\.0\.0/);
    assert.equal(notes.children.length, 1);
    assert.equal(progress.hidden, false);
    assert.equal(progressFill.style.width, '60%');
    assert.equal(btnAction.disabled, true);
}));

test('settings render helpers keep hero, preset list and feedback rendering stable', () => withDom(({ document }) => {
    const selectors = {
        '#current-config-hero': document.createElement('div'),
        '#preset-list': document.createElement('div'),
        '#config-save-feedback': document.createElement('div'),
        '#config-save-feedback-summary': document.createElement('div'),
        '#config-save-feedback-meta': document.createElement('div'),
        '#config-save-feedback-groups': document.createElement('div'),
        '#update-status-text': document.createElement('div'),
        '#update-status-meta': document.createElement('div'),
        '#btn-check-updates': document.createElement('button'),
        '#btn-open-update-download': document.createElement('button'),
        '#export-rag-status': document.createElement('div'),
    };
    const page = {
        _config: {
            bot: {
                rag_enabled: true,
                export_rag_enabled: true,
            },
            agent: {
                langsmith_api_key_configured: true,
            },
        },
        _configAudit: {
            version: 3,
            loaded_at: 1_700_000_000,
            audit: {
                unknown_override_paths: ['bot.a'],
                dormant_paths: ['bot.b'],
            },
        },
        _auditStatus: 'ready',
        _presetDrafts: [{
            name: 'default',
            provider_id: 'ollama',
            alias: 'Main',
            model: 'llama3',
            api_key_required: false,
        }],
        _providersById: new Map([
            ['ollama', { id: 'ollama', label: 'Ollama' }],
        ]),
        _activePreset: 'default',
        _heroTestFeedback: {
            presetName: 'default',
            state: 'success',
            message: 'ok',
        },
        $(selector) {
            return selectors[selector] || null;
        },
        getState(path) {
            const mapping = {
                'bot.connected': true,
                'bot.status.runtime_preset': 'default',
                'bot.status.model': 'llama3',
                'updater.enabled': true,
                'updater.checking': false,
                'updater.available': true,
                'updater.currentVersion': '1.0.0',
                'updater.latestVersion': '1.1.0',
                'updater.lastCheckedAt': 1_700_000_000,
                'updater.releaseDate': 1_700_000_000,
                'updater.error': '',
                'updater.skippedVersion': '',
                'updater.downloading': false,
                'updater.downloadProgress': 0,
                'updater.readyToInstall': false,
            };
            return mapping[path];
        },
        _testPresetByName() {},
        _testPreset() {},
        _openPresetModal() {},
        _removePreset() {},
        _renderPresetList() {},
        _renderHero() {},
        _scheduleAutoSave() {},
    };

    renderSettingsHero(page, true);
    renderPresetList(page);
    renderUpdatePanel(page);
    renderSaveFeedback(page, {
        success: true,
        changed_paths: ['bot.reply_mode'],
        runtime_apply: { message: 'applied' },
        default_config_sync_message: 'synced',
        reload_plan: [{
            component: 'bot',
            mode: 'hot_reload',
            note: 'ok',
            paths: ['bot.reply_mode'],
        }],
    }, 'failed');

    assert.equal(selectors['#current-config-hero'].children.length, 1);
    assert.match(selectors['#current-config-hero'].textContent, /回复模型与认证方式统一在“模型”页维护/);
    assert.match(selectors['#current-config-hero'].textContent, /运行审计与诊断/);
    assert.equal(selectors['#preset-list'].children.length, 1);
    assert.match(selectors['#preset-list'].textContent, /Ollama/);
    assert.match(selectors['#update-status-text'].textContent, /1\.1\.0/);
    assert.equal(selectors['#config-save-feedback'].hidden, false);
    assert.equal(selectors['#config-save-feedback-groups'].children.length, 1);
}));

test('readiness helpers normalize reports and gate first-run guide visibility', () => {
    const report = normalizeReadinessReport({
        success: true,
        ready: false,
        blocking_count: 2,
        checks: [
            {
                key: 'admin_permission',
                label: '管理员权限',
                status: 'failed',
                blocking: true,
                message: '未以管理员身份运行',
                action: 'restart_as_admin',
                action_label: '重新检查',
            },
            {
                key: 'api_config',
                label: 'API 配置',
                status: 'failed',
                blocking: true,
                message: '暂无可用预设',
                action: 'open_settings',
                action_label: '前往设置',
            },
        ],
        summary: {
            title: '还有 2 项准备未完成',
            detail: '请先处理阻塞项。',
        },
    });

    assert.equal(report.blockingCount, 2);
    assert.equal(getReadinessBlockingChecks(report, { onlyFirstRun: true }).length, 2);
    assert.equal(report.checks[0].action, 'restart_as_admin');
    assert.equal(report.checks[0].actionLabel, '以管理员身份重启');
    assert.deepEqual(pickSuggestedSelfHealAction(report), {
        action: 'restart_as_admin',
        label: '以管理员身份重启',
        sourceCheck: 'admin_permission',
    });
    assert.deepEqual(getRecoveryButtonModel({ readinessReport: report, diagnostics: null }), {
        mode: 'readiness',
        action: 'restart_as_admin',
        label: '以管理员身份重启',
    });
    assert.equal(
        shouldShowFirstRunGuide({
            firstRunPending: true,
            dismissed: false,
            report,
        }),
        true
    );
    assert.equal(
        shouldCompleteFirstRun({
            firstRunPending: true,
            report: { ready: true, blocking_count: 0, checks: [] },
        }),
        true
    );

    const unavailable = buildUnavailableReadinessReport('backend offline');
    assert.equal(unavailable.ready, false);
    assert.equal(unavailable.checks[0].action, 'retry');
});

test('app readiness flow auto-shows first-run guide and completes only after pass', async () => {
    const previousWindow = globalThis.window;
    const originalGetReadiness = apiService.getReadiness;

    const env = installDomStub();
    try {
        const { document, registerElement } = env;
        document.addEventListener = () => {};

        const modal = registerElement('first-run-modal', document.createElement('div'));
        const title = registerElement('first-run-title', document.createElement('div'));
        const subtitle = registerElement('first-run-subtitle', document.createElement('div'));
        const summary = registerElement('first-run-summary', document.createElement('div'));
        const list = registerElement('first-run-check-list', document.createElement('ul'));
        const settingsButton = registerElement('btn-first-run-settings', document.createElement('button'));
        registerElement('btn-close-first-run-modal', document.createElement('button'));
        registerElement('btn-first-run-later', document.createElement('button'));
        registerElement('btn-first-run-retry', document.createElement('button'));

        let setFirstRunCompleteCalls = 0;
        const switchPageCalls = [];
        globalThis.window = {
            addEventListener() {},
            electronAPI: {
                async setFirstRunComplete() {
                    setFirstRunCompleteCalls += 1;
                    return true;
                },
            },
        };

        resetReadinessState();
        stateManager.batchUpdate({
            'readiness.firstRunPending': true,
            'readiness.firstRunGuideDismissed': false,
        });

        const app = Object.create(App.prototype);
        app._readinessRefreshing = false;
        app._lastReadinessRefreshAt = 0;
        app._readinessMinIntervalMs = 0;
        app._switchPage = async (pageName, options = {}) => {
            switchPageCalls.push({ pageName, options });
        };
        app._refreshStatus = async () => {};

        const blockedReport = {
            success: true,
            ready: false,
            blocking_count: 1,
            checked_at: 100,
            summary: {
                title: '还差 1 项准备',
                detail: '请先补齐阻塞项。',
            },
            checks: [
                {
                    key: 'api_config',
                    label: 'API 配置',
                    status: 'failed',
                    blocking: true,
                    message: '未检测到可用 API 预设',
                    hint: '请前往设置页补齐至少一个可用预设。',
                    action: 'open_settings',
                    action_label: '前往设置',
                },
            ],
            suggested_actions: [
                {
                    action: 'open_settings',
                    label: '前往设置',
                    source_check: 'api_config',
                },
            ],
        };
        const readyReport = {
            success: true,
            ready: true,
            blocking_count: 0,
            checked_at: 101,
            summary: {
                title: '运行准备已完成',
                detail: '所有核心检查均已通过。',
            },
            checks: [
                {
                    key: 'api_config',
                    label: 'API 配置',
                    status: 'passed',
                    blocking: false,
                    message: '检测到 1 个可用预设',
                    action: 'open_settings',
                    action_label: '前往设置',
                },
            ],
            suggested_actions: [
                {
                    action: 'retry',
                    label: '重新检查',
                    source_check: '',
                },
            ],
        };

        const queue = [blockedReport, readyReport];
        apiService.getReadiness = async () => queue.shift();

        await app._refreshReadiness({ force: true });

        assert.equal(stateManager.get('readiness.firstRunPending'), true);
        assert.equal(setFirstRunCompleteCalls, 0);
        assert.equal(modal.classList.contains('active'), true);
        assert.equal(list.children.length, 1);
        assert.equal(settingsButton.hidden, false);
        assert.match(title.textContent, /还差 1 项准备/);
        assert.match(subtitle.textContent, /请先补齐阻塞项/);
        assert.match(summary.textContent, /开箱即用/);

        await app._handleReadinessAction('open_settings');

        assert.deepEqual(switchPageCalls, [
            {
                pageName: 'settings',
                options: { source: 'readiness' },
            },
        ]);
        assert.equal(stateManager.get('readiness.firstRunGuideDismissed'), true);

        stateManager.set('readiness.firstRunGuideDismissed', false);
        await app._refreshReadiness({ force: true });

        assert.equal(setFirstRunCompleteCalls, 1);
        assert.equal(stateManager.get('readiness.firstRunPending'), false);
        assert.equal(modal.classList.contains('active'), false);
    } finally {
        apiService.getReadiness = originalGetReadiness;
        resetReadinessState();
        env.restore();
        if (previousWindow === undefined) {
            delete globalThis.window;
        } else {
            globalThis.window = previousWindow;
        }
    }
});

test('app readiness action restart_as_admin delegates to electron api', async () => {
    const previousWindow = globalThis.window;
    const env = installDomStub();
    try {
        const { document, registerElement } = env;
        registerElement('first-run-modal', document.createElement('div'));

        let restartCalls = 0;
        globalThis.window = {
            electronAPI: {
                async restartAppAsAdmin() {
                    restartCalls += 1;
                    return {
                        success: true,
                        message: '正在以管理员身份重新启动应用...',
                    };
                },
            },
        };

        resetReadinessState();
        stateManager.batchUpdate({
            'readiness.firstRunPending': true,
            'readiness.firstRunGuideDismissed': false,
        });

        const app = Object.create(App.prototype);
        app._refreshStatus = async () => {};
        app._switchPage = async () => {};

        await app._handleReadinessAction('restart_as_admin');

        assert.equal(restartCalls, 1);
        assert.equal(stateManager.get('readiness.firstRunGuideDismissed'), true);
    } finally {
        resetReadinessState();
        env.restore();
        if (previousWindow === undefined) {
            delete globalThis.window;
        } else {
            globalThis.window = previousWindow;
        }
    }
});

test('about page wires updater state and renders update panel on enter', async () => {
    const page = new AboutPage();
    const bindings = [];
    const watchPaths = [];
    const calls = [];
    const linkCard = { dataset: { url: 'https://example.com', label: '示例链接' } };

    page.$$ = (selector) => selector === '.about-link-card' ? [linkCard] : [];
    page.bindEvent = (target, type, handler) => {
        bindings.push({ target, type, handler });
    };
    page.watchState = (path, handler) => {
        watchPaths.push({ path, handler });
    };
    page._renderUpdatePanel = () => {
        calls.push('render-update');
    };
    page._openLinkCard = async () => {
        calls.push('open-link');
    };

    await page.onInit();
    await page.onEnter();

    assert.equal(bindings.length, 3);
    assert.equal(watchPaths.length, 13);
    assert.deepEqual(watchPaths.map((item) => item.path), [
        'updater.enabled',
        'updater.checking',
        'updater.available',
        'updater.currentVersion',
        'updater.latestVersion',
        'updater.lastCheckedAt',
        'updater.releaseDate',
        'updater.error',
        'updater.skippedVersion',
        'updater.downloading',
        'updater.downloadProgress',
        'updater.readyToInstall',
        'updater.downloadedVersion',
    ]);

    await bindings[0].handler();
    assert.deepEqual(calls, ['render-update', 'open-link']);
});
