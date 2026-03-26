import { Events } from '../../core/EventBus.js';
import { toast } from '../../services/NotificationService.js';
import {
    handleGrowthTaskAction,
    recoverBot,
    restartBot,
    runReadinessAction,
    toggleBot,
    toggleGrowth,
    togglePause,
} from './actions.js';
import {
    handleIdleActionClick,
    getIdleState,
    wakeBackend,
} from './runtime-controller.js';
import {
    clearOfflineData,
    loadRecentMessages,
    refreshDashboardCost,
    refreshDashboardStability,
} from './data-loader.js';
import { updateBotUI } from './status-presenter.js';

function getToast(deps = {}) {
    return deps.toast || toast;
}

function getWindowApi(deps = {}) {
    return deps.windowApi || globalThis.window?.electronAPI || null;
}

function getHelper(deps = {}, key, fallback) {
    return deps[key] || fallback;
}

export function bindDashboardEvents(page, deps = {}) {
    const runToggleBot = getHelper(deps, 'toggleBot', toggleBot);
    const runToggleGrowth = getHelper(deps, 'toggleGrowth', toggleGrowth);
    const runHandleGrowthTaskAction = getHelper(deps, 'handleGrowthTaskAction', handleGrowthTaskAction);
    const runTogglePause = getHelper(deps, 'togglePause', togglePause);
    const runRestartBot = getHelper(deps, 'restartBot', restartBot);
    const runRecoverBot = getHelper(deps, 'recoverBot', recoverBot);
    const runHandleIdleActionClick = getHelper(deps, 'handleIdleActionClick', handleIdleActionClick);
    const runHandleReadinessClick = getHelper(deps, 'handleReadinessPanelClick', handleReadinessPanelClick);
    const runExportDiagnosticsSnapshot = getHelper(deps, 'exportDiagnosticsSnapshot', exportDiagnosticsSnapshot);
    const runHandleSectionTabClick = getHelper(deps, 'handleDashboardSectionTabClick', handleDashboardSectionTabClick);

    page.bindEvent('#btn-toggle-bot', 'click', () => runToggleBot(page));
    page.bindEvent('#btn-toggle-growth', 'click', () => runToggleGrowth(page));
    page.bindEvent('#growth-task-queue', 'click', (event) => runHandleGrowthTaskAction(page, event));
    page.bindEvent('#btn-pause', 'click', () => runTogglePause(page));
    page.bindEvent('#btn-restart', 'click', () => runRestartBot(page));
    page.bindEvent('#btn-recover-bot', 'click', () => runRecoverBot(page));
    page.bindEvent('#btn-open-costs', 'click', () => page.emit(Events.PAGE_CHANGE, 'costs'));
    page.bindEvent('#btn-view-logs', 'click', () => page.emit(Events.PAGE_CHANGE, 'logs'));
    page.bindEvent('#btn-view-all-messages', 'click', () => page.emit(Events.PAGE_CHANGE, 'messages'));
    page.bindEvent('#backend-idle-panel', 'click', (event) => runHandleIdleActionClick(page, event));
    page.bindEvent('#bot-readiness', 'click', (event) => runHandleReadinessClick(page, event, deps));
    page.bindEvent('#btn-refresh-status', 'click', () => handleRefreshStatus(page, deps));
    page.bindEvent('#btn-minimize-tray', 'click', () => {
        getWindowApi(deps)?.minimizeToTray?.();
    });
    page.bindEvent('#btn-open-wechat', 'click', () => openWeChatClient(deps));
    page.bindEvent('#btn-export-diagnostics-snapshot', 'click', () => {
        void runExportDiagnosticsSnapshot(deps);
    });
    page.bindEvent('#dashboard-section-tabs', 'click', (event) => runHandleSectionTabClick(page, event));

    bindDashboardWatchers(page, deps);
}

