const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('path');
const { pathToFileURL } = require('url');

const { registerIpcHandlers } = require('../src/main/ipc');

function createHarness(options = {}) {
    const handlers = new Map();
    const openedExternal = [];
    const backendCalls = [];
    const ipcMain = {
        handle(channel, handler) {
            handlers.set(channel, handler);
        },
    };

    registerIpcHandlers({
        ipcMain,
        GLOBAL_STATE: {
            flaskUrl: 'http://127.0.0.1:5000',
            sseTicket: '',
            updateManager: null,
            isQuitting: false,
            tray: null,
            mainWindow: null,
        },
        BackendManager: {
            requestJson: async (method, endpoint, payload) => {
                backendCalls.push({ method, endpoint, payload });
                return { success: true, method, endpoint };
            },
            checkServer: () => ({ running: true }),
            ensureReady: async () => {},
            stop: async () => {},
        },
        SharedConfigService: {
            get: () => ({}),
            patch: () => ({}),
            testConnection: () => ({}),
            subscribe: () => ({}),
        },
        RuntimeManager: {
            ensureService: () => ({}),
            startBot: () => ({}),
            stopBot: () => ({}),
            startGrowth: () => ({}),
            stopGrowth: () => ({}),
        },
        getRuntimeIdleState: () => ({}),
        applyRuntimeStatusSummary: () => ({}),
        runtimeIdleController: {
            cancelIdleShutdown: () => ({}),
        },
        GrowthPromptStore: {
            getState: () => ({}),
            markSeen: () => ({}),
        },
        shell: {
            openExternal(url) {
                if (typeof options.openExternalImpl === 'function') {
                    return options.openExternalImpl(url);
                }
                openedExternal.push(String(url));
            },
            openPath: async (targetPath) => {
                if (typeof options.openPathImpl === 'function') {
                    return options.openPathImpl(targetPath);
                }
                return '';
            },
        },
        app: {
            getVersion: () => '1.0.0',
            getName: () => 'wechat-ai-assistant',
            getPath: () => path.resolve(__dirname),
            quit: () => {},
        },
        exec: (...args) => {
            if (typeof options.execImpl === 'function') {
                return options.execImpl(...args);
            }
            return undefined;
        },
        execFile: () => {},
        fs: options.fsImpl || require('fs'),
        path,
        getMainWindowSafe: () => null,
        requestAppClose: () => {},
        installDownloadedUpdateAndQuit: () => ({ success: true }),
        showMainWindowSafe: () => {},
        store: {
            get: () => null,
            set: () => {},
        },
        dialog: {
            showSaveDialog: async () => ({ canceled: true }),
        },
    });

    return {
        openExternalHandler: handlers.get('open-external'),
        openWechatHandler: handlers.get('open-wechat'),
        backendRequestHandler: handlers.get('backend:request'),
        backendCalls,
        openedExternal,
    };
}

function createTrustedEvent() {
    return {
        senderFrame: {
            url: pathToFileURL(path.resolve(__dirname, '..', 'src', 'renderer', 'index.html')).toString(),
        },
    };
}

test('open-external allows public https and mailto URLs', async () => {
    const harness = createHarness();
    const event = createTrustedEvent();

    const httpsResult = await harness.openExternalHandler(event, 'https://example.com/docs');
    const mailtoResult = await harness.openExternalHandler(event, 'mailto:support@example.com');

    assert.equal(httpsResult.success, true);
    assert.equal(mailtoResult.success, true);
    assert.deepEqual(harness.openedExternal, [
        'https://example.com/docs',
        'mailto:support@example.com',
    ]);
});

test('open-external rejects unsafe or malformed URLs', async () => {
    const harness = createHarness();
    const event = createTrustedEvent();

    const malformed = await harness.openExternalHandler(event, 'not-a-valid-url');
    const javascriptUrl = await harness.openExternalHandler(event, 'javascript:alert(1)');

    assert.equal(malformed.success, false);
    assert.equal(malformed.error, 'invalid_url');
    assert.equal(javascriptUrl.success, false);
    assert.equal(javascriptUrl.error, 'blocked_protocol');
    assert.deepEqual(harness.openedExternal, []);
});

test('open-external rejects credentialed and private-network URLs', async () => {
    const harness = createHarness();
    const event = createTrustedEvent();

    const credentialed = await harness.openExternalHandler(event, 'https://user:pass@example.com/path');
    const localhost = await harness.openExternalHandler(event, 'https://localhost/path');
    const privateIp = await harness.openExternalHandler(event, 'https://192.168.1.5/path');
    const loopbackV6 = await harness.openExternalHandler(event, 'https://[::1]/path');
    const privateV6 = await harness.openExternalHandler(event, 'https://[fd12:3456::1]/path');

    assert.equal(credentialed.success, false);
    assert.equal(credentialed.error, 'blocked_credentials');
    assert.equal(localhost.success, false);
    assert.equal(localhost.error, 'blocked_private_host');
    assert.equal(privateIp.success, false);
    assert.equal(privateIp.error, 'blocked_private_host');
    assert.equal(loopbackV6.success, false);
    assert.equal(loopbackV6.error, 'blocked_private_host');
    assert.equal(privateV6.success, false);
    assert.equal(privateV6.error, 'blocked_private_host');
    assert.deepEqual(harness.openedExternal, []);
});

