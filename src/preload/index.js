/**
 * 微信AI助手 - 预加载脚本
 * 
 * 在渲染进程加载前执行，安全地暴露主进程 API
 */

const { contextBridge, ipcRenderer } = require('electron');

const listenerRegistry = new Map();

function ensureCallback(name, callback) {
    if (typeof callback === 'function') {
        return callback;
    }
    console.warn(`[Preload] ${name} callback must be a function`);
    return null;
}

function trackListener(channel, callback, handler) {
    let channelMap = listenerRegistry.get(channel);
    if (!channelMap) {
        channelMap = new Map();
        listenerRegistry.set(channel, channelMap);
    }
    channelMap.set(callback, handler);
}

function removeRegisteredListeners(channel, callback) {
    const channelMap = listenerRegistry.get(channel);
    if (!channelMap || channelMap.size === 0) {
        return;
    }
    if (typeof callback === 'function') {
        const handler = channelMap.get(callback);
        if (handler) {
            ipcRenderer.removeListener(channel, handler);
            channelMap.delete(callback);
        }
    } else {
        for (const handler of channelMap.values()) {
            ipcRenderer.removeListener(channel, handler);
        }
        channelMap.clear();
    }
    if (channelMap.size === 0) {
        listenerRegistry.delete(channel);
    }
}

function onChannel(channel, callback, transform) {
    const safeCallback = ensureCallback(channel, callback);
    if (!safeCallback) {
        return () => {};
    }
    const handler = (...args) => {
        try {
            safeCallback(transform(...args));
        } catch (error) {
            console.error(`[Preload] ${channel} callback failed:`, error);
        }
    };
    ipcRenderer.on(channel, handler);
    trackListener(channel, safeCallback, handler);
    return () => removeRegisteredListeners(channel, safeCallback);
}

// 暴露安全的 API 到渲染进程
contextBridge.exposeInMainWorld('electronAPI', {
    // ═══════════════════════════════════════════════════════════════════════
    //                           后端通信
    // ═══════════════════════════════════════════════════════════════════════

    /**
     * 获取 Flask 服务地址
     */
    getFlaskUrl: () => ipcRenderer.invoke('get-flask-url'),
    getSseTicket: () => ipcRenderer.invoke('get-sse-ticket'),
    backendRequest: (options) => ipcRenderer.invoke('backend:request', options || {}),

    /**
     * 检查后端是否运行
     */
    checkBackend: () => ipcRenderer.invoke('check-backend'),

    /**
     * 启动后端服务
     */
    startBackend: () => ipcRenderer.invoke('start-backend'),
    configGet: () => ipcRenderer.invoke('config:get'),
    configPatch: (patch) => ipcRenderer.invoke('config:patch', patch),
    configSubscribe: () => ipcRenderer.invoke('config:subscribe'),
    testConfigConnection: (options) => ipcRenderer.invoke('config:test-connection', options),
    runtimeEnsureService: () => ipcRenderer.invoke('runtime:ensure-service'),
    runtimeStartBot: () => ipcRenderer.invoke('runtime:start-bot'),
    runtimeStopBot: () => ipcRenderer.invoke('runtime:stop-bot'),
    runtimeStartGrowth: () => ipcRenderer.invoke('runtime:start-growth'),
    runtimeStopGrowth: () => ipcRenderer.invoke('runtime:stop-growth'),
    getRuntimeIdleState: () => ipcRenderer.invoke('runtime:get-idle-state'),
    runtimeReportStatus: (summary) => ipcRenderer.invoke('runtime:report-status', summary),
    runtimeCancelIdleShutdown: () => ipcRenderer.invoke('runtime:cancel-idle-shutdown'),
    getGrowthPromptState: () => ipcRenderer.invoke('growth:get-prompt-state'),
    markGrowthPromptSeen: (kind) => ipcRenderer.invoke('growth:mark-prompt-seen', kind),

    // ═══════════════════════════════════════════════════════════════════════
    //                           窗口控制
    // ═══════════════════════════════════════════════════════════════════════

    /**
     * 最小化窗口
     */
    minimizeWindow: () => ipcRenderer.invoke('window-minimize'),

    /**
     * 最大化/还原窗口
     */
    maximizeWindow: () => ipcRenderer.invoke('window-maximize'),

    /**
     * 关闭窗口（最小化到托盘）
     */
    closeWindow: () => ipcRenderer.invoke('window-close'),

    /**
     * 最小化到托盘
     */
    minimizeToTray: () => ipcRenderer.invoke('minimize-to-tray'),

    // ═══════════════════════════════════════════════════════════════════════
    //                           其他功能
    // ═══════════════════════════════════════════════════════════════════════

    /**
     * 打开外部链接
     */
    openExternal: (url) => ipcRenderer.invoke('open-external', url),

    /**
     * 打开微信客户端
     */
    openWeChat: () => ipcRenderer.invoke('open-wechat'),
    restartAppAsAdmin: () => ipcRenderer.invoke('restart-app-as-admin'),

    /**
     * 获取应用版本
     */
    getAppVersion: () => ipcRenderer.invoke('get-app-version'),
    getUpdateState: () => ipcRenderer.invoke('get-update-state'),
    checkForUpdates: (options) => ipcRenderer.invoke('check-for-updates', options),
    skipUpdateVersion: (version) => ipcRenderer.invoke('skip-update-version', version),
    downloadUpdate: () => ipcRenderer.invoke('download-update'),
    installDownloadedUpdate: () => ipcRenderer.invoke('install-downloaded-update'),
    openUpdateDownload: () => ipcRenderer.invoke('open-update-download'),
    exportDiagnosticsSnapshot: () => ipcRenderer.invoke('export-diagnostics-snapshot'),

    // ═══════════════════════════════════════════════════════════════════════
    //                           事件监听
    // ═══════════════════════════════════════════════════════════════════════

    /**
     * 监听托盘操作
     */
    onTrayAction: (callback) => onChannel('tray-action', callback, (_event, action) => action),

    /**
     * 移除托盘操作监听
     */
    removeTrayActionListener: (callback) => removeRegisteredListeners('tray-action', callback),

    onAppCloseDialog: (callback) => onChannel('app-close-dialog', callback, () => undefined),

    onConfigChanged: (callback) => onChannel('config:changed', callback, (_event, payload) => payload),

    onRuntimeIdleStateChanged: (callback) => onChannel('runtime:idle-state-changed', callback, (_event, payload) => payload),

    removeConfigChangedListener: (callback) => removeRegisteredListeners('config:changed', callback),

    removeRuntimeIdleStateListener: (callback) => removeRegisteredListeners('runtime:idle-state-changed', callback),

    confirmCloseAction: (action, remember) => ipcRenderer.invoke('confirm-close-action', { action, remember }),

    resetCloseBehavior: () => ipcRenderer.invoke('reset-close-behavior'),

    // ═══════════════════════════════════════════════════════════════════════
    //                           首次运行
    // ═══════════════════════════════════════════════════════════════════════

    /**
     * 检查是否首次运行
     */
    isFirstRun: () => ipcRenderer.invoke('is-first-run'),

    /**
     * 标记首次运行完成
     */
    setFirstRunComplete: () => ipcRenderer.invoke('set-first-run-complete'),
    onUpdateStateChanged: (callback) => onChannel('update-state-changed', callback, (_event, state) => state),
    removeUpdateStateListener: (callback) => removeRegisteredListeners('update-state-changed', callback)
});

console.log('[Preload] API 已暴露到 window.electronAPI');
