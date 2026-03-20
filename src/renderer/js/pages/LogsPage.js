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

export class LogsPage extends PageController {
    constructor() {
        super('LogsPage', 'page-logs');
        this._allLogs = [];
        this._visibleLogs = [];
        this._lineCount = 500;
        this._keyword = '';
        this._level = '';
        this._refreshTimer = null;
    }

    async onInit() {
        await super.onInit();
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
