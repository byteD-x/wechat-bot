const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');

const {
    buildRendererConfigPayload,
    createSharedConfigService,
} = require('../src/main/shared-config');

test('buildRendererConfigPayload masks secrets and drops runtime-only fields', () => {
    const payload = buildRendererConfigPayload({
        api: {
            presets: [
                {
                    name: 'OpenAI',
                    api_key: 'sk-1234567890abcdef',
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
