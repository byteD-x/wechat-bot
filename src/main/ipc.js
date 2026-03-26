const {
    buildDiagnosticsSnapshot,
    buildSnapshotFilename,
} = require('./diagnostics-snapshot');
const { launchElevatedApp } = require('./elevated-relaunch');

function registerIpcHandlers({
    ipcMain,
    GLOBAL_STATE,
    BackendManager,
    SharedConfigService,
    RuntimeManager,
    getRuntimeIdleState,
    applyRuntimeStatusSummary,
    runtimeIdleController,
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
}) {
    ipcMain.handle('get-flask-url', () => GLOBAL_STATE.flaskUrl);
    ipcMain.handle('get-api-token', () => GLOBAL_STATE.apiToken);
    ipcMain.handle('check-backend', () => BackendManager.checkServer());
    ipcMain.handle('start-backend', async () => {
        try {
            await BackendManager.ensureReady();
            return { success: true };
        } catch (err) {
            return { success: false, error: err.message };
        }
    });

    ipcMain.handle('config:get', () => SharedConfigService.get());
    ipcMain.handle('config:patch', (_, patch) => SharedConfigService.patch(patch || {}));
    ipcMain.handle('config:test-connection', (_, options) => SharedConfigService.testConnection(options || {}));
    ipcMain.handle('config:subscribe', () => SharedConfigService.subscribe());

    ipcMain.handle('runtime:ensure-service', () => RuntimeManager.ensureService());
    ipcMain.handle('runtime:start-bot', () => RuntimeManager.startBot());
    ipcMain.handle('runtime:stop-bot', () => RuntimeManager.stopBot());
    ipcMain.handle('runtime:start-growth', () => RuntimeManager.startGrowth());
    ipcMain.handle('runtime:stop-growth', () => RuntimeManager.stopGrowth());
    ipcMain.handle('runtime:get-idle-state', () => getRuntimeIdleState());
    ipcMain.handle('runtime:report-status', (_, summary) => ({
        success: true,
        idle_state: applyRuntimeStatusSummary(summary || {}),
    }));
    ipcMain.handle('runtime:cancel-idle-shutdown', () => ({
        success: true,
        idle_state: runtimeIdleController.cancelIdleShutdown(),
    }));

    ipcMain.handle('growth:get-prompt-state', () => GrowthPromptStore.getState());
    ipcMain.handle('growth:mark-prompt-seen', (_, kind) => GrowthPromptStore.markSeen(kind));

    ipcMain.handle('open-external', (_, url) => {
        if (!url || typeof url !== 'string') return;
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
            }
            console.log('[OpenWeChat] Path not found, trying protocol');
            shell.openExternal('weixin://');
            return { success: true, message: 'Attempted to open via protocol' };
        } catch (e) {
            console.error('[OpenWeChat] Error:', e);
            return { success: false, error: e.message };
        }
    });

    ipcMain.handle('restart-app-as-admin', async () => {
        if (process.platform !== 'win32') {
            return { success: false, message: '仅支持 Windows 自动提权重启' };
        }

        try {
            await launchElevatedApp({
                execFileImpl: execFile,
                processLike: process,
                appPath: app.getAppPath ? app.getAppPath() : '',
            });
        } catch (error) {
            const canceled = error?.code === 'uac_cancelled';
            return {
                success: false,
                canceled,
                message: canceled
                    ? '已取消管理员权限授权'
                    : `管理员重启失败: ${error?.message || error}`,
            };
        }

        setTimeout(async () => {
            GLOBAL_STATE.isQuitting = true;
            if (GLOBAL_STATE.tray) {
                try {
                    GLOBAL_STATE.tray.destroy();
                } catch (_) {}
                GLOBAL_STATE.tray = null;
            }

            try {
                await BackendManager.stop('restart-as-admin');
            } catch (error) {
                console.warn('[RestartAsAdmin] stop backend failed:', error?.message || error);
            }

            app.quit();
        }, 150);

        return {
            success: true,
            pendingRestart: true,
            message: '正在以管理员身份重新启动应用...',
        };
    });

    ipcMain.handle('minimize-to-tray', () => {
        const win = getMainWindowSafe();
        try { win?.hide(); } catch (_) {}
    });

    ipcMain.handle('window-minimize', () => {
        const win = getMainWindowSafe();
        try { win?.minimize(); } catch (_) {}
    });
    ipcMain.handle('window-maximize', () => {
        const win = getMainWindowSafe();
        if (!win) return;
        try {
            win.isMaximized() ? win.unmaximize() : win.maximize();
        } catch (_) {}
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
            await BackendManager.stop('quit');
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
        latestVersion: '',
        lastCheckedAt: '',
        releaseDate: '',
        downloadUrl: '',
        releasePageUrl: '',
        notes: [],
        error: '',
        skippedVersion: '',
        downloading: false,
        downloadProgress: 0,
        readyToInstall: false,
        downloadedVersion: '',
        downloadedInstallerPath: ''
    });

    ipcMain.handle('check-for-updates', (_, options) => (
        GLOBAL_STATE.updateManager?.checkForUpdates({ ...options, manual: true }) || { success: false, error: 'update manager unavailable' }
    ));

    ipcMain.handle('skip-update-version', (_, version) => (
        GLOBAL_STATE.updateManager?.skipVersion(version) || { success: false, error: 'update manager unavailable' }
    ));

    ipcMain.handle('download-update', () => (
        GLOBAL_STATE.updateManager?.downloadUpdate() || { success: false, error: 'update manager unavailable' }
    ));

    ipcMain.handle('install-downloaded-update', () => installDownloadedUpdateAndQuit());

    ipcMain.handle('open-update-download', () => (
        GLOBAL_STATE.updateManager?.openDownloadPage() || { success: false, error: 'download url unavailable' }
    ));

    ipcMain.handle('export-diagnostics-snapshot', async () => {
        const collectionErrors = [];
        const backendJson = async (endpoint) => {
            try {
                return await BackendManager.requestJson('GET', endpoint, null, 12000);
            } catch (error) {
                collectionErrors.push(`${endpoint}: ${error.message || error}`);
                return null;
            }
        };

        try {
            await BackendManager.ensureReady(12000);
        } catch (error) {
            collectionErrors.push(`backend: ${error.message || error}`);
        }

        let configPayload = {};
        try {
            const configResult = await SharedConfigService.get();
            configPayload = {
                api: configResult?.api || {},
                bot: configResult?.bot || {},
                logging: configResult?.logging || {},
                agent: configResult?.agent || {},
                services: configResult?.services || {},
            };
        } catch (error) {
            collectionErrors.push(`config: ${error.message || error}`);
        }

        const status = await backendJson('/api/status');
        const readiness = await backendJson('/api/readiness?refresh=true');
        const configAudit = await backendJson('/api/config/audit');
        const logsResult = await backendJson('/api/logs?lines=120');

        const snapshot = buildDiagnosticsSnapshot({
            appVersion: app.getVersion(),
            appName: app.getName ? app.getName() : 'wechat-ai-assistant',
            status,
            readiness,
            configAudit,
            configPayload,
            logs: Array.isArray(logsResult?.logs) ? logsResult.logs : [],
            updateState: GLOBAL_STATE.updateManager?.getState() || {},
            idleState: getRuntimeIdleState(),
            platform: {
                process_platform: process.platform,
                process_arch: process.arch,
            },
            collectionErrors,
        });

        const win = getMainWindowSafe() || undefined;
        const defaultPath = path.join(
            app.getPath('documents'),
            buildSnapshotFilename(new Date()),
        );
        const saveResult = await dialog.showSaveDialog(win, {
            title: '导出诊断快照',
            defaultPath,
            filters: [
                { name: 'JSON 文件', extensions: ['json'] },
            ],
        });
        if (saveResult.canceled || !saveResult.filePath) {
            return { success: false, canceled: true, message: '用户取消导出' };
        }

        fs.mkdirSync(path.dirname(saveResult.filePath), { recursive: true });
        fs.writeFileSync(
            saveResult.filePath,
            `${JSON.stringify(snapshot, null, 2)}\n`,
            'utf8',
        );
        return {
            success: true,
            filePath: saveResult.filePath,
            message: '诊断快照已导出',
        };
    });

    ipcMain.handle('is-first-run', () => store.get('isFirstRun'));
    ipcMain.handle('set-first-run-complete', () => {
        store.set('isFirstRun', false);
        return true;
    });
}

module.exports = {
    registerIpcHandlers,
};
