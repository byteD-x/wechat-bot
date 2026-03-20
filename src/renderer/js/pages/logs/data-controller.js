import { Events } from '../../core/EventBus.js';
import { apiService } from '../../services/ApiService.js';
import { toast } from '../../services/NotificationService.js';
import {
    downloadLogTextFile,
    isNoiseLogLine,
    LOG_TEXT,
    parseLogEntry,
} from './formatters.js';
import {
    renderLogList,
    updateLogMeta,
} from './renderers.js';
import { scrollToBottom } from './runtime-controller.js';

function getApiService(deps = {}) {
    return deps.apiService || apiService;
}

function getToast(deps = {}) {
    return deps.toast || toast;
}

function getDocument(deps = {}) {
    return deps.documentObj || globalThis.document;
}

function getNavigator(deps = {}) {
    return deps.navigatorObj || globalThis.navigator || {};
}

function renderLogs(page, deps = {}) {
    const renderList = deps.renderLogList || renderLogList;
    renderList(page, page._allLogs, page._visibleLogs);
    if (page._visibleLogs.length > 0 && page.getState('logs.autoScroll') !== false) {
        (deps.scrollToBottom || scrollToBottom)(page);
    }
}

function updateMeta(page, deps = {}) {
    const updateMetaView = deps.updateLogMeta || updateLogMeta;
    updateMetaView(page, page._allLogs.length, page._visibleLogs.length);
}

export function applyFilters(page, deps = {}) {
    const keyword = page._keyword;
    const level = page._level;
    const checkNoise = deps.isNoiseLogLine || isNoiseLogLine;
    const parseEntry = deps.parseLogEntry || parseLogEntry;

    page._visibleLogs = page._allLogs.filter((line) => {
        if (checkNoise(line)) {
            return false;
        }
        const entry = parseEntry(line);
        const searchable = `${entry.summary} ${entry.context} ${entry.raw}`.toLowerCase();
        if (keyword && !searchable.includes(keyword)) {
            return false;
        }
        if (level && entry.level !== level) {
            return false;
        }
        return true;
    });

    renderLogs(page, deps);
    updateMeta(page, deps);
}

export async function refreshLogs(page, options = {}, deps = {}) {
    const container = page.$('#log-content');
    const { silent = false } = options;
    const currentToast = getToast(deps);

    if (!page.getState('bot.connected')) {
        page._allLogs = [];
        page._visibleLogs = [];
        if (container) {
            container.textContent = LOG_TEXT.offline;
        }
        updateMeta(page, deps);
        return;
    }

    if (!silent && container) {
        container.textContent = LOG_TEXT.loading;
    }

    try {
        const result = await getApiService(deps).getLogs(page._lineCount);
        if (!result?.success) {
            throw new Error(result?.message || LOG_TEXT.loadFailed);
        }

        page._allLogs = Array.isArray(result.logs) ? result.logs : [];
        applyFilters(page, deps);
        updateMeta(page, deps);
        page.emit(Events.LOGS_LOADED, {
            total: page._allLogs.length,
            visible: page._visibleLogs.length,
        });
    } catch (error) {
        console.error('[LogsPage] load failed:', error);
        if (container) {
            container.textContent = currentToast.getErrorMessage(error, LOG_TEXT.loadFailed);
        }
        if (!silent) {
            currentToast.error(currentToast.getErrorMessage(error, LOG_TEXT.loadFailed));
        }
    }
}

export async function clearLogs(page, deps = {}) {
    const currentToast = getToast(deps);
    if (!page.getState('bot.connected')) {
        currentToast.info(LOG_TEXT.offline);
        return;
    }

    try {
        const result = await getApiService(deps).clearLogs();
        if (!result?.success) {
            throw new Error(result?.message || LOG_TEXT.clearFailed);
        }
        page._allLogs = [];
        page._visibleLogs = [];
        renderLogs(page, deps);
        updateMeta(page, deps);
        page.emit(Events.LOGS_CLEARED, {});
        currentToast.success(result?.message || LOG_TEXT.cleared);
    } catch (error) {
        console.error('[LogsPage] clear failed:', error);
        currentToast.error(currentToast.getErrorMessage(error, LOG_TEXT.clearFailed));
    }
}

export async function copyLogs(page, deps = {}) {
    const currentToast = getToast(deps);
    const content = page._visibleLogs.join('\n');
    if (!content) {
        currentToast.info(LOG_TEXT.empty);
        return;
    }

    try {
        const navigatorObj = getNavigator(deps);
        if (navigatorObj.clipboard?.writeText) {
            await navigatorObj.clipboard.writeText(content);
        } else {
            const documentObj = getDocument(deps);
            const textarea = documentObj.createElement('textarea');
            textarea.value = content;
            textarea.setAttribute('readonly', 'readonly');
            textarea.style.position = 'fixed';
            textarea.style.opacity = '0';
            documentObj.body.appendChild(textarea);
            textarea.select?.();
            documentObj.execCommand?.('copy');
            textarea.remove();
        }
        currentToast.success(LOG_TEXT.copied);
    } catch (error) {
        console.error('[LogsPage] copy failed:', error);
        currentToast.error(LOG_TEXT.copyFailed);
    }
}

export function exportLogs(page, deps = {}) {
    const currentToast = getToast(deps);
    const downloader = deps.downloadLogTextFile || downloadLogTextFile;
    const nowFn = deps.nowFn || Date.now;
    const content = page._visibleLogs.join('\n');
    downloader(`wechat-ai-assistant-logs-${nowFn()}.log`, content || '');
    currentToast.success(LOG_TEXT.exported);
}
