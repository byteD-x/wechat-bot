import { Events } from '../../core/EventBus.js';
import { apiService } from '../../services/ApiService.js';
import { toast } from '../../services/NotificationService.js';
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

function emitStatusRefresh(page, payload = {}, followups = []) {
    page.emit(Events.BOT_STATUS_CHANGE, payload);
    followups.forEach((delayMs) => {
        setTimeout(() => page.emit(Events.BOT_STATUS_CHANGE, payload), delayMs);
    });
}

export function handleIdleActionClick(page, event, deps = {}) {
    const target = event?.target;
    const button = typeof target?.closest === 'function' ? target.closest('button') : null;
    if (!button || button.disabled || button.hidden) {
        return;
    }

    if (button.id === 'btn-cancel-idle-shutdown') {
        event.preventDefault?.();
        event.stopPropagation?.();
        getToast(deps).info('正在处理自动停机设置...');
        void cancelIdleShutdown(page, deps);
        return;
    }

    if (button.id === 'btn-wake-backend') {
        event.preventDefault?.();
        event.stopPropagation?.();
        getToast(deps).info('正在尝试唤醒后端服务...');
        void wakeBackend(page, deps);
    }
}

export function startIdleTimer(page) {
    if (page._idleRenderTimer) {
        return;
    }
    page._idleRenderTimer = setInterval(() => {
        if (page.isActive()) {
            page._renderIdlePanel();
        }
    }, 1000);
}

export function stopIdleTimer(page) {
    if (!page._idleRenderTimer) {
        return;
    }
    clearInterval(page._idleRenderTimer);
    page._idleRenderTimer = null;
}

export function getIdleState(page) {
    return page.getState('backend.idle') || {
        state: 'active',
        delayMs: 15 * 60 * 1000,
        remainingMs: 15 * 60 * 1000,
        reason: '',
        updatedAt: Date.now(),
    };
}

export function getIdleRemainingMs(page, idleState = getIdleState(page)) {
    if (!idleState || idleState.state !== 'countdown') {
        return Math.max(0, Number(idleState?.remainingMs || 0));
    }
    const updatedAt = Number(idleState.updatedAt || Date.now());
    const elapsed = Math.max(0, Date.now() - updatedAt);
    return Math.max(0, Number(idleState.remainingMs || 0) - elapsed);
}

export async function cancelIdleShutdown(page, deps = {}) {
    const currentToast = getToast(deps);
    const windowApi = getWindowApi(deps);
    const currentIdleState = getIdleState(page);
    if (currentIdleState.state === 'active') {
        currentToast.info('当前没有进行中的自动停机计时');
        return;
    }
    if (currentIdleState.state === 'stopped_by_idle') {
        currentToast.info('后端已经休眠，可以直接点击立即唤醒');
        return;
    }
    if (!windowApi?.runtimeCancelIdleShutdown) {
        currentToast.warning('当前版本不支持取消自动停机，请重启应用后重试');
        return;
    }
    try {
        const result = await windowApi.runtimeCancelIdleShutdown();
        const idleState = result?.idle_state || (
            windowApi?.getRuntimeIdleState
                ? await windowApi.getRuntimeIdleState()
                : null
        );
        if (idleState) {
            page.setState('backend.idle', idleState);
        }
        page._renderIdlePanel();
        page.emit(Events.BOT_STATUS_CHANGE, { force: true });
        currentToast.success('已重置本轮后端休眠计时');
    } catch (error) {
        currentToast.error(currentToast.getErrorMessage(error, '取消自动停机失败'));
    }
}

export async function wakeBackend(page, deps = {}) {
    const currentToast = getToast(deps);
    const windowApi = getWindowApi(deps);
    const currentApiService = getApiService(deps);
    const currentIdleState = getIdleState(page);
    if (page.getState('bot.connected') && currentIdleState.state === 'active') {
        currentToast.info('后端当前已经在线，无需额外唤醒');
        return;
    }
    try {
        if (windowApi?.runtimeEnsureService) {
            await windowApi.runtimeEnsureService();
        } else if (windowApi?.startBackend) {
            await windowApi.startBackend();
        } else {
            currentToast.warning('当前版本不支持立即唤醒，请重启应用后重试');
            return;
        }

        if (windowApi?.getRuntimeIdleState) {
            const idleState = await windowApi.getRuntimeIdleState();
            page.setState('backend.idle', idleState);
        }

        try {
            const status = await currentApiService.getStatus();
            applyStatusSnapshot(page, status, deps);
        } catch (error) {
            console.warn('[DashboardPage] wake backend status refresh failed:', error);
        }

        emitStatusRefresh(page, { force: true }, [600]);
        emitStatusRefresh(page, {}, [600]);
        currentToast.success('后端已唤醒');
    } catch (error) {
        currentToast.error(currentToast.getErrorMessage(error, '唤醒后端失败'));
    }
}

export function applyStatusSnapshot(page, status, deps = {}) {
    if (!status || typeof status !== 'object') {
        return;
    }

    page.setState('bot.connected', true);
    page.setState('bot.running', !!status.running);
    page.setState('bot.paused', !!status.is_paused);
    page.setState('bot.status', status);
    (deps.updateBotUI || updateBotUI)(page);
}
