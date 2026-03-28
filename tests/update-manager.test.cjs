const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');

const { UpdateManager, _testUtils } = require('../src/main/update-manager');

class FakeStore {
    constructor(initial = {}) {
        this.data = JSON.parse(JSON.stringify(initial));
    }

    get(key, fallbackValue = undefined) {
        const keys = String(key || '').split('.').filter(Boolean);
        let cursor = this.data;
        for (const part of keys) {
            if (cursor == null || !(part in cursor)) {
                return fallbackValue;
            }
            cursor = cursor[part];
        }
        return cursor;
    }

    set(key, value) {
        const keys = String(key || '').split('.').filter(Boolean);
        let cursor = this.data;
        while (keys.length > 1) {
            const part = keys.shift();
            if (!cursor[part] || typeof cursor[part] !== 'object') {
                cursor[part] = {};
            }
            cursor = cursor[part];
        }
        cursor[keys[0]] = value;
    }
}

function sha256Of(text) {
    return crypto.createHash('sha256').update(String(text), 'utf8').digest('hex');
}

function createTempPackageDir() {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'wechat-update-manager-'));
    fs.writeFileSync(path.join(root, 'package.json'), JSON.stringify({
        name: 'wechat-ai-assistant',
        repository: {
            type: 'git',
            url: 'https://github.com/byteD-x/wechat-bot.git',
        },
    }), 'utf8');
    return root;
}

function buildReleasePayload({
    version = '1.2.0',
    setupUrl,
    checksumUrl = 'https://example.com/SHA256SUMS.txt',
} = {}) {
    const normalizedVersion = String(version || '1.2.0');
    const defaultSetupUrl = `https://example.com/wechat-ai-assistant-setup-${normalizedVersion}.exe`;
    return {
        tag_name: `v${normalizedVersion}`,
        html_url: `https://github.com/byteD-x/wechat-bot/releases/tag/v${normalizedVersion}`,
        published_at: '2026-03-20T12:00:00.000Z',
        body: '更新说明',
        assets: [
            {
                name: `wechat-ai-assistant-setup-${normalizedVersion}.exe`,
                browser_download_url: setupUrl || defaultSetupUrl,
            },
            {
                name: 'SHA256SUMS.txt',
                browser_download_url: checksumUrl,
            },
        ],
    };
}

function createManager(options = {}) {
    const packageDir = createTempPackageDir();
    const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'wechat-update-userdata-'));
    const store = options.store || new FakeStore({
        update: {
            autoCheckOnLaunch: false,
        },
    });
    const app = {
        isPackaged: false,
        getVersion: () => options.currentVersion || '1.0.0',
        getAppPath: () => packageDir,
        getPath: (name) => {
            assert.equal(name, 'userData');
            return userDataDir;
        },
    };

    const openExternalCalls = [];
    const openExternalImpl = typeof options.openExternalImpl === 'function'
        ? options.openExternalImpl
        : async () => {};

    return {
        app,
        store,
        userDataDir,
        packageDir,
        openExternalCalls,
        manager: new UpdateManager({
            app,
            shell: {
                openExternal: async (url) => {
                    openExternalCalls.push(url);
                    return openExternalImpl(url);
                },
            },
            store,
            isDev: true,
            getMainWindow: () => null,
            requestJsonImpl: options.requestJsonImpl,
            requestTextImpl: options.requestTextImpl,
            downloadToFileImpl: options.downloadToFileImpl,
        }),
    };
}

test('openDownloadPage opens trusted https release pages only', async () => {
    const { manager, openExternalCalls } = createManager();
    manager._setState({
        releasePageUrl: 'https://github.com/byteD-x/wechat-bot/releases/tag/v1.2.0',
    });

    const result = await manager.openDownloadPage();
    assert.equal(result.success, true);
    assert.equal(openExternalCalls.length, 1);
    assert.equal(openExternalCalls[0], 'https://github.com/byteD-x/wechat-bot/releases/tag/v1.2.0');
});

