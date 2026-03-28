import { createElement, formatDateTime } from './form-codec.js';

function getAuditStatusLabel(page) {
    switch (page._auditStatus) {
    case 'loading':
        return '加载中';
    case 'ready':
        return '已同步';
    case 'error':
        return '暂不可用';
    case 'offline':
        return '服务未连接';
    default:
        return page.getState('bot.connected') ? '待同步' : '服务未连接';
    }
}

function createHeroDetail(label, value) {
    const wrap = createElement('div', 'detail-item');
    wrap.appendChild(createElement('span', 'detail-label', label));
    wrap.appendChild(createElement('span', 'detail-value', value));
    return wrap;
}

function createHeroAuditDisclosure(items = []) {
    const disclosure = createElement('details', 'settings-hero-audit');
    const summary = createElement('summary', 'settings-hero-audit-summary');
    summary.appendChild(createElement('span', 'settings-hero-audit-title', '运行审计与诊断'));
    summary.appendChild(createElement('span', 'settings-hero-audit-hint', '展开查看更多低频信息'));
    disclosure.appendChild(summary);

    const body = createElement('div', 'settings-hero-audit-grid');
    items.forEach((item) => {
        body.appendChild(createHeroDetail(item.label, item.value));
    });
    disclosure.appendChild(body);
    return disclosure;
}

function createModelSummaryCard() {
    const card = createElement('div', 'settings-model-summary');
    const content = createElement('div', 'settings-model-summary-content');

    const label = createElement('span', 'settings-model-summary-label', '当前模型');
    const title = createElement('strong', 'settings-model-summary-title', '加载中...');
    title.id = 'settings-model-summary-title';
    const meta = createElement('div', 'settings-model-summary-meta', '正在同步模型信息');
    meta.id = 'settings-model-summary-meta';

    content.appendChild(label);
    content.appendChild(title);
    content.appendChild(meta);

    const button = createElement('button', 'btn btn-secondary btn-sm', '前往模型页');
    button.id = 'btn-open-models';
    button.type = 'button';
    content.appendChild(button);

    card.appendChild(content);
    return card;
}

export function renderSettingsHero(page, highlight = false) {
    const container = page.$('#current-config-hero');
    if (!container) {
        return;
    }

    const connected = !!page.getState('bot.connected');
    const audit = page._configAudit?.audit || null;
    const runtimeVersion = Number(page.getState('bot.status.config_snapshot.version') || 0);
    const unknownCount = Array.isArray(audit?.unknown_override_paths) ? audit.unknown_override_paths.length : 0;
    const dormantCount = Array.isArray(audit?.dormant_paths) ? audit.dormant_paths.length : 0;
    const summaryHint = page._auditMessage
        || '模型、认证与连接测试已迁移到“模型”页；这里仅保留机器人、提示词、记忆、发送策略、日志与备份配置。';

    container.textContent = '';
    const card = createElement('div', `config-hero-card${highlight ? ' highlight-pulse' : ''}`);
    const content = createElement('div', 'hero-content');
    const title = createElement('div', 'hero-title');
    title.appendChild(createElement('span', 'hero-name', '配置工作台'));
    title.appendChild(createElement(
        'span',
        'hero-live-badge',
        page._hasPendingChanges ? '有未保存改动' : '当前内容已同步',
    ));
    content.appendChild(title);

    content.appendChild(createElement(
        'div',
        'hero-subtitle',
        '这里只管理机器人、提示词、记忆、发送策略、日志与备份。回复模型与认证方式统一在“模型”页维护。',
    ));

    const details = createElement('div', 'hero-details');
    details.appendChild(createHeroDetail('运行能力', connected ? '已连接 Python 服务' : '未连接 Python 服务'));
    details.appendChild(createHeroDetail('配置审计', getAuditStatusLabel(page)));
    details.appendChild(createHeroDetail('运行配置版本', runtimeVersion > 0 ? String(runtimeVersion) : '--'));
    details.appendChild(createHeroDetail('最近审计时间', formatDateTime(page._configAudit?.loaded_at)));
    content.appendChild(details);

    content.appendChild(createHeroAuditDisclosure([
        { label: '审计版本', value: String(page._configAudit?.version || '--') },
        { label: '最后加载', value: formatDateTime(page._configAudit?.loaded_at) },
        { label: '未知覆盖', value: `${unknownCount} 项` },
        { label: '未消费配置', value: `${dormantCount} 项` },
        {
            label: 'LangSmith',
            value: page._config?.agent?.langsmith_api_key_configured ? '已配置 Key' : '未配置 Key',
        },
    ]));

    content.appendChild(createElement('div', 'detail-help', summaryHint));
    content.appendChild(createModelSummaryCard());
    card.appendChild(content);
    container.appendChild(card);
}
