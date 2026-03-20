import { apiService } from '../../services/ApiService.js';
import { toast } from '../../services/NotificationService.js';
import { COST_TEXT } from './formatters.js';
import {
    renderCostSessionDetails,
    renderCostSessionError,
    renderCostSessionLoading,
} from './renderers.js';
import { toCostApiParams } from './filter-sync.js';

function getApiService(deps = {}) {
    return deps.apiService || apiService;
}

function getToast(deps = {}) {
    return deps.toast || toast;
}

export async function toggleCostSession(page, chatId, item, deps = {}) {
    const detail = item.querySelector('.cost-session-detail');
    const trigger = item.querySelector('.cost-session-trigger');
    if (!detail || !trigger) {
        return;
    }

    const isOpen = item.classList.contains('is-open');
    item.classList.toggle('is-open', !isOpen);
    detail.hidden = isOpen;
    trigger.setAttribute('aria-expanded', String(!isOpen));
    if (isOpen) {
        return;
    }

    if (page._details.has(chatId)) {
        renderCostSessionDetails(detail, page._details.get(chatId));
        return;
    }

    renderCostSessionLoading(detail);

    try {
        const result = await getApiService(deps).getCostSessionDetails(chatId, toCostApiParams(page._filters));
        if (!result?.success) {
            throw new Error(result?.message || COST_TEXT.detailFailed);
        }

        const records = Array.isArray(result.records) ? result.records : [];
        page._details.set(chatId, records);
        renderCostSessionDetails(detail, records);
    } catch (error) {
        renderCostSessionError(detail, getToast(deps).getErrorMessage(error, COST_TEXT.detailFailed));
        trigger.focus();
    }
}