test('openDownloadPage blocks unsafe or untrusted release URLs', async () => {
    const { manager, openExternalCalls } = createManager();

    manager._setState({ releasePageUrl: 'javascript:alert(1)' });
    const blockedProtocol = await manager.openDownloadPage();
    assert.equal(blockedProtocol.success, false);

    manager._setState({ releasePageUrl: 'https://evil.example/releases/v1.2.0' });
    const blockedHost = await manager.openDownloadPage();
    assert.equal(blockedHost.success, false);
    assert.equal(blockedHost.error, 'untrusted_release_host');
    assert.equal(openExternalCalls.length, 0);
});

test('compareVersions sorts semantic versions', () => {
    assert.equal(_testUtils.compareVersions('1.2.0', '1.1.9'), 1);
    assert.equal(_testUtils.compareVersions('v1.2.0', '1.2.0'), 0);
    assert.equal(_testUtils.compareVersions('1.2.0', '1.2.1'), -1);
});

test('parseGitHubRepository supports https and ssh repository URLs', () => {
    assert.deepEqual(
        _testUtils.parseGitHubRepository('https://github.com/byteD-x/wechat-bot.git'),
        { owner: 'byteD-x', repo: 'wechat-bot' },
    );
    assert.deepEqual(
        _testUtils.parseGitHubRepository('git@github.com:byteD-x/wechat-bot.git'),
        { owner: 'byteD-x', repo: 'wechat-bot' },
    );
});

test('checkForUpdates loads checksum metadata and clears outdated skipped version', async () => {
    const store = new FakeStore({
        update: {
            autoCheckOnLaunch: false,
            skippedVersion: '1.1.0',
        },
    });
    const installerContent = 'fake-installer';
    const expectedChecksum = sha256Of(installerContent);
    const { manager } = createManager({
        store,
        currentVersion: '1.0.0',
        requestJsonImpl: async () => buildReleasePayload(),
        requestTextImpl: async () => `${expectedChecksum}  wechat-ai-assistant-setup-1.2.0.exe\n`,
    });

    const result = await manager.checkForUpdates();
    assert.equal(result.success, true);
    assert.equal(result.updateAvailable, true);
    assert.equal(manager.getState().latestVersion, '1.2.0');
    assert.equal(manager.getState().available, true);
    assert.equal(manager.getState().downloadUrl, 'https://example.com/wechat-ai-assistant-setup-1.2.0.exe');
    assert.equal(manager.getState().checksumAssetUrl, 'https://example.com/SHA256SUMS.txt');
    assert.equal(manager.getState().checksumExpected, expectedChecksum);
    assert.equal(manager.getState().skippedVersion, '');
});

test('checkForUpdates forwards metadata timeout options to request helpers', async () => {
    const expectedChecksum = sha256Of('installer-content');
    const jsonTimeouts = [];
    const textTimeouts = [];
    const { manager } = createManager({
        currentVersion: '1.0.0',
        requestJsonImpl: async (_url, options = {}) => {
            jsonTimeouts.push(Number(options.timeoutMs || 0));
            return buildReleasePayload();
        },
        requestTextImpl: async (_url, options = {}) => {
            textTimeouts.push(Number(options.timeoutMs || 0));
            return `${expectedChecksum}  wechat-ai-assistant-setup-1.2.0.exe\n`;
        },
    });

    const result = await manager.checkForUpdates();
    assert.equal(result.success, true);
    assert.equal(jsonTimeouts.length, 1);
    assert.equal(textTimeouts.length, 1);
    assert.equal(jsonTimeouts[0] > 0, true);
    assert.equal(textTimeouts[0] > 0, true);
});

test('checkForUpdates does not fail on checksum fetch errors when no update is available', async () => {
    let checksumFetchCalls = 0;
    const { manager } = createManager({
        currentVersion: '1.2.0',
        requestJsonImpl: async () => buildReleasePayload({ version: '1.2.0' }),
        requestTextImpl: async () => {
            checksumFetchCalls += 1;
            throw new Error('checksum endpoint unavailable');
        },
    });

    const result = await manager.checkForUpdates();
    assert.equal(result.success, true);
    assert.equal(result.updateAvailable, false);
    assert.equal(checksumFetchCalls, 0);
    assert.equal(manager.getState().error, '');
});

