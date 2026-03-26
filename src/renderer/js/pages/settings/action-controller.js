import { apiService } from '../../services/ApiService.js';
import { toast } from '../../services/NotificationService.js';

function getApiService(deps = {}) {
    return deps.apiService || apiService;
}

function getToast(deps = {}) {
    return deps.toast || toast;
}

function getWindowApi(deps = {}) {
    return deps.windowApi || globalThis.window?.electronAPI || null;
}

export async function saveSettings(page, options = {}, text = {}, deps = {}) {
    const currentToast = getToast(deps);
    const { scope = null, triggerButton = null, silentToast = false } = options;
    if (page._isSaving) {
        page._queuedAutoSave = true;
        return;
    }

    try {
        const payload = page._collectPayload(scope);
        if (!Object.keys(payload).length) {
            currentToast.info('未检测到需要保存的配置变更');
            return;
        }

        page._setSavingState(true, triggerButton);
        const windowApi = getWindowApi(deps);
        const result = windowApi?.configPatch
            ? await windowApi.configPatch(payload)
            : await getApiService(deps).saveConfig(payload);
        if (!result?.success) {
            throw new Error(result?.message || text.saveFailed);
        }

        await page.loadSettings({ silent: true, preserveFeedback: true });
        page._renderHero(true);
        page._renderSaveFeedback(result);
        page._renderExportRagStatus();
        page._resetDirtyState?.();
        page._setSavingState(false, triggerButton);
        if (!silentToast) {
            currentToast.success(result?.runtime_apply?.message || result?.message || '配置已保存');
        }
    } catch (error) {
        console.error('[SettingsPage] save failed:', error);
        page._renderSaveFeedback({ success: false, message: currentToast.getErrorMessage(error, text.saveFailed) });
        page._setSavingState(false, triggerButton);
        page._renderWorkbenchState?.();
        if (!silentToast) {
            currentToast.error(currentToast.getErrorMessage(error, text.saveFailed));
        }
    } finally {
        if (page._queuedAutoSave) {
            page._queuedAutoSave = false;
            page._scheduleAutoSave({ immediate: true });
        }
    }
}

export async function previewPrompt(page, text = {}, deps = {}) {
    const currentToast = getToast(deps);
    try {
        if (!page.getState('bot.connected')) {
            throw new Error('预览 Prompt 前请先连接 Python 服务');
        }
        const result = await getApiService(deps).previewPrompt({
            bot: page._collectPayload().bot,
            sample: {
                chat_name: page.$('#setting-preview-chat-name')?.value || '',
                sender: page.$('#setting-preview-sender')?.value || '',
                relationship: page.$('#setting-preview-relationship')?.value || '',
                emotion: page.$('#setting-preview-emotion')?.value || '',
                message: page.$('#setting-preview-message')?.value || '',
                is_group: !!page.$('#setting-preview-is-group')?.checked,
            },
        });
        if (!result?.success) {
            throw new Error(result?.message || text.previewFailed);
        }
        if (page.$('#settings-preview-summary')) {
            const info = result.summary || {};
            page.$('#settings-preview-summary').dataset.state = 'success';
            page.$('#settings-preview-summary').textContent = `预览完成，${info.lines || 0} 行 / ${info.chars || 0} 字符`;
        }
        if (page.$('#settings-prompt-preview')) {
            page.$('#settings-prompt-preview').textContent = String(result.prompt || '');
        }
    } catch (error) {
        console.error('[SettingsPage] preview failed:', error);
        if (page.$('#settings-preview-summary')) {
            page.$('#settings-preview-summary').dataset.state = 'error';
            page.$('#settings-preview-summary').textContent = currentToast.getErrorMessage(error, text.previewFailed);
        }
        if (page.$('#settings-prompt-preview')) {
            page.$('#settings-prompt-preview').textContent = '';
        }
        currentToast.error(currentToast.getErrorMessage(error, text.previewFailed));
    }
}

export async function checkUpdates(page, text = {}, deps = {}) {
    const currentToast = getToast(deps);
    try {
        const windowApi = getWindowApi(deps);
        const updateSource = String(deps.updateSource || 'settings-page').trim() || 'settings-page';
        if (!windowApi?.checkForUpdates) {
            throw new Error('当前环境未提供应用内更新能力');
        }
        const result = await windowApi.checkForUpdates({ source: updateSource });
        if (!result?.success && result?.error) {
            throw new Error(result.error);
        }
        page._renderUpdatePanel?.();
        currentToast.success(result?.updateAvailable ? '已发现新版本' : '当前已经是最新版本');
    } catch (error) {
        console.error('[Updater] check updates failed:', error);
        currentToast.error(currentToast.getErrorMessage(error, text.updateFailed));
    }
}

export async function openUpdateDownload(page, deps = {}) {
    const currentToast = getToast(deps);
    const windowApi = getWindowApi(deps);
    const readyToInstall = !!page.getState('updater.readyToInstall');

    if (readyToInstall && windowApi?.installDownloadedUpdate) {
        const result = await windowApi.installDownloadedUpdate();
        if (!result?.success) {
            currentToast.warning(result?.error || '安装更新失败，请稍后重试');
            return;
        }
        currentToast.info('安装包已就绪，应用即将重启安装...');
        return;
    }

    if (windowApi?.downloadUpdate && page.getState('updater.enabled')) {
        const result = await windowApi.downloadUpdate();
        if (!result?.success) {
            currentToast.warning(result?.error || '下载更新失败');
            return;
        }
        currentToast.info(result?.alreadyDownloaded ? '更新包已下载完成' : '开始下载新版本，请稍候...');
        return;
    }

    if (!windowApi?.openUpdateDownload) {
        currentToast.warning('当前环境未提供下载页入口');
        return;
    }
    const result = await windowApi.openUpdateDownload();
    if (!result?.success) {
        currentToast.warning(result?.error || '打开下载页面失败');
    }
}

export async function resetCloseBehavior(text = {}, deps = {}) {
    const currentToast = getToast(deps);
    try {
        const windowApi = getWindowApi(deps);
        if (!windowApi?.resetCloseBehavior) {
            throw new Error('当前环境未提供重置关闭行为能力');
        }
        await windowApi.resetCloseBehavior();
        currentToast.success(text.resetCloseSuccess);
    } catch (error) {
        currentToast.error(currentToast.getErrorMessage(error, '重置关闭行为失败'));
    }
}
