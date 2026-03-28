import { Events } from '../../core/EventBus.js';
import {
    applyFilters,
    clearLogs,
    copyLogs,
    exportLogs,
    refreshLogs,
} from './data-controller.js';
import {
    setupAutoRefresh,
    syncOptionState,
    updateWrapState,
} from './runtime-controller.js';

export function bindLogsEvents(page, deps = {}) {
    page.bindEvent('#btn-refresh-logs', 'click', () => {
        void (deps.refreshLogs || refreshLogs)(page, {}, deps);
    });

    page.bindEvent('#btn-clear-logs', 'click', () => {
        void (deps.clearLogs || clearLogs)(page, deps);
    });

    page.bindEvent('#btn-copy-logs', 'click', () => {
        void (deps.copyLogs || copyLogs)(page, deps);
    });

    page.bindEvent('#btn-export-logs', 'click', () => {
        (deps.exportLogs || exportLogs)(page, deps);
    });

    page.bindEvent('#btn-reset-log-filters', 'click', () => {
        page._keyword = '';
        page._level = '';
        page._lineCount = 500;

        const searchInput = page.$('#log-search');
        if (searchInput) {
            searchInput.value = '';
        }
        const levelSelect = page.$('#log-level');
        if (levelSelect) {
            levelSelect.value = '';
        }
        const lineSelect = page.$('#log-lines');
        if (lineSelect) {
            lineSelect.value = '500';
        }

        void (deps.refreshLogs || refreshLogs)(page, {}, deps);
    });

    page.bindEvent('#btn-restore-log-default-view', 'click', () => {
        page._keyword = '';
        page._level = '';
        page._lineCount = 500;

        page.setState('logs.autoScroll', true);
        page.setState('logs.autoRefresh', true);
        page.setState('logs.wrap', true);

        const searchInput = page.$('#log-search');
        if (searchInput) {
            searchInput.value = '';
        }
        const levelSelect = page.$('#log-level');
        if (levelSelect) {
            levelSelect.value = '';
        }
        const lineSelect = page.$('#log-lines');
        if (lineSelect) {
            lineSelect.value = '500';
        }
        const autoScroll = page.$('#setting-auto-scroll');
        if (autoScroll) {
            autoScroll.checked = true;
        }
        const autoRefresh = page.$('#setting-auto-refresh');
        if (autoRefresh) {
            autoRefresh.checked = true;
        }
        const wrap = page.$('#setting-wrap');
        if (wrap) {
            wrap.checked = true;
        }

        (deps.syncOptionState || syncOptionState)(page);
        (deps.updateWrapState || updateWrapState)(page, true);
        (deps.setupAutoRefresh || setupAutoRefresh)(page, deps);
        void (deps.refreshLogs || refreshLogs)(page, {}, deps);
    });

    const searchInput = page.$('#log-search');
    searchInput?.addEventListener('input', () => {
        page._keyword = String(searchInput.value || '').trim().toLowerCase();
        (deps.applyFilters || applyFilters)(page, deps);
    });

    const levelSelect = page.$('#log-level');
    levelSelect?.addEventListener('change', () => {
        page._level = String(levelSelect.value || '').trim().toLowerCase();
        (deps.applyFilters || applyFilters)(page, deps);
    });

    const lineSelect = page.$('#log-lines');
    lineSelect?.addEventListener('change', () => {
        const nextValue = Number(lineSelect.value || 500);
        page._lineCount = Number.isFinite(nextValue) && nextValue > 0 ? nextValue : 500;
        void (deps.refreshLogs || refreshLogs)(page, {}, deps);
    });

    const autoScroll = page.$('#setting-auto-scroll');
    autoScroll?.addEventListener('change', () => {
        page.setState('logs.autoScroll', !!autoScroll.checked);
        if (autoScroll.checked) {
            (deps.scrollToBottom || (() => {}))(page);
        }
    });

    const autoRefresh = page.$('#setting-auto-refresh');
    autoRefresh?.addEventListener('change', () => {
        page.setState('logs.autoRefresh', !!autoRefresh.checked);
        (deps.setupAutoRefresh || setupAutoRefresh)(page, deps);
    });

    const wrap = page.$('#setting-wrap');
    wrap?.addEventListener('change', () => {
        const enabled = !!wrap.checked;
        page.setState('logs.wrap', enabled);
        (deps.updateWrapState || updateWrapState)(page, enabled);
    });

    page.watchState('bot.connected', () => {
        if (!page.isActive()) {
            return;
        }
        (deps.setupAutoRefresh || setupAutoRefresh)(page, deps);
        void (deps.refreshLogs || refreshLogs)(page, { silent: true }, deps);
    });
}

export function syncLogsPageOptions(page, deps = {}) {
    (deps.syncOptionState || syncOptionState)(page);
}

export function emitLogsLoaded(page, total, visible) {
    page.emit(Events.LOGS_LOADED, { total, visible });
}

export function emitLogsCleared(page) {
    page.emit(Events.LOGS_CLEARED, {});
}
