import test from 'node:test';
import assert from 'node:assert/strict';

import {
    formatCurrencyGroups,
    formatDurationMs,
    formatStartupMeta,
    getGrowthTaskLabel,
} from '../../src/renderer/js/pages/dashboard/formatters.js';
import {
    renderDashboardCost,
    renderGrowthTasks,
    renderHealthMetrics,
    renderIdlePanel,
    renderReadiness,
    renderRetrieval,
    renderStabilitySummary,
} from '../../src/renderer/js/pages/dashboard/renderers.js';
import { installDomStub } from './dom-stub.mjs';

function withDom(run) {
    const env = installDomStub();
    try {
        run(env);
    } finally {
        env.restore();
    }
}

function createHealthItem(document) {
    const item = document.createElement('div');
    const text = document.createElement('span');
    text.className = 'health-check-text';
    item.appendChild(text);
    return item;
}

test('dashboard formatters expose stable labels and summaries', () => {
    assert.equal(getGrowthTaskLabel('emotion'), '情绪沉淀');
    assert.equal(formatDurationMs(61_000), '1 分 1 秒');
    assert.equal(
        formatCurrencyGroups([
            { currency: 'CNY', total_cost: 1.23 },
            { currency: 'LOCAL', total_cost: 0.5 },
        ]),
        '¥1.2300 / 本地 0.500000'
    );
    assert.match(
        formatStartupMeta({ progress: 42, stage: 'starting', updated_at: 1_700_000_000 }),
        /^42% · 启动中 · 更新于 \d{2}:\d{2}:\d{2}$/
    );
});

test('renderGrowthTasks renders queue, batch info and last error', () => withDom(({ document }) => {
    const queueElement = document.createElement('div');
    const batchElement = document.createElement('div');
    const nextElement = document.createElement('div');
    const errorElement = document.createElement('div');

    renderGrowthTasks(true, {
        paused_growth_task_types: ['emotion'],
        background_backlog_by_task: { emotion: 2 },
        growth_tasks_pending: 0,
        growth_mode: 'deferred_until_batch',
        next_background_batch_at: 1_700_000_000,
        last_growth_error: '连接抖动',
        last_background_batch: {
            completed: 3,
            failed: 1,
            started_at: 1_700_000_000,
            trigger: 'manual',
            reason: 'memory_unavailable',
        },
    }, {
        queueElement,
        batchElement,
        nextElement,
        errorElement,
    });

    assert.equal(queueElement.children.length, 1);
    const row = queueElement.children[0];
    assert.equal(row.className, 'growth-task-row');
    assert.match(row.textContent, /情绪沉淀/);
    assert.match(row.textContent, /已暂停/);
    assert.match(row.textContent, /排队 2/);

    const actions = row.children[1];
    assert.equal(actions.children.length, 3);
    assert.equal(actions.children[0].dataset.growthAction, 'run');
    assert.equal(actions.children[1].dataset.growthAction, 'resume');
    assert.equal(actions.children[1].dataset.taskType, 'emotion');

    assert.match(batchElement.textContent, /最近批次：完成 3/);
    assert.match(batchElement.textContent, /失败 1/);
    assert.match(batchElement.textContent, /手动触发/);
    assert.match(batchElement.textContent, /按批处理执行/);
    assert.match(batchElement.textContent, /记忆库不可用/);
    assert.match(nextElement.textContent, /下次批处理：/);
    assert.equal(errorElement.hidden, false);
    assert.equal(errorElement.textContent, '最近异常：连接抖动');
}));

