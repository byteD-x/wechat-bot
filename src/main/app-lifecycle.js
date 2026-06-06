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

module.exports = {
    stopBackendAndQuit,
};