test('checkForUpdates keeps ready-to-install state clean when checksum endpoint is temporarily unavailable', async () => {
    const installerContent = 'ready-installer';
    const expectedChecksum = sha256Of(installerContent);
    let checksumFetchCalls = 0;
    let failChecksumFetch = false;
    const { manager } = createManager({
        currentVersion: '1.0.0',
        requestJsonImpl: async () => buildReleasePayload({ version: '1.2.0' }),
        requestTextImpl: async () => {
            checksumFetchCalls += 1;
            if (failChecksumFetch) {
                throw new Error('checksum endpoint unavailable');
            }
            return `${expectedChecksum}  wechat-ai-assistant-setup-1.2.0.exe\n`;
        },
        downloadToFileImpl: async (_url, destinationPath) => {
            fs.writeFileSync(destinationPath, installerContent, 'utf8');
        },
    });

    await manager.checkForUpdates();
    await manager.downloadUpdate();
    failChecksumFetch = true;

    const result = await manager.checkForUpdates();
    assert.equal(result.success, true);
    assert.equal(manager.getState().readyToInstall, true);
    assert.equal(manager.getState().error, '');
    assert.equal(checksumFetchCalls, 1);
});

test('downloadUpdate verifies SHA256 and persists verified installer state', async () => {
    const installerContent = 'fake-installer';
    const expectedChecksum = sha256Of(installerContent);
    const { manager, store, userDataDir } = createManager({
        currentVersion: '1.0.0',
        requestJsonImpl: async () => buildReleasePayload(),
        requestTextImpl: async () => `${expectedChecksum}  wechat-ai-assistant-setup-1.2.0.exe\n`,
        downloadToFileImpl: async (_url, destinationPath, options = {}) => {
            if (typeof options.onProgress === 'function') {
                options.onProgress({ downloadedBytes: 50, totalBytes: 100 });
                options.onProgress({ downloadedBytes: 100, totalBytes: 100 });
            }
            fs.writeFileSync(destinationPath, installerContent, 'utf8');
        },
    });

    await manager.checkForUpdates();
    const result = await manager.downloadUpdate();
    const installerPath = path.join(userDataDir, 'updates', 'wechat-ai-assistant-setup-1.2.0.exe');

    assert.equal(result.success, true);
    assert.equal(manager.getState().readyToInstall, true);
    assert.equal(manager.getState().downloadProgress, 100);
    assert.equal(manager.getState().downloadedVersion, '1.2.0');
    assert.equal(manager.getState().checksumVerified, true);
    assert.equal(manager.getState().downloadedInstallerSha256, expectedChecksum);
    assert.equal(store.get('update.downloadedInstallerPath'), installerPath);
    assert.equal(store.get('update.downloadedInstallerVerified'), true);
    assert.equal(store.get('update.downloadedInstallerSha256'), expectedChecksum);
    assert.equal(fs.existsSync(installerPath), true);
});

test('downloadUpdate forwards download timeout options to file downloader', async () => {
    const installerContent = 'fake-installer';
    const expectedChecksum = sha256Of(installerContent);
    const downloadTimeouts = [];
    const { manager } = createManager({
        currentVersion: '1.0.0',
        requestJsonImpl: async () => buildReleasePayload(),
        requestTextImpl: async () => `${expectedChecksum}  wechat-ai-assistant-setup-1.2.0.exe\n`,
        downloadToFileImpl: async (_url, destinationPath, options = {}) => {
            downloadTimeouts.push(Number(options.timeoutMs || 0));
            fs.writeFileSync(destinationPath, installerContent, 'utf8');
        },
    });

    await manager.checkForUpdates();
    const result = await manager.downloadUpdate();

    assert.equal(result.success, true);
    assert.equal(downloadTimeouts.length, 1);
    assert.equal(downloadTimeouts[0] > 0, true);
});