test('renderIdlePanel and renderHealthMetrics update panel state', () => withDom(({ document, createPage }) => {
    const selectors = {
        '#backend-idle-panel': document.createElement('div'),
        '#backend-idle-title': document.createElement('div'),
        '#backend-idle-detail': document.createElement('div'),
        '#backend-idle-meta': document.createElement('div'),
        '#btn-cancel-idle-shutdown': document.createElement('button'),
        '#btn-wake-backend': document.createElement('button'),
        '#health-cpu': document.createElement('div'),
        '#health-memory': document.createElement('div'),
        '#health-queue': document.createElement('div'),
        '#health-latency': document.createElement('div'),
        '#health-warning': document.createElement('div'),
        '#health-merge-feedback': document.createElement('div'),
        '#health-ai': createHealthItem(document),
        '#health-wechat': createHealthItem(document),
        '#health-db': createHealthItem(document),
    };
    const page = createPage(selectors, {
        bot: {
            connected: true,
            running: false,
            status: {
                growth_running: false,
                startup: { active: false },
            },
        },
    });
    const idleState = {
        state: 'countdown',
        delayMs: 15 * 60 * 1000,
        remainingMs: 125_000,
        updatedAt: Date.now(),
    };

    renderIdlePanel(page, {
        connected: true,
        isRunning: false,
        growthRunning: false,
        startupActive: false,
        idleState,
    }, {
        getIdleState: () => idleState,
        getIdleRemainingMs: (state) => state.remainingMs,
        formatDurationMs,
    });

    assert.equal(selectors['#backend-idle-panel'].hidden, false);
    assert.equal(selectors['#btn-cancel-idle-shutdown'].hidden, false);
    assert.equal(selectors['#btn-wake-backend'].hidden, true);
    assert.match(selectors['#backend-idle-detail'].textContent, /自动休眠/);

    renderHealthMetrics(page, {
        cpu_percent: 12.34,
        process_memory_mb: 256,
        system_memory_percent: 51,
        pending_tasks: 2,
        merge_pending_chats: 1,
        merge_pending_messages: 3,
        ai_latency_ms: 420,
        warning: '负载偏高',
    }, {
        ai: { level: 'healthy', status: 'ok', message: 'AI 正常' },
        wechat: { level: 'warning', status: 'slow', message: '微信延迟' },
        database: { level: 'error', status: 'offline', message: '数据库异常' },
    }, {
        status_text: '消息合并状态：活跃',
        active: true,
    }, {
        attempted: 5,
        success_rate: 80,
        delayed: 1,
        retrieval_augmented: 2,
        empty: 1,
        helpful_count: 2,
        unhelpful_count: 1,
        history_24h: {
            attempted: 12,
            success_rate: 91.7,
            helpful_count: 5,
        },
    });

    assert.equal(selectors['#health-cpu'].textContent, '12.3%');
    assert.equal(selectors['#health-memory'].textContent, '256 MB / 51%');
    assert.equal(selectors['#health-queue'].textContent, '2 个任务 / 1 个会话 / 3 条消息');
    assert.equal(selectors['#health-latency'].textContent, '420 ms');
    assert.equal(selectors['#health-warning'].hidden, false);
    assert.equal(selectors['#health-merge-feedback'].dataset.active, 'true');
    assert.match(selectors['#health-merge-feedback'].textContent, /本次 80\.0%/);
    assert.match(selectors['#health-merge-feedback'].textContent, /近24h 91\.7%/);
    assert.match(selectors['#health-merge-feedback'].textContent, /有帮助 2/);
    assert.match(selectors['#health-merge-feedback'].textContent, /近24h 有帮助 5/);
    assert.match(selectors['#health-merge-feedback'].textContent, /检索增强 2/);
    assert.equal(selectors['#health-ai'].dataset.level, 'healthy');
    assert.equal(
        selectors['#health-ai'].querySelector('.health-check-text')?.textContent,
        'AI 正常'
    );
}));

