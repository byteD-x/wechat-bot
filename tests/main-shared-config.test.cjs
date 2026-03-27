const test = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('events');
const fs = require('fs');
const os = require('os');
const path = require('path');
const iconv = require('iconv-lite');

const {
    buildRendererConfigPayload,
    createConfigCli,
    createSharedConfigService,
    enrichModelCatalog,
} = require('../src/main/shared-config');
const { decodeBufferText } = require('../src/main/text-codec');
const {
    buildDiagnosticsSnapshot,
} = require('../src/main/diagnostics-snapshot');
const {
    buildElevatedLaunchPlan,
    buildElevatedPowerShellScript,
    launchElevatedApp,
} = require('../src/main/elevated-relaunch');

test('buildRendererConfigPayload masks secrets and drops runtime-only fields', () => {
    const payload = buildRendererConfigPayload({
        api: {
            presets: [
                {
                    name: 'OpenAI',
                    api_key: 'demo-openai-key-123456',
                    base_url: 'https://api.openai.com/v1',
                },
            ],
        },
        bot: {
            stream_reply: true,
            stream_buffer_chars: 12,
            stream_chunk_max_chars: 34,
            reply_timeout_fallback_text: 'fallback',
            keep_field: 'ok',
        },
        agent: {
            langsmith_api_key: 'ls-key',
            streaming_enabled: true,
            graph_mode: 'state_graph',
        },
    });

    assert.equal(payload.api.presets[0].api_key, undefined);
    assert.equal(payload.api.presets[0].api_key_configured, true);
    assert.match(payload.api.presets[0].api_key_masked, /\*\*\*\*/);
    assert.equal(payload.bot.keep_field, 'ok');
    assert.equal('stream_reply' in payload.bot, false);
    assert.equal('reply_timeout_fallback_text' in payload.bot, false);
    assert.equal(payload.agent.graph_mode, 'state_graph');
    assert.equal(payload.agent.langsmith_api_key_configured, true);
    assert.equal('langsmith_api_key' in payload.agent, false);
    assert.equal('streaming_enabled' in payload.agent, false);
});

test('buildRendererConfigPayload canonicalizes provider ids for claude, kimi, and zhipu presets', () => {
    const payload = buildRendererConfigPayload({
        api: {
            presets: [
                {
                    name: 'Claude Code',
                    base_url: 'https://api.anthropic.com/v1',
                    model: 'claude-sonnet-4-0',
                    api_key: 'claude-demo-key-123456',
                },
                {
                    name: 'Moonshot',
                    provider_id: 'moonshot',
                    base_url: 'https://api.moonshot.cn/v1',
                    model: 'kimi-k2-turbo-preview',
                    api_key: 'kimi-demo-key-123456',
                },
                {
                    name: 'GLM Coding Plan',
                    base_url: 'https://open.bigmodel.cn/api/coding/paas/v4',
                    model: 'glm-5',
                    api_key: 'glm-demo-key-123456',
                },
                {
                    name: 'Bailian Coding Plan',
                    provider_id: 'bailian',
                    base_url: 'https://coding.dashscope.aliyuncs.com/v1',
                    model: 'MiniMax-M2.5',
                    api_key: 'bailian-demo-key-123456',
                },
                {
                    name: 'Claude Vertex',
                    base_url: 'https://global-aiplatform.googleapis.com/v1/projects/demo/locations/global/publishers/anthropic/models',
                    model: 'claude-sonnet-4-6',
                    api_key: 'vertex-demo-key-123456',
                },
            ],
        },
    });

    assert.equal(payload.api.presets[0].provider_id, 'anthropic');
    assert.equal(payload.api.presets[1].provider_id, 'kimi');
    assert.equal(payload.api.presets[2].provider_id, 'zhipu');
    assert.equal(payload.api.presets[3].provider_id, 'qwen');
    assert.equal(payload.api.presets[4].provider_id, 'anthropic');
    assert.equal(payload.api.presets[0].api_key, undefined);
    assert.equal(payload.api.presets[1].api_key, undefined);
    assert.equal(payload.api.presets[2].api_key, undefined);
    assert.equal(payload.api.presets[3].api_key, undefined);
    assert.equal(payload.api.presets[4].api_key, undefined);
});

test('buildRendererConfigPayload canonicalizes minimax direct and anthropic-compatible endpoint presets', () => {
    const payload = buildRendererConfigPayload({
        api: {
            presets: [
                {
                    name: 'MiniMax China',
                    base_url: 'https://api.minimaxi.com/v1',
                    model: 'MiniMax-M2.5',
                    api_key: 'minimax-demo-key-123456',
                },
                {
                    name: 'MiniMax Coding Anthropic',
                    base_url: 'https://api.minimax.io/anthropic/v1',
                    model: 'MiniMax-M2.5',
                    api_key: 'minimax-anthropic-demo-key-123456',
                },
                {
                    name: 'MiniMax CN Messages',
                    base_url: 'https://api.minimaxi.com/anthropic/messages',
                    model: 'MiniMax-M2.5',
                    api_key: 'minimax-cn-anthropic-demo-key-123456',
                },
            ],
        },
    });

    assert.equal(payload.api.presets[0].provider_id, 'minimax');
    assert.equal(payload.api.presets[0].api_key, undefined);
    assert.equal(payload.api.presets[1].provider_id, 'minimax');
    assert.equal(payload.api.presets[1].api_key, undefined);
    assert.equal(payload.api.presets[2].provider_id, 'minimax');
    assert.equal(payload.api.presets[2].api_key, undefined);
});