test('open-external rejects untrusted renderer sender', async () => {
    const harness = createHarness();
    const event = {
        senderFrame: {
            url: 'https://attacker.example',
        },
    };

    assert.throws(
        () => harness.openExternalHandler(event, 'https://example.com'),
        /forbidden_sender/,
    );
    assert.deepEqual(harness.openedExternal, []);
});

test('open-external reports open_failed when shell call throws', async () => {
    const harness = createHarness({
        openExternalImpl: () => {
            throw new Error('shell failed');
        },
    });
    const event = createTrustedEvent();

    const result = await harness.openExternalHandler(event, 'https://example.com');

    assert.equal(result.success, false);
    assert.equal(result.error, 'open_failed');
    assert.deepEqual(harness.openedExternal, []);
});

test('open-wechat returns unverified error when protocol launch does not start process', async () => {
    const harness = createHarness({
        fsImpl: { existsSync: () => false },
        execImpl: (command, options, callback) => {
            if (command.startsWith('tasklist')) {
                callback(null, Buffer.from('INFO: No tasks are running which match the specified criteria.\r\n', 'utf8'));
                return;
            }
            if (command.startsWith('reg query')) {
                callback(new Error('not found'));
                return;
            }
            callback(null, Buffer.from('', 'utf8'));
        },
    });
    const event = createTrustedEvent();

    const result = await harness.openWechatHandler(event);

    assert.equal(result.success, false);
    assert.equal(result.error, 'wechat_launch_unverified');
    assert.equal(result.code, 'wechat_launch_unverified');
    assert.deepEqual(harness.openedExternal, ['weixin://']);
});

test('open-wechat protocol launch succeeds after process is detected', async () => {
    let protocolTriggered = false;
    const harness = createHarness({
        fsImpl: { existsSync: () => false },
        openExternalImpl: (url) => {
            protocolTriggered = url === 'weixin://';
        },
        execImpl: (command, options, callback) => {
            if (command.startsWith('tasklist')) {
                const output = protocolTriggered
                    ? '"WeChat.exe","1234","Console","1","10,000 K"\r\n'
                    : 'INFO: No tasks are running which match the specified criteria.\r\n';
                callback(null, Buffer.from(output, 'utf8'));
                return;
            }
            if (command.startsWith('reg query')) {
                callback(new Error('not found'));
                return;
            }
            callback(null, Buffer.from('', 'utf8'));
        },
    });
    const event = createTrustedEvent();

    const result = await harness.openWechatHandler(event);

    assert.equal(result.success, true);
    assert.equal(result.message, 'Launched via protocol');
    assert.equal(protocolTriggered, true);
});

test('backend:request rejects endpoints outside the trusted allowlist', async () => {
    const harness = createHarness();
    const event = createTrustedEvent();

    const result = await harness.backendRequestHandler(event, {
        method: 'GET',
        endpoint: '/api/events_ticket',
    });

    assert.equal(result.ok, false);
    assert.equal(result.error?.code, 'bad_request');
    assert.equal(result.error?.message, 'endpoint_not_allowed');
    assert.deepEqual(harness.backendCalls, []);
});

test('backend:request allows wechat export endpoints and pattern-based job query', async () => {
    const harness = createHarness();
    const event = createTrustedEvent();

    const probeResult = await harness.backendRequestHandler(event, {
        method: 'POST',
        endpoint: '/api/wechat_export/probe',
        payload: {},
    });
    const jobResult = await harness.backendRequestHandler(event, {
        method: 'GET',
        endpoint: '/api/wechat_export/decrypt/jobs/job_abc123',
    });

    assert.equal(probeResult.ok, true);
    assert.equal(jobResult.ok, true);
    assert.deepEqual(harness.backendCalls, [
        { method: 'POST', endpoint: '/api/wechat_export/probe', payload: {} },
        { method: 'GET', endpoint: '/api/wechat_export/decrypt/jobs/job_abc123', payload: null },
    ]);
});

test('backend:request enforces payload policy for GET and oversized POST payloads', async () => {
    const harness = createHarness();
    const event = createTrustedEvent();

    const getWithPayload = await harness.backendRequestHandler(event, {
        method: 'GET',
        endpoint: '/api/status',
        payload: { force: true },
    });
    assert.equal(getWithPayload.ok, false);
    assert.equal(getWithPayload.error?.message, 'payload_not_allowed_for_get');

    const hugePayload = await harness.backendRequestHandler(event, {
        method: 'POST',
        endpoint: '/api/config',
        payload: { blob: 'x'.repeat(70 * 1024) },
    });
    assert.equal(hugePayload.ok, false);
    assert.equal(hugePayload.error?.message, 'payload_too_large');
    assert.deepEqual(harness.backendCalls, []);
});
