/**
 * 仪表盘页面控制器
 */

import { PageController } from '../core/PageController.js';
import { Events } from '../core/EventBus.js';
import {
    appendRecentMessage,
    clearOfflineData,
    loadRecentMessages,
    refreshDashboardCost,
} from './dashboard/data-loader.js';
import {
    formatDurationMs,
} from './dashboard/formatters.js';
import {
    renderIdlePanel,
} from './dashboard/renderers.js';
import {
    getIdleRemainingMs,
    getIdleState,
    startIdleTimer,
    stopIdleTimer,
} from './dashboard/runtime-controller.js';
import {
    updateBotUI,
    updateStats as presentStats,
} from './dashboard/status-presenter.js';
import { bindDashboardEvents } from './dashboard/page-shell.js';

export class DashboardPage extends PageController {
    constructor() {
        super('DashboardPage', 'page-dashboard');
        this._lastStats = null;
        this._recentMessages = [];
        this._lastCostFetchAt = 0;
        this._idleRenderTimer = null;
        this._dashboardCost = {
            today: null,
            recent: null,
        };
        this._renderIdlePanel = () => {
            const status = this.getState('bot.status') || {};
            const idleState = getIdleState(this);
            renderIdlePanel(this, {
                connected: !!this.getState('bot.connected'),
                isRunning: !!this.getState('bot.running'),
                growthRunning: !!status.growth_running,
                startupActive: !!status?.startup?.active,
                idleState,
            }, {
                getIdleState: () => idleState,
                getIdleRemainingMs: (state) => getIdleRemainingMs(this, state),
                formatDurationMs,
            });
        };
        this._updateBotUI = () => updateBotUI(this);
    }

    async onInit() {
        await super.onInit();
        bindDashboardEvents(this);
        this.listenEvent(Events.MESSAGE_RECEIVED, (message) => {
            appendRecentMessage(this, message);
        });
    }

    async onEnter() {
        await super.onEnter();
        startIdleTimer(this);
        updateBotUI(this);

        const status = this.getState('bot.status');
        if (status) {
            this.updateStats(status);
        }

        if (!this.getState('bot.connected')) {
            clearOfflineData(this);
            return;
        }

        await Promise.all([
            loadRecentMessages(this),
            refreshDashboardCost(this, true),
        ]);
    }

    async onLeave() {
        stopIdleTimer(this);
        await super.onLeave();
    }

    async onDestroy() {
        stopIdleTimer(this);
        await super.onDestroy();
    }

    updateStats(stats) {
        presentStats(this, stats);
    }
}

export default DashboardPage;
