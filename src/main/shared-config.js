const fs = require('fs');

const EXTRA_MODEL_PROVIDERS = [
    {
        id: 'google',
        label: 'Google / Gemini CLI',
        base_url: 'https://generativelanguage.googleapis.com/v1beta/openai',
        api_key_url: 'https://aistudio.google.com/apikey',
        aliases: ['google', 'gemini', 'vertex'],
        default_model: 'gemini-2.5-flash',
        models: ['gemini-2.5-flash', 'gemini-2.5-pro', 'gemini-2.5-flash-lite'],
    },
    {
        id: 'yuanbao',
        label: 'Tencent Yuanbao',
        base_url: '',
        api_key_url: 'https://yuanbao.tencent.com/',
        aliases: ['yuanbao', '腾讯元宝'],
        default_model: 'yuanbao-web',
        models: ['yuanbao-web'],
    },
];

const AUTH_METHODS_BY_PROVIDER = {
    openai: [
        { id: 'api_key', type: 'api_key', tier: 'stable', supports_local_reuse: false, requires_browser_flow: false, requires_fields: [], requires_extra_fields: [] },
        { id: 'codex_local', type: 'local_import', provider_id: 'openai_codex', tier: 'stable', supports_local_reuse: true, requires_browser_flow: true, requires_fields: [], requires_extra_fields: [] },
    ],
    qwen: [
        { id: 'api_key', type: 'api_key', tier: 'stable', supports_local_reuse: false, requires_browser_flow: false, requires_fields: [], requires_extra_fields: [] },
        { id: 'qwen_oauth', type: 'oauth', provider_id: 'qwen_oauth', tier: 'stable', supports_local_reuse: true, requires_browser_flow: true, requires_fields: [], requires_extra_fields: [] },
        { id: 'qwen_local', type: 'local_import', provider_id: 'qwen_oauth', tier: 'stable', supports_local_reuse: true, requires_browser_flow: true, requires_fields: [], requires_extra_fields: [] },
        { id: 'coding_plan_api_key', type: 'api_key', tier: 'stable', supports_local_reuse: false, requires_browser_flow: false, requires_fields: [], requires_extra_fields: [] },
    ],
    google: [
        { id: 'api_key', type: 'api_key', tier: 'stable', supports_local_reuse: false, requires_browser_flow: false, requires_fields: [], requires_extra_fields: [] },
        { id: 'google_oauth', type: 'oauth', provider_id: 'google_gemini_cli', tier: 'experimental', supports_local_reuse: true, requires_browser_flow: true, requires_fields: [], requires_extra_fields: [] },
        { id: 'gemini_cli_local', type: 'local_import', provider_id: 'google_gemini_cli', tier: 'experimental', supports_local_reuse: true, requires_browser_flow: true, requires_fields: [], requires_extra_fields: [] },
    ],
    yuanbao: [
        { id: 'yuanbao_web_session', type: 'web_session', provider_id: 'tencent_yuanbao', tier: 'experimental', supports_local_reuse: false, requires_browser_flow: true, requires_fields: [], requires_extra_fields: [], runtime_supported: false },
    ],
};

function buildAuthMethods(provider = {}) {
    const providerId = String(provider.id || '').trim().toLowerCase();
    if (AUTH_METHODS_BY_PROVIDER[providerId]) {
        return JSON.parse(JSON.stringify(AUTH_METHODS_BY_PROVIDER[providerId]));
    }
    return [
        { id: 'api_key', type: 'api_key', tier: 'stable', supports_local_reuse: false, requires_browser_flow: false, requires_fields: [], requires_extra_fields: [] },
    ];
}

