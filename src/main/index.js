/**
 * 微信AI助手 - Electron 主进程
 * 
 * 架构优化说明：
 * 1. 采用 ready-to-show 事件机制，彻底消除白屏闪烁
 * 2. 异步并行启动 Python 后端，不阻塞 UI 渲染
 * 3. 模块化组织代码，提升可维护性
 * 4. 增强的进程生命周期管理
 */

const { app, BrowserWindow, Tray, Menu, ipcMain, shell, nativeImage, Notification, dialog } = require('electron');
const fs = require('fs');
const path = require('path');
const { spawn, exec, execFile } = require('child_process');
const http = require('http');
const crypto = require('crypto');
const Store = require('electron-store');
const iconv = require('iconv-lite');
const { UpdateManager } = require('./update-manager');
const { BackendIdleController, DEFAULT_IDLE_SHUTDOWN_MS } = require('./backend-idle-controller');
const { createBackendManager } = require('./backend-manager');
const {
    createConfigCli,
    createSharedConfigService,
} = require('./shared-config');
const { registerIpcHandlers } = require('./ipc');

// Electron on Windows can be launched without a valid stdout/stderr (or the pipe can be closed),
// which makes console.* throw synchronously with EPIPE and crash the main process.
function installBrokenPipeGuards() {
    const wrapWrite = (stream) => {
        if (!stream || typeof stream.write !== 'function') return;
        const origWrite = stream.write.bind(stream);
        stream.write = (...args) => {
            try {
                return origWrite(...args);
            } catch (e) {
                if (e && e.code === 'EPIPE') return false;
                throw e;
            }
        };
        if (typeof stream.on === 'function') {
            stream.on('error', (e) => {
                if (e && e.code === 'EPIPE') return;
            });
        }
    };

    wrapWrite(process.stdout);
    wrapWrite(process.stderr);
}
installBrokenPipeGuards();

// ═══════════════════════════════════════════════════════════════════════════════
//                               配置与全局状态
// ═══════════════════════════════════════════════════════════════════════════════

const store = new Store({
    defaults: {
        windowBounds: { width: 1200, height: 800 },
        startMinimized: false,
        autoStartBot: false,
        flaskPort: 5000,
        isFirstRun: true,
        closeBehavior: 'ask',
        apiToken: '',
        growthEnableCostPromptSeen: false,
        growthDisableRiskPromptSeen: false,
        update: {
            feedUrl: '',
            autoCheckOnLaunch: true,
            checkIntervalHours: 6,
            notifyOnUpdate: true,
            skippedVersion: '',
            lastCheckedAt: '',
            downloadedVersion: '',
            downloadedInstallerPath: ''
        }
    }
});

const GLOBAL_STATE = {
    mainWindow: null,
    splashWindow: null,
    tray: null,
    pythonProcess: null,
    updateManager: null,
    installingUpdate: false,
    isQuitting: false,
    isDev: process.argv.includes('--dev'),
    flaskPort: store.get('flaskPort'),
    apiToken: (() => {
        const existing = String(store.get('apiToken') || '').trim();
        if (existing) {
            return existing;
        }
        const next = crypto.randomBytes(24).toString('hex');
        store.set('apiToken', next);
        return next;
    })(),
    get flaskUrl() { return `http://localhost:${this.flaskPort}`; }
};

function getMainWindowSafe() {
    const win = GLOBAL_STATE.mainWindow;
    if (!win || (typeof win.isDestroyed === 'function' && win.isDestroyed())) return null;
    return win;
}

function showMainWindowSafe() {
    const win = getMainWindowSafe();
    if (!win) return false;
    try {
        if (typeof win.isMinimized === 'function' && win.isMinimized()) win.restore();
        win.show();
        win.focus();
        return true;
    } catch (e) {
        return false;
    }
}

function getMainWindowVisible() {
    const win = getMainWindowSafe();
    if (!win) {
        return false;
    }
    try {
        return win.isVisible() && !win.isMinimized();
    } catch (e) {
        return false;
    }
}

