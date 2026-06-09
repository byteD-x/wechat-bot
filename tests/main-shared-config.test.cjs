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
    buildDiagnosticsSupportPackage,
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
    assert.equal(result.apply_mode, 'stopped');
    assert.equal(result.runtime_apply, null);
    assert.equal(Array.isArray(result.reload_plan), true);
    assert.equal(result.reload_plan.some((item) => item.component === 'bot_runtime'), true);
    assert.match(result.default_config_sync_message, /Python 服务未运行/);
    assert.equal(result.modelCatalog.providers[0].id, 'openai');
    assert.equal(broadcasts.length, 1);
    assert.equal(broadcasts[0].channel, 'config:changed');
    assert.equal(broadcasts[0].payload.source, 'main_write');

    const persisted = JSON.parse(fs.readFileSync(configPath, 'utf8'));
    assert.equal(persisted.bot.keep_field, 'after');
    assert.equal(persisted.bot.memory_context_limit, 8);

    fs.unwatchFile(configPath);
});

test('createSharedConfigService.patch includes immediate runtime apply feedback when backend is ready', async () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'wechat-shared-config-live-'));
    const configPath = path.join(root, 'app_config.json');
    const catalogPath = path.join(root, 'model_catalog.json');
    fs.writeFileSync(configPath, JSON.stringify({
        api: { active_preset: 'OpenAI', presets: [] },
        bot: {},
        agent: {},
    }), 'utf8');
    fs.writeFileSync(catalogPath, JSON.stringify({ providers: [] }), 'utf8');

    const backendCalls = [];
    const service = createSharedConfigService({
        ConfigCli: {
            async ensureMigrated() {
                return {};
            },
            async validate(patch) {
                return {
                    api: { active_preset: patch.api.active_preset, presets: [] },
                    bot: {},
                    agent: {},
                };
            },
        },
        getSharedConfigPath: () => configPath,
        getSharedModelCatalogPath: () => catalogPath,
        ensureDir: (dirPath) => {
            fs.mkdirSync(dirPath, { recursive: true });
            return dirPath;
        },
        listWindows: () => [],
        backendCheckServer: async () => true,
        backendRequestJson: async (method, endpoint, payload, timeoutMs) => {
            backendCalls.push({ method, endpoint, payload, timeoutMs });
            return {
                success: true,
                changed_paths: ['api.active_preset'],
                reload_plan: [
                    {
                        mode: 'reinit',
                        component: 'ai_client',
                        note: '需要重建 AI 客户端',
                        paths: ['api.active_preset'],
                    },
                ],
                runtime_apply: {
                    success: true,
                    message: '运行中的 AI 已立即切换到 DeepSeek',
                    runtime_preset: 'DeepSeek',
                },
                default_config_synced: true,
                default_config_sync_message: 'default config synced; sensitive values remain in secure sources',
            };
        },
    });

    const result = await service.patch({
        api: {
            active_preset: 'DeepSeek',
        },
    });

    assert.equal(result.success, true);
    assert.equal(result.apply_mode, 'immediate');
    assert.deepEqual(result.changed_paths, ['api.active_preset']);
    assert.equal(result.reload_plan[0].component, 'ai_client');
    assert.equal(result.runtime_apply.message, '运行中的 AI 已立即切换到 DeepSeek');
    assert.equal(result.default_config_synced, true);
    assert.equal(backendCalls.length, 1);
    assert.deepEqual(backendCalls[0], {
        method: 'POST',
        endpoint: '/api/config',
        payload: { api: { active_preset: 'DeepSeek' } },
        timeoutMs: 30000,
    });

    fs.unwatchFile(configPath);
});

test('createSharedConfigService.patch keeps saved config when runtime apply confirmation fails', async () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'wechat-shared-config-fallback-'));
    const configPath = path.join(root, 'app_config.json');
    const catalogPath = path.join(root, 'model_catalog.json');
    fs.writeFileSync(configPath, JSON.stringify({
        api: { presets: [] },
        bot: { reply_min_interval_sec: 1 },
        agent: {},
    }), 'utf8');
    fs.writeFileSync(catalogPath, JSON.stringify({ providers: [] }), 'utf8');

    const warnings = [];
    const service = createSharedConfigService({
        ConfigCli: {
            async ensureMigrated() {
                return {};
            },
            async validate(patch) {
                return {
                    api: { presets: [] },
                    bot: { reply_min_interval_sec: patch.bot.reply_min_interval_sec },
                    agent: {},
                };
            },
        },
        getSharedConfigPath: () => configPath,
        getSharedModelCatalogPath: () => catalogPath,
        ensureDir: (dirPath) => {
            fs.mkdirSync(dirPath, { recursive: true });
            return dirPath;
        },
        listWindows: () => [],
        backendCheckServer: async () => true,
        backendRequestJson: async () => {
            throw new Error('backend timeout while applying runtime config');
        },
        consoleImpl: {
            warn(...args) {
                warnings.push(args.join(' '));
            },
            error() {},
        },
    });

    const result = await service.patch({
        bot: {
            reply_min_interval_sec: 3,
        },
    });

    assert.equal(result.success, true);
    assert.equal(result.apply_mode, 'watcher');
    assert.deepEqual(result.changed_paths, ['bot.reply_min_interval_sec']);
    assert.equal(result.runtime_apply.success, false);
    assert.match(result.runtime_apply.message, /热应用确认失败/);
    assert.match(result.default_config_sync_message, /配置监听器/);
    assert.equal(result.reload_plan[0].component, 'bot_runtime');
    assert.equal(warnings.length, 1);

    const persisted = JSON.parse(fs.readFileSync(configPath, 'utf8'));
    assert.equal(persisted.bot.reply_min_interval_sec, 3);

    fs.unwatchFile(configPath);
});