function enrichModelCatalog(payload = {}) {
    const providers = Array.isArray(payload.providers) ? payload.providers.map((provider) => ({ ...provider })) : [];
    const existingIds = new Set(providers.map((provider) => String(provider.id || '').trim().toLowerCase()));
    EXTRA_MODEL_PROVIDERS.forEach((provider) => {
        if (!existingIds.has(provider.id)) {
            providers.push({ ...provider });
        }
    });
    providers.forEach((provider) => {
        if (!Array.isArray(provider.auth_methods) || !provider.auth_methods.length) {
            provider.auth_methods = buildAuthMethods(provider);
        }
    });
    return {
        ...payload,
        providers,
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
    if (name.includes('gemini') || model.includes('gemini') || baseUrl.includes('generativelanguage') || baseUrl.includes('aiplatform.googleapis.com')) return 'google';
    if (name.includes('yuanbao') || model.includes('yuanbao') || baseUrl.includes('yuanbao.tencent.com')) return 'yuanbao';
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

function createConfigCli({
    spawn,
    getBackendCommand,
    getSharedConfigPath,
    readJsonFileImpl = readJsonFile,
    fsModule = fs,
}) {
    return {
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
                    } catch (_) {
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
            if (fsModule.existsSync(configPath)) {
                return readJsonFileImpl(configPath, {});
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
}

function createSharedConfigService({
    ConfigCli,
    getSharedConfigPath,
    getSharedModelCatalogPath,
    ensureDir,
    buildRendererConfigPayloadImpl = buildRendererConfigPayload,
    readJsonFileImpl = readJsonFile,
    atomicWriteJsonImpl = atomicWriteJson,
    diffConfigPathsImpl = diffConfigPaths,
    listWindows,
    backendCheckServer,
    backendRequestJson,
    consoleImpl = console,
    fsModule = fs,
}) {
    return {
        _cache: null,
        _watching: false,
        _writeQueue: Promise.resolve(),
        _modelCatalogCache: null,

        async ensureLoaded() {
            if (this._cache) {
                return this._cache;
            }
            await ConfigCli.ensureMigrated();
            this._cache = readJsonFileImpl(getSharedConfigPath(), {});
            this._ensureWatcher();
            return this._cache;
        },

        _ensureWatcher() {
            if (this._watching) {
                return;
            }
            const configPath = getSharedConfigPath();
            fsModule.watchFile(configPath, { interval: 500 }, async (current, previous) => {
                if (current.mtimeMs === previous.mtimeMs) {
                    return;
                }
                try {
                    this._cache = readJsonFileImpl(configPath, {});
                    this.broadcast('external');
                } catch (error) {
                    consoleImpl.error('[Config] reload failed:', error);
                }
            });
            this._watching = true;
        },

        getModelCatalog() {
            const catalogPath = getSharedModelCatalogPath();
            try {
                const stat = fsModule.statSync(catalogPath);
                if (
                    this._modelCatalogCache
                    && this._modelCatalogCache.mtimeMs === stat.mtimeMs
                ) {
                    return this._modelCatalogCache.payload;
                }
                const payload = enrichModelCatalog(readJsonFileImpl(catalogPath, { providers: [] }));
                this._modelCatalogCache = {
                    mtimeMs: stat.mtimeMs,
                    payload,
                };
                return payload;
            } catch (_) {
                this._modelCatalogCache = null;
                return enrichModelCatalog({ providers: [] });
            }
        },

        buildPayload(config = {}) {
            return {
                success: true,
                ...buildRendererConfigPayloadImpl(config),
                modelCatalog: this.getModelCatalog(),
                configPath: getSharedConfigPath(),
            };
        },

        broadcast(source = 'external') {
            const payload = {
                ...this.buildPayload(this._cache || {}),
                source,
            };
            for (const win of listWindows()) {
                if (!win || (typeof win.isDestroyed === 'function' && win.isDestroyed())) {
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
                const changedPaths = diffConfigPathsImpl(previous, nextConfig);
                const configPath = getSharedConfigPath();
                ensureDir(require('path').dirname(configPath));
                atomicWriteJsonImpl(configPath, nextConfig);
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
            if (await backendCheckServer()) {
                try {
                    return await backendRequestJson(
                        'POST',
                        '/api/test_connection',
                        {
                            preset_name: presetName || null,
                            patch,
                        },
                        12000,
                    );
                } catch (error) {
                    consoleImpl.warn('[SharedConfigService] live connection test failed, fallback to CLI:', error);
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
}

module.exports = {
    atomicWriteJson,
    buildRendererConfigPayload,
    createConfigCli,
    createSharedConfigService,
    diffConfigPaths,
    inferProviderId,
    maskPreset,
    readJsonFile,
};
