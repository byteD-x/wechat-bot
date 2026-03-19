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
        growthEnableCostPromptSeen: false,
        growthDisableRiskPromptSeen: false,
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

function flattenPaths(input, prefix = '', output = {}) {
    if (!input || typeof input !== 'object' || Array.isArray(input)) {
        if (prefix) {
            output[prefix] = input;
        }
        return output;
    }
    const entries = Object.entries(input);
    if (!entries.length && prefix) {
        output[prefix] = input;
        return output;
    }
    for (const [key, value] of entries) {
        const nextPrefix = prefix ? `${prefix}.${key}` : key;
        if (value && typeof value === 'object' && !Array.isArray(value)) {
            flattenPaths(value, nextPrefix, output);
        } else {
            output[nextPrefix] = value;
        }
    }
    return output;
}

function diffConfigPaths(before = {}, after = {}) {
    const left = flattenPaths(before);
    const right = flattenPaths(after);
    const keys = new Set([...Object.keys(left), ...Object.keys(right)]);
    return [...keys].filter((key) => JSON.stringify(left[key]) !== JSON.stringify(right[key])).sort();
}

function inferProviderId(preset = {}) {
    const existing = String(preset.provider_id || '').trim().toLowerCase();
    if (existing) {
        return existing;
    }
    const name = String(preset.name || '').trim().toLowerCase();
    const baseUrl = String(preset.base_url || '').trim().toLowerCase();
    const model = String(preset.model || '').trim().toLowerCase();
    if (name.includes('ollama') || baseUrl.includes('11434')) return 'ollama';
    if (name.includes('openai') || baseUrl.includes('openai.com')) return 'openai';
    if (name.includes('deepseek') || baseUrl.includes('deepseek.com')) return 'deepseek';
    if (name.includes('qwen') || model.includes('qwen') || baseUrl.includes('dashscope')) return 'qwen';
    if (name.includes('claude') || model.includes('claude') || baseUrl.includes('anthropic')) return 'anthropic';
    if (name.includes('gemini') || model.includes('gemini') || baseUrl.includes('generativelanguage')) return 'gemini';
    return '';
}

function maskPreset(preset = {}) {
    const nextPreset = { ...preset };
    nextPreset.provider_id = inferProviderId(nextPreset);
    const apiKey = String(nextPreset.api_key || '').trim();
    const allowEmptyKey = !!nextPreset.allow_empty_key;
    if (allowEmptyKey) {
        nextPreset.api_key_configured = false;
        nextPreset.api_key_masked = '';
    } else if (apiKey && !apiKey.startsWith('YOUR_')) {
        nextPreset.api_key_configured = true;
        nextPreset.api_key_masked = apiKey.length > 12 ? `${apiKey.slice(0, 8)}****${apiKey.slice(-4)}` : '****';
    } else {
        nextPreset.api_key_configured = false;
        nextPreset.api_key_masked = '';
    }
    nextPreset.api_key_required = !allowEmptyKey;
    delete nextPreset.api_key;
    return nextPreset;
}

function buildRendererConfigPayload(config = {}) {
    const api = { ...(config.api || {}) };
    api.presets = Array.isArray(api.presets) ? api.presets.map((preset) => maskPreset(preset)) : [];

    const bot = { ...(config.bot || {}) };
    delete bot.reply_timeout_fallback_text;
    delete bot.stream_buffer_chars;
    delete bot.stream_chunk_max_chars;
    delete bot.stream_reply;

    const agent = { ...(config.agent || {}) };
    agent.langsmith_api_key_configured = !!String(agent.langsmith_api_key || '').trim();
    delete agent.langsmith_api_key;
    delete agent.streaming_enabled;

    return {
        api,
        bot,
        logging: { ...(config.logging || {}) },
        agent,
        services: { ...(config.services || {}) },
    };
}

function readJsonFile(filePath, fallback = {}) {
    try {
        return JSON.parse(fs.readFileSync(filePath, 'utf8'));
    } catch (_) {
        return fallback;
    }
}

