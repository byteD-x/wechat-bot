const fs = require('fs');
const fsp = require('fs/promises');
const http = require('http');
const https = require('https');
const path = require('path');
const crypto = require('crypto');
const { spawn } = require('child_process');
const { validateExternalOpenUrl } = require('./external-url-policy');

const DEFAULT_HEADERS = {
    'accept': 'application/vnd.github+json',
    'user-agent': 'wechat-ai-assistant-updater',
    'x-github-api-version': '2022-11-28',
};

const SETUP_ASSET_PATTERN = /^wechat-ai-assistant-setup-.*\.exe$/i;
const CHECKSUM_ASSET_PATTERN = /^sha256sums\.txt$/i;
const UPDATE_METADATA_TIMEOUT_MS = 15000;
const UPDATE_DOWNLOAD_TIMEOUT_MS = 3 * 60 * 1000;
const TRUSTED_RELEASE_HOSTS = new Set(['github.com', 'www.github.com']);

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

function selectChecksumAsset(assets) {
    const normalizedAssets = Array.isArray(assets) ? assets : [];
    return normalizedAssets.find((asset) => {
        const name = String(asset?.name || '').trim();
        return CHECKSUM_ASSET_PATTERN.test(name);
    }) || null;
}

function parseChecksumManifest(rawText = '') {
    const checksums = new Map();
    String(rawText || '')
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter(Boolean)
        .forEach((line) => {
            const match = line.match(/^([a-f0-9]{64})\s+\*?(.+)$/i);
            if (!match?.[1] || !match?.[2]) {
                return;
            }
            const checksum = String(match[1] || '').trim().toLowerCase();
            const filename = path.basename(String(match[2] || '').trim()).toLowerCase();
            if (checksum && filename) {
                checksums.set(filename, checksum);
            }
        });
    return checksums;
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

function isSha256(value) {
    return /^[a-f0-9]{64}$/i.test(String(value || '').trim());
}

async function computeFileSha256(filePath) {
    return new Promise((resolve, reject) => {
        const hash = crypto.createHash('sha256');
        const reader = fs.createReadStream(filePath);
        reader.on('error', reject);
        reader.on('data', (chunk) => hash.update(chunk));
        reader.on('end', () => resolve(hash.digest('hex').toLowerCase()));
    });
}

function computeFileSha256Sync(filePath) {
    const hash = crypto.createHash('sha256');
    const fd = fs.openSync(filePath, 'r');
    const buffer = Buffer.allocUnsafe(1024 * 1024);
    try {
        let bytesRead = 0;
        do {
            bytesRead = fs.readSync(fd, buffer, 0, buffer.length, null);
            if (bytesRead > 0) {
                hash.update(buffer.subarray(0, bytesRead));
            }
        } while (bytesRead > 0);
    } finally {
        fs.closeSync(fd);
    }
    return hash.digest('hex').toLowerCase();
}

function requestJson(url, options = {}) {
    const {
        headers = {},
        maxRedirects = 5,
        timeoutMs = UPDATE_METADATA_TIMEOUT_MS,
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
                    reject(new Error('too many redirects'));
                    return;
                }
                const redirectUrl = new URL(response.headers.location, urlObject).toString();
                response.resume();
                resolve(requestJson(redirectUrl, { headers, maxRedirects: maxRedirects - 1, timeoutMs }));
                return;
            }

            const chunks = [];
            response.on('data', (chunk) => chunks.push(chunk));
            response.on('end', () => {
                const raw = Buffer.concat(chunks).toString('utf8');
                if (statusCode < 200 || statusCode >= 300) {
                    let message = `闂傚倷娴囧畷鍨叏閺夋嚚娲敇閵忕姷鍝楅梻渚囧墮缁夌敻宕曢幋锔界厽婵°倐鍋撻柣妤€妫涘▎銏ゆ倷閸濆嫮楠囬梺鍓插亽閸嬪嫭绂嶉婊勫仏?(${statusCode})`;
                    try {
                        const payload = JSON.parse(raw);
                        const detail = String(payload?.message || '').trim();
                        if (detail) {
                            message = `闂傚倷娴囧畷鍨叏閺夋嚚娲敇閵忕姷鍝楅梻渚囧墮缁夌敻宕曢幋锔界厽婵°倐鍋撻柣妤€妫涘▎銏ゆ倷閸濆嫮楠囬梺鍓插亽閸嬪嫭绂嶉婊勫仏?(${statusCode}): ${detail}`;
                        }
                    } catch (_) {
                        if (raw.trim()) {
                            message = `闂傚倷娴囧畷鍨叏閺夋嚚娲敇閵忕姷鍝楅梻渚囧墮缁夌敻宕曢幋锔界厽婵°倐鍋撻柣妤€妫涘▎銏ゆ倷閸濆嫮楠囬梺鍓插亽閸嬪嫭绂嶉婊勫仏?(${statusCode}): ${raw.trim()}`;
                        }
                    }
                    reject(new Error(message));
                    return;
                }

                try {
                    resolve(JSON.parse(raw));
                } catch (error) {
                    reject(new Error('闂傚倸鍊风粈渚€骞栭鈷氭椽濡舵径瀣槐闂侀潧艌閺呮盯鎷戦悢灏佹斀闁绘ê寮堕幖鎰版倵濮橆剦妲洪柍褜鍓欑粻宥夊磿闁秴绠犻幖鎼厜缂嶆牠鏌曢崼婵愭Ц缂佺嫏鍥ㄧ厓闁告繂瀚埀顒€缍婇幃锟犲Ψ閿斿墽顔曢梺鍛婄懃椤﹁鲸鏅堕鍌滅＜闁稿本姘ㄦ晥閻庤娲栧畷顒冪亽婵炴潙鍚嬮悷鈺呮偘濠婂牊鈷?JSON'));
                }
            });
        });

        if (Number(timeoutMs) > 0) {
            request.setTimeout(Number(timeoutMs), () => {
                request.destroy(new Error('request timeout'));
            });
        }
        request.on('error', reject);
        request.end();
    });
}

