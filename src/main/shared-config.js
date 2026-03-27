const fs = require('fs');
const { decodeBufferText } = require('./text-codec');

const PROVIDER_ID_ALIASES = {
    claude: 'anthropic',
    bailian: 'qwen',
    dashscope: 'qwen',
    moonshot: 'kimi',
};

const EXTRA_MODEL_PROVIDERS = [
    {
        id: 'qwen',
        label: 'Qwen',
        base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        api_key_url: 'https://dashscope.console.aliyun.com/apiKey',
        aliases: ['qwen', 'dashscope', 'bailian'],
        default_model: 'qwen3.5-plus',
        models: ['qwen3.5-plus', 'qwen3.5-flash', 'qwen3-max-2026-01-23', 'qwen-plus-latest', 'qwen-turbo-latest', 'qwen3-coder-next', 'qwen3-coder-plus', 'qwen3-coder-flash', 'MiniMax-M2.5', 'glm-5', 'glm-4.7', 'kimi-k2.5'],
    },
    {
        id: 'anthropic',
        label: 'Anthropic / Claude',
        base_url: 'https://api.anthropic.com/v1',
        api_key_url: 'https://platform.claude.com/settings/keys',
        aliases: ['anthropic', 'claude'],
        default_model: 'claude-sonnet-4-0',
        models: ['claude-sonnet-4-6', 'claude-opus-4-6', 'claude-haiku-4-5', 'claude-sonnet-4-5', 'claude-opus-4-5', 'claude-sonnet-4-0', 'claude-opus-4-1', 'claude-opus-4-0', 'claude-3-7-sonnet-latest', 'claude-3-5-haiku-latest'],
    },
    {
        id: 'google',
        label: 'Google / Gemini CLI',
        base_url: 'https://generativelanguage.googleapis.com/v1beta/openai',
        api_key_url: 'https://aistudio.google.com/apikey',
        aliases: ['google', 'gemini', 'vertex'],
        default_model: 'gemini-2.5-flash',
        models: ['gemini-3.1-pro-preview', 'gemini-3-flash-preview', 'gemini-3.1-flash-lite-preview', 'gemini-2.5-pro', 'gemini-2.5-flash', 'gemini-2.5-flash-lite'],
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
    {
        id: 'kimi',
        label: 'Kimi / Moonshot',
        base_url: 'https://api.moonshot.cn/v1',
        api_key_url: 'https://platform.moonshot.cn/console/api-keys',
        aliases: ['moonshot', 'kimi'],
        default_model: 'kimi-k2-turbo-preview',
        models: ['kimi-for-coding', 'kimi-k2-turbo-preview', 'kimi-k2-0905-preview', 'kimi-k2-thinking-turbo', 'kimi-thinking-preview', 'kimi-latest'],
    },
    {
        id: 'zhipu',
        label: 'Zhipu',
        base_url: 'https://open.bigmodel.cn/api/paas/v4',
        api_key_url: 'https://open.bigmodel.cn/usercenter/apikeys',
        aliases: ['zhipu', 'glm'],
        default_model: 'glm-5',
        models: ['glm-5', 'glm-4.7', 'glm-4.6', 'glm-4.5-air'],
    },
    {
        id: 'minimax',
        label: 'MiniMax',
        base_url: 'https://api.minimax.io/v1',
        api_key_url: 'https://platform.minimax.io/',
        aliases: ['minimax', 'minimaxi'],
        default_model: 'MiniMax-M2.5',
        models: ['MiniMax-M2.7', 'MiniMax-M2.7-highspeed', 'MiniMax-M2.5', 'MiniMax-M2.5-highspeed', 'MiniMax-M2.1', 'MiniMax-M2.1-highspeed', 'MiniMax-M2', 'MiniMax-Text-01'],
    },
];

const AUTH_METHODS_BY_PROVIDER = {
    openai: [
        { id: 'api_key', type: 'api_key', tier: 'stable', supports_local_reuse: false, requires_browser_flow: false, requires_fields: [], requires_extra_fields: [], metadata: { recommended_base_url: 'https://api.openai.com/v1', recommended_model: 'gpt-5.4-mini' } },
        { id: 'codex_local', type: 'local_import', provider_id: 'openai_codex', tier: 'stable', supports_local_reuse: true, requires_browser_flow: true, requires_fields: [], requires_extra_fields: [], metadata: { recommended_base_url: 'https://api.openai.com/v1', recommended_model: 'gpt-5.4-mini' } },
    ],
    qwen: [
        { id: 'api_key', type: 'api_key', tier: 'stable', supports_local_reuse: false, requires_browser_flow: false, requires_fields: [], requires_extra_fields: [], metadata: { recommended_base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', recommended_model: 'qwen3.5-plus', key_env_hint: 'DASHSCOPE_API_KEY' } },
        { id: 'qwen_oauth', type: 'oauth', provider_id: 'qwen_oauth', tier: 'stable', supports_local_reuse: true, requires_browser_flow: true, requires_fields: [], requires_extra_fields: [], metadata: { recommended_base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', recommended_model: 'qwen3-coder-plus' } },
        { id: 'qwen_local', type: 'local_import', provider_id: 'qwen_oauth', tier: 'stable', supports_local_reuse: true, requires_browser_flow: true, requires_fields: [], requires_extra_fields: [], metadata: { recommended_base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', recommended_model: 'qwen3-coder-plus' } },
        { id: 'coding_plan_api_key', type: 'api_key', tier: 'stable', supports_local_reuse: false, requires_browser_flow: false, requires_fields: [], requires_extra_fields: [], metadata: { recommended_base_url: 'https://coding.dashscope.aliyuncs.com/v1', recommended_model: 'qwen3-coder-next', key_env_hint: 'BAILIAN_CODING_PLAN_API_KEY', key_prefix_hint: 'sk-sp-', subscription: true } },
    ],
    google: [
        { id: 'api_key', type: 'api_key', tier: 'stable', supports_local_reuse: false, requires_browser_flow: false, requires_fields: [], requires_extra_fields: [], metadata: { recommended_base_url: 'https://generativelanguage.googleapis.com/v1beta/openai', recommended_model: 'gemini-2.5-flash' } },
        { id: 'google_oauth', type: 'oauth', provider_id: 'google_gemini_cli', tier: 'experimental', supports_local_reuse: true, requires_browser_flow: true, requires_fields: ['oauth_project_id'], requires_extra_fields: [], metadata: { recommended_base_url: 'https://generativelanguage.googleapis.com/v1beta/openai', recommended_model: 'gemini-2.5-flash' } },
        { id: 'gemini_cli_local', type: 'local_import', provider_id: 'google_gemini_cli', tier: 'experimental', supports_local_reuse: true, requires_browser_flow: true, requires_fields: ['oauth_project_id'], requires_extra_fields: [], metadata: { recommended_base_url: 'https://generativelanguage.googleapis.com/v1beta/openai', recommended_model: 'gemini-2.5-flash' } },
    ],
    anthropic: [
        { id: 'api_key', type: 'api_key', tier: 'stable', supports_local_reuse: false, requires_browser_flow: false, requires_fields: [], requires_extra_fields: [], metadata: { recommended_base_url: 'https://api.anthropic.com/v1', recommended_model: 'claude-sonnet-4-0' } },
        { id: 'claude_code_local', type: 'local_import', provider_id: 'claude_code_local', tier: 'experimental', supports_local_reuse: true, requires_browser_flow: true, requires_fields: [], requires_extra_fields: [], metadata: { recommended_base_url: 'https://api.anthropic.com/v1', recommended_model: 'claude-sonnet-4-0' } },
        { id: 'claude_code_oauth', type: 'oauth', provider_id: 'claude_code_local', tier: 'experimental', supports_local_reuse: true, requires_browser_flow: true, requires_fields: [], requires_extra_fields: [], metadata: { recommended_base_url: 'https://api.anthropic.com/v1', recommended_model: 'claude-sonnet-4-0' } },
        { id: 'claude_vertex_local', type: 'local_import', provider_id: 'claude_vertex_local', tier: 'experimental', supports_local_reuse: true, requires_browser_flow: true, requires_fields: ['oauth_project_id', 'oauth_location'], requires_extra_fields: [], metadata: { recommended_base_url: 'https://global-aiplatform.googleapis.com/v1/projects/{project}/locations/global/publishers/anthropic/models', recommended_model: 'claude-sonnet-4-6' } },
    ],
    kimi: [
        { id: 'api_key', type: 'api_key', tier: 'stable', supports_local_reuse: false, requires_browser_flow: false, requires_fields: [], requires_extra_fields: [], metadata: { recommended_base_url: 'https://api.moonshot.cn/v1', recommended_model: 'kimi-k2-turbo-preview' } },
        { id: 'kimi_code_oauth', type: 'oauth', provider_id: 'kimi_code_local', tier: 'experimental', supports_local_reuse: true, requires_browser_flow: true, requires_fields: [], requires_extra_fields: [], metadata: { recommended_base_url: 'https://api.kimi.com/coding/v1', recommended_model: 'kimi-for-coding' } },
        { id: 'kimi_code_local', type: 'local_import', provider_id: 'kimi_code_local', tier: 'experimental', supports_local_reuse: true, requires_browser_flow: true, requires_fields: [], requires_extra_fields: [], metadata: { recommended_base_url: 'https://api.kimi.com/coding/v1', recommended_model: 'kimi-for-coding' } },
        { id: 'coding_plan_api_key', type: 'api_key', tier: 'stable', supports_local_reuse: false, requires_browser_flow: false, requires_fields: [], requires_extra_fields: [], metadata: { recommended_base_url: 'https://api.kimi.com/coding/v1', recommended_model: 'kimi-for-coding', key_env_hint: 'KIMI_API_KEY' } },
    ],
    zhipu: [
        { id: 'api_key', type: 'api_key', tier: 'stable', supports_local_reuse: false, requires_browser_flow: false, requires_fields: [], requires_extra_fields: [], metadata: { recommended_base_url: 'https://open.bigmodel.cn/api/paas/v4', recommended_model: 'glm-5' } },
        { id: 'coding_plan_api_key', type: 'api_key', tier: 'stable', supports_local_reuse: false, requires_browser_flow: false, requires_fields: [], requires_extra_fields: [], metadata: { recommended_base_url: 'https://open.bigmodel.cn/api/coding/paas/v4', recommended_model: 'glm-5', subscription: true } },
    ],
    minimax: [
        { id: 'api_key', type: 'api_key', tier: 'stable', supports_local_reuse: false, requires_browser_flow: false, requires_fields: [], requires_extra_fields: [], metadata: { recommended_base_url: 'https://api.minimax.io/v1', recommended_model: 'MiniMax-M2.5' } },
        { id: 'coding_plan_api_key', type: 'api_key', tier: 'stable', supports_local_reuse: false, requires_browser_flow: false, requires_fields: [], requires_extra_fields: [], metadata: { recommended_base_url: 'https://api.minimax.io/v1', recommended_model: 'MiniMax-M2.5', regional_base_urls: ['https://api.minimax.io/v1', 'https://api.minimaxi.com/v1', 'https://api.minimax.io/anthropic', 'https://api.minimaxi.com/anthropic'], key_env_hint: 'MINIMAX_API_KEY', subscription: true } },
    ],
    yuanbao: [
        { id: 'yuanbao_web_session', type: 'web_session', provider_id: 'tencent_yuanbao', tier: 'experimental', supports_local_reuse: false, requires_browser_flow: true, requires_fields: [], requires_extra_fields: [], runtime_supported: false },
    ],
};

function canonicalizeProviderId(providerId) {
    const normalized = String(providerId || '').trim().toLowerCase();
    if (!normalized) {
        return '';
    }
    return PROVIDER_ID_ALIASES[normalized] || normalized;
}

function buildAuthMethods(provider = {}) {
    const providerId = canonicalizeProviderId(provider.id);
    if (AUTH_METHODS_BY_PROVIDER[providerId]) {
        return JSON.parse(JSON.stringify(AUTH_METHODS_BY_PROVIDER[providerId]));
    }
    return [
        { id: 'api_key', type: 'api_key', tier: 'stable', supports_local_reuse: false, requires_browser_flow: false, requires_fields: [], requires_extra_fields: [] },
    ];
}

function mergeTextList(...groups) {
    const merged = [];
    const seen = new Set();
    groups.forEach((group) => {
        (group || []).forEach((item) => {
            const value = String(item || '').trim();
            if (!value) {
                return;
            }
            const lowered = value.toLowerCase();
            if (seen.has(lowered)) {
                return;
            }
            seen.add(lowered);
            merged.push(value);
        });
    });
    return merged;
}

function mergeAuthMethods(existingMethods = [], fallbackMethods = []) {
    const merged = [];
    const indexById = new Map();

    (existingMethods || []).forEach((item) => {
        if (!item || typeof item !== 'object') {
            return;
        }
        const method = { ...item };
        const methodId = String(method.id || '').trim();
        if (!methodId || indexById.has(methodId)) {
            return;
        }
        indexById.set(methodId, merged.length);
        merged.push(method);
    });

    (fallbackMethods || []).forEach((item) => {
        if (!item || typeof item !== 'object') {
            return;
        }
        const method = { ...item };
        const methodId = String(method.id || '').trim();
        if (!methodId) {
            return;
        }
        if (!indexById.has(methodId)) {
            indexById.set(methodId, merged.length);
            merged.push(method);
            return;
        }
        const current = merged[indexById.get(methodId)];
        Object.entries(method).forEach(([key, value]) => {
            const currentValue = current[key];
            if (currentValue === undefined || currentValue === null || currentValue === '') {
                current[key] = Array.isArray(value) ? [...value] : value;
                return;
            }
            if (Array.isArray(currentValue) && !currentValue.length) {
                current[key] = Array.isArray(value) ? [...value] : value;
            }
        });
    });

    return merged;
}

function mergeProviderDetails(provider = {}, fallback = {}) {
    const nextProvider = { ...provider };
    const fallbackProvider = { ...fallback };
    const canonicalId = canonicalizeProviderId(nextProvider.id || fallbackProvider.id);
    const rawId = String(nextProvider.id || fallbackProvider.id || '').trim().toLowerCase();
    ['label', 'base_url', 'api_key_url', 'default_model'].forEach((fieldName) => {
        if (!String(nextProvider[fieldName] || '').trim() && String(fallbackProvider[fieldName] || '').trim()) {
            nextProvider[fieldName] = fallbackProvider[fieldName];
        }
    });
    if (nextProvider.allow_empty_key === undefined && fallbackProvider.allow_empty_key !== undefined) {
        nextProvider.allow_empty_key = !!fallbackProvider.allow_empty_key;
    }
    nextProvider.id = canonicalId || rawId;
    const aliases = mergeTextList(nextProvider.aliases, fallbackProvider.aliases);
    if (aliases.length) {
        nextProvider.aliases = aliases;
    }
    const models = mergeTextList(nextProvider.models, fallbackProvider.models);
    if (models.length) {
        nextProvider.models = models;
    }
    const fallbackAuthMethods = Array.isArray(fallbackProvider.auth_methods) && fallbackProvider.auth_methods.length
        ? fallbackProvider.auth_methods
        : buildAuthMethods({ id: nextProvider.id });
    nextProvider.auth_methods = mergeAuthMethods(nextProvider.auth_methods, fallbackAuthMethods);
    return nextProvider;
}

function enrichModelCatalog(payload = {}) {
    const providers = Array.isArray(payload.providers)
        ? payload.providers.map((provider) => mergeProviderDetails(provider))
        : [];
    const providerIndexById = new Map(
        providers
            .map((provider, index) => [canonicalizeProviderId(provider.id), index])
            .filter(([providerId]) => providerId),
    );
    EXTRA_MODEL_PROVIDERS.forEach((provider) => {
        const providerId = canonicalizeProviderId(provider.id);
        const nextProvider = mergeProviderDetails(provider);
        if (providerIndexById.has(providerId)) {
            const currentIndex = providerIndexById.get(providerId);
            providers[currentIndex] = mergeProviderDetails(providers[currentIndex], nextProvider);
            return;
        }
        providerIndexById.set(providerId, providers.length);
        providers.push(nextProvider);
    });
    providers.forEach((provider, index) => {
        providers[index] = mergeProviderDetails(provider);
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
    const existing = canonicalizeProviderId(preset.provider_id);
    if (existing) {
        return existing;
    }
    const name = String(preset.name || '').trim().toLowerCase();
    const baseUrl = String(preset.base_url || '').trim().toLowerCase();
    const model = String(preset.model || '').trim().toLowerCase();
    const isMiniMax = name.includes('minimax')
        || model.includes('minimax')
        || baseUrl.includes('minimax.io')
        || baseUrl.includes('minimaxi.com');
    if (name.includes('ollama') || baseUrl.includes('11434')) return 'ollama';
    if (name.includes('openai') || baseUrl.includes('openai.com')) return 'openai';
    if (name.includes('deepseek') || baseUrl.includes('deepseek.com')) return 'deepseek';
    if (name.includes('qwen') || model.includes('qwen') || baseUrl.includes('dashscope')) return 'qwen';
    if (name.includes('zhipu') || model.includes('glm') || baseUrl.includes('open.bigmodel.cn')) return 'zhipu';
    if (isMiniMax) return 'minimax';
    if (baseUrl.includes('aiplatform.googleapis.com') && (baseUrl.includes('/publishers/anthropic/') || name.includes('claude') || model.includes('claude'))) return 'anthropic';
    if (name.includes('claude') || model.includes('claude') || baseUrl.includes('anthropic')) return 'anthropic';
    if (name.includes('gemini') || model.includes('gemini') || baseUrl.includes('generativelanguage') || baseUrl.includes('aiplatform.googleapis.com')) return 'google';
    if (name.includes('kimi') || name.includes('moonshot') || model.includes('kimi') || baseUrl.includes('moonshot.cn') || baseUrl.includes('api.kimi.com')) return 'kimi';
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
    decodeBufferImpl = decodeBufferText,
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
                    const stdout = decodeBufferImpl(Buffer.concat(stdoutChunks)).trim();
                    const stderr = decodeBufferImpl(Buffer.concat(stderrChunks)).trim();
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
    enrichModelCatalog,
    inferProviderId,
    maskPreset,
    readJsonFile,
};