function sendToMainWindowSafe(channel, ...args) {
    const win = getMainWindowSafe();
    if (!win) return false;
    const wc = win.webContents;
    if (!wc || (typeof wc.isDestroyed === 'function' && wc.isDestroyed())) return false;
    try {
        wc.send(channel, ...args);
        return true;
    } catch (e) {
        return false;
    }
}

function broadcastToRenderer(channel, payload) {
    for (const win of BrowserWindow.getAllWindows()) {
        if (!win || (typeof win.isDestroyed === 'function' && win.isDestroyed())) {
            continue;
        }
        const webContents = win.webContents;
        if (!webContents || (typeof webContents.isDestroyed === 'function' && webContents.isDestroyed())) {
            continue;
        }
        try {
            webContents.send(channel, payload);
        } catch (_) {}
    }
}

function updateSplashStatus(message, progress = 0) {
    const splash = GLOBAL_STATE.splashWindow;
    if (!splash || splash.isDestroyed()) {
        return;
    }
    const safeMessage = JSON.stringify(String(message || '正在初始化...'));
    const safeProgress = Number.isFinite(progress) ? Math.max(0, Math.min(progress, 100)) : 0;
    splash.webContents.executeJavaScript(
        `window.updateSplashStatus && window.updateSplashStatus(${safeMessage}, ${safeProgress});`
    ).catch(() => {});
}

// ═══════════════════════════════════════════════════════════════════════════════
//                               工具函数
// ═══════════════════════════════════════════════════════════════════════════════

const PathUtils = {
    get resourcePath() {
        return GLOBAL_STATE.isDev 
            ? path.join(__dirname, '..', '..') 
            : process.resourcesPath;
    },
    
    get iconPath() {
        return path.join(__dirname, '..', 'assets', 'icon.png');
    },

    get backendExecutable() {
        if (GLOBAL_STATE.isDev) return null;
        const candidates = [
            path.join(process.resourcesPath, 'backend', 'wechat-bot-backend.exe'),
            path.join(process.resourcesPath, 'backend', 'wechat-bot-backend', 'wechat-bot-backend.exe')
        ];
        return candidates.find(candidate => fs.existsSync(candidate)) || candidates[candidates.length - 1];
    }
};

function ensureDir(dirPath) {
    fs.mkdirSync(dirPath, { recursive: true });
    return dirPath;
}

function getSharedDataRoot() {
    if (GLOBAL_STATE.isDev) {
        return ensureDir(path.join(PathUtils.resourcePath, 'data'));
    }
    return ensureDir(path.join(app.getPath('userData'), 'data'));
}

function getSharedConfigPath() {
    return path.join(getSharedDataRoot(), 'app_config.json');
}

function getSharedModelCatalogPath() {
    return path.join(PathUtils.resourcePath, 'shared', 'model_catalog.json');
}

function getBackendSpawnOptions() {
    const env = {
        ...process.env,
        WECHAT_BOT_API_TOKEN: GLOBAL_STATE.apiToken,
        WECHAT_BOT_DATA_DIR: getSharedDataRoot(),
        PYTHONLEGACYWINDOWSSTDIO: '1',
    };
    if (GLOBAL_STATE.isDev) {
        env.PYTHONUNBUFFERED = '1';
        env.PYTHONIOENCODING = 'utf-8';
    }
    return env;
}

function getBackendCommand(commandArgs = []) {
    if (GLOBAL_STATE.isDev) {
        const venvPython = path.join(PathUtils.resourcePath, '.venv', 'Scripts', 'python.exe');
        return {
            cmd: venvPython,
            args: ['run.py', ...commandArgs],
            options: {
                cwd: PathUtils.resourcePath,
                env: getBackendSpawnOptions(),
            },
        };
    }

    const exePath = PathUtils.backendExecutable;
    return {
        cmd: exePath,
        args: commandArgs,
        options: {
            cwd: path.dirname(exePath),
            env: getBackendSpawnOptions(),
        },
    };
}

// ═══════════════════════════════════════════════════════════════════════════════
//                               Python 后端管理
// ═══════════════════════════════════════════════════════════════════════════════

