import { PageController } from '../core/PageController.js';
import { Events } from '../core/EventBus.js';
import { apiService } from '../services/ApiService.js';
import { toast } from '../services/NotificationService.js';
import {
    downloadLogTextFile,
    isNoiseLogLine,
    LOG_TEXT,
    parseLogEntry,
} from './logs/formatters.js';
import {
    renderLogList,
    updateLogMeta,
} from './logs/renderers.js';

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
        this._bindEvents();
        this._syncOptionState();
        this.watchState('bot.connected', () => {
            if (!this.isActive()) {
                return;
            }
            this._setupAutoRefresh();
            void this._refreshLogs({ silent: true });
        });
    }

    async onEnter() {
        await super.onEnter();
        this._syncOptionState();
        await this._refreshLogs({ silent: true });
        this._setupAutoRefresh();
    }

    async onLeave() {
        this._clearRefreshTimer();
        await super.onLeave();
    }

    async onDestroy() {
        this._clearRefreshTimer();
        await super.onDestroy();
    }

    _bindEvents() {
        this.bindEvent('#btn-refresh-logs', 'click', () => {
            void this._refreshLogs();
        });

        this.bindEvent('#btn-clear-logs', 'click', () => {
            void this._clearLogs();
        });

        this.bindEvent('#btn-copy-logs', 'click', () => {
            void this._copyLogs();
        });

        this.bindEvent('#btn-export-logs', 'click', () => {
            this._exportLogs();
        });

        const searchInput = this.$('#log-search');
        searchInput?.addEventListener('input', () => {
            this._keyword = String(searchInput.value || '').trim().toLowerCase();
            this._applyFilters();
        });

        const levelSelect = this.$('#log-level');
        levelSelect?.addEventListener('change', () => {
            this._level = String(levelSelect.value || '').trim().toLowerCase();
            this._applyFilters();
        });

        const lineSelect = this.$('#log-lines');
        lineSelect?.addEventListener('change', () => {
            const nextValue = Number(lineSelect.value || 500);
            this._lineCount = Number.isFinite(nextValue) && nextValue > 0 ? nextValue : 500;
            void this._refreshLogs();
        });

        const autoScroll = this.$('#setting-auto-scroll');
        autoScroll?.addEventListener('change', () => {
            this.setState('logs.autoScroll', !!autoScroll.checked);
            if (autoScroll.checked) {
                this._scrollToBottom();
            }
        });

        const autoRefresh = this.$('#setting-auto-refresh');
        autoRefresh?.addEventListener('change', () => {
            this.setState('logs.autoRefresh', !!autoRefresh.checked);
            this._setupAutoRefresh();
        });

        const wrap = this.$('#setting-wrap');
        wrap?.addEventListener('change', () => {
            const enabled = !!wrap.checked;
            this.setState('logs.wrap', enabled);
            this._updateWrapState(enabled);
        });
    }

    _syncOptionState() {
        const autoScroll = this.$('#setting-auto-scroll');
        const autoRefresh = this.$('#setting-auto-refresh');
        const wrap = this.$('#setting-wrap');
        if (autoScroll) {
            autoScroll.checked = this.getState('logs.autoScroll') !== false;
        }
        if (autoRefresh) {
            autoRefresh.checked = this.getState('logs.autoRefresh') !== false;
        }
        if (wrap) {
            wrap.checked = this.getState('logs.wrap') !== false;
        }
        this._updateWrapState(this.getState('logs.wrap') !== false);
    }

    async _refreshLogs(options = {}) {
        const container = this.$('#log-content');
        const { silent = false } = options;

        if (!this.getState('bot.connected')) {
            this._allLogs = [];
            this._visibleLogs = [];
            if (container) {
                container.textContent = LOG_TEXT.offline;
            }
            this._updateMeta();
            return;
        }

        if (!silent && container) {
            container.textContent = LOG_TEXT.loading;
        }

        try {
            const result = await apiService.getLogs(this._lineCount);
            if (!result?.success) {
                throw new Error(result?.message || LOG_TEXT.loadFailed);
            }

            this._allLogs = Array.isArray(result.logs) ? result.logs : [];
            this._applyFilters();
            this._updateMeta();
            this.emit(Events.LOGS_LOADED, {
                total: this._allLogs.length,
                visible: this._visibleLogs.length,
            });
        } catch (error) {
            console.error('[LogsPage] load failed:', error);
            if (container) {
                container.textContent = toast.getErrorMessage(error, LOG_TEXT.loadFailed);
            }
            if (!silent) {
                toast.error(toast.getErrorMessage(error, LOG_TEXT.loadFailed));
            }
        }
    }

    async _clearLogs() {
        if (!this.getState('bot.connected')) {
            toast.info(LOG_TEXT.offline);
            return;
        }

        try {
            const result = await apiService.clearLogs();
            if (!result?.success) {
                throw new Error(result?.message || LOG_TEXT.clearFailed);
            }
            this._allLogs = [];
            this._visibleLogs = [];
            this._renderLogs();
            this._updateMeta();
            this.emit(Events.LOGS_CLEARED, {});
            toast.success(result?.message || LOG_TEXT.cleared);
        } catch (error) {
            console.error('[LogsPage] clear failed:', error);
            toast.error(toast.getErrorMessage(error, LOG_TEXT.clearFailed));
        }
    }

    async _copyLogs() {
        const content = this._visibleLogs.join('\n');
        if (!content) {
            toast.info(LOG_TEXT.empty);
            return;
        }

        try {
            if (navigator.clipboard?.writeText) {
                await navigator.clipboard.writeText(content);
            } else {
                const textarea = document.createElement('textarea');
                textarea.value = content;
                textarea.setAttribute('readonly', 'readonly');
                textarea.style.position = 'fixed';
                textarea.style.opacity = '0';
                document.body.appendChild(textarea);
                textarea.select();
                document.execCommand('copy');
                textarea.remove();
            }
            toast.success(LOG_TEXT.copied);
        } catch (error) {
            console.error('[LogsPage] copy failed:', error);
            toast.error(LOG_TEXT.copyFailed);
        }
    }

    _exportLogs() {
        const content = this._visibleLogs.join('\n');
        downloadLogTextFile(`wechat-ai-assistant-logs-${Date.now()}.log`, content || '');
        toast.success(LOG_TEXT.exported);
    }

    _applyFilters() {
        const keyword = this._keyword;
        const level = this._level;

        this._visibleLogs = this._allLogs.filter((line) => {
            if (this._isNoiseLine(line)) {
                return false;
            }
            const entry = this._parseLogEntry(line);
            const searchable = `${entry.summary} ${entry.context} ${entry.raw}`.toLowerCase();
            if (keyword && !searchable.includes(keyword)) {
                return false;
            }
            if (level && entry.level !== level) {
                return false;
            }
            return true;
        });

        this._renderLogs();
        this._updateMeta();
    }

    _renderLogs() {
        renderLogList(this, this._allLogs, this._visibleLogs);
        if (this._visibleLogs.length > 0 && this.getState('logs.autoScroll') !== false) {
            this._scrollToBottom();
        }
    }

    _updateMeta() {
        updateLogMeta(this, this._allLogs.length, this._visibleLogs.length);
    }

    _setupAutoRefresh() {
        this._clearRefreshTimer();

        if (
            !this.isActive()
            || this.getState('logs.autoRefresh') === false
            || !this.getState('bot.connected')
        ) {
            return;
        }

        this._refreshTimer = window.setInterval(() => {
            void this._refreshLogs({ silent: true });
        }, 5000);
        this.setState('intervals.logs', this._refreshTimer);
    }

    _clearRefreshTimer() {
        if (this._refreshTimer) {
            clearInterval(this._refreshTimer);
            this._refreshTimer = null;
        }
        this.setState('intervals.logs', null);
    }

    _updateWrapState(enabled) {
        const container = this.$('.log-container');
        container?.classList.toggle('wrap', enabled);
    }

    _scrollToBottom() {
        const container = this.$('#log-content');
        if (!container) {
            return;
        }
        container.scrollTop = container.scrollHeight;
    }

    _isNoiseLine(line) {
        return isNoiseLogLine(line);
    }

    _parseLogEntry(line) {
        return parseLogEntry(line);
    }
}

export default LogsPage;
