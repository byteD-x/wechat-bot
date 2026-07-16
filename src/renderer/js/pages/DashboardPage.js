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
    refreshDashboardStability,
} from './dashboard/data-loader.js';
import {
    formatDurationMs,
} from './dashboard/formatters.js';
import {
    renderIdlePanel,
    renderStabilitySummary,
} from './dashboard/renderers.js';
import { renderDashboardPageShell } from '../app-shell/pages/index.js';
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

const DASHBOARD_SECTIONS = new Set(['overview', 'recovery', 'business', 'messages']);

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
        this._stability = {
            backups: null,
            latestEval: null,
        };
        this._lastStabilityFetchAt = 0;
        this._dashboardSection = 'overview';
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
        this._renderStability = () => renderStabilitySummary(
            this,
            (this.getState('bot.status') || {}).pending_replies || {},
            this._stability || {},
        );
        this._updateBotUI = () => updateBotUI(this);
    }

    _setDashboardSection(section = 'overview') {
        const normalized = DASHBOARD_SECTIONS.has(section) ? section : 'overview';
        this._dashboardSection = normalized;

        this.$$('.dashboard-section-tab').forEach((button) => {
            const active = button.dataset.dashboardSectionButton === normalized;
            button.classList.toggle('active', active);
            button.setAttribute('aria-pressed', active ? 'true' : 'false');
        });

        this.$$('.dashboard-stage').forEach((stage) => {
            const active = stage.dataset.dashboardSection === normalized;
            stage.hidden = !active;
            stage.classList.toggle('active', active);
        });
    }

    async onInit() {
        await super.onInit();
        const container = this.container || (typeof document !== 'undefined' ? this.getContainer() : null);
        if (container) {
            container.innerHTML = renderDashboardPageShell();
        }
        bindDashboardEvents(this);
        this._setDashboardSection(this._dashboardSection);
        this.listenEvent(Events.MESSAGE_RECEIVED, (message) => {
            appendRecentMessage(this, message);
        });
    }

    async onEnter() {
        await super.onEnter();
        this._setDashboardSection(this._dashboardSection);
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
            refreshDashboardStability(this, true),
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
