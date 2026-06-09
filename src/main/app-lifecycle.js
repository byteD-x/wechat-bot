function createRendererCrashRecovery(options = {}) {
    const coerceInt = (value, fallback, minValue) => {
        const next = Math.floor(Number(value));
        if (!Number.isFinite(next)) {
            return fallback;
        }
        return Math.max(minValue, next);
    };
    const maxReloads = coerceInt(options.maxReloads, 3, 1);
    const windowMs = coerceInt(options.windowMs, 60000, 1000);
    const reloadDelayMs = coerceInt(options.reloadDelayMs, 800, 0);
    const now = typeof options.now === 'function' ? options.now : () => Date.now();
    const setTimer = typeof options.setTimer === 'function' ? options.setTimer : setTimeout;
    const logger = options.logger || console;
    const crashes = [];

    const prune = (timestamp) => {
        while (crashes.length && (timestamp - crashes[0]) > windowMs) {
            crashes.shift();
        }
    };

    return {
        handleGone(win, details = {}) {
            const timestamp = now();
            prune(timestamp);
            if (crashes.length >= maxReloads) {
                logger?.warn?.('[MainWindow] Renderer crash recovery suppressed:', {
                    crashCount: crashes.length + 1,
                    maxReloads,
                    windowMs,
                    details,
                });
                return {
                    action: 'reload_suppressed',
                    crashCount: crashes.length + 1,
                    maxReloads,
                    windowMs,
                };
            }

            crashes.push(timestamp);
            setTimer(() => {
                try {
                    if (win && !win.isDestroyed()) {
                        win.reload();
                    }
                } catch (_) {}
            }, reloadDelayMs);
            return {
                action: 'reload_scheduled',
                crashCount: crashes.length,
                maxReloads,
                windowMs,
                reloadDelayMs,
            };
        },
    };
}

async function stopBackendAndQuit({
    GLOBAL_STATE,
    BackendManager,
    app,
    reason = 'quit',
    logger = console,
} = {}) {
    if (GLOBAL_STATE) {
        GLOBAL_STATE.isQuitting = true;
        if (GLOBAL_STATE.tray) {
            try {
                GLOBAL_STATE.tray.destroy();
            } catch (_) {}
            GLOBAL_STATE.tray = null;
        }
    }

    let stopFailed = false;
    try {
        await BackendManager?.stop?.(reason);
    } catch (error) {
        stopFailed = true;
        logger?.warn?.('[Lifecycle] backend stop before quit failed:', error?.message || error);
    } finally {
        app?.quit?.();
    }

    return stopFailed
        ? { success: true, action: 'quit', warning: 'backend_stop_failed' }
        : { success: true, action: 'quit' };
}

async function installPreparedUpdateAndQuit({
    GLOBAL_STATE,
    BackendManager,
    app,
    updateManager,
    logger = console,
} = {}) {
    const manager = updateManager || GLOBAL_STATE?.updateManager;
    const prepareResult = manager?.prepareInstall?.() || {
        success: false,
        error: 'update manager unavailable',
    };
    if (!prepareResult.success) {
        return prepareResult;
    }

    if (GLOBAL_STATE) {
        GLOBAL_STATE.installingUpdate = true;
    }

    try {
        await BackendManager?.stop?.('install-update');
    } catch (error) {
        if (GLOBAL_STATE) {
            GLOBAL_STATE.installingUpdate = false;
        }
        logger?.warn?.('[Lifecycle] backend stop before update install failed:', error?.message || error);
        return {
            success: false,
            error: 'backend_stop_failed',
        };
    }

    const launchResult = manager?.launchPreparedInstaller?.() || {
        success: false,
        error: 'installer launch unavailable',
    };
    if (!launchResult.success) {
        if (GLOBAL_STATE) {
            GLOBAL_STATE.installingUpdate = false;
        }
        return launchResult;
    }

    if (GLOBAL_STATE) {
        GLOBAL_STATE.isQuitting = true;
        if (GLOBAL_STATE.tray) {
            try {
                GLOBAL_STATE.tray.destroy();
            } catch (_) {}
            GLOBAL_STATE.tray = null;
        }
    }
    app?.quit?.();
    return { success: true, action: 'install-update' };
}

module.exports = {
    createRendererCrashRecovery,
    installPreparedUpdateAndQuit,
    stopBackendAndQuit,
};
