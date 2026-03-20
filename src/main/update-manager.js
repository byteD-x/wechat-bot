const fs = require('fs');
const fsp = require('fs/promises');
const http = require('http');
const https = require('https');
const path = require('path');
const { spawn } = require('child_process');

const DEFAULT_HEADERS = {
    'accept': 'application/vnd.github+json',
    'user-agent': 'wechat-ai-assistant-updater',
    'x-github-api-version': '2022-11-28',
};

const SETUP_ASSET_PATTERN = /^wechat-ai-assistant-setup-.*\.exe$/i;

function normalizeVersion(value) {
    return String(value || '').trim().replace(/^v/i, '');
}

function compareVersions(left, right) {
    const leftParts = normalizeVersion(left).split('.').map((part) => Number.parseInt(part, 10) || 0);
    const rightParts = normalizeVersion(right).split('.').map((part) => Number.parseInt(part, 10) || 0);
    const maxLength = Math.max(leftParts.length, rightParts.length, 3);
    for (let index = 0; index < maxLength; index += 1) {
        const leftValue = leftParts[index] || 0;
        const rightValue = rightParts[index] || 0;
        if (leftValue > rightValue) {
            return 1;
        }
        if (leftValue < rightValue) {
            return -1;
        }
    }
    return 0;
}

function parseGitHubRepository(rawValue) {
    const rawUrl = String(rawValue || '').trim();
    if (!rawUrl) {
        return null;
    }

    const normalized = rawUrl
        .replace(/^git\+/, '')
        .replace(/\.git$/, '');

    const httpsMatch = normalized.match(/^https:\/\/github\.com\/([^/]+)\/([^/]+)$/i);
    if (httpsMatch?.[1] && httpsMatch?.[2]) {
        return {
            owner: httpsMatch[1],
            repo: httpsMatch[2],
        };
    }

    const sshMatch = normalized.match(/^git@github\.com:([^/]+)\/([^/]+)$/i);
    if (sshMatch?.[1] && sshMatch?.[2]) {
        return {
            owner: sshMatch[1],
            repo: sshMatch[2],
        };
    }

    return null;
}

function buildReleasePageUrl(repositoryInfo) {
    if (!repositoryInfo?.owner || !repositoryInfo?.repo) {
        return '';
    }
    return `https://github.com/${repositoryInfo.owner}/${repositoryInfo.repo}/releases/latest`;
}

function buildLatestReleaseApiUrl(repositoryInfo) {
    if (!repositoryInfo?.owner || !repositoryInfo?.repo) {
        return '';
    }
    return `https://api.github.com/repos/${repositoryInfo.owner}/${repositoryInfo.repo}/releases/latest`;
}

