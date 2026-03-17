const fs = require('fs');
const path = require('path');

class UpdateManager {
    constructor({ app, shell, getMainWindow }) {
        this.app = app;
        this.shell = shell;
        this.getMainWindow = getMainWindow;
        this._packageMetadata = null;
        this.state = this._buildInitialState();
    }

    init() {
        this._refreshState();
        this._emitState();
    }

    dispose() {}

    getState() {
        this._refreshState();
        return {
            ...this.state,
            notes: [...this.state.notes],
        };
    }

    async checkForUpdates() {
        this._refreshState();
        this.state.error = '应用内更新已停用，请前往 GitHub Releases 下载最新版本。';
        this._emitState();
        return {
            success: false,
            error: this.state.error,
            state: this.getState(),
        };
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
            enabled: true,
            checking: false,
            available: false,
            currentVersion: this.app.getVersion(),
            latestVersion: '',
            lastCheckedAt: '',
            releaseDate: '',
            downloadUrl: '',
            releasePageUrl: this._getReleasePageUrl(),
            notes: [
                '应用内自动更新已停用。',
                '请通过 GitHub Releases 页面获取最新安装包。',
            ],
            error: '',
        };
    }

    _refreshState() {
        this.state = {
            ...this.state,
            enabled: true,
            checking: false,
            available: false,
            currentVersion: this.app.getVersion(),
            latestVersion: '',
            lastCheckedAt: '',
            releaseDate: '',
            downloadUrl: '',
            releasePageUrl: this._getReleasePageUrl(),
            notes: [
                '应用内自动更新已停用。',
                '请通过 GitHub Releases 页面获取最新安装包。',
            ],
        };
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
        } catch (error) {
            // ignore window teardown races
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
}

module.exports = {
    UpdateManager,
};