test('enrichModelCatalog merges existing qwen provider with latest coding plan models and auth methods', () => {
    const result = enrichModelCatalog({
        providers: [
            {
                id: 'bailian',
                label: 'Bailian Coding Plan',
                base_url: 'https://coding.dashscope.aliyuncs.com/v1',
                models: ['qwen3-coder-next'],
            },
        ],
    });

    const qwen = result.providers.find((provider) => provider.id === 'qwen');
    assert.ok(qwen);
    assert.equal(qwen.base_url, 'https://coding.dashscope.aliyuncs.com/v1');
    assert.equal(qwen.label, 'Bailian Coding Plan');
    assert.equal(qwen.models.includes('qwen3-coder-next'), true);
    assert.equal(qwen.models.includes('MiniMax-M2.5'), true);
    assert.equal(qwen.models.includes('glm-5'), true);
    assert.equal(qwen.models.includes('kimi-k2.5'), true);
    assert.equal(qwen.auth_methods.some((method) => method.id === 'qwen_oauth'), true);
    assert.equal(qwen.auth_methods.some((method) => method.id === 'coding_plan_api_key'), true);
});

test('enrichModelCatalog exposes runtime metadata for coding plan and oauth auth methods', () => {
    const result = enrichModelCatalog({
        providers: [
            { id: 'qwen' },
            { id: 'kimi' },
            { id: 'zhipu' },
            { id: 'minimax' },
        ],
    });

    const providers = Object.fromEntries(result.providers.map((provider) => [provider.id, provider]));
    const qwenMethods = Object.fromEntries((providers.qwen.auth_methods || []).map((method) => [method.id, method]));
    const kimiMethods = Object.fromEntries((providers.kimi.auth_methods || []).map((method) => [method.id, method]));
    const zhipuMethods = Object.fromEntries((providers.zhipu.auth_methods || []).map((method) => [method.id, method]));
    const minimaxMethods = Object.fromEntries((providers.minimax.auth_methods || []).map((method) => [method.id, method]));

    assert.equal(qwenMethods.qwen_oauth.metadata.recommended_base_url, 'https://dashscope.aliyuncs.com/compatible-mode/v1');
    assert.equal(qwenMethods.qwen_oauth.metadata.recommended_model, 'qwen3-coder-plus');
    assert.equal(qwenMethods.coding_plan_api_key.metadata.recommended_base_url, 'https://coding.dashscope.aliyuncs.com/v1');
    assert.equal(qwenMethods.coding_plan_api_key.metadata.recommended_model, 'qwen3-coder-next');
    assert.equal(kimiMethods.kimi_code_oauth.metadata.recommended_base_url, 'https://api.kimi.com/coding/v1');
    assert.equal(kimiMethods.kimi_code_oauth.metadata.recommended_model, 'kimi-for-coding');
    assert.equal(zhipuMethods.coding_plan_api_key.metadata.recommended_base_url, 'https://open.bigmodel.cn/api/coding/paas/v4');
    assert.equal(minimaxMethods.coding_plan_api_key.metadata.regional_base_urls.includes('https://api.minimax.io/anthropic'), true);
});

test('decodeBufferText decodes Chinese text from gb18030 bytes', () => {
    const encoded = iconv.encode('配置命令失败', 'gb18030');

    assert.equal(decodeBufferText(encoded), '配置命令失败');
});

test('createConfigCli.run surfaces Chinese stderr from Windows buffers', async () => {
    const cli = createConfigCli({
        spawn() {
            const child = new EventEmitter();
            child.stdout = new EventEmitter();
            child.stderr = new EventEmitter();
            child.stdin = {
                write() {},
                end() {},
            };
            process.nextTick(() => {
                child.stderr.emit('data', iconv.encode('配置命令退出失败', 'gb18030'));
                child.emit('exit', 1);
            });
            return child;
        },
        getBackendCommand() {
            return {
                cmd: 'python',
                args: ['run.py', 'config', 'probe'],
                options: {},
            };
        },
        getSharedConfigPath() {
            return 'E:\\fake\\app_config.json';
        },
    });

    await assert.rejects(
        () => cli.run(['config', 'probe']),
        /配置命令退出失败/,
    );
});