function parseReleaseNotes(body) {
    return String(body || '')
        .split(/\r?\n/)
        .map((line) => String(line || '').trim())
        .filter(Boolean)
        .map((line) => line.replace(/^[-*]\s*/, '').replace(/^#{1,6}\s*/, '').trim())
        .filter(Boolean)
        .slice(0, 12);
}

function selectSetupAsset(assets) {
    const normalizedAssets = Array.isArray(assets) ? assets : [];
    return normalizedAssets.find((asset) => {
        const name = String(asset?.name || '').trim();
        return SETUP_ASSET_PATTERN.test(name);
    }) || null;
}

function isRedirectStatus(statusCode) {
    return [301, 302, 303, 307, 308].includes(Number(statusCode || 0));
}

function getHttpModule(urlObject) {
    return urlObject.protocol === 'http:' ? http : https;
}

function powershellSingleQuote(value) {
    return String(value || '').replace(/'/g, "''");
}

async function ensureDirectory(dirPath) {
    await fsp.mkdir(dirPath, { recursive: true });
}

async function safeUnlink(filePath) {
    if (!filePath) {
        return;
    }
    try {
        await fsp.unlink(filePath);
    } catch (error) {
        if (error?.code !== 'ENOENT') {
            throw error;
        }
    }
}

function requestJson(url, options = {}) {
    const {
        headers = {},
        maxRedirects = 5,
    } = options;

    return new Promise((resolve, reject) => {
        const urlObject = new URL(url);
        const client = getHttpModule(urlObject);
        const request = client.request(urlObject, {
            method: 'GET',
            headers: {
                ...DEFAULT_HEADERS,
                ...headers,
            },
        }, (response) => {
            const statusCode = Number(response.statusCode || 0);
            if (isRedirectStatus(statusCode) && response.headers.location) {
                if (maxRedirects <= 0) {
                    response.resume();
                    reject(new Error('请求重定向次数过多'));
                    return;
                }
                const redirectUrl = new URL(response.headers.location, urlObject).toString();
                response.resume();
                resolve(requestJson(redirectUrl, { headers, maxRedirects: maxRedirects - 1 }));
                return;
            }

            const chunks = [];
            response.on('data', (chunk) => chunks.push(chunk));
            response.on('end', () => {
                const raw = Buffer.concat(chunks).toString('utf8');
                if (statusCode < 200 || statusCode >= 300) {
                    let message = `请求失败 (${statusCode})`;
                    try {
                        const payload = JSON.parse(raw);
                        const detail = String(payload?.message || '').trim();
                        if (detail) {
                            message = `请求失败 (${statusCode}): ${detail}`;
                        }
                    } catch (_) {
                        if (raw.trim()) {
                            message = `请求失败 (${statusCode}): ${raw.trim()}`;
                        }
                    }
                    reject(new Error(message));
                    return;
                }

                try {
                    resolve(JSON.parse(raw));
                } catch (error) {
                    reject(new Error('更新服务返回了无效 JSON'));
                }
            });
        });

        request.on('error', reject);
        request.end();
    });
}

function downloadToFile(url, destinationPath, options = {}) {
    const {
        headers = {},
        onProgress = null,
        maxRedirects = 5,
    } = options;

    return new Promise((resolve, reject) => {
        const urlObject = new URL(url);
        const client = getHttpModule(urlObject);
        const request = client.request(urlObject, {
            method: 'GET',
            headers: {
                ...DEFAULT_HEADERS,
                ...headers,
            },
        }, (response) => {
            const statusCode = Number(response.statusCode || 0);
            if (isRedirectStatus(statusCode) && response.headers.location) {
                if (maxRedirects <= 0) {
                    response.resume();
                    reject(new Error('下载重定向次数过多'));
                    return;
                }
                const redirectUrl = new URL(response.headers.location, urlObject).toString();
                response.resume();
                resolve(downloadToFile(redirectUrl, destinationPath, {
                    headers,
                    onProgress,
                    maxRedirects: maxRedirects - 1,
                }));
                return;
            }

            if (statusCode < 200 || statusCode >= 300) {
                response.resume();
                reject(new Error(`下载安装包失败 (${statusCode})`));
                return;
            }

            const totalBytes = Number.parseInt(String(response.headers['content-length'] || '0'), 10) || 0;
            let downloadedBytes = 0;
            let settled = false;
            const writer = fs.createWriteStream(destinationPath);

            const finishWithError = (error) => {
                if (settled) {
                    return;
                }
                settled = true;
                writer.destroy();
                reject(error);
            };

            response.on('data', (chunk) => {
                downloadedBytes += chunk.length;
                if (typeof onProgress === 'function') {
                    onProgress({ downloadedBytes, totalBytes });
                }
            });

            response.on('error', finishWithError);
            writer.on('error', finishWithError);
            writer.on('finish', () => {
                if (settled) {
                    return;
                }
                settled = true;
                resolve({
                    downloadedBytes,
                    totalBytes,
                });
            });

            response.pipe(writer);
        });

        request.on('error', reject);
        request.end();
    });
}

class UpdateManager {
    constructor({
        app,
        shell,
        store,
        isDev = false,
        getMainWindow,
        requestJsonImpl = requestJson,
        downloadToFileImpl = downloadToFile,
    }) {
        this.app = app;
        this.shell = shell;
        this.store = store;
        this.isDev = !!isDev;
        this.getMainWindow = getMainWindow;
        this._requestJson = requestJsonImpl;
        this._downloadToFile = downloadToFileImpl;
        this._packageMetadata = null;
        this._autoCheckTimer = null;
        this._currentDownloadPromise = null;
        this._pendingInstallerPath = '';
        this.state = this._buildInitialState();
    }

    init() {
        this._refreshStateFromDisk();
        this._emitState();
        if (this._shouldAutoCheckOnLaunch()) {
            this._autoCheckTimer = setTimeout(() => {
                this.checkForUpdates({ manual: false, source: 'launch' }).catch((error) => {
                    console.warn('[UpdateManager] auto check failed:', error?.message || error);
                });
            }, 1500);
        }
    }

    dispose() {
        if (this._autoCheckTimer) {
            clearTimeout(this._autoCheckTimer);
            this._autoCheckTimer = null;
        }
    }

    getState() {
        return {
            ...this.state,
            notes: [...(Array.isArray(this.state.notes) ? this.state.notes : [])],
        };
    }

    async checkForUpdates(options = {}) {
        if (!this._isUpdateSupported()) {
            const error = this._getUnsupportedMessage();
            this._setState({
                enabled: false,
                checking: false,
                error,
            });
            return {
                success: false,
                error,
                state: this.getState(),
            };
        }

        if (this.state.checking) {
            return {
                success: false,
                error: '正在检查更新，请稍后再试',
                state: this.getState(),
            };
        }

        const checkedAt = new Date().toISOString();
        this._storeSet('update.lastCheckedAt', checkedAt);
        this._setState({
            checking: true,
            error: '',
            lastCheckedAt: checkedAt,
        });

        try {
            const release = await this._requestJson(this._getLatestReleaseApiUrl());
            const latestVersion = normalizeVersion(release?.tag_name || release?.name || '');
            if (!latestVersion) {
                throw new Error('未解析到最新版本号');
            }

            this.clearSkippedVersionIfOutdated(latestVersion);

            const asset = selectSetupAsset(release?.assets);
            const downloadUrl = String(asset?.browser_download_url || '').trim();
            const releasePageUrl = String(release?.html_url || this._getReleasePageUrl()).trim();
            const notes = parseReleaseNotes(release?.body);
            const updateAvailable = compareVersions(latestVersion, this.app.getVersion()) > 0;
            const readyToInstall = this._hasDownloadedInstallerForVersion(latestVersion);
            const statePatch = {
                checking: false,
                enabled: true,
                available: updateAvailable || readyToInstall,
                latestVersion: updateAvailable || readyToInstall ? latestVersion : '',
                releaseDate: release?.published_at || '',
                downloadUrl,
                releasePageUrl,
                notes,
                error: '',
                readyToInstall,
                downloadedVersion: readyToInstall ? latestVersion : this.state.downloadedVersion,
                downloadedInstallerPath: readyToInstall ? this.state.downloadedInstallerPath : this.state.downloadedInstallerPath,
            };

            if (updateAvailable && !downloadUrl) {
                statePatch.error = '发现新版本，但未找到可下载的安装包';
            }

            if (!updateAvailable && !readyToInstall) {
                statePatch.downloadUrl = '';
                statePatch.releaseDate = release?.published_at || '';
                statePatch.notes = [];
            }

            this._setState(statePatch);

            return {
                success: !statePatch.error,
                updateAvailable: !!updateAvailable,
                state: this.getState(),
                error: statePatch.error || '',
            };
        } catch (error) {
            const message = this._formatErrorMessage(error, '检查更新失败');
            this._setState({
                checking: false,
                enabled: this._isUpdateSupported(),
                error: message,
            });
            return {
                success: false,
                error: message,
                state: this.getState(),
            };
        }
    }

    async openDownloadPage() {
        const targetUrl = this.state.releasePageUrl || this._getReleasePageUrl();
        if (!targetUrl) {
            return { success: false, error: '未找到 GitHub Releases 地址' };
        }

        await this.shell.openExternal(targetUrl);
        return { success: true, url: targetUrl };
    }

    skipVersion(version) {
        const nextVersion = normalizeVersion(version || this.state.latestVersion);
        if (!nextVersion) {
            return { success: false, error: '未指定要跳过的版本' };
        }

        this._storeSet('update.skippedVersion', nextVersion);
        this._setState({
            skippedVersion: nextVersion,
        });
        return { success: true, state: this.getState() };
    }

    clearSkippedVersionIfOutdated(latestVersion) {
        const skippedVersion = normalizeVersion(this._storeGet('update.skippedVersion', this.state.skippedVersion || ''));
        if (!skippedVersion || compareVersions(latestVersion, skippedVersion) <= 0) {
            return false;
        }

        this._storeSet('update.skippedVersion', '');
        this._setState({
            skippedVersion: '',
        });
        return true;
    }

    async downloadUpdate() {
        if (!this.state.available || !this.state.latestVersion) {
            return { success: false, error: '当前没有可下载的新版本', state: this.getState() };
        }

        if (!this.state.downloadUrl) {
            return { success: false, error: '未找到更新下载地址', state: this.getState() };
        }

        if (this.state.readyToInstall && this._hasDownloadedInstallerForVersion(this.state.latestVersion)) {
            return { success: true, alreadyDownloaded: true, state: this.getState() };
        }

        if (this._currentDownloadPromise) {
            return this._currentDownloadPromise;
        }

        this._currentDownloadPromise = this._downloadUpdateImpl().finally(() => {
            this._currentDownloadPromise = null;
        });
        return this._currentDownloadPromise;
    }

    prepareInstall() {
        const installerPath = this.state.downloadedInstallerPath;
        if (!this.state.readyToInstall || !installerPath || !fs.existsSync(installerPath)) {
            return { success: false, error: '更新安装包尚未准备好' };
        }

        this._pendingInstallerPath = installerPath;
        return { success: true, state: this.getState() };
    }

    launchPreparedInstaller() {
        if (!this._pendingInstallerPath || !fs.existsSync(this._pendingInstallerPath)) {
            return { success: false, error: '未找到待安装的更新包' };
        }

        const installerPath = this._pendingInstallerPath;
        this._pendingInstallerPath = '';

        const command = `Start-Sleep -Seconds 2; Start-Process -FilePath '${powershellSingleQuote(installerPath)}'`;
        const child = spawn('powershell.exe', [
            '-NoProfile',
            '-ExecutionPolicy', 'Bypass',
            '-WindowStyle', 'Hidden',
            '-Command',
            command,
        ], {
            detached: true,
            stdio: 'ignore',
        });

        child.unref();
        return { success: true, installerPath };
    }

    _buildInitialState() {
        const currentVersion = normalizeVersion(this.app.getVersion());
        const storedPath = String(this._storeGet('update.downloadedInstallerPath', '') || '').trim();
        const storedVersion = normalizeVersion(this._storeGet('update.downloadedVersion', ''));
        const hasDownloaded = !!(storedPath && storedVersion && fs.existsSync(storedPath) && compareVersions(storedVersion, currentVersion) > 0);
        return {
            enabled: this._isUpdateSupported(),
            checking: false,
            available: hasDownloaded,
            currentVersion,
            latestVersion: hasDownloaded ? storedVersion : '',
            lastCheckedAt: String(this._storeGet('update.lastCheckedAt', '') || ''),
            releaseDate: '',
            downloadUrl: '',
            releasePageUrl: this._getReleasePageUrl(),
            notes: [],
            error: this._isUpdateSupported() ? '' : this._getUnsupportedMessage(),
            skippedVersion: normalizeVersion(this._storeGet('update.skippedVersion', '')),
            downloading: false,
            downloadProgress: 0,
            readyToInstall: hasDownloaded,
            downloadedVersion: hasDownloaded ? storedVersion : '',
            downloadedInstallerPath: hasDownloaded ? storedPath : '',
        };
    }

    _refreshStateFromDisk() {
        const nextState = this._buildInitialState();
        if (nextState.readyToInstall) {
            nextState.notes = ['已下载更新安装包，确认后即可安装并重启。'];
        }
        this.state = nextState;
    }

    _setState(patch = {}) {
        this.state = {
            ...this.state,
            ...patch,
        };
        this._emitState();
    }

    _emitState() {
        const win = this.getMainWindow?.();
        if (!win || win.isDestroyed()) {
            return;
        }

        const wc = win.webContents;
        if (!wc || (typeof wc.isDestroyed === 'function' && wc.isDestroyed())) {
            return;
        }

        try {
            wc.send('update-state-changed', this.getState());
        } catch (_) {
            // Ignore renderer teardown races.
        }
    }

    _readPackageMetadata() {
        if (this._packageMetadata) {
            return this._packageMetadata;
        }

        try {
            const packageJsonPath = path.join(this.app.getAppPath(), 'package.json');
            this._packageMetadata = JSON.parse(fs.readFileSync(packageJsonPath, 'utf-8'));
        } catch (error) {
            console.warn('[UpdateManager] failed to read package metadata:', error.message);
            this._packageMetadata = {};
        }
        return this._packageMetadata;
    }

    _getRepositoryInfo() {
        const metadata = this._readPackageMetadata();
        const repository = metadata.repository;
        const rawUrl = typeof repository === 'string' ? repository : repository?.url;
        return parseGitHubRepository(rawUrl);
    }

    _getReleasePageUrl() {
        return buildReleasePageUrl(this._getRepositoryInfo());
    }

    _getLatestReleaseApiUrl() {
        return buildLatestReleaseApiUrl(this._getRepositoryInfo());
    }

    _getDownloadDirectory() {
        return path.join(this.app.getPath('userData'), 'updates');
    }

    _hasDownloadedInstallerForVersion(version) {
        const normalizedVersion = normalizeVersion(version);
        const downloadedVersion = normalizeVersion(this.state.downloadedVersion || this._storeGet('update.downloadedVersion', ''));
        const installerPath = String(this.state.downloadedInstallerPath || this._storeGet('update.downloadedInstallerPath', '') || '').trim();
        return !!(
            normalizedVersion
            && downloadedVersion
            && compareVersions(downloadedVersion, normalizedVersion) === 0
            && installerPath
            && fs.existsSync(installerPath)
        );
    }

    _isPortableEnvironment() {
        return !!String(process.env.PORTABLE_EXECUTABLE_FILE || '').trim();
    }

    _isUpdateSupported() {
        return !!(this._getRepositoryInfo() && !this._isPortableEnvironment());
    }

    _shouldAutoCheckOnLaunch() {
        return !!(this._isUpdateSupported() && this.app.isPackaged && !this.isDev && this._storeGet('update.autoCheckOnLaunch', true));
    }

    _getUnsupportedMessage() {
        if (this._isPortableEnvironment()) {
            return '应用内自动更新仅支持安装版，请前往 GitHub Releases 下载最新版本。';
        }
        return '当前环境未启用更新检查。';
    }

    _formatErrorMessage(error, fallback) {
        const message = String(error?.message || '').trim();
        return message || fallback;
    }

    _storeGet(key, fallbackValue = '') {
        if (!this.store || typeof this.store.get !== 'function') {
            return fallbackValue;
        }
        return this.store.get(key, fallbackValue);
    }

    _storeSet(key, value) {
        if (!this.store || typeof this.store.set !== 'function') {
            return;
        }
        this.store.set(key, value);
    }

    async _downloadUpdateImpl() {
        const latestVersion = this.state.latestVersion;
        const downloadUrl = this.state.downloadUrl;
        const releasePageUrl = this.state.releasePageUrl || this._getReleasePageUrl();
        if (!latestVersion || !downloadUrl) {
            return { success: false, error: '未找到更新下载地址', state: this.getState() };
        }

        const downloadDir = this._getDownloadDirectory();
        const tempPath = path.join(downloadDir, `wechat-ai-assistant-setup-${latestVersion}.download`);
        const finalPath = path.join(downloadDir, `wechat-ai-assistant-setup-${latestVersion}.exe`);
        const previousPath = String(this._storeGet('update.downloadedInstallerPath', '') || '').trim();

        await ensureDirectory(downloadDir);
        await safeUnlink(tempPath);

        this._setState({
            downloading: true,
            downloadProgress: 0,
            readyToInstall: false,
            error: '',
            releasePageUrl,
        });

        try {
            await this._downloadToFile(downloadUrl, tempPath, {
                onProgress: ({ downloadedBytes, totalBytes }) => {
                    if (!totalBytes || totalBytes <= 0) {
                        return;
                    }
                    const progress = Math.min(100, Math.max(0, Math.round((downloadedBytes / totalBytes) * 100)));
                    if (progress !== this.state.downloadProgress) {
                        this._setState({ downloadProgress: progress });
                    }
                },
            });

            await safeUnlink(finalPath);
            await fsp.rename(tempPath, finalPath);

            if (previousPath && previousPath !== finalPath) {
                await safeUnlink(previousPath);
            }

            this._storeSet('update.downloadedInstallerPath', finalPath);
            this._storeSet('update.downloadedVersion', latestVersion);
            this._setState({
                downloading: false,
                downloadProgress: 100,
                readyToInstall: true,
                downloadedVersion: latestVersion,
                downloadedInstallerPath: finalPath,
                notes: [
                    ...(Array.isArray(this.state.notes) ? this.state.notes : []),
                ],
            });

            return {
                success: true,
                state: this.getState(),
            };
        } catch (error) {
            await safeUnlink(tempPath);
            const message = this._formatErrorMessage(error, '下载安装包失败');
            this._setState({
                downloading: false,
                downloadProgress: 0,
                readyToInstall: this._hasDownloadedInstallerForVersion(latestVersion),
                error: message,
            });
            return {
                success: false,
                error: message,
                state: this.getState(),
            };
        }
    }
}

module.exports = {
    UpdateManager,
    _testUtils: {
        normalizeVersion,
        compareVersions,
        parseGitHubRepository,
        buildReleasePageUrl,
        buildLatestReleaseApiUrl,
        parseReleaseNotes,
        selectSetupAsset,
    },
};
