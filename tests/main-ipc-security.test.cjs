const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('path');
const { pathToFileURL } = require('url');

const {
    buildSafeDesktopNotificationOptions,
    registerIpcHandlers,
} = require('../src/main/ipc');
const { stopBackendAndQuit } = require('../src/main/app-lifecycle');

function createHarness(options = {}) {
    const handlers = new Map();
    const openedExternal = [];
    const backendCalls = [];
    const openDialogCalls = [];
    const storeWrites = [];
    const systemMenuCalls = [];
    const hideToTrayCalls = [];
    const quitCalls = [];
    const windowState = options.windowState || {
        exists: true,
        isVisible: true,
        isMinimized: false,
        isMaximized: false,
        title: '微信 AI 助手',
    };
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
        getMainWindowSafe: options.getMainWindowSafe || (() => null),
        getMainWindowState: options.getMainWindowState || (() => windowState),
        broadcastWindowState: options.broadcastWindowState || (() => windowState),
        showWindowSystemMenu: options.showWindowSystemMenu || ((point) => {
            systemMenuCalls.push(point);
            return { success: true, state: windowState };
        }),
        hideMainWindowToTray: options.hideMainWindowToTray || (() => {
            hideToTrayCalls.push('minimize');
            return { success: true, action: 'minimize', state: windowState };
        }),
        quitAppGracefully: options.quitAppGracefully || (async (reason) => {
            quitCalls.push(reason);
            return { success: true, action: 'quit' };
        }),
        requestAppClose: () => {},
        installDownloadedUpdateAndQuit: () => ({ success: true }),
        showMainWindowSafe: () => {},
        store: {
            get: () => null,
            set: (key, value) => {
                storeWrites.push({ key, value });
            },
        },
        dialog: {
            showSaveDialog: async () => ({ canceled: true }),
            showOpenDialog: async (win, config) => {
                openDialogCalls.push({ win, config });
                if (typeof options.showOpenDialogImpl === 'function') {
                    return options.showOpenDialogImpl(win, config);
                }
                return { canceled: true };
            },
        },
    });

    return {
        openExternalHandler: handlers.get('open-external'),
        openWechatHandler: handlers.get('open-wechat'),
        backendRequestHandler: handlers.get('backend:request'),
        confirmCloseActionHandler: handlers.get('confirm-close-action'),
        minimizeToTrayHandler: handlers.get('minimize-to-tray'),
        windowGetStateHandler: handlers.get('window:get-state'),
        windowMaximizeHandler: handlers.get('window-maximize'),
        windowShowSystemMenuHandler: handlers.get('window:show-system-menu'),
        knowledgeBaseSelectFileHandler: handlers.get('knowledge-base:select-file'),
        backendCalls,
        hideToTrayCalls,
        openedExternal,
        openDialogCalls,
        quitCalls,
        storeWrites,
        systemMenuCalls,
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

test('knowledge-base file selector reads one explicit text file without leaking full path', async () => {
    const selectedPath = path.resolve('C:/private/runbooks/release-runbook.md');
    const harness = createHarness({
        fsImpl: {
            statSync(targetPath) {
                assert.equal(targetPath, selectedPath);
                return {
                    size: 32,
                    isFile: () => true,
                };
            },
            readFileSync(targetPath) {
                assert.equal(targetPath, selectedPath);
                return Buffer.from('# Release\ntrusted notes', 'utf8');
            },
        },
        showOpenDialogImpl: async () => ({
            canceled: false,
            filePaths: [selectedPath],
        }),
    });
    const event = createTrustedEvent();

    const result = await harness.knowledgeBaseSelectFileHandler(event);

    assert.equal(result.success, true);
    assert.equal(result.canceled, false);
    assert.equal(result.name, 'release-runbook.md');
    assert.equal(result.extension, 'md');
    assert.equal(result.content_type, 'markdown');
    assert.equal(result.content, '# Release\ntrusted notes');
    assert.equal(result.source_file, '.../release-runbook.md');
    assert.equal(Object.hasOwn(result, 'filePath'), false);
    assert.equal(Object.hasOwn(result, 'path'), false);
    assert.equal(JSON.stringify(result).includes('C:'), false);
    assert.equal(JSON.stringify(result).includes('private'), false);
    assert.equal(harness.openDialogCalls.length, 1);
    assert.deepEqual(harness.openDialogCalls[0].config.properties, ['openFile']);
    assert.deepEqual(harness.openDialogCalls[0].config.filters, [
        { name: 'Text or Markdown', extensions: ['txt', 'md', 'markdown'] },
    ]);
});

test('knowledge-base file selector handles cancel and rejects unsafe files', async () => {
    const canceledHarness = createHarness();
    const event = createTrustedEvent();

    const canceled = await canceledHarness.knowledgeBaseSelectFileHandler(event);

    assert.equal(canceled.success, false);
    assert.equal(canceled.canceled, true);
    assert.equal(canceled.message, 'file selection canceled');

    const unsupportedPath = path.resolve('C:/private/runbooks/secrets.pdf');
    const unsupportedHarness = createHarness({
        showOpenDialogImpl: async () => ({
            canceled: false,
            filePaths: [unsupportedPath],
        }),
    });
    const unsupported = await unsupportedHarness.knowledgeBaseSelectFileHandler(event);
    assert.equal(unsupported.success, false);
    assert.equal(unsupported.canceled, false);
    assert.equal(unsupported.message, 'unsupported_file_type');

    const hugePath = path.resolve('C:/private/runbooks/huge.md');
    const hugeHarness = createHarness({
        fsImpl: {
            statSync() {
                return {
                    size: 300 * 1024,
                    isFile: () => true,
                };
            },
            readFileSync() {
                throw new Error('should not read oversized files');
            },
        },
        showOpenDialogImpl: async () => ({
            canceled: false,
            filePaths: [hugePath],
        }),
    });
    const huge = await hugeHarness.knowledgeBaseSelectFileHandler(event);
    assert.equal(huge.success, false);
    assert.equal(huge.canceled, false);
    assert.equal(huge.message, 'file_too_large');
});

test('knowledge-base file selector logs read failures without full local path', async () => {
    const selectedPath = path.resolve('C:/private/runbooks/failure.md');
    const originalWarn = console.warn;
    const warnCalls = [];
    console.warn = (...args) => {
        warnCalls.push(args.map((item) => String(item)));
    };
    const harness = createHarness({
        fsImpl: {
            statSync() {
                const error = new Error(`cannot access ${selectedPath}`);
                error.code = 'EACCES';
                throw error;
            },
        },
        showOpenDialogImpl: async () => ({
            canceled: false,
            filePaths: [selectedPath],
        }),
    });

    try {
        const result = await harness.knowledgeBaseSelectFileHandler(createTrustedEvent());

        assert.equal(result.success, false);
        assert.equal(result.canceled, false);
        assert.equal(result.message, 'file_read_failed');
        assert.deepEqual(warnCalls.at(-1), [
            '[IPC] Knowledge base file selection failed:',
            'EACCES',
        ]);
        assert.equal(JSON.stringify(warnCalls).includes('C:'), false);
        assert.equal(JSON.stringify(warnCalls).includes('private'), false);
    } finally {
        console.warn = originalWarn;
    }
});

test('knowledge-base file selector rejects untrusted renderer sender', () => {
    const harness = createHarness();
    const event = {
        senderFrame: {
            url: 'https://attacker.example',
        },
    };

    assert.throws(
        () => harness.knowledgeBaseSelectFileHandler(event),
        /forbidden_sender/,
    );
    assert.equal(harness.openDialogCalls.length, 0);
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

test('backend:request allows fixed knowledge base governance endpoints only', async () => {
    const harness = createHarness();
    const event = createTrustedEvent();

    const statusResult = await harness.backendRequestHandler(event, {
        method: 'GET',
        endpoint: '/api/knowledge_base/status',
    });
    const dryRunResult = await harness.backendRequestHandler(event, {
        method: 'POST',
        endpoint: '/api/knowledge_base/dry-run',
        payload: { content: 'release notes', content_type: 'markdown' },
    });
    const batchDryRunResult = await harness.backendRequestHandler(event, {
        method: 'POST',
        endpoint: '/api/knowledge_base/batch-dry-run',
        payload: { documents: [{ content: 'release notes' }] },
    });
    const ingestResult = await harness.backendRequestHandler(event, {
        method: 'POST',
        endpoint: '/api/knowledge_base/ingest',
        payload: { content: 'release notes', doc_id: 'release' },
    });
    const batchIngestResult = await harness.backendRequestHandler(event, {
        method: 'POST',
        endpoint: '/api/knowledge_base/batch-ingest',
        payload: { documents: [{ content: 'release notes', doc_id: 'release' }] },
    });
    const rebuildResult = await harness.backendRequestHandler(event, {
        method: 'POST',
        endpoint: '/api/knowledge_base/rebuild',
        payload: { content: 'release notes', doc_id: 'release' },
    });
    const batchRebuildResult = await harness.backendRequestHandler(event, {
        method: 'POST',
        endpoint: '/api/knowledge_base/batch-rebuild',
        payload: { documents: [{ content: 'release notes', doc_id: 'release' }] },
    });
    const deleteBlocked = await harness.backendRequestHandler(event, {
        method: 'POST',
        endpoint: '/api/knowledge_base/delete',
        payload: { doc_id: 'release' },
    });

    assert.equal(statusResult.ok, true);
    assert.equal(dryRunResult.ok, true);
    assert.equal(batchDryRunResult.ok, true);
    assert.equal(ingestResult.ok, true);
    assert.equal(batchIngestResult.ok, true);
    assert.equal(rebuildResult.ok, true);
    assert.equal(batchRebuildResult.ok, true);
    assert.equal(deleteBlocked.ok, false);
    assert.equal(deleteBlocked.error?.message, 'endpoint_not_allowed');
    assert.deepEqual(harness.backendCalls, [
        { method: 'GET', endpoint: '/api/knowledge_base/status', payload: null },
        {
            method: 'POST',
            endpoint: '/api/knowledge_base/dry-run',
            payload: { content: 'release notes', content_type: 'markdown' },
        },
        {
            method: 'POST',
            endpoint: '/api/knowledge_base/batch-dry-run',
            payload: { documents: [{ content: 'release notes' }] },
        },
        {
            method: 'POST',
            endpoint: '/api/knowledge_base/ingest',
            payload: { content: 'release notes', doc_id: 'release' },
        },
        {
            method: 'POST',
            endpoint: '/api/knowledge_base/batch-ingest',
            payload: { documents: [{ content: 'release notes', doc_id: 'release' }] },
        },
        {
            method: 'POST',
            endpoint: '/api/knowledge_base/rebuild',
            payload: { content: 'release notes', doc_id: 'release' },
        },
        {
            method: 'POST',
            endpoint: '/api/knowledge_base/batch-rebuild',
            payload: { documents: [{ content: 'release notes', doc_id: 'release' }] },
        },
    ]);
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

test('backend:request only allows prompt governance paths', async () => {
    const harness = createHarness();
    const event = createTrustedEvent();

    const rollbackAllowed = await harness.backendRequestHandler(event, {
        method: 'POST',
        endpoint: '/api/v1/admin/prompts/12/rollback',
        payload: { reason: 'restore stable prompt' },
    });
    const revisionsAllowed = await harness.backendRequestHandler(event, {
        method: 'GET',
        endpoint: '/api/v1/admin/prompts/revisions',
    });
    const diffAllowed = await harness.backendRequestHandler(event, {
        method: 'GET',
        endpoint: '/api/v1/admin/prompts/12/diff',
    });
    const rollbackBlocked = await harness.backendRequestHandler(event, {
        method: 'POST',
        endpoint: '/api/v1/admin/prompts/abc/rollback',
        payload: { reason: 'bad path' },
    });
    const diffBlocked = await harness.backendRequestHandler(event, {
        method: 'GET',
        endpoint: '/api/v1/admin/prompts/abc/diff',
    });
    const blockedList = await harness.backendRequestHandler(event, {
        method: 'GET',
        endpoint: '/api/v1/admin/prompts',
    });

    assert.equal(rollbackAllowed.ok, true);
    assert.equal(revisionsAllowed.ok, true);
    assert.equal(diffAllowed.ok, true);
    assert.equal(rollbackBlocked.ok, false);
    assert.equal(rollbackBlocked.error?.message, 'endpoint_not_allowed');
    assert.equal(diffBlocked.ok, false);
    assert.equal(diffBlocked.error?.message, 'endpoint_not_allowed');
    assert.equal(blockedList.ok, false);
    assert.equal(blockedList.error?.message, 'endpoint_not_allowed');
    assert.deepEqual(harness.backendCalls, [
        {
            method: 'POST',
            endpoint: '/api/v1/admin/prompts/12/rollback',
            payload: { reason: 'restore stable prompt' },
        },
        {
            method: 'GET',
            endpoint: '/api/v1/admin/prompts/revisions',
            payload: null,
        },
        {
            method: 'GET',
            endpoint: '/api/v1/admin/prompts/12/diff',
            payload: null,
        },
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

test('window ipc reports state and delegates titlebar system menu requests', async () => {
    const harness = createHarness();
    const event = createTrustedEvent();

    const state = await harness.windowGetStateHandler(event);
    const menuResult = await harness.windowShowSystemMenuHandler(event, { x: 24.6, y: 8.2 });

    assert.equal(state.title, '微信 AI 助手');
    assert.equal(state.isMaximized, false);
    assert.equal(menuResult.success, true);
    assert.deepEqual(harness.systemMenuCalls, [{ x: 24.6, y: 8.2 }]);
});

test('window control ipc returns state and close actions stay explicit', async () => {
    const harness = createHarness();
    const event = createTrustedEvent();

    const minimizeResult = await harness.minimizeToTrayHandler(event);
    const invalidResult = await harness.confirmCloseActionHandler(event, { action: 'hide-chat', remember: true });
    const rememberedMinimize = await harness.confirmCloseActionHandler(event, { action: 'minimize', remember: true });
    const quitResult = await harness.confirmCloseActionHandler(event, { action: 'quit', remember: false });

    assert.deepEqual(minimizeResult, {
        success: true,
        action: 'minimize',
        state: {
            exists: true,
            isVisible: true,
            isMinimized: false,
            isMaximized: false,
            title: '微信 AI 助手',
        },
    });
    assert.deepEqual(invalidResult, { success: false, message: 'invalid action' });
    assert.equal(rememberedMinimize.action, 'minimize');
    assert.equal(quitResult.action, 'quit');
    assert.deepEqual(harness.hideToTrayCalls, ['minimize', 'minimize']);
    assert.deepEqual(harness.quitCalls, ['quit']);
    assert.deepEqual(harness.storeWrites, [{ key: 'closeBehavior', value: 'minimize' }]);
});

test('stopBackendAndQuit always quits even when backend stop fails', async () => {
    const calls = [];
    const GLOBAL_STATE = {
        isQuitting: false,
        tray: {
            destroy: () => calls.push('tray.destroy'),
        },
    };

    const result = await stopBackendAndQuit({
        GLOBAL_STATE,
        BackendManager: {
            stop: async (reason) => {
                calls.push(['stop', reason]);
                throw new Error('stop failed');
            },
        },
        app: {
            quit: () => calls.push('app.quit'),
        },
        reason: 'install-update',
        logger: {
            warn: (...args) => calls.push(['warn', args[0]]),
        },
    });

    assert.equal(GLOBAL_STATE.isQuitting, true);
    assert.equal(GLOBAL_STATE.tray, null);
    assert.deepEqual(result, {
        success: true,
        action: 'quit',
        warning: 'backend_stop_failed',
    });
    assert.deepEqual(calls, [
        'tray.destroy',
        ['stop', 'install-update'],
        ['warn', '[Lifecycle] backend stop before quit failed:'],
        'app.quit',
    ]);
});

test('safe desktop notification options never echo arbitrary message content', () => {
    const sensitiveText = 'wxid_alice: 明天转账 123456，credential marker demo-value';
    const options = buildSafeDesktopNotificationOptions('background-running', {
        body: sensitiveText,
    });

    assert.equal(options.title, '微信 AI 助手');
    assert.match(options.body, /后台运行|托盘/);
    assert.equal(options.body.includes('wxid_alice'), false);
    assert.equal(options.body.includes('123456'), false);
    assert.equal(options.body.includes('demo-value'), false);
    assert.equal(buildSafeDesktopNotificationOptions('chat-message'), null);
});
