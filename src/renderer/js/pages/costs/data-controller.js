import { apiService } from '../../services/ApiService.js';
import { toast } from '../../services/NotificationService.js';
import { COST_TEXT } from './formatters.js';
import {
    renderCostError,
    renderCostFilterOptions,
    renderCostLoading,
    renderCostModelBreakdown,
    renderCostOverview,
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

export function renderCostSummary(page) {
    renderCostOverview(page, page._summary?.overview || {});
    renderCostModelBreakdown(page, page._summary?.models || []);
    renderCostFilterOptions(page, page._filters, page._summary?.options || {});
}

export function renderCostPage(page, deps = {}) {
    const onToggleSession = deps.onToggleSession || (() => {});
    renderCostSummary(page);
    renderCostSessions(page, page._sessions, (chatId, item) => onToggleSession(chatId, item));
}

export async function refreshCosts(page, deps = {}) {
    if (page._loading) {
        return;
    }

    if (!page.getState('bot.connected')) {
        page._summary = null;
        page._sessions = [];
        page._details.clear();
        renderCostError(page, COST_TEXT.offline);
        syncCostFilters(page);
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
        renderCostPage(page, deps);
    } catch (error) {
        renderCostError(page, getToast(deps).getErrorMessage(error, COST_TEXT.loadFailed));
    } finally {
        syncCostFilters(page);
        page._loading = false;
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
            currentToast.warning(`${COST_TEXT.refreshPricingPartial}${failures.join('；')}`);
        } else {
            currentToast.success(COST_TEXT.refreshPricingSuccess);
        }

        const runRefresh = deps.refreshCosts || ((targetPage) => targetPage.refresh?.());
        await runRefresh(page);
    } catch (error) {
        currentToast.error(currentToast.getErrorMessage(error, COST_TEXT.refreshPricingFailed));
    }
}
