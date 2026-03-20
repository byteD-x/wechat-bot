import { createElement, formatDateTime } from './form-codec.js';
import {
    createModelKindBadge,
    getActivePresetDraft,
    getEffectivePreset,
    getPresetModelMeta,
    getProviderLabel,
    getRuntimePresetDraft,
} from './preset-service.js';

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

export function renderPresetList(page) {
    const list = page.$('#preset-list');
    if (!list) {
        return;
    }
    list.textContent = '';

    if (!page._presetDrafts.length) {
        list.appendChild(createElement('div', 'empty-state-text', '暂无预设，点击“新增”创建一个。'));
        return;
    }

    const fragment = document.createDocumentFragment();
    page._presetDrafts.forEach((preset, index) => {
        const provider = page._providersById.get(preset.provider_id) || null;
        const modelMeta = getPresetModelMeta(page, preset);
        const card = createElement('div', `preset-card${preset.name === page._activePreset ? ' active' : ''}`);
        const header = createElement('div', 'preset-card-header');
        const info = createElement('div', 'preset-info');
        const name = createElement('div', 'preset-name');
        name.appendChild(document.createTextNode(preset.name || '未命名预设'));
        if (preset.name === page._activePreset) {
            name.appendChild(createElement('span', 'config-save-feedback-badge live', '当前激活'));
        }
        info.appendChild(name);

        const meta = createElement('div', 'preset-meta');
        meta.appendChild(createElement('span', 'meta-item', provider?.label || preset.provider_id || '--'));
        meta.appendChild(createElement('span', 'meta-separator', '·'));
        meta.appendChild(createElement('span', 'meta-item model-name', preset.model || '--'));
        if (modelMeta) {
            meta.appendChild(createModelKindBadge(modelMeta));
        }
        info.appendChild(meta);

        const detail = createElement('div', 'ping-result', preset.api_key_required === false ? '无需 API Key' : (preset.api_key_configured ? '已配置 API Key' : '未配置 API Key'));
        info.appendChild(detail);
        header.appendChild(info);
        card.appendChild(header);

        const actions = createElement('div', 'preset-card-actions');
        const useButton = createElement('button', 'btn btn-secondary btn-sm', preset.name === page._activePreset ? '已启用' : '设为当前');
        useButton.type = 'button';
        useButton.disabled = preset.name === page._activePreset;
        useButton.addEventListener('click', () => {
            page._activePreset = preset.name;
            page._renderPresetList();
            page._renderHero();
            page._scheduleAutoSave({ immediate: true });
        });

        const testButton = createElement('button', 'btn btn-secondary btn-sm', '测试');
        testButton.type = 'button';
        testButton.addEventListener('click', () => void page._testPreset(index, detail));

        const editButton = createElement('button', 'btn btn-primary btn-sm', '编辑');
        editButton.type = 'button';
        editButton.addEventListener('click', () => page._openPresetModal(index));

        actions.appendChild(useButton);
        actions.appendChild(testButton);
        actions.appendChild(editButton);
        if (page._presetDrafts.length > 1) {
            const deleteButton = createElement('button', 'btn btn-secondary btn-sm', '删除');
            deleteButton.type = 'button';
            deleteButton.addEventListener('click', () => page._removePreset(index));
            actions.appendChild(deleteButton);
        }
        card.appendChild(actions);
        fragment.appendChild(card);
    });

    list.appendChild(fragment);
}