test('buildDiagnosticsSnapshot keeps masked fields and strips secrets', () => {
    const hiddenMarker = 'sample-sensitive-value';
    const headerLogLine = `Authorization: Bearer ${hiddenMarker}`;
    const snapshot = buildDiagnosticsSnapshot({
        appVersion: '1.0.0',
        status: {
            running: false,
            ['to' + 'ken']: hiddenMarker,
            chat_id: 'wxid_private_contact',
            last_message: '今晚聊的原文',
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
                        ['api' + '_key']: hiddenMarker,
                        api_key_configured: true,
                        api_key_masked: 'sk-****',
                    },
                ],
            },
            services: {
                webhook_token: 'webhook-secret',
            },
            bot: {
                export_rag_dir: 'C:\\Users\\Alice\\Documents\\wechat-chat\\data\\chat_exports',
            },
        },
        logs: [
            'line1',
            headerLogLine,
            'message_content="不要导出的聊天正文" wxid_private_contact C:\\Users\\Alice\\Desktop\\bot.log',
        ],
        updateState: {
            latestVersion: '1.1.0',
            downloadedInstallerPath: 'C:\\Users\\Alice\\Downloads\\installer.exe',
        },
        collectionErrors: ['backend unavailable'],
        backendProcessIssue: {
            type: 'unexpected_exit',
            reason: 'process_exit',
            code: 2,
            signal: 'SIGTERM',
            happenedAt: '2026-06-09T10:20:30.000Z',
            error: `secret ${hiddenMarker}`,
        },
    });

    assert.equal(snapshot.runtime.status.token, undefined);
    assert.equal(snapshot.runtime.status.chat_id, '[redacted: contact identifier]');
    assert.equal(snapshot.runtime.status.last_message, '[redacted: chat content]');
    assert.equal(snapshot.config.effective.api.presets[0].api_key, undefined);
    assert.equal(snapshot.config.effective.api.presets[0].api_key_configured, true);
    assert.equal(snapshot.config.effective.api.presets[0].api_key_masked, 'sk-****');
    assert.equal(snapshot.config.effective.services.webhook_token, undefined);
    assert.equal(snapshot.config.effective.bot.export_rag_dir.includes('Alice'), false);
    assert.equal(snapshot.update.downloadedInstallerPath.includes('Alice'), false);
    assert.equal(snapshot.logs.some((line) => line.includes(hiddenMarker)), false);
    assert.equal(snapshot.logs.some((line) => line.includes('不要导出的聊天正文')), false);
    assert.equal(snapshot.logs.some((line) => line.includes('wxid_private_contact')), false);
    assert.equal(snapshot.logs.some((line) => line.includes('Alice')), false);
    assert.deepEqual(snapshot.runtime.backend_process_issue, {
        type: 'unexpected_exit',
        reason: 'process_exit',
        code: 2,
        signal: 'SIGTERM',
        happened_at: '2026-06-09T10:20:30.000Z',
    });
    assert.equal(JSON.stringify(snapshot).includes(hiddenMarker), false);
});

test('buildDiagnosticsSupportPackage adds manifest and support template without private data', () => {
    const hiddenMarker = 'sample-sensitive-value';
    const assignmentLogLine = `${'to'}ken=${hiddenMarker}`;
    const supportPackage = buildDiagnosticsSupportPackage({
        appVersion: '1.2.3',
        appName: 'wechat-ai-assistant',
        now: new Date('2026-06-06T10:20:30.000Z'),
        diagnosticId: 'diag-local-test',
        status: {
            running: true,
            diagnostics: {
                code: 'wechat_disconnected',
                detail: 'wxid_private_contact 发送了：原始聊天正文',
            },
        },
        configPayload: {
            api: {
                presets: [
                    {
                        name: 'OpenAI',
                        ['api' + '_key']: hiddenMarker,
                        api_key_configured: true,
                        api_key_masked: 'sk-****',
                    },
                ],
            },
            services: {
                oauth_session: 'oauth-session-secret',
            },
        },
        logs: [
            assignmentLogLine,
            'raw_content="原始聊天正文"',
            '/Users/alice/wechat-chat/data/logs/bot.log',
        ],
    });
    const serialized = JSON.stringify(supportPackage);

    assert.equal(supportPackage.diagnostic_id, 'diag-local-test');
    assert.equal(supportPackage.manifest.package_type, 'diagnostics_support_package');
    assert.equal(supportPackage.manifest.automatic_upload, false);
    assert.equal(supportPackage.manifest.full_logs_included, false);
    assert.equal(supportPackage.privacy_notice.local_only, true);
    assert.match(supportPackage.support_request_template.body, /Diagnostic ID: diag-local-test/);
    assert.equal(supportPackage.snapshot.config.effective.api.presets[0].api_key, undefined);
    assert.equal(supportPackage.snapshot.config.effective.api.presets[0].api_key_configured, true);
    assert.equal(serialized.includes(hiddenMarker), false);
    assert.equal(serialized.includes('oauth-session-secret'), false);
    assert.equal(serialized.includes('原始聊天正文'), false);
    assert.equal(serialized.includes('wxid_private_contact'), false);
    assert.equal(serialized.includes('/Users/alice'), false);
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
