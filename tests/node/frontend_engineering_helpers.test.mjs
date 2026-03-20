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
    assert.match(selectors['#current-config-hero'].textContent, /default/);
    assert.equal(selectors['#preset-list'].children.length, 1);
    assert.match(selectors['#preset-list'].textContent, /Ollama/);
    assert.match(selectors['#update-status-text'].textContent, /1\.1\.0/);
    assert.equal(selectors['#config-save-feedback'].hidden, false);
    assert.equal(selectors['#config-save-feedback-groups'].children.length, 1);
}));

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
