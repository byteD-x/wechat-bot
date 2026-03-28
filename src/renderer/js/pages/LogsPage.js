import { PageController } from '../core/PageController.js';
import {
    refreshLogs,
} from './logs/data-controller.js';
import {
    bindLogsEvents,
    syncLogsPageOptions,
} from './logs/page-shell.js';
import {
    clearRefreshTimer,
    setupAutoRefresh,
} from './logs/runtime-controller.js';
import { renderLogsPageShell } from '../app-shell/pages/index.js';

export class LogsPage extends PageController {
    constructor() {
        super('LogsPage', 'page-logs');
        this._allLogs = [];
        this._visibleLogs = [];
        this._lineCount = 500;
        this._keyword = '';
        this._level = '';
        this._refreshTimer = null;
        this._refreshSeq = 0;
        this._latestRefreshSeq = 0;
    }

    async onInit() {
        await super.onInit();
        const container = this.container || (typeof document !== 'undefined' ? this.getContainer() : null);
        if (container) {
            container.innerHTML = renderLogsPageShell();
        }
        bindLogsEvents(this);
        syncLogsPageOptions(this);
    }

    async onEnter() {
        await super.onEnter();
        syncLogsPageOptions(this);
        await refreshLogs(this, { silent: true });
        setupAutoRefresh(this, { refreshLogs });
    }

    async onLeave() {
        clearRefreshTimer(this);
        await super.onLeave();
    }

    async onDestroy() {
        clearRefreshTimer(this);
        await super.onDestroy();
    }
}

export default LogsPage;