function requestText(url, options = {}) {
    const {
        headers = {},
        maxRedirects = 5,
        timeoutMs = UPDATE_METADATA_TIMEOUT_MS,
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
                    reject(new Error('request timeout'));
                    return;
                }
                const redirectUrl = new URL(response.headers.location, urlObject).toString();
                response.resume();
                resolve(requestText(redirectUrl, { headers, maxRedirects: maxRedirects - 1, timeoutMs }));
                return;
            }

            const chunks = [];
            response.on('data', (chunk) => chunks.push(chunk));
            response.on('end', () => {
                const raw = Buffer.concat(chunks).toString('utf8');
                if (statusCode < 200 || statusCode >= 300) {
                    reject(new Error(`濠电姷鏁搁崑鐐哄垂閸洖绠伴柟闂寸贰閺佸嫰鏌涢锝囪穿鐟滅増甯掗悙濠冦亜閹哄棗浜鹃梺鍛婂姀閸嬫捇姊绘担鑺ョ《闁哥姵鎸婚幈銊ョ暋閹殿喗娈鹃梺鎸庣箓椤︿即鎮″☉銏＄厱閻忕偛澧介。鏌ユ煟椤撶噥娈曠紒缁樼洴瀹曢亶骞囬鍌欑棯闁诲骸鐏氬妯尖偓姘煎幖椤洩绠涘☉杈ㄦ櫇闂?(${statusCode})`));
                    return;
                }
                resolve(raw);
            });
        });

        if (Number(timeoutMs) > 0) {
            request.setTimeout(Number(timeoutMs), () => {
                request.destroy(new Error('request timeout'));
            });
        }
        request.on('error', reject);
        request.end();
    });
}