test('renderRetrieval and renderDashboardCost render structured metrics', () => withDom(({ document, createPage }) => {
    const selectors = {
        '#retrieval-vector': document.createElement('div'),
        '#retrieval-export': document.createElement('div'),
        '#retrieval-topk': document.createElement('div'),
        '#retrieval-threshold': document.createElement('div'),
        '#retrieval-rerank': document.createElement('div'),
        '#retrieval-hits': document.createElement('div'),
        '#retrieval-timings': document.createElement('div'),
        '#retrieval-timings-empty': document.createElement('div'),
        '#stat-today-cost': document.createElement('div'),
        '#dashboard-cost-summary': document.createElement('div'),
        '#dashboard-cost-top-models': document.createElement('div'),
    };
    const page = createPage(selectors);

    renderRetrieval(page, {
        top_k: 8,
        score_threshold: 0.3,
        rerank_backend: 'cross_encoder',
        cross_encoder_configured: false,
        rerank_fallbacks: 2,
        hits: 12,
    }, {
        prepare_total_sec: 0.4,
        stream_sec: 1.2,
    }, {
        enabled: true,
        vector_memory_enabled: true,
        vector_memory_ready: false,
    });

    assert.equal(selectors['#retrieval-vector'].textContent, '初始化中');
    assert.equal(selectors['#retrieval-export'].textContent, '已启用');
    assert.equal(selectors['#retrieval-topk'].textContent, '8');
    assert.equal(selectors['#retrieval-threshold'].textContent, '0.3');
    assert.match(selectors['#retrieval-rerank'].textContent, /未配置/);
    assert.match(selectors['#retrieval-rerank'].textContent, /回退 2/);
    assert.equal(selectors['#retrieval-hits'].textContent, '12');
    assert.equal(selectors['#retrieval-timings-empty'].hidden, true);
    assert.equal(selectors['#retrieval-timings'].children.length, 2);

    renderDashboardCost(page, {
        today: {
            overview: {
                currency_groups: [{ currency: 'CNY', total_cost: 1.23 }],
            },
        },
        recent: {
            overview: {
                currency_groups: [{ currency: 'USD', total_cost: 3.5 }],
                total_tokens: 1234,
                priced_reply_count: 8,
            },
            models: [
                { model: 'gpt-4.1', provider_id: 'openai', total_tokens: 1200, currency_groups: [{ currency: 'USD', total_cost: 2.5 }] },
                { model: 'gpt-4.1-mini', provider_id: 'openai', total_tokens: 600, currency_groups: [{ currency: 'USD', total_cost: 1.0 }] },
            ],
        },
    });

    assert.equal(selectors['#stat-today-cost'].textContent, '¥1.2300');
    assert.equal(selectors['#dashboard-cost-summary'].children.length, 3);
    assert.equal(selectors['#dashboard-cost-top-models'].children.length, 2);
    assert.match(selectors['#dashboard-cost-top-models'].children[0].textContent, /gpt-4\.1/);
    assert.match(selectors['#dashboard-cost-top-models'].children[0].textContent, /1\.2K/);
}));

test('renderStabilitySummary renders pending approvals, backup summary and eval status', () => withDom(({ document, createPage }) => {
    const selectors = {
        '#dashboard-pending-replies': document.createElement('div'),
        '#dashboard-backup-summary': document.createElement('div'),
        '#dashboard-eval-status': document.createElement('div'),
        '#dashboard-restore-summary': document.createElement('div'),
    };
    const page = createPage(selectors);

    renderStabilitySummary(page, {
        pending: 3,
    }, {
        backups: {
            summary: {
                latest_quick_backup_at: 1_700_000_000,
                last_restore_result: {
                    success: true,
                    pre_restore_backup: { id: 'pre-1' },
                },
            },
        },
        latestEval: {
            report: {
                summary: {
                    passed: true,
                    total_cases: 20,
                    empty_reply_rate: 0,
                    retrieval_hit_rate: 0.5,
                },
            },
        },
    });

    assert.equal(selectors['#dashboard-pending-replies'].textContent, '3');
    assert.equal(selectors['#dashboard-backup-summary'].textContent.includes('/'), true);
    assert.equal(selectors['#dashboard-eval-status'].textContent, '已通过');
    assert.equal(selectors['#dashboard-restore-summary'].textContent.includes('最近一次质量检查已通过'), true);
    assert.equal(selectors['#dashboard-restore-summary'].textContent.includes('保险备份 pre-1'), true);
}));

test('renderReadiness renders blocking checks and actions', () => withDom(({ document, createPage }) => {
    const selectors = {
        '#bot-readiness': document.createElement('div'),
        '#bot-readiness-badge': document.createElement('div'),
        '#bot-readiness-title': document.createElement('div'),
        '#bot-readiness-detail': document.createElement('div'),
        '#bot-readiness-list': document.createElement('ul'),
    };
    const page = createPage(selectors);

    renderReadiness(page, {
        success: true,
        ready: false,
        blocking_count: 2,
        checks: [
            {
                key: 'wechat_process',
                label: '微信进程',
                status: 'failed',
                blocking: true,
                message: '未检测到微信客户端',
                hint: '请先打开并登录微信。',
                action: 'open_wechat',
                action_label: '打开微信',
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

    assert.equal(selectors['#bot-readiness'].hidden, false);
    assert.equal(selectors['#bot-readiness'].dataset.state, 'blocked');
    assert.equal(selectors['#bot-readiness-badge'].textContent, '阻塞 2');
    assert.equal(selectors['#bot-readiness-list'].children.length, 2);
    assert.equal(
        selectors['#bot-readiness-list'].children[0].children[1]?.dataset.readinessAction,
        'open_wechat'
    );
}));
