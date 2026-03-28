const {
    buildDiagnosticsSnapshot,
    buildSnapshotFilename,
} = require('./diagnostics-snapshot');
const { launchElevatedApp } = require('./elevated-relaunch');
const { decodeBufferText } = require('./text-codec');
const { validateExternalOpenUrl } = require('./external-url-policy');

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
    const normalizeRendererPath = (rawPath) => {
        let value = decodeURIComponent(String(rawPath || '')).replace(/\\/g, '/');
        if (/^\/[a-zA-Z]:\//.test(value)) {
            value = value.slice(1);
        }
        return path
            .normalize(value)
            .replace(/\\/g, '/')
            .toLowerCase();
    };

    const trustedRendererPath = normalizeRendererPath(
        path.resolve(path.join(__dirname, '..', 'renderer', 'index.html')),
    );

    const isTrustedRendererSender = (event) => {
        const frameUrl = String(
            event?.senderFrame?.url
            || (typeof event?.sender?.getURL === 'function' ? event.sender.getURL() : '')
            || '',
        ).trim();
        if (!frameUrl) {
            return false;
        }
        try {
            const parsed = new URL(frameUrl);
            if (parsed.protocol !== 'file:') {
                return false;
            }
            const normalizedPath = normalizeRendererPath(parsed.pathname || '');
            return normalizedPath === trustedRendererPath;
        } catch (_) {
            return false;
        }
    };

    const assertTrustedRendererSender = (event, channel) => {
        if (!isTrustedRendererSender(event)) {
            const senderUrl = String(event?.senderFrame?.url || '').trim();
            console.warn(`[IPC] Blocked untrusted sender for ${channel}: ${senderUrl || '<empty>'}`);
            throw new Error('forbidden_sender');
        }
    };

    const handleTrusted = (channel, handler) => {
        ipcMain.handle(channel, (event, ...args) => {
            assertTrustedRendererSender(event, channel);
            return handler(event, ...args);
        });
    };

    const ALLOWED_BACKEND_PATHS = new Set([
        '/api/status',
        '/api/ping',
        '/api/readiness',
        '/api/start',
        '/api/stop',
        '/api/restart',
        '/api/recover',
        '/api/pause',
        '/api/resume',
        '/api/test_connection',
        '/api/ollama/models',
        '/api/growth/start',
        '/api/growth/stop',
        '/api/growth/tasks',
        '/api/messages',
        '/api/contact_profile',
        '/api/contact_prompt',
        '/api/message_feedback',
        '/api/send',
        '/api/reply_policies',
        '/api/pending_replies',
        '/api/config',
        '/api/config/audit',
        '/api/model_catalog',
        '/api/model_auth/overview',
        '/api/model_auth/action',
        '/api/preview_prompt',
        '/api/backups',
        '/api/backups/cleanup',
        '/api/backups/restore',
        '/api/data_controls',
        '/api/data_controls/clear',
        '/api/evals/latest',
        '/api/logs',
        '/api/logs/clear',
        '/api/usage',
        '/api/pricing',
        '/api/pricing/refresh',
        '/api/costs/summary',
        '/api/costs/sessions',
        '/api/costs/session_details',
        '/api/costs/review_queue_export',
    ]);
    const ALLOWED_BACKEND_PATH_PATTERNS = [
        /^\/api\/growth\/tasks\/[^/?#]+\/(clear|run|pause|resume)$/,
        /^\/api\/pending_replies\/[^/?#]+\/(approve|reject)$/,
    ];
    const isPlainObject = (value) => (
        value != null
        && typeof value === 'object'
        && !Array.isArray(value)
    );
    const normalizeBackendEndpoint = (endpointValue) => {
        const raw = String(endpointValue || '').trim();
        if (!raw || raw.length > 512 || raw.includes('\n') || raw.includes('\r')) {
            return { ok: false, error: 'invalid_endpoint' };
        }
        if (!raw.startsWith('/api/')) {
            return { ok: false, error: 'invalid_endpoint' };
        }
        let parsed;
        try {
            parsed = new URL(raw, 'http://127.0.0.1');
        } catch (_) {
            return { ok: false, error: 'invalid_endpoint' };
        }
        const pathOnly = String(parsed.pathname || '');
        const allowedPath = ALLOWED_BACKEND_PATHS.has(pathOnly)
            || ALLOWED_BACKEND_PATH_PATTERNS.some((pattern) => pattern.test(pathOnly));
        if (!allowedPath) {
            return { ok: false, error: 'endpoint_not_allowed' };
        }
        const search = String(parsed.search || '');
        if (search.length > 2048) {
            return { ok: false, error: 'invalid_query' };
        }
        return { ok: true, endpoint: `${pathOnly}${search}` };
    };
    const normalizeBackendPayload = (payload) => {
        if (payload == null) {
            return { ok: true, value: null };
        }
        if (!isPlainObject(payload)) {
            return { ok: false, error: 'invalid_payload' };
        }
        try {
            const serialized = JSON.stringify(payload);
            if (serialized.length > 64 * 1024) {
                return { ok: false, error: 'payload_too_large' };
            }
        } catch (_) {
            return { ok: false, error: 'invalid_payload' };
        }
        return { ok: true, value: payload };
    };

    handleTrusted('get-flask-url', () => GLOBAL_STATE.flaskUrl);
    handleTrusted('get-sse-ticket', () => GLOBAL_STATE.sseTicket);
    handleTrusted('backend:request', async (_event, options) => {
        const payload = options && typeof options === 'object' ? options : {};
        const method = String(payload.method || 'GET').trim().toUpperCase();
        const endpoint = String(payload.endpoint || '').trim();
        const timeoutRaw = Number(payload.timeoutMs || 0);
        const timeoutMs = Number.isFinite(timeoutRaw) ? Math.max(1000, Math.min(120000, Math.floor(timeoutRaw))) : 10000;
        const body = payload.payload ?? null;
        const normalizedEndpoint = normalizeBackendEndpoint(endpoint);

        if (!['GET', 'POST'].includes(method)) {
            return {
                ok: false,
                error: {
                    code: 'bad_request',
                    message: 'unsupported method',
                    status: 400,
                    endpoint,
                },
            };
        }
        if (!normalizedEndpoint.ok) {
            return {
                ok: false,
                error: {
                    code: 'bad_request',
                    message: normalizedEndpoint.error || 'invalid endpoint',
                    status: 400,
                    endpoint,
                },
            };
        }
        if (method === 'GET' && body != null) {
            return {
                ok: false,
                error: {
                    code: 'bad_request',
                    message: 'payload_not_allowed_for_get',
                    status: 400,
                    endpoint: normalizedEndpoint.endpoint,
                },
            };
        }
        const normalizedPayload = normalizeBackendPayload(body);
        if (!normalizedPayload.ok) {
            return {
                ok: false,
                error: {
                    code: 'bad_request',
                    message: normalizedPayload.error || 'invalid payload',
                    status: 400,
                    endpoint: normalizedEndpoint.endpoint,
                },
            };
        }

        try {
            const result = await BackendManager.requestJson(
                method,
                normalizedEndpoint.endpoint,
                method === 'GET' ? null : normalizedPayload.value,
                timeoutMs,
            );
            return { ok: true, data: result };
        } catch (error) {
            return {
                ok: false,
                error: {
                    code: String(error?.code || 'backend_error'),
                    message: String(error?.message || 'backend request failed'),
                    status: Number(error?.status || 500),
                    endpoint: String(error?.endpoint || normalizedEndpoint.endpoint),
                    data: error?.data || {},
                },
            };
        }
    });
    handleTrusted('check-backend', () => BackendManager.checkServer());
    handleTrusted('start-backend', async () => {
        try {
            await BackendManager.ensureReady();
            return { success: true };
        } catch (err) {
            return { success: false, error: err.message };
        }
    });

    handleTrusted('config:get', () => SharedConfigService.get());
    handleTrusted('config:patch', (_event, patch) => {
        if (!isPlainObject(patch)) {
            return { success: false, message: 'invalid patch payload' };
        }
        return SharedConfigService.patch(patch);
    });
    handleTrusted('config:test-connection', (_event, options) => {
        if (!isPlainObject(options)) {
            return { success: false, message: 'invalid test_connection payload' };
        }
        return SharedConfigService.testConnection(options);
    });
    handleTrusted('config:subscribe', () => SharedConfigService.subscribe());

    handleTrusted('runtime:ensure-service', () => RuntimeManager.ensureService());
    handleTrusted('runtime:start-bot', () => RuntimeManager.startBot());
    handleTrusted('runtime:stop-bot', () => RuntimeManager.stopBot());
    handleTrusted('runtime:start-growth', () => RuntimeManager.startGrowth());
    handleTrusted('runtime:stop-growth', () => RuntimeManager.stopGrowth());
    handleTrusted('runtime:get-idle-state', () => getRuntimeIdleState());
    handleTrusted('runtime:report-status', (_event, summary) => {
        return {
            success: true,
            idle_state: applyRuntimeStatusSummary(summary || {}),
        };
    });
    handleTrusted('runtime:cancel-idle-shutdown', () => {
        return {
            success: true,
            idle_state: runtimeIdleController.cancelIdleShutdown(),
        };
    });

    handleTrusted('growth:get-prompt-state', () => GrowthPromptStore.getState());
    handleTrusted('growth:mark-prompt-seen', (_event, kind) => GrowthPromptStore.markSeen(kind));

    handleTrusted('open-external', async (_event, url) => {
        const policy = validateExternalOpenUrl(url);
        if (!policy.success) {
            console.warn(`Blocked external URL (${policy.error}): ${String(url || '')}`);
            return { success: false, error: policy.error };
        }

        const targetUrl = String(policy.normalizedUrl || '').trim();
        if (!targetUrl) {
            return { success: false, error: 'invalid_url' };
        }

        try {
            await shell.openExternal(targetUrl);
            return { success: true };
        } catch (error) {
            console.warn(`openExternal failed: ${targetUrl}`, error);
            return { success: false, error: 'open_failed' };
        }
    });
    handleTrusted('get-app-version', () => app.getVersion());

    handleTrusted('open-wechat', async () => {
        try {
            const isWechatRunning = () => new Promise((resolve) => {
                exec('tasklist /FI "IMAGENAME eq WeChat.exe" /FO CSV /NH', { windowsHide: true, encoding: 'buffer' }, (err, stdout) => {
                    if (err) return resolve(false);
                    const rows = decodeBufferText(stdout)
                        .split(/\r?\n/)
                        .map(item => item.trim())
                        .filter(Boolean);
                    resolve(rows.some(row => !row.startsWith('INFO:')));
                });
            });
            const waitForWechatRunning = async (attempts = 6, intervalMs = 300) => {
                for (let attempt = 0; attempt < attempts; attempt += 1) {
                    if (await isWechatRunning()) {
                        return true;
                    }
                    if (attempt < attempts - 1) {
                        await new Promise((resolve) => setTimeout(resolve, intervalMs));
                    }
                }
                return false;
            };

            if (await isWechatRunning()) {
                console.log('[OpenWeChat] WeChat already running, skip duplicate launch');
                return { success: true, message: 'WeChat is already running' };
            }
            const getInstallPath = () => new Promise((resolve) => {
                exec('reg query "HKEY_CURRENT_USER\\Software\\Tencent\\WeChat" /v InstallPath', { windowsHide: true, encoding: 'buffer' }, (err, stdout) => {
                    if (err || !stdout) return resolve(null);
                    const decoded = decodeBufferText(stdout);
                    const match = decoded.match(/InstallPath\s+REG_SZ\s+(.+)/);
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
                    'D:\\Program Files\\Tencent\\WeChat\\WeChat.exe',
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
                const openPathError = await shell.openPath(wechatPath);
                if (openPathError) {
                    return { success: false, error: openPathError };
                }
                const launched = await waitForWechatRunning();
                if (!launched) {
                    return { success: false, error: 'wechat_launch_unverified', code: 'wechat_launch_unverified' };
                }
                return { success: true };
            }
            console.log('[OpenWeChat] Path not found, trying protocol');
            await shell.openExternal('weixin://');
            const launched = await waitForWechatRunning();
            if (!launched) {
                return { success: false, error: 'wechat_launch_unverified', code: 'wechat_launch_unverified' };
            }
            return { success: true, message: 'Launched via protocol' };
        } catch (e) {
            console.error('[OpenWeChat] Error:', e);
            return { success: false, error: e.message };
        }
    });

    handleTrusted('restart-app-as-admin', async () => {
        if (process.platform !== 'win32') {
            return { success: false, message: '浠呮敮鎸?Windows 鑷姩鎻愭潈閲嶅惎' };
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
                    ? '宸插彇娑堢鐞嗗憳鏉冮檺鎺堟潈'
                    : `绠＄悊鍛橀噸鍚け璐? ${error?.message || error}`,
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
            message: '姝ｅ湪浠ョ鐞嗗憳韬唤閲嶆柊鍚姩搴旂敤...',
        };
    });

    handleTrusted('minimize-to-tray', () => {
        const win = getMainWindowSafe();
        try { win?.hide(); } catch (_) {}
    });

    handleTrusted('window-minimize', () => {
        const win = getMainWindowSafe();
        try { win?.minimize(); } catch (_) {}
    });
    handleTrusted('window-maximize', () => {
        const win = getMainWindowSafe();
        if (!win) return;
        try {
            win.isMaximized() ? win.unmaximize() : win.maximize();
        } catch (_) {}
    });
    handleTrusted('window-close', () => requestAppClose({ showWindow: false }));

    handleTrusted('confirm-close-action', async (_event, payload) => {
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

    handleTrusted('reset-close-behavior', () => {
        store.set('closeBehavior', 'ask');
        return { success: true };
    });

    handleTrusted('get-update-state', () => GLOBAL_STATE.updateManager?.getState() || {
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
        downloadedInstallerPath: '',
        downloadedInstallerSha256: '',
        checksumAssetUrl: '',
        checksumExpected: '',
        checksumActual: '',
        checksumVerified: false,
    });

    handleTrusted('check-for-updates', (_event, options) => (
        GLOBAL_STATE.updateManager?.checkForUpdates({ ...options, manual: true }) || { success: false, error: 'update manager unavailable' }
    ));

    handleTrusted('skip-update-version', (_event, version) => (
        GLOBAL_STATE.updateManager?.skipVersion(version) || { success: false, error: 'update manager unavailable' }
    ));

    handleTrusted('download-update', () => (
        GLOBAL_STATE.updateManager?.downloadUpdate() || { success: false, error: 'update manager unavailable' }
    ));

    handleTrusted('install-downloaded-update', () => installDownloadedUpdateAndQuit());

    handleTrusted('open-update-download', () => (
        GLOBAL_STATE.updateManager?.openDownloadPage() || { success: false, error: 'download url unavailable' }
    ));

    handleTrusted('export-diagnostics-snapshot', async () => {
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
        const backupsResult = await backendJson('/api/backups?limit=1');

        const snapshot = buildDiagnosticsSnapshot({
            appVersion: app.getVersion(),
            appName: app.getName ? app.getName() : 'wechat-ai-assistant',
            status,
            readiness,
            configAudit,
            configPayload,
            logs: Array.isArray(logsResult?.logs) ? logsResult.logs : [],
            updateState: GLOBAL_STATE.updateManager?.getState() || {},
            backupSummary: backupsResult?.summary || null,
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
            title: '瀵煎嚭璇婃柇蹇収',
            defaultPath,
            filters: [
                { name: 'JSON 鏂囦欢', extensions: ['json'] },
            ],
        });
        if (saveResult.canceled || !saveResult.filePath) {
            return { success: false, canceled: true, message: '鐢ㄦ埛鍙栨秷瀵煎嚭' };
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
            message: 'Diagnostics snapshot exported',
        };
    });
    handleTrusted('is-first-run', () => store.get('isFirstRun'));
    handleTrusted('set-first-run-complete', () => {
        store.set('isFirstRun', false);
        return true;
    });
}

module.exports = {
    registerIpcHandlers,
};