export function renderUpdatePanel(page) {
    const statusText = page.$('#update-status-text');
    const statusMeta = page.$('#update-status-meta');
    const checkButton = page.$('#btn-check-updates');
    const downloadButton = page.$('#btn-open-update-download');
    if (!statusText || !statusMeta || !downloadButton || !checkButton) {
        return;
    }
    const enabled = !!page.getState('updater.enabled');
    const checking = !!page.getState('updater.checking');
    const available = !!page.getState('updater.available');
    const currentVersion = page.getState('updater.currentVersion') || '--';
    const latestVersion = page.getState('updater.latestVersion') || '';
    const lastCheckedAt = page.getState('updater.lastCheckedAt');
    const releaseDate = page.getState('updater.releaseDate');
    const error = page.getState('updater.error');
    const skippedVersion = page.getState('updater.skippedVersion') || '';
    const downloading = !!page.getState('updater.downloading');
    const downloadProgress = Math.min(100, Math.max(0, Number(page.getState('updater.downloadProgress') || 0)));
    const readyToInstall = !!page.getState('updater.readyToInstall');

    checkButton.disabled = checking || downloading;

    if (!enabled) {
        statusText.textContent = '当前环境未启用应用内更新';
        statusMeta.textContent = `当前版本：v${currentVersion}`;
        downloadButton.textContent = '打开发布页';
        downloadButton.style.display = 'inline-flex';
        downloadButton.disabled = false;
    } else if (checking) {
        statusText.textContent = '正在检查更新...';
        statusMeta.textContent = `当前版本：v${currentVersion}`;
        downloadButton.style.display = 'none';
    } else if (downloading) {
        statusText.textContent = `正在下载新版本 v${latestVersion}...`;
        statusMeta.textContent = `当前版本：v${currentVersion} · 下载进度：${downloadProgress}% · 最近检查：${formatDateTime(lastCheckedAt)}`;
        downloadButton.style.display = 'inline-flex';
        downloadButton.textContent = `下载中 ${downloadProgress}%`;
        downloadButton.disabled = true;
    } else if (readyToInstall) {
        statusText.textContent = `更新已下载完成 v${latestVersion || currentVersion}`;
        statusMeta.textContent = `当前版本：v${currentVersion} · 发布日期：${formatDateTime(releaseDate)} · 最近检查：${formatDateTime(lastCheckedAt)}`;
        downloadButton.style.display = 'inline-flex';
        downloadButton.textContent = '立即安装并重启';
        downloadButton.disabled = false;
    } else if (error) {
        statusText.textContent = error;
        statusMeta.textContent = `当前版本：v${currentVersion} · 最近检查：${formatDateTime(lastCheckedAt)}`;
        downloadButton.style.display = available ? 'inline-flex' : 'none';
        downloadButton.textContent = '下载更新';
        downloadButton.disabled = !available;
    } else if (available && latestVersion) {
        statusText.textContent = `发现新版本 v${latestVersion}`;
        statusMeta.textContent = [
            `当前版本：v${currentVersion}`,
            `发布日期：${formatDateTime(releaseDate)}`,
            `最近检查：${formatDateTime(lastCheckedAt)}`,
            skippedVersion === latestVersion ? `已跳过：v${latestVersion}` : '',
        ].filter(Boolean).join(' · ');
        downloadButton.style.display = 'inline-flex';
        downloadButton.textContent = '下载更新';
        downloadButton.disabled = false;
    } else {
        statusText.textContent = '当前已经是最新版本';
        statusMeta.textContent = `当前版本：v${currentVersion} · 最近检查：${formatDateTime(lastCheckedAt)}`;
        downloadButton.style.display = 'none';
    }
}

export function renderSaveFeedback(page, result, saveFailedText) {
    const container = page.$('#config-save-feedback');
    const summary = page.$('#config-save-feedback-summary');
    const meta = page.$('#config-save-feedback-meta');
    const groups = page.$('#config-save-feedback-groups');
    if (!container || !summary || !meta || !groups) {
        return;
    }
    container.hidden = false;
    groups.textContent = '';

    if (result?.save_state === 'saving') {
        container.dataset.state = 'warning';
        summary.textContent = result?.message || '保存中...';
        meta.textContent = '正在将修改写入共享配置文件。';
        return;
    }

    if (!result?.success) {
        container.dataset.state = 'error';
        summary.textContent = result?.message || saveFailedText;
        meta.textContent = '本次保存未写入配置，请先修正问题后重试。';
        return;
    }

    const changedPaths = Array.isArray(result.changed_paths) ? result.changed_paths : [];
    const runtimeApply = result.runtime_apply;
    const reloadPlan = Array.isArray(result.reload_plan) ? result.reload_plan : [];
    const persistenceText = result.default_config_sync_message || '共享配置文件 app_config.json 已更新';
    container.dataset.state = changedPaths.length > 0 ? 'warning' : 'success';
    summary.textContent = changedPaths.length > 0 ? '配置已保存' : '未检测到有效配置变更';
    meta.textContent = [
        `变更项：${changedPaths.length} 个`,
        runtimeApply?.message ? `运行时反馈：${runtimeApply.message}` : '运行时反馈：等待运行中实例感知新配置',
        persistenceText,
    ].join(' · ');

    reloadPlan.forEach((item) => {
        const block = createElement('div', 'config-save-feedback-item');
        const top = createElement('div', 'config-save-feedback-item-top');
        top.appendChild(createElement('div', 'config-save-feedback-item-title', item.component || 'unknown'));
        top.appendChild(createElement('span', `config-save-feedback-badge ${item.mode || 'unknown'}`, item.mode || 'unknown'));
        block.appendChild(top);
        block.appendChild(createElement('div', 'config-save-feedback-item-note', item.note || ''));
        block.appendChild(createElement('div', 'config-save-feedback-item-paths', (item.paths || []).join(', ')));
        groups.appendChild(block);
    });
}

export function renderExportRagStatus(page) {
    const status = page.$('#export-rag-status');
    if (!status || !page._config) {
        return;
    }
    status.textContent = page._config.bot?.rag_enabled
        ? `状态：运行期向量记忆已开启${page._config.bot?.export_rag_enabled ? '，导出聊天记录 RAG 已开启' : ''}`
        : '状态：向量记忆总开关已关闭，运行期 RAG 和导出 RAG 都不会执行召回';
}
