const fs = require('fs');
const path = require('path');
const { autoUpdater } = require('electron-updater');

const DEFAULT_CHECK_INTERVAL_MS = 6 * 60 * 60 * 1000;
const STARTUP_CHECK_DELAY_MS = 15 * 1000;

function normalizeVersion(value) {
    return String(value || '')
        .trim()
        .replace(/^v/i, '')
        .split('-')[0];
}

function compareVersions(left, right) {
    const a = normalizeVersion(left).split('.').map(part => Number.parseInt(part, 10) || 0);
    const b = normalizeVersion(right).split('.').map(part => Number.parseInt(part, 10) || 0);
    const length = Math.max(a.length, b.length);

    for (let index = 0; index < length; index += 1) {
        const delta = (a[index] || 0) - (b[index] || 0);
        if (delta !== 0) {
            return delta > 0 ? 1 : -1;
        }
    }

    return 0;
}

function toNotesArray(value) {
    if (Array.isArray(value)) {
        return value
            .map(item => {
                if (!item) {
                    return '';
                }
                if (typeof item === 'string') {
                    return item.trim();
                }
                return String(item.note || item.releaseName || '').trim();
            })
            .filter(Boolean);
    }

    if (typeof value === 'string') {
        return value.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
    }

    return [];
}

class UpdateManager {
    constructor({ app, shell, store, Notification, getMainWindow, isDev = false }) {
        this.app = app;
        this.shell = shell;
        this.store = store;
        this.Notification = Notification;
        this.getMainWindow = getMainWindow;
        this.isDev = isDev;
        this.updater = autoUpdater;
        this._startupTimer = null;
        this._intervalTimer = null;
        this._listenersBound = false;
        this._packageMetadata = null;
        this.state = this._buildInitialState();
    }

    init() {
        this._refreshEnabledState();
        this._emitState();

        if (this.isDev || !this.state.enabled) {
            return;
        }

        this.updater.autoDownload = false;
        this.updater.autoInstallOnAppQuit = false;
        this.updater.logger = {
            info: (...args) => console.log('[Updater]', ...args),
            warn: (...args) => console.warn('[Updater]', ...args),
            error: (...args) => console.error('[Updater]', ...args)
        };

        if (!this._listenersBound) {
            this._bindUpdaterEvents();
            this._listenersBound = true;
        }

        const config = this._getConfig();
        if (!config.autoCheckOnLaunch) {
            return;
        }

        this._startupTimer = setTimeout(() => {
            this.checkForUpdates({ manual: false, source: 'startup' }).catch(error => {
                console.error('[Updater] startup check failed:', error);
            });
        }, STARTUP_CHECK_DELAY_MS);

        this._intervalTimer = setInterval(() => {
            this.checkForUpdates({ manual: false, source: 'timer' }).catch(error => {
                console.error('[Updater] scheduled check failed:', error);
            });
        }, config.checkIntervalMs);
    }

    dispose() {
        if (this._startupTimer) {
            clearTimeout(this._startupTimer);
            this._startupTimer = null;
        }

        if (this._intervalTimer) {
            clearInterval(this._intervalTimer);
            this._intervalTimer = null;
        }
    }

    getState() {
        this._refreshEnabledState();
        return { ...this.state, notes: [...this.state.notes] };
    }

