import { apiService } from '../../services/ApiService.js';
import { toast } from '../../services/NotificationService.js';
import { COST_TEXT } from './formatters.js';
import {
    renderCostError,
    renderCostFilterOptions,
    renderCostLoading,
    renderCostModelBreakdown,
    renderCostOverview,
    renderCostReviewQueue,
    renderCostSessions,
} from './renderers.js';
import {
    readCostFilters,
    syncCostFilters,
    toCostApiParams,
} from './filter-sync.js';

function getApiService(deps = {}) {
    return deps.apiService || apiService;
}

function getToast(deps = {}) {
    return deps.toast || toast;
}

function formatTimeLabel(value) {
    if (!value) {
        return '尚未刷新';
    }
    return `更新于 ${new Intl.DateTimeFormat('zh-CN', {
        hour: '2-digit',
        minute: '2-digit',
    }).format(value)}`;
}

function renderToolbarMeta(page, summaryText) {
    const summaryElem = page.$('#cost-filter-summary');
    const updatedElem = page.$('#cost-last-updated');
    if (summaryElem) {
        summaryElem.textContent = summaryText;
    }
    if (updatedElem) {
        updatedElem.textContent = formatTimeLabel(page._lastLoadedAt);
    }
}

function buildFilterSummary(filters = {}) {
    const parts = [];
    if (filters.period) {
        parts.push(`时间：${filters.period}`);
    }
    if (filters.provider_id) {
        parts.push(`服务方：${filters.provider_id}`);
    }
    if (filters.model) {
        parts.push(`模型：${filters.model}`);
    }
    if (filters.review_reason) {
        parts.push(`原因：${filters.review_reason}`);
    }
    if (filters.suggested_action) {
        parts.push(`建议：${filters.suggested_action}`);
    }
    if (filters.only_priced) {
        parts.push('仅已定价');
    }
    if (filters.include_estimated === false) {
        parts.push('不含估算');
    }
    return `当前筛选：${parts.join(' / ') || '近 30 天'}`;
}

export function renderCostSummary(page) {
    renderCostOverview(page, page._summary?.overview || {});
    renderCostModelBreakdown(page, page._summary?.models || []);
    renderCostReviewQueue(
        page,
        page._summary?.review_queue || [],
        page._summary?.review_playbook || {},
    );
    renderCostFilterOptions(page, page._filters, page._summary?.options || {});
}

export function renderCostPage(page, deps = {}) {
    const onToggleSession = deps.onToggleSession || (() => {});
    renderCostSummary(page);
    renderCostSessions(page, page._sessions, (chatId, item) => onToggleSession(chatId, item));
    renderToolbarMeta(page, buildFilterSummary(page._filters));
}

export async function refreshCosts(page, deps = {}) {
    if (page._loading) {
        readCostFilters(page);
        page._pendingRefresh = true;
        return;
    }

    if (!page.getState('bot.connected')) {
        page._summary = null;
        page._sessions = [];
        page._details.clear();
        renderCostError(page, COST_TEXT.offline);
        syncCostFilters(page);
        renderToolbarMeta(page, '当前筛选：等待连接后可查看');
        return;
    }

    page._loading = true;
    readCostFilters(page);
    renderCostLoading(page);

    try {
        const params = toCostApiParams(page._filters);
        const [summary, sessions] = await Promise.all([
            getApiService(deps).getCostSummary(params),
            getApiService(deps).getCostSessions(params),
        ]);

        if (!summary?.success) {
            throw new Error(summary?.message || COST_TEXT.loadSummaryFailed);
        }
        if (!sessions?.success) {
            throw new Error(sessions?.message || COST_TEXT.loadSessionsFailed);
        }

        page._summary = summary;
        page._sessions = Array.isArray(sessions.sessions) ? sessions.sessions : [];
        page._details.clear();
        page._lastLoadedAt = Date.now();
        renderCostPage(page, deps);
    } catch (error) {
        renderCostError(page, getToast(deps).getErrorMessage(error, COST_TEXT.loadFailed));
        renderToolbarMeta(page, buildFilterSummary(page._filters));
    } finally {
        syncCostFilters(page);
        page._loading = false;
        if (page._pendingRefresh) {
            page._pendingRefresh = false;
            void refreshCosts(page, deps);
        }
    }
}

export async function refreshPricingCatalog(page, deps = {}) {
    const currentToast = getToast(deps);
    if (!page.getState('bot.connected')) {
        currentToast.info(COST_TEXT.offline);
        return;
    }

    try {
        const result = await getApiService(deps).refreshPricing();
        if (!result?.success) {
            throw new Error(result?.message || COST_TEXT.refreshPricingFailed);
        }

        const failures = Object.entries(result.results || {})
            .filter(([, item]) => item?.success === false)
            .map(([providerId, item]) => `${providerId}: ${item?.message || COST_TEXT.refreshPricingFailed}`);

        if (failures.length > 0) {
            currentToast.warning(`${COST_TEXT.refreshPricingPartial}${failures.join(', ')}`);
        } else {
            currentToast.success(COST_TEXT.refreshPricingSuccess);
        }

        const runRefresh = deps.refreshCosts || ((targetPage) => targetPage.refresh?.());
        await runRefresh(page);
    } catch (error) {
        currentToast.error(currentToast.getErrorMessage(error, COST_TEXT.refreshPricingFailed));
    }
}

export async function exportCostReviewQueue(page, deps = {}) {
    const currentToast = getToast(deps);
    if (!page.getState('bot.connected')) {
        currentToast.info(COST_TEXT.offline);
        return;
    }

    readCostFilters(page);
    try {
        const params = toCostApiParams(page._filters);
        const result = await getApiService(deps).exportCostReviewQueue(params);
        if (!result?.success) {
            throw new Error(result?.message || '导出复盘队列失败');
        }

        const payload = JSON.stringify(result, null, 2);
        const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
        const presetSuffix = params.preset ? `-preset-${String(params.preset).replace(/[^a-zA-Z0-9_-]+/g, '_')}` : '';
        const reasonSuffix = params.review_reason ? `-reason-${String(params.review_reason).replace(/[^a-zA-Z0-9_-]+/g, '_')}` : '';
        const filename = `cost-review-queue${presetSuffix}${reasonSuffix}-${timestamp}.json`;
        const urlApi = globalThis.URL;
        if (typeof Blob === 'function' && urlApi?.createObjectURL) {
            const blob = new Blob([payload], { type: 'application/json;charset=utf-8' });
            const href = urlApi.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = href;
            link.download = filename;
            link.click();
            if (typeof urlApi.revokeObjectURL === 'function') {
                urlApi.revokeObjectURL(href);
            }
            const scopeParts = [];
            if (params.preset) {
                scopeParts.push(`preset ${params.preset}`);
            }
            if (params.review_reason) {
                scopeParts.push(`reason ${params.review_reason}`);
            }
            const scopeLabel = scopeParts.length > 0 ? ` for ${scopeParts.join(', ')}` : '';
            currentToast.success(`Exported ${result.total || 0} review items${scopeLabel}`);
            return;
        }

        currentToast.warning(`Export returned ${result.total || 0} items, but auto download is unavailable`);
    } catch (error) {
        currentToast.error(currentToast.getErrorMessage(error, 'Export review queue failed'));
    }
}