const RUNTIME_IDLE_CONTROLLER = new BackendIdleController({
    delayMs: DEFAULT_IDLE_SHUTDOWN_MS,
    onStateChange: (idleState) => {
        broadcastToRenderer('runtime:idle-state-changed', idleState);
    },
    onStopService: async () => {
        await BackendManager.stop('idle_timeout');
    },
});

const BackendManager = createBackendManager({
    http,
    spawn,
    iconv,
    GLOBAL_STATE,
    getBackendCommand,
    getMainWindowVisible,
    updateSplashStatus,
    runtimeIdleController: RUNTIME_IDLE_CONTROLLER,
});

function getRuntimeIdleState() {
    return RUNTIME_IDLE_CONTROLLER.getState();
}

function applyRuntimeStatusSummary(summary = {}) {
    RUNTIME_IDLE_CONTROLLER.setWindowVisible(getMainWindowVisible());
    return RUNTIME_IDLE_CONTROLLER.updateRuntime({
        botRunning: !!summary.botRunning,
        growthRunning: !!summary.growthRunning,
    });
}

function applyRuntimeStatus(status) {
    if (!status || typeof status !== 'object') {
        return getRuntimeIdleState();
    }
    return applyRuntimeStatusSummary({
        botRunning: !!(status.bot_running ?? status.running),
        growthRunning: !!status.growth_running,
    });
}

const ConfigCli = createConfigCli({
    spawn,
    getBackendCommand,
    getSharedConfigPath,
});

const SharedConfigService = createSharedConfigService({
    ConfigCli,
    getSharedConfigPath,
    getSharedModelCatalogPath,
    ensureDir,
    listWindows: () => BrowserWindow.getAllWindows(),
    backendCheckServer: () => BackendManager.checkServer(),
    backendRequestJson: (...args) => BackendManager.requestJson(...args),
});

const RuntimeManager = {
    async ensureService() {
        await BackendManager.ensureReady();
        const status = await this.safeStatus();
        applyRuntimeStatus(status);
        return { success: true, idle_state: getRuntimeIdleState() };
    },

    async startBot() {
        await BackendManager.ensureReady();
        const result = await BackendManager.requestJson('POST', '/api/start', null, 45000);
        const status = await this.safeStatus();
        applyRuntimeStatus(status);
        return result;
    },

    async stopBot() {
        const result = await BackendManager.requestJson('POST', '/api/stop');
        const status = await this.safeStatus();
        applyRuntimeStatus(status);
        return {
            ...result,
            service_stopped: false,
            idle_state: getRuntimeIdleState(),
        };
    },

    async startGrowth() {
        await BackendManager.ensureReady();
        const result = await BackendManager.requestJson('POST', '/api/growth/start', null, 45000);
        const status = await this.safeStatus();
        applyRuntimeStatus(status);
        return result;
    },

    async stopGrowth() {
        const result = await BackendManager.requestJson('POST', '/api/growth/stop');
        const status = await this.safeStatus();
        applyRuntimeStatus(status);
        return {
            ...result,
            service_stopped: false,
            idle_state: getRuntimeIdleState(),
        };
    },

    async safeStatus() {
        if (!(await BackendManager.checkServer())) {
            return null;
        }
        try {
            return await BackendManager.requestJson('GET', '/api/status');
        } catch (_) {
            return null;
        }
    },
};

const GrowthPromptStore = {
    getState() {
        return {
            enableCostSeen: !!store.get('growthEnableCostPromptSeen'),
            disableRiskSeen: !!store.get('growthDisableRiskPromptSeen'),
        };
    },

    markSeen(kind) {
        if (kind === 'enable-cost') {
            store.set('growthEnableCostPromptSeen', true);
        }
        if (kind === 'disable-risk') {
            store.set('growthDisableRiskPromptSeen', true);
        }
        return this.getState();
    },
};

async function requestAppClose(options = {}) {
    const { showWindow } = options;
    const win = getMainWindowSafe();
    const pref = store.get('closeBehavior') || 'ask';
    if (pref === 'minimize') {
        try { win?.hide(); } catch (e) {}
        return { action: 'minimize' };
    }
    if (pref === 'quit') {
        GLOBAL_STATE.isQuitting = true;
        if (GLOBAL_STATE.tray) {
            GLOBAL_STATE.tray.destroy();
            GLOBAL_STATE.tray = null;
        }
        await BackendManager.stop('quit');
        app.quit();
        return { action: 'quit' };
    }
    if (showWindow) {
        showMainWindowSafe();
    }
    sendToMainWindowSafe('app-close-dialog');
    return { action: 'ask' };
}