test('downloadUpdate reports checksum-blocked state before download-url fallback', async () => {
    const { manager } = createManager({
        currentVersion: '1.0.0',
        requestJsonImpl: async () => buildReleasePayload({ checksumUrl: '' }),
        requestTextImpl: async () => '',
    });

    await manager.checkForUpdates();
    const result = await manager.downloadUpdate();
    assert.equal(result.success, false);
    assert.match(String(result.error || ''), /校验|checksum/i);
});

test('downloadUpdate returns alreadyDownloaded even when release downloadUrl is temporarily empty', async () => {
    const installerContent = 'offline-ready-installer';
    const expectedChecksum = sha256Of(installerContent);
    let releaseWithUrl = true;
    const { manager } = createManager({
        currentVersion: '1.0.0',
        requestJsonImpl: async () => buildReleasePayload({
            version: '1.2.0',
            setupUrl: releaseWithUrl ? 'https://example.com/wechat-ai-assistant-setup-1.2.0.exe' : '',
        }),
        requestTextImpl: async () => `${expectedChecksum}  wechat-ai-assistant-setup-1.2.0.exe\n`,
        downloadToFileImpl: async (_url, destinationPath) => {
            fs.writeFileSync(destinationPath, installerContent, 'utf8');
        },
    });

    await manager.checkForUpdates();
    await manager.downloadUpdate();
    releaseWithUrl = false;
    await manager.checkForUpdates();

    const result = await manager.downloadUpdate();
    assert.equal(result.success, true);
    assert.equal(result.alreadyDownloaded, true);
    assert.equal(manager.getState().readyToInstall, true);
});

test('prepareInstall succeeds only when installer is verified', async () => {
    const installerContent = 'fake-installer';
    const expectedChecksum = sha256Of(installerContent);
    const { manager } = createManager({
        currentVersion: '1.0.0',
        requestJsonImpl: async () => buildReleasePayload(),
        requestTextImpl: async () => `${expectedChecksum}  wechat-ai-assistant-setup-1.2.0.exe\n`,
        downloadToFileImpl: async (_url, destinationPath) => {
            fs.writeFileSync(destinationPath, installerContent, 'utf8');
        },
    });

    await manager.checkForUpdates();
    await manager.downloadUpdate();
    const result = manager.prepareInstall();
    assert.equal(result.success, true);
});

test('prepareInstall rejects tampered installer even when store flag is verified', async () => {
    const installerContent = 'fake-installer';
    const expectedChecksum = sha256Of(installerContent);
    const { manager, store } = createManager({
        currentVersion: '1.0.0',
        requestJsonImpl: async () => buildReleasePayload(),
        requestTextImpl: async () => `${expectedChecksum}  wechat-ai-assistant-setup-1.2.0.exe\n`,
        downloadToFileImpl: async (_url, destinationPath) => {
            fs.writeFileSync(destinationPath, installerContent, 'utf8');
        },
    });

    await manager.checkForUpdates();
    await manager.downloadUpdate();
    fs.writeFileSync(manager.getState().downloadedInstallerPath, 'tampered-after-download', 'utf8');

    const result = manager.prepareInstall();
    assert.equal(result.success, false);
    assert.match(String(result.error || ''), /checksum/i);
    assert.equal(store.get('update.downloadedInstallerVerified'), false);
    assert.equal(manager.getState().readyToInstall, false);
});

test('downloadUpdate fails when SHA256 checksum mismatches', async () => {
    const installerContent = 'tampered-installer';
    const expectedChecksum = sha256Of('expected-installer');
    const { manager } = createManager({
        currentVersion: '1.0.0',
        requestJsonImpl: async () => buildReleasePayload(),
        requestTextImpl: async () => `${expectedChecksum}  wechat-ai-assistant-setup-1.2.0.exe\n`,
        downloadToFileImpl: async (_url, destinationPath) => {
            fs.writeFileSync(destinationPath, installerContent, 'utf8');
        },
    });

    await manager.checkForUpdates();
    const result = await manager.downloadUpdate();

    assert.equal(result.success, false);
    assert.match(String(result.error || ''), /SHA256|校验/i);
    assert.equal(manager.getState().readyToInstall, false);
    assert.equal(manager.getState().checksumVerified, false);
});
