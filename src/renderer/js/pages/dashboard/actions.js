import { Events } from '../../core/EventBus.js';
import { apiService } from '../../services/ApiService.js';
import { toast } from '../../services/NotificationService.js';
import { pickSuggestedSelfHealAction } from '../../app/self-heal.js';
import { getGrowthTaskLabel } from './formatters.js';
import { updateBotUI } from './status-presenter.js';

function getToast(deps = {}) {
    return deps.toast || toast;
}

function getApiService(deps = {}) {
    return deps.apiService || apiService;
}

function getWindowApi(deps = {}) {
    return deps.windowApi || globalThis.window?.electronAPI || null;
}

function getConfirmFn(deps = {}) {
    return deps.confirmAction
        || globalThis.window?.appConfirm
        || globalThis.window?.confirm
        || null;
}

function emitStatusRefresh(page, options = {}) {
    const {
        payload = {},
        followups = [],
    } = options;
    page.emit(Events.BOT_STATUS_CHANGE, payload);
    followups.forEach((delayMs) => {
        setTimeout(() => page.emit(Events.BOT_STATUS_CHANGE, payload), delayMs);
    });
}

function isTransientRestartError(error) {
    const code = String(error?.code || '').toLowerCase();
    return code === 'timeout' || code === 'network' || code === 'network_error';
}

function getDashboardActionLocks(page) {
    if (!page || typeof page !== 'object') {
        return new Set();
    }
    if (!(page._dashboardActionLocks instanceof Set)) {
        page._dashboardActionLocks = new Set();
    }
    return page._dashboardActionLocks;
}

async function runDashboardActionWithLock(page, lockKey, deps = {}, handler) {
    const locks = getDashboardActionLocks(page);
    const currentToast = getToast(deps);
    if (locks.has(lockKey)) {
        currentToast.info('操作执行中，请稍候...');
        return false;
    }
    locks.add(lockKey);
    try {
        await handler();
        return true;
    } finally {
        locks.delete(lockKey);
    }
}

export async function runReadinessAction(page, action, deps = {}) {
    const currentToast = getToast(deps);
    const windowApi = getWindowApi(deps);
    const normalizedAction = String(action || '').trim();
    if (!normalizedAction) {
        return;
    }

    if (normalizedAction === 'open_settings') {
        page.emit(Events.PAGE_CHANGE, 'settings');
        currentToast.info('已切换到设置页，请补齐配置后再重新检查。');
        return;
    }

    if (normalizedAction === 'open_wechat') {
        try {
            if (windowApi?.openWeChat) {
                const result = await windowApi.openWeChat();
                if (result?.success === false) {
                    currentToast.error(result?.error || result?.message || '打开微信客户端失败');
                    return;
                }
                currentToast.success('正在打开微信客户端...');
            } else {
                currentToast.info('请手动打开并登录微信客户端。');
            }
        } catch (error) {
            currentToast.error(currentToast.getErrorMessage(error, '打开微信客户端失败'));
            return;
        }
        emitStatusRefresh(page, { followups: [800, 2200], payload: { force: true, refreshReadiness: true } });
        return;
    }

    if (normalizedAction === 'restart_as_admin') {
        if (!windowApi?.restartAppAsAdmin) {
            currentToast.warning('当前环境暂不支持自动提权重启，请手动以管理员身份重新启动应用。');
            return;
        }

        currentToast.info('正在请求管理员权限并重新启动应用...');
        try {
            const result = await windowApi.restartAppAsAdmin();
            if (result?.success) {
                currentToast.success(result.message || '正在以管理员身份重新启动应用...');
                return;
            }
            if (result?.canceled) {
                currentToast.info(result.message || '已取消管理员权限授权');
                return;
            }
            currentToast.error(result?.message || '管理员重启失败');
        } catch (error) {
            currentToast.error(currentToast.getErrorMessage(error, '管理员重启失败'));
        }
        return;
    }

    emitStatusRefresh(page, { followups: [1000], payload: { force: true, refreshReadiness: true } });
}