async function installDownloadedUpdateAndQuit() {
    const prepareResult = GLOBAL_STATE.updateManager?.prepareInstall() || {
        success: false,
        error: 'update manager unavailable'
    };
    if (!prepareResult.success) {
        return prepareResult;
    }

    GLOBAL_STATE.installingUpdate = true;
    setTimeout(async () => {
        try {
            GLOBAL_STATE.isQuitting = true;
            if (GLOBAL_STATE.tray) {
                GLOBAL_STATE.tray.destroy();
                GLOBAL_STATE.tray = null;
            }
            await BackendManager.stop('install-update');
        } catch (error) {
            console.warn('[Update] stop backend before install failed:', error?.message || error);
        } finally {
            app.quit();
        }
    }, 150);

    return { success: true };
}

// ═══════════════════════════════════════════════════════════════════════════════
//                               窗口管理
// ═══════════════════════════════════════════════════════════════════════════════

const WindowManager = {
    createSplash() {
        GLOBAL_STATE.splashWindow = new BrowserWindow({
            width: 400,
            height: 300,
            frame: false,
            transparent: true,
            resizable: false,
            center: true,
            skipTaskbar: true,
            alwaysOnTop: true,
            focusable: false,
            webPreferences: { contextIsolation: true, nodeIntegration: false }
        });
        // Splash is display-only. Never let it intercept clicks intended for the main window.
        try {
            GLOBAL_STATE.splashWindow.setIgnoreMouseEvents(true);
        } catch (e) {
            console.warn('[Splash] Failed to ignore mouse events:', e?.message || e);
        }
        GLOBAL_STATE.splashWindow.loadFile(path.join(__dirname, '..', 'renderer', 'splash.html'));
        updateSplashStatus('正在启动桌面客户端...', 12);
    },

    createMain() {
        const { width, height } = store.get('windowBounds');

        // Close any existing (possibly hidden) main window instance.
        try {
            const existing = GLOBAL_STATE.mainWindow;
            if (existing && !existing.isDestroyed()) {
                existing.removeAllListeners();
                existing.close();
            }
        } catch (e) {
            // ignore
        }

        GLOBAL_STATE.mainWindow = new BrowserWindow({
            width, height,
            minWidth: 900,
            minHeight: 600,
            title: '微信AI助手',
            icon: PathUtils.iconPath,
            backgroundColor: '#F3EFE7', // 关键：与 CSS 背景一致，防止白屏
            frame: false,
            show: false, // 关键：初始隐藏
            webPreferences: {
                preload: path.join(__dirname, '..', 'preload', 'index.js'),
                contextIsolation: true,
                nodeIntegration: false,
                devTools: GLOBAL_STATE.isDev
            }
        });

        GLOBAL_STATE.mainWindow.loadFile(path.join(__dirname, '..', 'renderer', 'index.html'));
        updateSplashStatus('正在加载界面资源...', 72);

        GLOBAL_STATE.mainWindow.webContents.on('console-message', (_event, level, message, line, sourceId) => {
            const safeSource = sourceId ? `${sourceId}:${line}` : `line:${line}`;
            console.log(`[Renderer:${level}] ${safeSource} ${message}`);
        });
        GLOBAL_STATE.mainWindow.webContents.on('did-fail-load', (_event, errorCode, errorDescription, validatedURL) => {
            console.error(`[Renderer Load Failed] ${errorCode} ${errorDescription} ${validatedURL || ''}`.trim());
        });
        GLOBAL_STATE.mainWindow.webContents.on('dom-ready', () => {
            console.log('[Renderer] dom-ready');
        });
        GLOBAL_STATE.mainWindow.webContents.on('did-finish-load', () => {
            console.log('[Renderer] did-finish-load');
            const splash = GLOBAL_STATE.splashWindow;
            if (splash && !splash.isDestroyed()) {
                try { splash.close(); } catch (e) {}
                GLOBAL_STATE.splashWindow = null;
            }
        });

        GLOBAL_STATE.mainWindow.webContents.setWindowOpenHandler(({ url }) => {
            if (typeof url === 'string' && /^(https?|mailto):/i.test(url)) {
                shell.openExternal(url);
            } else {
                console.warn('[WindowOpen] Blocked:', url);
            }
            return { action: 'deny' };
        });

        this._setupMainListeners();

        GLOBAL_STATE.mainWindow.on('closed', () => {
            if (GLOBAL_STATE.mainWindow && GLOBAL_STATE.mainWindow.isDestroyed()) {
                GLOBAL_STATE.mainWindow = null;
            }
        });
        
        // if (GLOBAL_STATE.isDev) GLOBAL_STATE.mainWindow.webContents.openDevTools();
    },

    _setupWebSecurity() {
        const win = GLOBAL_STATE.mainWindow;
        if (!win || win.isDestroyed()) {
            return;
        }

        win.webContents.on('will-navigate', (event, url) => {
            if (typeof url === 'string' && (url.startsWith('file:') || url.startsWith('about:'))) {
                return;
            }
            event.preventDefault();
            console.warn('[Navigate] Blocked:', url);
        });

        win.webContents.on('will-redirect', (event, url) => {
            if (typeof url === 'string' && (url.startsWith('file:') || url.startsWith('about:'))) {
                return;
            }
            event.preventDefault();
            console.warn('[Redirect] Blocked:', url);
        });
    },

    _setupMainListeners() {
        const win = GLOBAL_STATE.mainWindow;

        this._setupWebSecurity();

        // If the renderer crashes, try to recover instead of leaving the app in a broken state.
        win.webContents.on('render-process-gone', (_event, details) => {
            console.error('[MainWindow] Renderer process gone:', details);
            if (GLOBAL_STATE.isQuitting) {
                return;
            }
            try {
                setTimeout(() => {
                    if (win && !win.isDestroyed()) {
                        win.reload();
                    }
                }, 800);
            } catch (e) {
                // ignore
            }
        });

        // 关键：原生级平滑启动
        win.once('ready-to-show', () => {
            // 给一个小延迟确保 CSS 渲染完成
            setTimeout(() => {
                updateSplashStatus('界面已准备完成...', 100);
                const splash = GLOBAL_STATE.splashWindow;
                if (splash && !splash.isDestroyed()) {
                    try { splash.close(); } catch (e) {}
                }
                GLOBAL_STATE.splashWindow = null;

                if (win && !win.isDestroyed()) {
                    try {
                        win.show();
                        win.focus();
                    } catch (e) {}
                }
            }, 50); 
        });

        win.on('show', () => {
            RUNTIME_IDLE_CONTROLLER.setWindowVisible(getMainWindowVisible());
        });

        win.on('hide', () => {
            RUNTIME_IDLE_CONTROLLER.setWindowVisible(getMainWindowVisible());
        });

        win.on('minimize', () => {
            RUNTIME_IDLE_CONTROLLER.setWindowVisible(getMainWindowVisible());
        });

        win.on('restore', () => {
            RUNTIME_IDLE_CONTROLLER.setWindowVisible(getMainWindowVisible());
        });

        win.on('resize', () => {
            const { width, height } = win.getBounds();
            store.set('windowBounds', { width, height });
        });

        win.on('close', (event) => {
            if (!GLOBAL_STATE.isQuitting) {
                event.preventDefault();
                requestAppClose({ showWindow: false });
            }
        });
    },

    createTray() {
        const icon = nativeImage.createFromPath(PathUtils.iconPath);
        GLOBAL_STATE.tray = new Tray(icon.resize({ width: 16, height: 16 }));
        
        const contextMenu = Menu.buildFromTemplate([
            { label: '显示主窗口', click: () => showMainWindowSafe() },
            { type: 'separator' },
            { label: '启动机器人', click: () => sendToMainWindowSafe('tray-action', 'start-bot') },
            { label: '停止机器人', click: () => sendToMainWindowSafe('tray-action', 'stop-bot') },
            { type: 'separator' },
            { label: '退出', click: () => {
                requestAppClose({ showWindow: true });
            }}
        ]);

        // Ensure tray operations won't throw if the window/webContents has been destroyed.
        try {
            const items = contextMenu.items || [];
            if (items[0]) items[0].click = () => showMainWindowSafe();
            if (items[2]) items[2].click = () => sendToMainWindowSafe('tray-action', 'start-bot');
            if (items[3]) items[3].click = () => sendToMainWindowSafe('tray-action', 'stop-bot');
        } catch (e) {}

        GLOBAL_STATE.tray.setToolTip('微信AI助手');
        GLOBAL_STATE.tray.setContextMenu(contextMenu);
        GLOBAL_STATE.tray.on('double-click', () => showMainWindowSafe());
    }
};