    async checkForUpdates() {
        if (!this.state.enabled) {
            this._setState({
                enabled: false,
                checking: false,
                error: this.isDev ? '开发模式下不检查更新。' : '当前环境未启用 GitHub 更新检查。'
            });
            return { success: false, error: this.state.error, state: this.getState() };
        }

        if (this.state.checking) {
            return { success: true, updateAvailable: this.state.available, state: this.getState() };
        }

        this._setState({
            checking: true,
            error: ''
        });

        try {
            const result = await this.updater.checkForUpdates();
            const info = result?.updateInfo || null;
            const latestVersion = normalizeVersion(info?.version || this.state.currentVersion);
            const updateAvailable = compareVersions(latestVersion, this.state.currentVersion) > 0;

            this._setState({
                checking: false,
                available: updateAvailable,
                latestVersion,
                lastCheckedAt: new Date().toISOString(),
                releaseDate: info?.releaseDate || '',
                notes: toNotesArray(info?.releaseNotes),
                error: ''
            });

            return { success: true, updateAvailable, state: this.getState() };
        } catch (error) {
            const message = error instanceof Error ? error.message : '检查更新失败';
            this._setState({
                checking: false,
                lastCheckedAt: new Date().toISOString(),
                error: message
            });
            return { success: false, error: message, state: this.getState() };
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

    _buildInitialState() {
        return {
            enabled: false,
            checking: false,
            available: false,
            currentVersion: this.app.getVersion(),
            latestVersion: null,
            lastCheckedAt: null,
            releaseDate: null,
            downloadUrl: '',
            releasePageUrl: this._getReleasePageUrl(),
            notes: [],
            error: ''
        };
    }

    _setState(nextState) {
        this.state = {
            ...this.state,
            ...nextState,
            currentVersion: this.app.getVersion(),
            releasePageUrl: this._getReleasePageUrl()
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
        } catch (e) {
            // If the window is closing/destroyed during send, ignore to avoid crashing the main process.
        }
    }

    _refreshEnabledState() {
        const config = this._getConfig();
        this.state.enabled = config.enabled;
        this.state.currentVersion = this.app.getVersion();
        this.state.releasePageUrl = this._getReleasePageUrl();
    }

    _getConfig() {
        const storedConfig = this.store.get('update') || {};
        const intervalHours = Number.parseInt(String(storedConfig.checkIntervalHours ?? ''), 10);

        return {
            enabled: this._hasAppUpdateConfig(),
            autoCheckOnLaunch: storedConfig.autoCheckOnLaunch !== false,
            notifyOnUpdate: storedConfig.notifyOnUpdate !== false,
            checkIntervalMs: Number.isFinite(intervalHours) && intervalHours > 0
                ? intervalHours * 60 * 60 * 1000
                : DEFAULT_CHECK_INTERVAL_MS
        };
    }

    _hasAppUpdateConfig() {
        if (this.isDev) {
            return false;
        }

        const configPath = path.join(process.resourcesPath, 'app-update.yml');
        return fs.existsSync(configPath);
    }

    _readPackageMetadata() {
        if (this._packageMetadata) {
            return this._packageMetadata;
        }

        try {
            const packageJsonPath = path.join(this.app.getAppPath(), 'package.json');
            this._packageMetadata = JSON.parse(fs.readFileSync(packageJsonPath, 'utf-8'));
        } catch (error) {
            console.warn('[Updater] failed to read package metadata:', error.message);
            this._packageMetadata = {};
        }

        return this._packageMetadata;
    }

    _getReleasePageUrl() {
        const metadata = this._readPackageMetadata();
        const repository = metadata.repository;
        const rawUrl = typeof repository === 'string' ? repository : repository?.url;
        if (!rawUrl) {
            return '';
        }

        const normalized = String(rawUrl)
            .replace(/^git\+/, '')
            .replace(/\.git$/, '');

        if (normalized.startsWith('https://github.com/')) {
            return `${normalized}/releases/latest`;
        }

        const sshMatch = normalized.match(/^git@github\.com:(.+\/.+)$/);
        if (sshMatch?.[1]) {
            return `https://github.com/${sshMatch[1]}/releases/latest`;
        }

        return '';
    }

    _bindUpdaterEvents() {
        this.updater.on('update-available', (info) => {
            const version = normalizeVersion(info?.version || '');
            this._setState({
                checking: false,
                available: true,
                latestVersion: version,
                lastCheckedAt: new Date().toISOString(),
                releaseDate: info?.releaseDate || '',
                notes: toNotesArray(info?.releaseNotes),
                error: ''
            });
            this._notifyIfNeeded(version);
        });

        this.updater.on('update-not-available', (info) => {
            this._setState({
                checking: false,
                available: false,
                latestVersion: normalizeVersion(info?.version || this.state.currentVersion),
                lastCheckedAt: new Date().toISOString(),
                releaseDate: info?.releaseDate || '',
                notes: toNotesArray(info?.releaseNotes),
                error: ''
            });
        });

        this.updater.on('error', (error) => {
            this._setState({
                checking: false,
                lastCheckedAt: new Date().toISOString(),
                error: error?.message || '检查更新失败'
            });
        });
    }

    _notifyIfNeeded(version) {
        const config = this._getConfig();
        if (!config.notifyOnUpdate || !version || !this.Notification?.isSupported?.()) {
            return;
        }

        const notifiedVersion = this.store.get('update.lastNotifiedVersion');
        if (notifiedVersion === version) {
            return;
        }

        const notification = new this.Notification({
            title: `发现新版本 v${version}`,
            body: '点击跳转到 GitHub Releases 下载并更新。'
        });

        notification.on('click', () => {
            this.openDownloadPage().catch(error => {
                console.error('[Updater] failed to open release page:', error);
            });
        });

        notification.show();
        this.store.set('update.lastNotifiedVersion', version);
    }
}

module.exports = {
    UpdateManager
};