export async function toggleBot(page, deps = {}) {
    const windowApi = getWindowApi(deps);
    const currentToast = getToast(deps);
    const currentApiService = getApiService(deps);
    const btn = page.$('#btn-toggle-bot');
    const btnText = btn?.querySelector('span');
    if (!btn) {
        return;
    }

    btn.disabled = true;

    try {
        const isRunning = !!page.getState('bot.running');

        if (isRunning) {
            if (btnText) {
                btnText.textContent = '停止中...';
            }
            const result = windowApi?.runtimeStopBot
                ? await windowApi.runtimeStopBot()
                : await currentApiService.stopBot();
            currentToast.show(
                result?.message || (result?.success ? '机器人已停止' : '停止机器人失败'),
                result?.success ? 'success' : 'error'
            );
        } else {
            const accepted = await ensureGrowthEnablePrompt(deps);
            if (!accepted) {
                return;
            }
            if (btnText) {
                btnText.textContent = '启动中...';
            }

            const prevStatus = page.getState('bot.status');
            const base = prevStatus && typeof prevStatus === 'object' ? prevStatus : {};
            page.setState('bot.status', {
                ...base,
                startup: {
                    stage: 'starting',
                    message: '正在启动机器人...',
                    progress: 0,
                    active: true,
                    updated_at: Date.now() / 1000,
                },
            });

            const result = windowApi?.runtimeStartBot
                ? await windowApi.runtimeStartBot()
                : await currentApiService.startBot();
            currentToast.show(
                result?.message || (result?.success ? '机器人启动中' : '启动机器人失败'),
                result?.success ? 'success' : 'error'
            );
        }

        emitStatusRefresh(page, { followups: [1000] });
    } catch (error) {
        currentToast.error(currentToast.getErrorMessage(error, '启动机器人失败'));
    } finally {
        btn.disabled = false;
    }
}

export async function toggleGrowth(page, deps = {}) {
    const windowApi = getWindowApi(deps);
    const currentToast = getToast(deps);
    const currentApiService = getApiService(deps);
    const button = page.$('#btn-toggle-growth');
    const buttonText = button?.querySelector('span') || button;
    if (!button) {
        return;
    }

    button.disabled = true;
    try {
        const status = page.getState('bot.status') || {};
        const growthRunning = !!status.growth_running;
        if (growthRunning) {
            const accepted = await ensureGrowthDisablePrompt(deps);
            if (!accepted) {
                return;
            }
            if (buttonText) {
                buttonText.textContent = '停止中...';
            }
            const result = windowApi?.runtimeStopGrowth
                ? await windowApi.runtimeStopGrowth()
                : await currentApiService.request?.('/api/growth/stop', { method: 'POST' });
            currentToast.show(
                result?.message || (result?.success ? '成长任务已停止' : '停止成长任务失败'),
                result?.success ? 'success' : 'error'
            );
        } else {
            if (buttonText) {
                buttonText.textContent = '启动中...';
            }
            const result = windowApi?.runtimeStartGrowth
                ? await windowApi.runtimeStartGrowth()
                : await currentApiService.request?.('/api/growth/start', { method: 'POST' });
            currentToast.show(
                result?.message || (result?.success ? '成长任务已启动' : '启动成长任务失败'),
                result?.success ? 'success' : 'error'
            );
        }

        emitStatusRefresh(page, { followups: [1000] });
    } catch (error) {
        currentToast.error(currentToast.getErrorMessage(error, '成长任务操作失败'));
    } finally {
        button.disabled = false;
        updateBotUI(page);
    }
}

export async function handleGrowthTaskAction(page, event, deps = {}) {
    const button = event?.target?.closest?.('[data-growth-action]');
    if (!button) {
        return;
    }

    const taskType = String(button.dataset.taskType || '').trim();
    const action = String(button.dataset.growthAction || '').trim();
    if (!taskType || !action) {
        return;
    }

    if (action === 'clear') {
        const accepted = await confirmAction({
            kicker: '队列操作',
            title: '确认清空成长任务队列',
            subtitle: '该操作会立即移除当前等待执行的任务。',
            message: `确认清空“${getGrowthTaskLabel(taskType)}”队列吗？`,
            confirmText: '确认清空',
        }, deps);
        if (!accepted) {
            return;
        }
    }

    button.disabled = true;
    try {
        await runGrowthTaskAction(page, taskType, action, deps);
        emitStatusRefresh(page, { followups: [400] });
    } catch (error) {
        const currentToast = getToast(deps);
        currentToast.error(currentToast.getErrorMessage(error, '成长任务操作失败'));
    } finally {
        button.disabled = false;
    }
}

export async function runGrowthTaskAction(page, taskType, action, deps = {}) {
    const currentApiService = getApiService(deps);
    const currentToast = getToast(deps);
    const label = getGrowthTaskLabel(taskType);
    let result = null;

    if (action === 'run') {
        result = await currentApiService.runGrowthTaskNow(taskType);
        currentToast.show(result?.message || `已触发 ${label} 立即执行`, result?.success ? 'success' : 'error');
        return result;
    }

    if (action === 'clear') {
        result = await currentApiService.clearGrowthTask(taskType);
        currentToast.show(result?.message || `已清空 ${label} 队列`, result?.success ? 'success' : 'error');
        return result;
    }

    if (action === 'pause') {
        result = await currentApiService.pauseGrowthTask(taskType);
        currentToast.show(result?.message || `已暂停 ${label}`, result?.success ? 'success' : 'error');
        return result;
    }

    if (action === 'resume') {
        result = await currentApiService.resumeGrowthTask(taskType);
        currentToast.show(result?.message || `已恢复 ${label}`, result?.success ? 'success' : 'error');
        return result;
    }

    throw new Error(`unsupported_growth_action:${action}`);
}

