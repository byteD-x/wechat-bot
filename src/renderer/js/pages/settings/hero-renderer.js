import { createElement, formatDateTime } from './form-codec.js';
import {
    createModelKindBadge,
    getActivePresetDraft,
    getEffectivePreset,
    getPresetModelMeta,
    getProviderLabel,
    getRuntimePresetDraft,
} from './preset-meta.js';

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

export function renderSettingsHero(page, highlight = false) {
    const container = page.$('#current-config-hero');
    if (!container || !page._config) {
        return;
    }

    const runtimePresetName = String(page.getState('bot.status.runtime_preset') || '').trim();
    const runtimePreset = getRuntimePresetDraft(page);
    const activePreset = getActivePresetDraft(page);
    const effectivePreset = getEffectivePreset(page);
    const effectivePresetName = effectivePreset?.name || '未设置激活预设';
    const effectiveProviderLabel = effectivePreset ? getProviderLabel(page, effectivePreset.provider_id) : '--';
    const effectiveModel = String(page.getState('bot.status.model') || effectivePreset?.model || '').trim() || '--';
    const effectiveAlias = String(effectivePreset?.alias || '').trim();
    const effectiveModelMeta = getPresetModelMeta(page, effectivePreset, effectiveModel);
    const effectiveScopeLabel = runtimePresetName
        ? '当前运行中'
        : (activePreset ? '当前保存配置' : '等待配置');
    const audit = page._configAudit?.audit || null;
    const auditStatus = getAuditStatusLabel(page);
    const hasAudit = !!audit;
    const unknownCount = hasAudit ? (audit?.unknown_override_paths?.length || 0) : '--';
    const dormantCount = hasAudit ? (audit?.dormant_paths?.length || 0) : '--';
    const configuredPresets = page._presetDrafts.filter((preset) => preset.api_key_configured || preset.api_key_required === false).length;
    const heroTestFeedback = page._heroTestFeedback && page._heroTestFeedback.presetName === effectivePreset?.name
        ? page._heroTestFeedback
        : null;

    container.textContent = '';
    const card = createElement('div', `config-hero-card${highlight ? ' highlight-pulse' : ''}`);
    const content = createElement('div', 'hero-content');
    const title = createElement('div', 'hero-title');
    title.appendChild(createElement('span', 'hero-name', effectivePresetName));
    title.appendChild(createElement('span', 'hero-live-badge', effectiveScopeLabel));
    if (effectiveModelMeta) {
        title.appendChild(createModelKindBadge(effectiveModelMeta, 'is-hero'));
    }
    content.appendChild(title);

    const subtitleParts = [effectiveProviderLabel, effectiveAlias || '未设置别名'].filter(Boolean);
    content.appendChild(createElement('div', 'hero-subtitle', subtitleParts.join(' · ')));

    const modelWrap = createElement('div', 'hero-model-row');
    const modelText = createElement('div', 'hero-model-main');
    modelText.appendChild(createElement('span', 'hero-model-label', '当前生效模型'));
    modelText.appendChild(createElement('span', 'hero-model-value', effectiveModel));
    modelWrap.appendChild(modelText);
    if (effectiveModelMeta) {
        modelWrap.appendChild(createElement('div', 'hero-model-hint', effectiveModelMeta.title || effectiveModelMeta.label));
    }
    content.appendChild(modelWrap);

    const details = createElement('div', 'hero-details');
    details.appendChild(createHeroDetail('当前运行预设', runtimePreset?.name || '--'));
    details.appendChild(createHeroDetail('当前保存预设', activePreset?.name || '--'));
    details.appendChild(createHeroDetail('运行态审计', auditStatus));
    details.appendChild(createHeroDetail('已配置预设', `${configuredPresets}/${page._presetDrafts.length}`));
    details.appendChild(createHeroDetail('审计版本', String(page._configAudit?.version || '--')));
    details.appendChild(createHeroDetail('最后加载', formatDateTime(page._configAudit?.loaded_at)));
    details.appendChild(createHeroDetail('未知覆盖', typeof unknownCount === 'number' ? `${unknownCount} 项` : '--'));
    details.appendChild(createHeroDetail('未消费配置', typeof dormantCount === 'number' ? `${dormantCount} 项` : '--'));
    details.appendChild(createHeroDetail('LangSmith', page._config.agent?.langsmith_api_key_configured ? '已配置 Key' : '未配置 Key'));
    content.appendChild(details);

    const actions = createElement('div', 'hero-actions');
    const button = createElement('button', 'btn btn-secondary', '测试当前连接');
    button.type = 'button';
    button.disabled = !effectivePreset?.name;
    button.addEventListener('click', () => void page._testPresetByName(effectivePreset?.name || ''));
    actions.appendChild(button);

    const hintClassName = heroTestFeedback
        ? `ping-result ${heroTestFeedback.state === 'success' ? 'success' : (heroTestFeedback.state === 'error' ? 'error' : 'pending')}`
        : 'ping-result';
    const hintText = heroTestFeedback?.message
        || (effectivePreset?.name ? '可直接测试当前生效预设的连通性，不会启动机器人。' : '请先配置并激活一个预设。');
    actions.appendChild(createElement('div', hintClassName, hintText));

    card.appendChild(content);
    card.appendChild(actions);
    container.appendChild(card);
}
