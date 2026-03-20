import { createElement, formatDateTime } from './form-codec.js';

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
        `变更项：${changedPaths.length} 项`,
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