function atomicWriteJson(filePath, payload) {
    const rendered = `${JSON.stringify(payload, null, 2)}\n`;
    const tempPath = `${filePath}.tmp`;
    fs.writeFileSync(tempPath, rendered, 'utf8');
    fs.renameSync(tempPath, filePath);
}

// ═══════════════════════════════════════════════════════════════════════════════
//                               Python 后端管理
// ═══════════════════════════════════════════════════════════════════════════════

const BackendManager = {
    checkServer() {
        return new Promise((resolve) => {
            const req = http.get({
                hostname: '127.0.0.1',
                port: GLOBAL_STATE.flaskPort,
                path: '/api/ping',
                headers: GLOBAL_STATE.apiToken ? { 'X-Api-Token': GLOBAL_STATE.apiToken } : {},
            }, (res) => {
                resolve(res.statusCode === 200);
            });
            req.on('error', () => resolve(false));
            req.setTimeout(1000, () => {
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

        const { cmd, args, options } = getBackendCommand([
            'web',
            '--host',
            '127.0.0.1',
            '--port',
            GLOBAL_STATE.flaskPort.toString(),
        ]);

        console.log(`[Backend] 启动: ${cmd} ${args.join(' ')}`);
        updateSplashStatus('正在启动后端服务...', 35);
        
        GLOBAL_STATE.pythonProcess = spawn(cmd, args, options);
        this._setupProcessListeners(GLOBAL_STATE.pythonProcess);
    },

    async ensureReady(timeoutMs = 20000) {
        await this.start();
        const startedAt = Date.now();
        while ((Date.now() - startedAt) < timeoutMs) {
            if (await this.checkServer()) {
                return true;
            }
            await new Promise((resolve) => setTimeout(resolve, 400));
        }
        throw new Error('Python 服务启动超时');
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
    },

    requestJson(method, endpoint, payload = null, timeoutMs = 10000) {
        return new Promise((resolve, reject) => {
            const body = payload == null ? null : JSON.stringify(payload);
            const req = http.request(
                {
                    hostname: '127.0.0.1',
                    port: GLOBAL_STATE.flaskPort,
                    path: endpoint,
                    method,
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Api-Token': GLOBAL_STATE.apiToken,
                        ...(body ? { 'Content-Length': Buffer.byteLength(body) } : {}),
                    },
                    timeout: timeoutMs,
                },
                (res) => {
                    const chunks = [];
                    res.on('data', (chunk) => chunks.push(chunk));
                    res.on('end', () => {
                        const raw = Buffer.concat(chunks).toString('utf8');
                        let data = {};
                        if (raw.trim()) {
                            try {
                                data = JSON.parse(raw);
                            } catch (error) {
                                reject(new Error(`后端返回了无效 JSON: ${raw.slice(0, 200)}`));
                                return;
                            }
                        }
                        if ((res.statusCode || 500) >= 400) {
                            reject(new Error(data?.message || `后端请求失败 (${res.statusCode})`));
                            return;
                        }
                        resolve(data);
                    });
                }
            );
            req.on('error', reject);
            req.on('timeout', () => req.destroy(new Error('请求超时')));
            if (body) {
                req.write(body);
            }
            req.end();
        });
    }
};

const ConfigCli = {
    async run(commandArgs, options = {}) {
        const {
            stdinPayload = null,
            timeoutMs = 20000,
        } = options;
        const { cmd, args, options: spawnOptions } = getBackendCommand(commandArgs);

        return new Promise((resolve, reject) => {
            const child = spawn(cmd, args, {
                ...spawnOptions,
                stdio: ['pipe', 'pipe', 'pipe'],
            });
            const stdoutChunks = [];
            const stderrChunks = [];
            let settled = false;

            const finish = (error, value) => {
                if (settled) {
                    return;
                }
                settled = true;
                if (timer) {
                    clearTimeout(timer);
                }
                if (error) {
                    reject(error);
                } else {
                    resolve(value);
                }
            };

            const timer = setTimeout(() => {
                try {
                    child.kill('SIGTERM');
                } catch (_) {}
                finish(new Error(`配置命令执行超时: ${commandArgs.join(' ')}`));
            }, timeoutMs);

            child.stdout.on('data', (chunk) => stdoutChunks.push(Buffer.from(chunk)));
            child.stderr.on('data', (chunk) => stderrChunks.push(Buffer.from(chunk)));
            child.on('error', (error) => finish(error));
            child.on('exit', (code) => {
                const stdout = Buffer.concat(stdoutChunks).toString('utf8').trim();
                const stderr = Buffer.concat(stderrChunks).toString('utf8').trim();
                if (code !== 0) {
                    finish(new Error(stderr || stdout || `配置命令退出失败 (${code})`));
                    return;
                }
                const lines = stdout.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
                const jsonLine = [...lines].reverse().find((line) => line.startsWith('{') && line.endsWith('}'));
                if (!jsonLine) {
                    finish(new Error(stdout || '配置命令未返回 JSON 结果'));
                    return;
                }
                try {
                    finish(null, JSON.parse(jsonLine));
                } catch (error) {
                    finish(new Error(`配置命令返回了不可解析 JSON: ${jsonLine}`));
                }
            });

            if (stdinPayload != null) {
                child.stdin.write(JSON.stringify(stdinPayload));
            }
            child.stdin.end();
        });
    },

    async ensureMigrated() {
        const configPath = getSharedConfigPath();
        if (fs.existsSync(configPath)) {
            return readJsonFile(configPath, {});
        }
        const result = await this.run(['config', 'migrate', '--output', configPath], { timeoutMs: 30000 });
        return result.config || {};
    },

    async validate(patch = {}) {
        await this.ensureMigrated();
        const useStdin = !!patch && Object.keys(patch).length > 0;
        const args = ['config', 'validate', '--base-path', getSharedConfigPath()];
        if (useStdin) {
            args.push('--stdin');
        }
        const result = await this.run(args, {
            stdinPayload: useStdin ? patch : null,
            timeoutMs: 30000,
        });
        if (!result?.success) {
            throw new Error(result?.message || '配置校验失败');
        }
        return result.config || {};
    },

    async probe({ patch = null, presetName = '' } = {}) {
        await this.ensureMigrated();
        const useStdin = !!patch && Object.keys(patch).length > 0;
        const args = ['config', 'probe', '--base-path', getSharedConfigPath()];
        if (useStdin) {
            args.push('--stdin');
        }
        if (presetName) {
            args.push('--preset-name', presetName);
        }
        return this.run(args, {
            stdinPayload: useStdin ? patch : null,
            timeoutMs: 15000,
        });
    },
};

const SharedConfigService = {
    _cache: null,
    _watching: false,
    _writeQueue: Promise.resolve(),
    _modelCatalogCache: null,

    async ensureLoaded() {
        if (this._cache) {
            return this._cache;
        }
        await ConfigCli.ensureMigrated();
        this._cache = readJsonFile(getSharedConfigPath(), {});
        this._ensureWatcher();
        return this._cache;
    },

    _ensureWatcher() {
        if (this._watching) {
            return;
        }
        const configPath = getSharedConfigPath();
        fs.watchFile(configPath, { interval: 500 }, async (current, previous) => {
            if (current.mtimeMs === previous.mtimeMs) {
                return;
            }
            try {
                this._cache = readJsonFile(configPath, {});
                this.broadcast('external');
            } catch (error) {
                console.error('[Config] reload failed:', error);
            }
        });
        this._watching = true;
    },

    getModelCatalog() {
        const catalogPath = getSharedModelCatalogPath();
        try {
            const stat = fs.statSync(catalogPath);
            if (
                this._modelCatalogCache
                && this._modelCatalogCache.mtimeMs === stat.mtimeMs
            ) {
                return this._modelCatalogCache.payload;
            }
            const payload = readJsonFile(catalogPath, { providers: [] });
            this._modelCatalogCache = {
                mtimeMs: stat.mtimeMs,
                payload,
            };
            return payload;
        } catch (_) {
            this._modelCatalogCache = null;
            return { providers: [] };
        }
    },

    buildPayload(config = {}) {
        return {
            success: true,
            ...buildRendererConfigPayload(config),
            modelCatalog: this.getModelCatalog(),
            configPath: getSharedConfigPath(),
        };
    },

    broadcast(source = 'external') {
        const payload = {
            ...this.buildPayload(this._cache || {}),
            source,
        };
        for (const win of BrowserWindow.getAllWindows()) {
            if (!win || win.isDestroyed()) {
                continue;
            }
            try {
                win.webContents.send('config:changed', payload);
            } catch (_) {}
        }
    },

    async get() {
        const config = await this.ensureLoaded();
        return this.buildPayload(config);
    },

    async patch(patch = {}) {
        let response = null;
        const task = this._writeQueue.catch(() => {}).then(async () => {
            const previous = JSON.parse(JSON.stringify(await this.ensureLoaded()));
            const nextConfig = await ConfigCli.validate(patch);
            const changedPaths = diffConfigPaths(previous, nextConfig);
            const configPath = getSharedConfigPath();
            ensureDir(path.dirname(configPath));
            atomicWriteJson(configPath, nextConfig);
            this._cache = nextConfig;
            response = {
                ...this.buildPayload(nextConfig),
                changed_paths: changedPaths,
                message: changedPaths.length ? '配置已保存' : '未检测到配置变更',
                save_state: 'saved',
            };
        });
        this._writeQueue = task.then(() => null, () => null);
        await task;
        this.broadcast('main_write');
        return response;
    },

    async testConnection(options = {}) {
        const patch = options?.patch && typeof options.patch === 'object' ? options.patch : null;
        const presetName = String(options?.presetName || '').trim();
        if (await BackendManager.checkServer()) {
            try {
                return await BackendManager.requestJson(
                    'POST',
                    '/api/test_connection',
                    {
                        preset_name: presetName || null,
                        patch,
                    },
                    12000,
                );
            } catch (error) {
                console.warn('[SharedConfigService] live connection test failed, fallback to CLI:', error);
            }
        }
        return ConfigCli.probe({ patch, presetName });
    },

    async subscribe() {
        await this.ensureLoaded();
        this._ensureWatcher();
        return this.buildPayload(this._cache || {});
    },
};

const RuntimeManager = {
    async ensureService() {
        await BackendManager.ensureReady();
        return { success: true };
    },

    async startBot() {
        await BackendManager.ensureReady();
        return BackendManager.requestJson('POST', '/api/start', null, 45000);
    },

    async stopBot() {
        const result = await BackendManager.requestJson('POST', '/api/stop');
        const idleResult = await this.stopServiceIfIdle();
        return {
            ...result,
            service_stopped: !!idleResult?.stopped,
        };
    },

    async startGrowth() {
        await BackendManager.ensureReady();
        return BackendManager.requestJson('POST', '/api/growth/start', null, 45000);
    },

    async stopGrowth() {
        const result = await BackendManager.requestJson('POST', '/api/growth/stop');
        const idleResult = await this.stopServiceIfIdle();
        return {
            ...result,
            service_stopped: !!idleResult?.stopped,
        };
    },

    async stopServiceIfIdle() {
        const status = await this.safeStatus();
        if (status && !status.bot_running && !status.growth_running) {
            await BackendManager.stop();
            return { success: true, stopped: true };
        }
        return { success: true, stopped: false };
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

    ipcMain.handle('growth:get-prompt-state', () => GrowthPromptStore.getState());
    ipcMain.handle('growth:mark-prompt-seen', (_, kind) => GrowthPromptStore.markSeen(kind));
    
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
        BackendManager.stop();
    });

    app.on('window-all-closed', () => {
        // 保持托盘运行
    });

    app.on('activate', () => {
        if (BrowserWindow.getAllWindows().length === 0) WindowManager.createMain();
    });
}
