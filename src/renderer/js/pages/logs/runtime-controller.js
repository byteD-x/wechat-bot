export function syncOptionState(page) {
    const autoScroll = page.$('#setting-auto-scroll');
    const autoRefresh = page.$('#setting-auto-refresh');
    const wrap = page.$('#setting-wrap');
    if (autoScroll) {
        autoScroll.checked = page.getState('logs.autoScroll') !== false;
    }
    if (autoRefresh) {
        autoRefresh.checked = page.getState('logs.autoRefresh') !== false;
    }
    if (wrap) {
        wrap.checked = page.getState('logs.wrap') !== false;
    }
    updateWrapState(page, page.getState('logs.wrap') !== false);
}

export function setupAutoRefresh(page, deps = {}) {
    clearRefreshTimer(page, deps);

    if (
        !page.isActive()
        || page.getState('logs.autoRefresh') === false
        || !page.getState('bot.connected')
    ) {
        return;
    }

    const setIntervalFn = deps.setIntervalFn || globalThis.window?.setInterval || globalThis.setInterval;
    const refreshLogs = deps.refreshLogs || (() => Promise.resolve());
    page._refreshTimer = setIntervalFn(() => {
        void refreshLogs(page, { silent: true }, deps);
    }, 5000);
    page.setState('intervals.logs', page._refreshTimer);
}

export function clearRefreshTimer(page, deps = {}) {
    if (page._refreshTimer) {
        const clearIntervalFn = deps.clearIntervalFn || globalThis.clearInterval;
        clearIntervalFn(page._refreshTimer);
        page._refreshTimer = null;
    }
    page.setState('intervals.logs', null);
}

export function updateWrapState(page, enabled) {
    const container = page.$('.log-container');
    container?.classList.toggle('wrap', enabled);
}

export function scrollToBottom(page) {
    const container = page.$('#log-content');
    if (!container) {
        return;
    }
    container.scrollTop = container.scrollHeight;
}
