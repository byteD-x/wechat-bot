import { apiService } from '../../services/ApiService.js';
import {
    renderDashboardCost,
    renderMessages,
} from './renderers.js';

function getApiService(deps = {}) {
    return deps.apiService || apiService;
}

function createEmptyDashboardCost() {
    return {
        today: null,
        recent: null,
    };
}

export function clearOfflineData(page) {
    page._recentMessages = [];
    page._dashboardCost = createEmptyDashboardCost();

    const container = page.$('#recent-messages');
    if (container) {
        renderMessages(container, page._recentMessages);
    }
    renderDashboardCost(page, page._dashboardCost);
}

export async function loadRecentMessages(page, deps = {}) {
    if (!page.getState('bot.connected')) {
        clearOfflineData(page);
        return;
    }

    try {
        const result = await getApiService(deps).getMessages({ limit: 5, offset: 0 });
        const container = page.$('#recent-messages');
        if (result?.success && Array.isArray(result.messages) && container) {
            page._recentMessages = [...result.messages].reverse();
            renderMessages(container, page._recentMessages);
        }
    } catch (error) {
        console.error('[DashboardPage] 加载最近消息失败:', error);
    }
}

export function appendRecentMessage(page, message) {
    if (!message) {
        return;
    }
    const container = page.$('#recent-messages');
    if (!container) {
        return;
    }

    const normalized = {
        sender: message.sender,
        content: message.content,
        text: message.text,
        timestamp: message.timestamp,
        is_self: message.direction === 'outgoing',
    };

    page._recentMessages = [...page._recentMessages, normalized].slice(-5);
    renderMessages(container, page._recentMessages);
}

export async function refreshDashboardCost(page, force = false, deps = {}) {
    if (!page.getState('bot.connected')) {
        page._dashboardCost = createEmptyDashboardCost();
        renderDashboardCost(page, page._dashboardCost);
        return;
    }

    const now = Date.now();
    if (!force && now - page._lastCostFetchAt < 15000) {
        return;
    }
    page._lastCostFetchAt = now;

    try {
        const currentApiService = getApiService(deps);
        const [today, recent] = await Promise.all([
            currentApiService.getCostSummary({
                period: 'today',
                include_estimated: true,
            }),
            currentApiService.getCostSummary({
                period: '30d',
                include_estimated: true,
            }),
        ]);

        if (today?.success) {
            page._dashboardCost.today = today;
        }
        if (recent?.success) {
            page._dashboardCost.recent = recent;
        }

        renderDashboardCost(page, page._dashboardCost);
    } catch (error) {
        console.error('[DashboardPage] 加载成本概览失败:', error);
    }
}
