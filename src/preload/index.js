/**
 * 微信AI助手 - 预加载脚本
 * 
 * 在渲染进程加载前执行，安全地暴露主进程 API
 */

const { contextBridge, ipcRenderer } = require('electron');

// 暴露安全的 API 到渲染进程
contextBridge.exposeInMainWorld('electronAPI', {
    // ═══════════════════════════════════════════════════════════════════════
    //                           后端通信
    // ═══════════════════════════════════════════════════════════════════════

    /**
     * 获取 Flask 服务地址
     */
    getFlaskUrl: () => ipcRenderer.invoke('get-flask-url'),

    getApiToken: () => ipcRenderer.invoke('get-api-token'),

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
    onTrayAction: (callback) => {
        ipcRenderer.on('tray-action', (event, action) => callback(action));
    },

    /**
     * 移除托盘操作监听
     */
    removeTrayActionListener: () => {
        ipcRenderer.removeAllListeners('tray-action');
    },

    onAppCloseDialog: (callback) => {
        ipcRenderer.on('app-close-dialog', () => callback());
    },

    onConfigChanged: (callback) => {
        const handler = (_, payload) => callback(payload);
        ipcRenderer.on('config:changed', handler);
        return () => ipcRenderer.removeListener('config:changed', handler);
    },

    onRuntimeIdleStateChanged: (callback) => {
        const handler = (_, payload) => callback(payload);
        ipcRenderer.on('runtime:idle-state-changed', handler);
        return () => ipcRenderer.removeListener('runtime:idle-state-changed', handler);
    },

    removeConfigChangedListener: () => {
        ipcRenderer.removeAllListeners('config:changed');
    },

    removeRuntimeIdleStateListener: () => {
        ipcRenderer.removeAllListeners('runtime:idle-state-changed');
    },

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
    onUpdateStateChanged: (callback) => {
        const handler = (_, state) => callback(state);
        ipcRenderer.on('update-state-changed', handler);
        return () => ipcRenderer.removeListener('update-state-changed', handler);
    },
    removeUpdateStateListener: () => {
        ipcRenderer.removeAllListeners('update-state-changed');
    }
});

console.log('[Preload] API 已暴露到 window.electronAPI');