// ═══════════════════════════════════════════════════════════════════════════════
//                               IPC 通信
// ═══════════════════════════════════════════════════════════════════════════════

function setupIPC() {
    registerIpcHandlers({
        ipcMain,
        GLOBAL_STATE,
        BackendManager,
        SharedConfigService,
        RuntimeManager,
        getRuntimeIdleState,
        applyRuntimeStatusSummary,
        runtimeIdleController: RUNTIME_IDLE_CONTROLLER,
        GrowthPromptStore,
        shell,
        app,
        exec,
        execFile,
        fs,
        path,
        getMainWindowSafe,
        requestAppClose,
        installDownloadedUpdateAndQuit,
        showMainWindowSafe,
        store,
        dialog,
    });
}

function safeSetupIPC() {
    try {
        setupIPC();
    } catch (e) {
        console.error('[IPC] setup failed:', e);
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
//                               应用生命周期
// ═══════════════════════════════════════════════════════════════════════════════

if (!app.requestSingleInstanceLock()) {
    app.quit();
} else {
    app.on('second-instance', () => {
        // The event may fire while the first instance is still booting.
        // Only touch BrowserWindow after app is ready.
        app.whenReady().then(() => {
            try {
                const windows = BrowserWindow.getAllWindows();
                const win = (windows || []).find(w => w && !w.isDestroyed()) || null;
                if (win) {
                    GLOBAL_STATE.mainWindow = win;
                    try {
                        if (win.isMinimized()) win.restore();
                        win.show();
                        win.focus();
                        return;
                    } catch (e) {
                        console.warn('[SecondInstance] Failed to focus window:', e);
                    }
                }

                // If the main window is missing, recreate it.
                WindowManager.createMain();
            } catch (e) {
                console.error('[SecondInstance] Handler failed:', e);
            }
        }).catch((e) => {
            console.error('[SecondInstance] whenReady failed:', e);
        });
    });

    app.whenReady().then(() => {
        // 1. 先显示启动画面
        WindowManager.createSplash();

        // 2. 设置 IPC
        safeSetupIPC();

        // 3. 预热共享配置，但不自动拉起 Python 服务
        SharedConfigService.ensureLoaded().catch(err => console.error('Config preload error:', err));

        // 4. 创建主窗口 (后台加载，ready-to-show 时自动切换)
        WindowManager.createMain();
        WindowManager.createTray();

        GLOBAL_STATE.updateManager = new UpdateManager({
            app,
            shell,
            store,
            Notification,
            isDev: GLOBAL_STATE.isDev,
            getMainWindow: () => GLOBAL_STATE.mainWindow
        });
        GLOBAL_STATE.updateManager.init();
    });

    app.on('before-quit', () => {
        GLOBAL_STATE.isQuitting = true;
        GLOBAL_STATE.updateManager?.dispose();
        BackendManager.stop(GLOBAL_STATE.installingUpdate ? 'install-update' : 'quit');
    });

    app.on('will-quit', () => {
        if (GLOBAL_STATE.installingUpdate) {
            GLOBAL_STATE.updateManager?.launchPreparedInstaller();
        }
    });

    app.on('window-all-closed', () => {
        // 保持托盘运行
    });

    app.on('activate', () => {
        if (BrowserWindow.getAllWindows().length === 0) WindowManager.createMain();
    });
}
