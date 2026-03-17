/**
 * 微信AI助手 - Electron 主进程
 * 
 * 架构优化说明：
 * 1. 采用 ready-to-show 事件机制，彻底消除白屏闪烁
 * 2. 异步并行启动 Python 后端，不阻塞 UI 渲染
 * 3. 模块化组织代码，提升可维护性
 * 4. 增强的进程生命周期管理
 */

const { app, BrowserWindow, Tray, Menu, ipcMain, shell, nativeImage, Notification } = require('electron');
const fs = require('fs');
const path = require('path');
const { spawn, exec } = require('child_process');
const http = require('http');
const crypto = require('crypto');
const Store = require('electron-store');
const iconv = require('iconv-lite');
const { UpdateManager } = require('./update-manager');

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
        update: {
            feedUrl: '',
            autoCheckOnLaunch: true,
            checkIntervalHours: 6,
            notifyOnUpdate: true
        }
    }
});

const GLOBAL_STATE = {
    mainWindow: null,
    splashWindow: null,
    tray: null,
    pythonProcess: null,
    updateManager: null,
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

// ═══════════════════════════════════════════════════════════════════════════════
//                               Python 后端管理
// ═══════════════════════════════════════════════════════════════════════════════

const BackendManager = {
    checkServer() {
        return new Promise((resolve) => {
            const tokenParam = GLOBAL_STATE.apiToken ? `?token=${encodeURIComponent(GLOBAL_STATE.apiToken)}` : '';
            const req = http.get(`${GLOBAL_STATE.flaskUrl}/api/status${tokenParam}`, (res) => {
                resolve(res.statusCode === 200);
            });
            req.on('error', () => resolve(false));
            req.setTimeout(2000, () => {
                req.destroy();
                resolve(false);
            });
        });
    },

    async start() {
        if (await this.checkServer()) {
            console.log('[Backend] 服务已在运行');
            updateSplashStatus('后端服务已就绪，正在加载界面...', 60);
            return;
        }

        if (GLOBAL_STATE.pythonProcess) {
            console.log('[Backend] 后端正在启动');
            updateSplashStatus('后端服务启动中...', 50);
            return;
        }

        let cmd, args, options;

        if (GLOBAL_STATE.isDev) {
            const venvPython = path.join(PathUtils.resourcePath, '.venv', 'Scripts', 'python.exe');
            cmd = venvPython;
            args = ['run.py', 'web', '--host', '127.0.0.1', '--port', GLOBAL_STATE.flaskPort.toString()];
            options = {
                cwd: PathUtils.resourcePath,
                env: {
                    ...process.env,
                    WECHAT_BOT_API_TOKEN: GLOBAL_STATE.apiToken,
                    PYTHONUNBUFFERED: '1',
                    PYTHONIOENCODING: 'utf-8',
                    PYTHONLEGACYWINDOWSSTDIO: '1'
                }
            };
        } else {
            const exePath = PathUtils.backendExecutable;
            cmd = exePath;
            args = ['web', '--host', '127.0.0.1', '--port', GLOBAL_STATE.flaskPort.toString()];
            options = {
                cwd: path.dirname(exePath),
                env: {
                    ...process.env,
                    WECHAT_BOT_API_TOKEN: GLOBAL_STATE.apiToken,
                    PYTHONLEGACYWINDOWSSTDIO: '1'
                }
            };
        }

        console.log(`[Backend] 启动: ${cmd} ${args.join(' ')}`);
        updateSplashStatus('正在启动后端服务...', 35);
        
        GLOBAL_STATE.pythonProcess = spawn(cmd, args, options);
        this._setupProcessListeners(GLOBAL_STATE.pythonProcess);
    },

    stop() {
        const proc = GLOBAL_STATE.pythonProcess;
        if (!proc) return Promise.resolve();
        return new Promise((resolve) => {
            let resolved = false;
            const done = () => {
                if (resolved) return;
                resolved = true;
                resolve();
            };
            console.log('[Backend] 正在停止...');
            proc.once('exit', done);
            try {
                proc.kill('SIGTERM');
            } catch (e) {
                // If the process is already gone, treat it as stopped.
                done();
            }
            const pid = proc.pid;
            setTimeout(() => {
                try { process.kill(pid, 0) && process.kill(pid, 'SIGKILL'); } catch (e) {}
            }, 3000);
            setTimeout(done, 3500);
            GLOBAL_STATE.pythonProcess = null;
        });
    },

    _setupProcessListeners(proc) {
        if (!proc) {
            return;
        }
        proc.on('error', (err) => {
            console.error(`[Backend Spawn Error] ${err.message}`);
            GLOBAL_STATE.pythonProcess = null;
        });

        const decodeSafe = (data) => {
            try {
                const buffer = Buffer.isBuffer(data) ? data : Buffer.from(String(data));
                const utf8 = iconv.decode(buffer, 'utf-8');
                if (!utf8.includes('\ufffd')) {
                    return utf8;
                }
                return iconv.decode(buffer, 'cp936');
            } catch (e) {
                try {
                    return Buffer.isBuffer(data) ? data.toString('utf8') : String(data);
                } catch (_) {
                    return '';
                }
            }
        };

        if (proc.stdout && typeof proc.stdout.on === 'function') {
            // Avoid crashing the main process on unhandled stream errors.
            proc.stdout.on('error', (err) => {
                console.warn('[Backend Stdout Error]', err?.message || err);
            });
            proc.stdout.on('data', (data) => {
                const str = decodeSafe(data);
                console.log(`[Backend] ${str.trim()}`);
                updateSplashStatus('后端服务启动中...', 50);
            });
        }

        if (proc.stderr && typeof proc.stderr.on === 'function') {
            proc.stderr.on('error', (err) => {
                console.warn('[Backend Stderr Error]', err?.message || err);
            });
            proc.stderr.on('data', (data) => {
                const str = decodeSafe(data);
                console.error(`[Backend Err] ${str.trim()}`);
            });
        }

        proc.on('exit', (code) => {
            console.log(`[Backend] 退出代码: ${code}`);
            GLOBAL_STATE.pythonProcess = null;
        });
    }
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
        await BackendManager.stop();
        app.quit();
        return { action: 'quit' };
    }
    if (showWindow) {
        showMainWindowSafe();
    }
    sendToMainWindowSafe('app-close-dialog');
    return { action: 'ask' };
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
            backgroundColor: '#F7F7F8', // 关键：与 CSS 背景一致，防止白屏
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
    ipcMain.handle('get-flask-url', () => GLOBAL_STATE.flaskUrl);
    ipcMain.handle('get-api-token', () => GLOBAL_STATE.apiToken);
    ipcMain.handle('check-backend', () => BackendManager.checkServer());
    ipcMain.handle('start-backend', async () => {
        try {
            await BackendManager.start();
            return { success: true };
        } catch (err) {
            return { success: false, error: err.message };
        }
    });
    
    ipcMain.handle('open-external', (_, url) => {
        if (!url || typeof url !== 'string') return;
        // 简单安全检查：只允许 http/https/mailto
        if (/^(https?|mailto):/i.test(url)) {
            shell.openExternal(url);
        } else {
            console.warn(`Blocked unsafe URL: ${url}`);
        }
    });
    ipcMain.handle('get-app-version', () => app.getVersion());

    ipcMain.handle('open-wechat', async () => {
        try {
            const isWechatRunning = () => new Promise((resolve) => {
                exec('tasklist /FI "IMAGENAME eq WeChat.exe" /FO CSV /NH', { windowsHide: true }, (err, stdout) => {
                    if (err) return resolve(false);
                    const rows = String(stdout || '')
                        .split(/\r?\n/)
                        .map(item => item.trim())
                        .filter(Boolean);
                    resolve(rows.some(row => !row.startsWith('INFO:')));
                });
            });

            if (await isWechatRunning()) {
                console.log('[OpenWeChat] WeChat already running, skip duplicate launch');
                return { success: true, message: 'WeChat is already running' };
            }
            // 尝试从注册表获取安装路径
            const getInstallPath = () => new Promise((resolve) => {
                exec('reg query "HKEY_CURRENT_USER\\Software\\Tencent\\WeChat" /v InstallPath', (err, stdout) => {
                    if (err || !stdout) return resolve(null);
                    const match = stdout.match(/InstallPath\s+REG_SZ\s+(.+)/);
                    if (match && match[1]) {
                        resolve(path.join(match[1].trim(), 'WeChat.exe'));
                    } else {
                        resolve(null);
                    }
                });
            });

            let wechatPath = await getInstallPath();
            
            if (!wechatPath) {
                // 回退到常见路径
                const commonPaths = [
                    'C:\\Program Files (x86)\\Tencent\\WeChat\\WeChat.exe',
                    'C:\\Program Files\\Tencent\\WeChat\\WeChat.exe',
                    'D:\\Program Files (x86)\\Tencent\\WeChat\\WeChat.exe',
                    'D:\\Program Files\\Tencent\\WeChat\\WeChat.exe'
                ];
                for (const p of commonPaths) {
                    if (fs.existsSync(p)) {
                        wechatPath = p;
                        break;
                    }
                }
            }

            if (wechatPath) {
                console.log(`[OpenWeChat] Opening WeChat at ${wechatPath}`);
                shell.openPath(wechatPath); 
                return { success: true };
            } else {
                // 最后的尝试：协议
                console.log('[OpenWeChat] Path not found, trying protocol');
                shell.openExternal('weixin://');
                return { success: true, message: 'Attempted to open via protocol' };
            }
        } catch (e) {
            console.error('[OpenWeChat] Error:', e);
            return { success: false, error: e.message };
        }
    });

    ipcMain.handle('minimize-to-tray', () => {
        const win = getMainWindowSafe();
        try { win?.hide(); } catch (e) {}
    });

    // 窗口控制
    ipcMain.handle('window-minimize', () => {
        const win = getMainWindowSafe();
        try { win?.minimize(); } catch (e) {}
    });
    ipcMain.handle('window-maximize', () => {
        const win = getMainWindowSafe();
        if (!win) return;
        try {
            win.isMaximized() ? win.unmaximize() : win.maximize();
        } catch (e) {}
    });
    ipcMain.handle('window-close', () => requestAppClose({ showWindow: false }));

    ipcMain.handle('confirm-close-action', async (_, payload) => {
        const { action, remember } = payload || {};
        if (remember && (action === 'minimize' || action === 'quit')) {
            store.set('closeBehavior', action);
        }
        if (action === 'minimize') {
            GLOBAL_STATE.mainWindow?.hide();
            return { success: true };
        }
        if (action === 'quit') {
            GLOBAL_STATE.isQuitting = true;
            if (GLOBAL_STATE.tray) {
                GLOBAL_STATE.tray.destroy();
                GLOBAL_STATE.tray = null;
            }
            await BackendManager.stop();
            app.quit();
            return { success: true };
        }
        return { success: false, message: 'invalid action' };
    });

    ipcMain.handle('reset-close-behavior', () => {
        store.set('closeBehavior', 'ask');
        return { success: true };
    });

    ipcMain.handle('get-update-state', () => GLOBAL_STATE.updateManager?.getState() || {
        enabled: false,
        checking: false,
        available: false,
        currentVersion: app.getVersion(),
        latestVersion: null,
        lastCheckedAt: null,
        releaseDate: null,
        downloadUrl: '',
        releasePageUrl: '',
        notes: [],
        error: ''
    });

    ipcMain.handle('check-for-updates', (_, options) => (
        GLOBAL_STATE.updateManager?.checkForUpdates({ ...options, manual: true }) || { success: false, error: 'update manager unavailable' }
    ));

    ipcMain.handle('open-update-download', () => (
        GLOBAL_STATE.updateManager?.openDownloadPage() || { success: false, error: 'download url unavailable' }
    ));

    // 状态管理
    ipcMain.handle('is-first-run', () => store.get('isFirstRun'));
    ipcMain.handle('set-first-run-complete', () => {
        store.set('isFirstRun', false);
        return true;
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

        // 2. 并行启动后端 (不阻塞)
        BackendManager.start().catch(err => console.error('Backend start error:', err));

        // 3. 设置 IPC
        safeSetupIPC();

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
        BackendManager.stop();
    });

    app.on('window-all-closed', () => {
        // 保持托盘运行
    });

    app.on('activate', () => {
        if (BrowserWindow.getAllWindows().length === 0) WindowManager.createMain();
    });
}