export async function ensureGrowthEnablePrompt(deps = {}) {
    const windowApi = getWindowApi(deps);
    if (!windowApi?.getGrowthPromptState || !windowApi?.markGrowthPromptSeen) {
        return true;
    }
    const promptState = await windowApi.getGrowthPromptState();
    if (promptState?.enableCostSeen) {
        return true;
    }
    const accepted = await confirmAction({
        kicker: '启动提醒',
        title: '确认启动机器人',
        subtitle: '成长任务会随机器人一起启动。',
        message: '启动机器人会自动开启成长任务，并持续消耗模型额度用于后台整理记忆、画像和语料。确认继续吗？',
        confirmText: '确认启动',
    }, deps);
    if (!accepted) {
        return false;
    }
    await windowApi.markGrowthPromptSeen('enable-cost');
    return true;
}

export async function ensureGrowthDisablePrompt(deps = {}) {
    const windowApi = getWindowApi(deps);
    if (!windowApi?.getGrowthPromptState || !windowApi?.markGrowthPromptSeen) {
        return true;
    }
    const promptState = await windowApi.getGrowthPromptState();
    if (promptState?.disableRiskSeen) {
        return true;
    }
    const accepted = await confirmAction({
        kicker: '风险提示',
        title: '确认关闭成长任务',
        subtitle: '关闭后不会影响当前界面操作，但会影响后续回复质量的成长链路。',
        message: '关闭成长任务后，后台记忆整理、画像更新和语料增量处理都会暂停，可能影响后续回复质量。确认继续吗？',
        confirmText: '确认关闭',
    }, deps);
    if (!accepted) {
        return false;
    }
    await windowApi.markGrowthPromptSeen('disable-risk');
    return true;
}

export async function confirmAction(options, deps = {}) {
    const confirmFn = getConfirmFn(deps);
    if (typeof confirmFn === 'function') {
        return confirmFn(options);
    }
    return true;
}

export async function togglePause(page, deps = {}) {
    const currentApiService = getApiService(deps);
    const currentToast = getToast(deps);
    await runDashboardActionWithLock(page, 'toggle-pause', deps, async () => {
        try {
            const isPaused = !!page.getState('bot.paused');
            const result = isPaused
                ? await currentApiService.resumeBot()
                : await currentApiService.pauseBot();

            currentToast.show(
                result?.message || (result?.success ? '操作成功' : '操作失败'),
                result?.success ? 'success' : 'error'
            );
            page.emit(Events.BOT_STATUS_CHANGE, {});
        } catch (error) {
            currentToast.error(currentToast.getErrorMessage(error, '暂停/恢复失败'));
        }
    });
}

export async function restartBot(page, deps = {}) {
    const currentApiService = getApiService(deps);
    const currentToast = getToast(deps);
    await runDashboardActionWithLock(page, 'restart-bot', deps, async () => {
        try {
            currentToast.info('正在重启机器人...');
            const result = await currentApiService.restartBot();
            currentToast.show(
                result?.message || (result?.success ? '机器人正在重启' : '重启机器人失败'),
                result?.success ? 'success' : 'error'
            );
            emitStatusRefresh(page, { followups: [1000, 2500, 5000], payload: { force: true, refreshReadiness: true } });
        } catch (error) {
            if (isTransientRestartError(error)) {
                currentToast.warning('重启请求可能已提交，正在持续检查运行状态...');
                emitStatusRefresh(page, { followups: [800, 2200, 4500, 8000], payload: { force: true, refreshReadiness: true } });
                return;
            }
            currentToast.error(currentToast.getErrorMessage(error, '重启机器人失败'));
        }
    });
}

export async function recoverBot(page, deps = {}) {
    const currentApiService = getApiService(deps);
    const currentToast = getToast(deps);
    const readinessAction = pickSuggestedSelfHealAction(page.getState('readiness.report'));
    if (readinessAction?.action) {
        currentToast.info(`先处理启动前阻塞项：${readinessAction.label}`);
        await runReadinessAction(page, readinessAction.action, deps);
        return;
    }
    await runDashboardActionWithLock(page, 'recover-bot', deps, async () => {
        try {
            currentToast.info('正在尝试恢复机器人...');
            const result = await currentApiService.recoverBot();
            currentToast.show(
                result?.message || (result?.success ? '机器人恢复中' : '恢复机器人失败'),
                result?.success ? 'success' : 'error'
            );
            emitStatusRefresh(page, { followups: [1500] });
        } catch (error) {
            currentToast.error(currentToast.getErrorMessage(error, '恢复机器人失败'));
        }
    });
}