test('createSharedConfigService.patch persists config and broadcasts changes', async () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'wechat-shared-config-'));
    const configPath = path.join(root, 'app_config.json');
    const catalogPath = path.join(root, 'model_catalog.json');
    fs.writeFileSync(configPath, JSON.stringify({
        api: { presets: [] },
        bot: { keep_field: 'before' },
        agent: {},
    }), 'utf8');
    fs.writeFileSync(catalogPath, JSON.stringify({ providers: [{ id: 'openai' }] }), 'utf8');

    const broadcasts = [];
    const service = createSharedConfigService({
        ConfigCli: {
            async ensureMigrated() {
                return {};
            },
            async validate(patch) {
                return {
                    api: { presets: [] },
                    bot: { ...(patch.bot || {}), keep_field: 'after' },
                    agent: {},
                };
            },
            async probe() {
                return { success: true };
            },
        },
        getSharedConfigPath: () => configPath,
        getSharedModelCatalogPath: () => catalogPath,
        ensureDir: (dirPath) => {
            fs.mkdirSync(dirPath, { recursive: true });
            return dirPath;
        },
        listWindows: () => [
            {
                isDestroyed: () => false,
                webContents: {
                    send(channel, payload) {
                        broadcasts.push({ channel, payload });
                    },
                },
            },
        ],
        backendCheckServer: async () => false,
        backendRequestJson: async () => ({ success: true }),
    });

    const result = await service.patch({
        bot: {
            memory_context_limit: 8,
        },
    });

    assert.equal(result.success, true);
    assert.deepEqual(result.changed_paths, ['bot.keep_field', 'bot.memory_context_limit']);
    assert.equal(result.modelCatalog.providers[0].id, 'openai');
    assert.equal(broadcasts.length, 1);
    assert.equal(broadcasts[0].channel, 'config:changed');
    assert.equal(broadcasts[0].payload.source, 'main_write');

    const persisted = JSON.parse(fs.readFileSync(configPath, 'utf8'));
    assert.equal(persisted.bot.keep_field, 'after');
    assert.equal(persisted.bot.memory_context_limit, 8);

    fs.unwatchFile(configPath);
});

test('buildDiagnosticsSnapshot keeps masked fields and strips secrets', () => {
    const snapshot = buildDiagnosticsSnapshot({
        appVersion: '1.0.0',
        status: {
            running: false,
            token: 'secret-token',
        },
        readiness: {
            ready: false,
        },
        configAudit: {
            loaded: true,
        },
        configPayload: {
            api: {
                presets: [
                    {
                        name: 'OpenAI',
                        api_key: 'demo-secret-key',
                        api_key_configured: true,
                        api_key_masked: 'sk-****',
                    },
                ],
            },
            services: {
                webhook_token: 'webhook-secret',
            },
        },
        logs: ['line1'],
        updateState: {
            latestVersion: '1.1.0',
        },
        collectionErrors: ['backend unavailable'],
    });

    assert.equal(snapshot.runtime.status.token, undefined);
    assert.equal(snapshot.config.effective.api.presets[0].api_key, undefined);
    assert.equal(snapshot.config.effective.api.presets[0].api_key_configured, true);
    assert.equal(snapshot.config.effective.api.presets[0].api_key_masked, 'sk-****');
    assert.equal(snapshot.config.effective.services.webhook_token, undefined);
    assert.deepEqual(snapshot.logs, ['line1']);
});

test('elevated relaunch helpers preserve default app arguments and PowerShell quoting', () => {
    const plan = buildElevatedLaunchPlan({
        processLike: {
            execPath: 'C:\\Program Files\\Electron\\electron.exe',
            defaultApp: true,
            argv: [
                'C:\\Program Files\\Electron\\electron.exe',
                '.',
                '--dev',
                "--profile=O'Reilly",
            ],
        },
        appPath: 'E:\\Project\\wechat-chat',
    });

    assert.equal(plan.filePath, 'C:\\Program Files\\Electron\\electron.exe');
    assert.deepEqual(plan.args, [
        'E:\\Project\\wechat-chat',
        '--dev',
        "--profile=O'Reilly",
    ]);

    const script = buildElevatedPowerShellScript(plan);
    assert.match(script, /Start-Process/);
    assert.match(script, /-Verb RunAs/);
    assert.match(script, /O''Reilly/);
});

test('launchElevatedApp invokes PowerShell with encoded command and returns launch plan', async () => {
    const calls = [];
    const result = await launchElevatedApp({
        execFileImpl(file, args, callback) {
            calls.push({ file, args });
            callback(null, '', '');
        },
        processLike: {
            execPath: 'C:\\Program Files\\wechat-ai-assistant.exe',
            defaultApp: false,
            argv: [
                'C:\\Program Files\\wechat-ai-assistant.exe',
                '--dev',
            ],
        },
    });

    assert.equal(result.success, true);
    assert.equal(result.filePath, 'C:\\Program Files\\wechat-ai-assistant.exe');
    assert.deepEqual(result.args, ['--dev']);
    assert.equal(calls.length, 1);
    assert.equal(calls[0].file, 'powershell.exe');
    assert.equal(calls[0].args.includes('-EncodedCommand'), true);
});