function downloadToFile(url, destinationPath, options = {}) {
    const {
        headers = {},
        onProgress = null,
        maxRedirects = 5,
        timeoutMs = UPDATE_DOWNLOAD_TIMEOUT_MS,
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
                    reject(new Error('request timeout'));
                    return;
                }
                const redirectUrl = new URL(response.headers.location, urlObject).toString();
                response.resume();
                resolve(downloadToFile(redirectUrl, destinationPath, {
                    headers,
                    onProgress,
                    maxRedirects: maxRedirects - 1,
                    timeoutMs,
                }));
                return;
            }

            if (statusCode < 200 || statusCode >= 300) {
                response.resume();
                reject(new Error(`濠电姷鏁搁崑鐐哄垂閸洖绠伴柟闂寸贰閺佸嫰鏌涢锝囪穿鐟滅増甯掗悙濠囨煃鐟欏嫬鍔ゅù婊堢畺閺岋綁鎮㈤悡搴濆枈濠碘剝褰冮崥瀣Φ閸曨垰唯闁靛鍨甸崥顐︽倵鐟欏嫭绀堝┑鐐╁亾閻庤娲忛崝鎴︺€佸Ο渚叆闁逞屽墴瀵爼顢橀姀锛勫幗?(${statusCode})`));
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

        if (Number(timeoutMs) > 0) {
            request.setTimeout(Number(timeoutMs), () => {
                request.destroy(new Error('download timeout'));
            });
        }
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
        requestTextImpl = requestText,
        downloadToFileImpl = downloadToFile,
    }) {
        this.app = app;
        this.shell = shell;
        this.store = store;
        this.isDev = !!isDev;
        this.getMainWindow = getMainWindow;
        this._requestJson = requestJsonImpl;
        this._requestText = requestTextImpl;
        this._downloadToFile = downloadToFileImpl;
        this._packageMetadata = null;
        this._autoCheckTimer = null;
        this._currentDownloadPromise = null;
        this._pendingInstallerPath = '';
        this._pendingInstallerSha256 = '';
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
                error: 'update check failed',
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
            const release = await this._requestJson(this._getLatestReleaseApiUrl(), {
                timeoutMs: UPDATE_METADATA_TIMEOUT_MS,
            });
            const latestVersion = normalizeVersion(release?.tag_name || release?.name || '');
            if (!latestVersion) {
                throw new Error('checksum manifest is required before download');
            }

            this.clearSkippedVersionIfOutdated(latestVersion);

            const asset = selectSetupAsset(release?.assets);
            const assetName = String(asset?.name || '').trim();
            const downloadUrl = String(asset?.browser_download_url || '').trim();
            const checksumAsset = selectChecksumAsset(release?.assets);
            const checksumAssetUrl = String(checksumAsset?.browser_download_url || '').trim();
            let checksumExpected = '';
            const releasePageUrl = String(release?.html_url || this._getReleasePageUrl()).trim();
            const notes = parseReleaseNotes(release?.body);
            const updateAvailable = compareVersions(latestVersion, this.app.getVersion()) > 0;
            const readyToInstall = this._hasDownloadedInstallerForVersion(latestVersion);
            const downloadedChecksum = String(this.state.downloadedInstallerSha256 || '').trim().toLowerCase();
            let checksumError = '';
            if (updateAvailable && !readyToInstall && downloadUrl && assetName) {
                if (!checksumAssetUrl) {
                    checksumError = 'Release is missing SHA256SUMS.txt, in-app install is blocked';
                } else {
                    try {
                        const checksumManifest = await this._requestText(checksumAssetUrl, {
                            timeoutMs: UPDATE_METADATA_TIMEOUT_MS,
                        });
                        const checksumMap = parseChecksumManifest(checksumManifest);
                        checksumExpected = String(checksumMap.get(assetName.toLowerCase()) || '').trim().toLowerCase();
                        if (!isSha256(checksumExpected)) {
                            checksumError = 'Setup checksum is missing from SHA256SUMS.txt';
                        }
                    } catch (checksumFetchError) {
                        checksumError = this._formatErrorMessage(
                            checksumFetchError,
                            'Failed to load SHA256SUMS.txt',
                        );
                    }
                }
            }
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
                checksumAssetUrl: updateAvailable ? checksumAssetUrl : '',
                checksumExpected: checksumExpected || (readyToInstall ? downloadedChecksum : ''),
                checksumActual: readyToInstall ? downloadedChecksum : '',
                checksumVerified: readyToInstall,
            };

            if (updateAvailable && !readyToInstall && !downloadUrl) {
                statePatch.error = 'Update found but no downloadable installer asset was detected.';
            }

            if (!statePatch.error && checksumError) {
                statePatch.error = checksumError;
            }

            if (!updateAvailable && !readyToInstall) {
                statePatch.downloadUrl = '';
                statePatch.releaseDate = release?.published_at || '';
                statePatch.notes = [];
                statePatch.checksumAssetUrl = '';
                statePatch.checksumExpected = '';
                statePatch.checksumActual = '';
                statePatch.checksumVerified = false;
            }

            this._setState(statePatch);

            return {
                success: !statePatch.error,
                updateAvailable: !!updateAvailable,
                state: this.getState(),
                error: statePatch.error || '',
            };
        } catch (error) {
            const message = this._formatErrorMessage(error, 'Failed to check updates');
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
            return { success: false, error: 'GitHub Releases URL was not found.' };
        }

        const policy = validateExternalOpenUrl(targetUrl);
        if (!policy.success) {
            return { success: false, error: policy.error };
        }

        const normalizedUrl = String(policy.normalizedUrl || '').trim();
        if (!normalizedUrl) {
            return { success: false, error: 'invalid_url' };
        }

        let parsed;
        try {
            parsed = new URL(normalizedUrl);
        } catch (_) {
            return { success: false, error: 'invalid_url' };
        }
        if (parsed.protocol !== 'https:') {
            return { success: false, error: 'blocked_protocol' };
        }
        if (!this._isTrustedReleaseHost(parsed.hostname)) {
            return { success: false, error: 'untrusted_release_host' };
        }

        await this.shell.openExternal(normalizedUrl);
        return { success: true, url: normalizedUrl };
    }

    skipVersion(version) {
        const nextVersion = normalizeVersion(version || this.state.latestVersion);
        if (!nextVersion) {
            return { success: false, error: 'No downloadable update is available right now.', state: this.getState() };
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
            return { success: false, error: 'Installer package is not ready yet', state: this.getState() };
        }

        if (this.state.readyToInstall && this._hasDownloadedInstallerForVersion(this.state.latestVersion)) {
            return { success: true, alreadyDownloaded: true, state: this.getState() };
        }

        if (!isSha256(this.state.checksumExpected)) {
            return { success: false, error: 'Missing trusted checksum metadata, please check updates again', state: this.getState() };
        }

        if (!this.state.downloadUrl) {
            return { success: false, error: 'Missing update download URL', state: this.getState() };
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
        this._pendingInstallerPath = '';
        this._pendingInstallerSha256 = '';
        if (!this.state.readyToInstall || !installerPath || !fs.existsSync(installerPath) || !this.state.checksumVerified || !isSha256(this.state.downloadedInstallerSha256 || '')) {
            return { success: false, error: 'Failed to download installer, please retry later', state: this.getState() };
        }

        const expectedChecksum = String(this.state.downloadedInstallerSha256 || '').trim().toLowerCase();
        const integrity = this._validateInstallerChecksum(installerPath, expectedChecksum);
        if (!integrity.valid) {
            this._markInstallerUnverified(installerPath, integrity.actualChecksum);
            return { success: false, error: 'Installer checksum mismatch, please re-download update' };
        }

        this._pendingInstallerPath = installerPath;
        this._pendingInstallerSha256 = expectedChecksum;
        return { success: true, state: this.getState() };
    }

    launchPreparedInstaller() {
        if (!this._pendingInstallerPath || !fs.existsSync(this._pendingInstallerPath)) {
            return { success: false, error: 'Missing prepared installer file' };
        }

        const installerPath = this._pendingInstallerPath;
        const expectedChecksum = String(this._pendingInstallerSha256 || '').trim().toLowerCase();
        const integrity = this._validateInstallerChecksum(installerPath, expectedChecksum);
        if (!integrity.valid) {
            this._pendingInstallerPath = '';
            this._pendingInstallerSha256 = '';
            this._markInstallerUnverified(installerPath, integrity.actualChecksum);
            return { success: false, error: 'Installer checksum mismatch, install aborted' };
        }

        this._pendingInstallerPath = '';
        this._pendingInstallerSha256 = '';

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
        const storedChecksum = String(this._storeGet('update.downloadedInstallerSha256', '') || '').trim().toLowerCase();
        const storedVerified = !!this._storeGet('update.downloadedInstallerVerified', false);
        const storedIntegrity = this._validateInstallerChecksum(storedPath, storedChecksum);
        const hasDownloaded = !!(
            storedPath
            && storedVersion
            && storedVerified
            && isSha256(storedChecksum)
            && storedIntegrity.valid
            && compareVersions(storedVersion, currentVersion) > 0
        );
        if (storedPath && storedVerified && !storedIntegrity.valid) {
            this._storeSet('update.downloadedInstallerVerified', false);
        }
        const verifiedChecksum = hasDownloaded
            ? (storedIntegrity.actualChecksum || storedChecksum)
            : '';
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
            downloadedInstallerSha256: verifiedChecksum,
            checksumAssetUrl: '',
            checksumExpected: verifiedChecksum,
            checksumActual: verifiedChecksum,
            checksumVerified: hasDownloaded,
        };
    }

    _refreshStateFromDisk() {
        const nextState = this._buildInitialState();
        if (nextState.readyToInstall) {
            nextState.notes = ['Update package is ready. Please install and restart to complete update.'];
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

    _isTrustedReleaseHost(hostname) {
        const normalized = String(hostname || '').trim().toLowerCase();
        if (!normalized) {
            return false;
        }
        return TRUSTED_RELEASE_HOSTS.has(normalized);
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
        const downloadedChecksum = String(this.state.downloadedInstallerSha256 || this._storeGet('update.downloadedInstallerSha256', '') || '').trim().toLowerCase();
        const downloadedVerified = !!(this.state.checksumVerified || this._storeGet('update.downloadedInstallerVerified', false));
        const integrity = this._validateInstallerChecksum(installerPath, downloadedChecksum);
        return !!(
            normalizedVersion
            && downloadedVersion
            && compareVersions(downloadedVersion, normalizedVersion) === 0
            && installerPath
            && downloadedVerified
            && isSha256(downloadedChecksum)
            && integrity.valid
        );
    }

    _validateInstallerChecksum(installerPath, expectedChecksum) {
        const normalizedPath = String(installerPath || '').trim();
        const normalizedExpected = String(expectedChecksum || '').trim().toLowerCase();
        if (!normalizedPath || !isSha256(normalizedExpected) || !fs.existsSync(normalizedPath)) {
            return { valid: false, actualChecksum: '' };
        }
        try {
            const actualChecksum = computeFileSha256Sync(normalizedPath);
            return {
                valid: actualChecksum === normalizedExpected,
                actualChecksum,
            };
        } catch (_) {
            return { valid: false, actualChecksum: '' };
        }
    }

    _markInstallerUnverified(installerPath, actualChecksum = '') {
        const normalizedPath = String(installerPath || '').trim();
        const normalizedActual = String(actualChecksum || '').trim().toLowerCase();
        this._storeSet('update.downloadedInstallerVerified', false);
        this._setState({
            readyToInstall: false,
            checksumVerified: false,
            checksumActual: normalizedActual || '',
            downloadedInstallerPath: normalizedPath || this.state.downloadedInstallerPath,
        });
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
            return 'Automatic in-app update is unavailable in this environment. Please download from GitHub Releases.';
        }
        return 'Current environment does not support update checks.';
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
        const expectedChecksum = String(this.state.checksumExpected || '').trim().toLowerCase();
        if (!latestVersion) {
            return { success: false, error: 'No target version is available yet, please check updates first', state: this.getState() };
        }

        if (!isSha256(expectedChecksum)) {
            return { success: false, error: 'Missing checksum metadata, please check updates again', state: this.getState() };
        }

        if (!downloadUrl) {
            return { success: false, error: 'Missing trusted checksum metadata, please check updates again', state: this.getState() };
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
            checksumExpected: expectedChecksum,
            checksumActual: '',
            checksumVerified: false,
        });

        try {
            await this._downloadToFile(downloadUrl, tempPath, {
                timeoutMs: UPDATE_DOWNLOAD_TIMEOUT_MS,
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
            const actualChecksum = await computeFileSha256(finalPath);
            if (actualChecksum !== expectedChecksum) {
                await safeUnlink(finalPath);
                throw new Error('Update package SHA256 verification failed, please re-download');
            }

            if (previousPath && previousPath !== finalPath) {
                await safeUnlink(previousPath);
            }

            this._storeSet('update.downloadedInstallerPath', finalPath);
            this._storeSet('update.downloadedVersion', latestVersion);
            this._storeSet('update.downloadedInstallerSha256', actualChecksum);
            this._storeSet('update.downloadedInstallerVerified', true);
            this._setState({
                downloading: false,
                downloadProgress: 100,
                readyToInstall: true,
                downloadedVersion: latestVersion,
                downloadedInstallerPath: finalPath,
                downloadedInstallerSha256: actualChecksum,
                checksumExpected: expectedChecksum,
                checksumActual: actualChecksum,
                checksumVerified: true,
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
            const message = this._formatErrorMessage(error, 'Failed to download installer');
            const fallbackReady = this._hasDownloadedInstallerForVersion(latestVersion);
            const fallbackChecksum = fallbackReady
                ? String(this.state.downloadedInstallerSha256 || this._storeGet('update.downloadedInstallerSha256', '') || '').trim().toLowerCase()
                : '';
            this._setState({
                downloading: false,
                downloadProgress: 0,
                readyToInstall: fallbackReady,
                checksumExpected: fallbackReady ? fallbackChecksum : expectedChecksum,
                checksumActual: fallbackReady ? fallbackChecksum : '',
                checksumVerified: fallbackReady,
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
        selectChecksumAsset,
        parseChecksumManifest,
        isSha256,
    },
};