export function bindDashboardWatchers(page, deps = {}) {
    const runUpdateBotUI = getHelper(deps, 'updateBotUI', updateBotUI);
    const runClearOfflineData = getHelper(deps, 'clearOfflineData', clearOfflineData);
    const runLoadRecentMessages = getHelper(deps, 'loadRecentMessages', loadRecentMessages);
    const runRefreshDashboardCost = getHelper(deps, 'refreshDashboardCost', refreshDashboardCost);
    const runRefreshDashboardStability = getHelper(deps, 'refreshDashboardStability', refreshDashboardStability);

    const updateIfActive = () => {
        if (page.isActive()) {
            runUpdateBotUI(page);
        }
    };

    page.watchState('bot.status', updateIfActive);
    page.watchState('bot.running', updateIfActive);
    page.watchState('bot.paused', updateIfActive);
    page.watchState('backend.idle', updateIfActive);
    page.watchState('readiness.report', updateIfActive);
    page.watchState('bot.connected', (connected) => {
        if (!page.isActive()) {
            return;
        }
        runUpdateBotUI(page);
        if (!connected) {
            runClearOfflineData(page);
            return;
        }
        void runLoadRecentMessages(page);
        void runRefreshDashboardCost(page, true);
        void runRefreshDashboardStability(page, true);
    });
}

export function handleRefreshStatus(page, deps = {}) {
    const currentToast = getToast(deps);
    const runGetIdleState = getHelper(deps, 'getIdleState', getIdleState);
    const runWakeBackend = getHelper(deps, 'wakeBackend', wakeBackend);
    const runRefreshDashboardCost = getHelper(deps, 'refreshDashboardCost', refreshDashboardCost);
    const runRefreshDashboardStability = getHelper(deps, 'refreshDashboardStability', refreshDashboardStability);
    if (runGetIdleState(page).state === 'stopped_by_idle') {
        void runWakeBackend(page);
        return;
    }
    page.emit(Events.BOT_STATUS_CHANGE, { force: true, refreshReadiness: true });
    currentToast.success('已请求刷新运行状态');
    void runRefreshDashboardCost(page, true);
    void runRefreshDashboardStability(page, true);
}

export function handleReadinessPanelClick(page, event, deps = {}) {
    const button = event?.target?.closest?.('[data-readiness-action]');
    if (!button) {
        return;
    }
    event.preventDefault?.();
    event.stopPropagation?.();
    void handleReadinessAction(page, button.dataset.readinessAction, deps);
}

export function handleDashboardSectionTabClick(page, event) {
    const button = event?.target?.closest?.('[data-dashboard-section-button]');
    if (!button) {
        return;
    }
    const nextSection = String(button.dataset.dashboardSectionButton || '').trim();
    if (!nextSection || typeof page?._setDashboardSection !== 'function') {
        return;
    }
    page._setDashboardSection(nextSection);
}

export async function handleReadinessAction(page, action, deps = {}) {
    await runReadinessAction(page, action, deps);
}

export async function exportDiagnosticsSnapshot(deps = {}) {
    const currentToast = getToast(deps);
    const windowApi = getWindowApi(deps);
    if (!windowApi?.exportDiagnosticsSnapshot) {
        currentToast.warning('当前安装包暂不支持导出诊断快照');
        return;
    }

    try {
        const result = await windowApi.exportDiagnosticsSnapshot();
        if (result?.success) {
            currentToast.success(result.message || '诊断快照已导出');
            return;
        }
        if (!result?.canceled) {
            currentToast.error(result?.message || '导出诊断快照失败');
        }
    } catch (error) {
        currentToast.error(currentToast.getErrorMessage(error, '导出诊断快照失败'));
    }
}

export async function openWeChatClient(deps = {}) {
    const currentToast = getToast(deps);
    const windowApi = getWindowApi(deps);
    try {
        if (windowApi?.openWeChat) {
            await windowApi.openWeChat();
            currentToast.success('正在打开微信客户端...');
        } else {
            currentToast.info('请手动打开微信客户端');
        }
    } catch (error) {
        console.error('[DashboardPage] open WeChat failed:', error);
        if (String(error?.message || '').includes('No handler registered')) {
            currentToast.error('请重启应用后再试一次');
        } else {
            currentToast.error('打开微信客户端失败');
        }
    }
}
