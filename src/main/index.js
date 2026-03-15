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
const Store = require('electron-store');
const iconv = require('iconv-lite');
const { UpdateManager } = require('./update-manager');

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
    get flaskUrl() { return `http://localhost:${this.flaskPort}`; }
};

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
            const req = http.get(`${GLOBAL_STATE.flaskUrl}/api/status`, (res) => {
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
            console.log('[Backend] 鍚庣姝ｅ湪鍚姩');
            updateSplashStatus('鍚庣鏈嶅姟鍚姩涓?..', 50);
            return;
        }

        let cmd, args, options;

        if (GLOBAL_STATE.isDev) {
            const venvPython = path.join(PathUtils.resourcePath, '.venv', 'Scripts', 'python.exe');
            cmd = venvPython;
            args = ['run.py', 'web', '--port', GLOBAL_STATE.flaskPort.toString()];
            options = {
                cwd: PathUtils.resourcePath,
                env: {
                    ...process.env,
                    PYTHONUNBUFFERED: '1',
                    PYTHONIOENCODING: 'utf-8',
                    PYTHONLEGACYWINDOWSSTDIO: '1'
                }
            };
        } else {
            const exePath = PathUtils.backendExecutable;
            cmd = exePath;
            args = ['web', '--port', GLOBAL_STATE.flaskPort.toString()];
            options = {
                cwd: path.dirname(exePath),
                env: {
                    ...process.env,
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
            proc.kill('SIGTERM');
            const pid = proc.pid;
            setTimeout(() => {
                try { process.kill(pid, 0) && process.kill(pid, 'SIGKILL'); } catch (e) {}
            }, 3000);
            setTimeout(done, 3500);
            GLOBAL_STATE.pythonProcess = null;
        });
    },

    _setupProcessListeners(proc) {
        proc.on('error', (err) => {
            console.error(`[Backend Spawn Error] ${err.message}`);
            GLOBAL_STATE.pythonProcess = null;
        });

        proc.stdout.on('data', (data) => {
            const str = iconv.decode(data, 'utf-8');
            console.log(`[Backend] ${str.trim()}`);
            updateSplashStatus('后端服务启动中...', 50);
        });

        proc.stderr.on('data', (data) => {
            const str = iconv.decode(data, 'utf-8');
            console.error(`[Backend Err] ${str.trim()}`);
        });

        proc.on('exit', (code) => {
            console.log(`[Backend] 退出代码: ${code}`);
            GLOBAL_STATE.pythonProcess = null;
        });
    }
};

async function requestAppClose(options = {}) {
    const { showWindow } = options;
    const win = GLOBAL_STATE.mainWindow;
    const pref = store.get('closeBehavior') || 'ask';
    if (pref === 'minimize') {
        win?.hide();
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
        win?.show();
        win?.focus();
    }
    win?.webContents.send('app-close-dialog');
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
            webPreferences: { contextIsolation: true, nodeIntegration: false }
        });
        GLOBAL_STATE.splashWindow.loadFile(path.join(__dirname, '..', 'renderer', 'splash.html'));
        updateSplashStatus('正在启动桌面客户端...', 12);
    },

    createMain() {
        const { width, height } = store.get('windowBounds');

        GLOBAL_STATE.mainWindow = new BrowserWindow({
            width, height,
            minWidth: 900,
            minHeight: 600,
            title: '微信AI助手',
            icon: PathUtils.iconPath,
            backgroundColor: '#0A0A0F', // 关键：与 CSS 背景一致，防止白屏
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

        this._setupMainListeners();
        
        // if (GLOBAL_STATE.isDev) GLOBAL_STATE.mainWindow.webContents.openDevTools();
    },

    _setupMainListeners() {
        const win = GLOBAL_STATE.mainWindow;

        // 关键：原生级平滑启动
        win.once('ready-to-show', () => {
            // 给一个小延迟确保 CSS 渲染完成
            setTimeout(() => {
                updateSplashStatus('界面已准备完成...', 100);
                if (GLOBAL_STATE.splashWindow) {
                    GLOBAL_STATE.splashWindow.close();
                    GLOBAL_STATE.splashWindow = null;
                }
                win.show();
                win.focus();
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
            { label: '显示主窗口', click: () => GLOBAL_STATE.mainWindow?.show() },
            { type: 'separator' },
            { label: '启动机器人', click: () => GLOBAL_STATE.mainWindow?.webContents.send('tray-action', 'start-bot') },
            { label: '停止机器人', click: () => GLOBAL_STATE.mainWindow?.webContents.send('tray-action', 'stop-bot') },
            { type: 'separator' },
            { label: '退出', click: () => {
                requestAppClose({ showWindow: true });
            }}
        ]);

        GLOBAL_STATE.tray.setToolTip('微信AI助手');
        GLOBAL_STATE.tray.setContextMenu(contextMenu);
        GLOBAL_STATE.tray.on('double-click', () => GLOBAL_STATE.mainWindow?.show());
    }
};

// ═══════════════════════════════════════════════════════════════════════════════
//                               IPC 通信
// ═══════════════════════════════════════════════════════════════════════════════

function setupIPC() {
    ipcMain.handle('get-flask-url', () => GLOBAL_STATE.flaskUrl);
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

    ipcMain.handle('minimize-to-tray', () => GLOBAL_STATE.mainWindow?.hide());

    // 窗口控制
    ipcMain.handle('window-minimize', () => GLOBAL_STATE.mainWindow?.minimize());
    ipcMain.handle('window-maximize', () => {
        const win = GLOBAL_STATE.mainWindow;
        win?.isMaximized() ? win.unmaximize() : win.maximize();
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

// ═══════════════════════════════════════════════════════════════════════════════
//                               应用生命周期
// ═══════════════════════════════════════════════════════════════════════════════

if (!app.requestSingleInstanceLock()) {
    app.quit();
} else {
    app.on('second-instance', () => {
        const win = GLOBAL_STATE.mainWindow;
        if (win) {
            if (win.isMinimized()) win.restore();
            win.show();
            win.focus();
        }
    });

    app.whenReady().then(() => {
        // 1. 先显示启动画面
        WindowManager.createSplash();

        // 2. 并行启动后端 (不阻塞)
        BackendManager.start().catch(err => console.error('Backend start error:', err));

        // 3. 设置 IPC
        setupIPC();

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
