const test = require('node:test');
const assert = require('node:assert/strict');
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

    return {
        app,
        store,
        userDataDir,
        packageDir,
        manager: new UpdateManager({
            app,
            shell: { openExternal: async () => {} },
            store,
            isDev: true,
            getMainWindow: () => null,
            requestJsonImpl: options.requestJsonImpl,
            downloadToFileImpl: options.downloadToFileImpl,
        }),
    };
}

test('compareVersions 按语义版本排序', () => {
    assert.equal(_testUtils.compareVersions('1.2.0', '1.1.9'), 1);
    assert.equal(_testUtils.compareVersions('v1.2.0', '1.2.0'), 0);
    assert.equal(_testUtils.compareVersions('1.2.0', '1.2.1'), -1);
});

test('parseGitHubRepository 支持 https 与 ssh 仓库地址', () => {
    assert.deepEqual(
        _testUtils.parseGitHubRepository('https://github.com/byteD-x/wechat-bot.git'),
        { owner: 'byteD-x', repo: 'wechat-bot' },
    );
    assert.deepEqual(
        _testUtils.parseGitHubRepository('git@github.com:byteD-x/wechat-bot.git'),
        { owner: 'byteD-x', repo: 'wechat-bot' },
    );
});

test('checkForUpdates 发现新版本时更新状态并清除过期跳过版本', async () => {
    const store = new FakeStore({
        update: {
            autoCheckOnLaunch: false,
            skippedVersion: '1.1.0',
        },
    });
    const { manager } = createManager({
        store,
        currentVersion: '1.0.0',
        requestJsonImpl: async () => ({
            tag_name: 'v1.2.0',
            html_url: 'https://github.com/byteD-x/wechat-bot/releases/tag/v1.2.0',
            published_at: '2026-03-20T12:00:00.000Z',
            body: '## 更新说明\n- 修复升级链路\n- 优化状态展示',
            assets: [
                {
                    name: 'wechat-ai-assistant-setup-1.2.0.exe',
                    browser_download_url: 'https://example.com/wechat-ai-assistant-setup-1.2.0.exe',
                },
            ],
        }),
    });

    const result = await manager.checkForUpdates();
    assert.equal(result.success, true);
    assert.equal(result.updateAvailable, true);
    assert.equal(manager.getState().latestVersion, '1.2.0');
    assert.equal(manager.getState().available, true);
    assert.equal(manager.getState().downloadUrl, 'https://example.com/wechat-ai-assistant-setup-1.2.0.exe');
    assert.equal(manager.getState().skippedVersion, '');
});

test('downloadUpdate 下载完成后进入 readyToInstall 状态并落盘', async () => {
    const { manager, store, userDataDir } = createManager({
        currentVersion: '1.0.0',
        requestJsonImpl: async () => ({
            tag_name: 'v1.2.0',
            html_url: 'https://github.com/byteD-x/wechat-bot/releases/tag/v1.2.0',
            published_at: '2026-03-20T12:00:00.000Z',
            body: '更新说明',
            assets: [
                {
                    name: 'wechat-ai-assistant-setup-1.2.0.exe',
                    browser_download_url: 'https://example.com/wechat-ai-assistant-setup-1.2.0.exe',
                },
            ],
        }),
        downloadToFileImpl: async (_url, destinationPath, options = {}) => {
            if (typeof options.onProgress === 'function') {
                options.onProgress({ downloadedBytes: 50, totalBytes: 100 });
                options.onProgress({ downloadedBytes: 100, totalBytes: 100 });
            }
            fs.writeFileSync(destinationPath, 'fake-installer', 'utf8');
        },
    });

    await manager.checkForUpdates();
    const result = await manager.downloadUpdate();
    const installerPath = path.join(userDataDir, 'updates', 'wechat-ai-assistant-setup-1.2.0.exe');

    assert.equal(result.success, true);
    assert.equal(manager.getState().readyToInstall, true);
    assert.equal(manager.getState().downloadProgress, 100);
    assert.equal(manager.getState().downloadedVersion, '1.2.0');
    assert.equal(store.get('update.downloadedInstallerPath'), installerPath);
    assert.equal(fs.existsSync(installerPath), true);
});

test('prepareInstall 在安装包存在时返回成功', async () => {
    const { manager } = createManager({
        currentVersion: '1.0.0',
        requestJsonImpl: async () => ({
            tag_name: 'v1.2.0',
            html_url: 'https://github.com/byteD-x/wechat-bot/releases/tag/v1.2.0',
            published_at: '2026-03-20T12:00:00.000Z',
            body: '更新说明',
            assets: [
                {
                    name: 'wechat-ai-assistant-setup-1.2.0.exe',
                    browser_download_url: 'https://example.com/wechat-ai-assistant-setup-1.2.0.exe',
                },
            ],
        }),
        downloadToFileImpl: async (_url, destinationPath) => {
            fs.writeFileSync(destinationPath, 'fake-installer', 'utf8');
        },
    });

    await manager.checkForUpdates();
    await manager.downloadUpdate();

    const result = manager.prepareInstall();
    assert.equal(result.success, true);
});
