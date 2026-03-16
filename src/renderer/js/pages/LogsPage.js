import { PageController } from '../core/PageController.js';
import { Events } from '../core/EventBus.js';
import { apiService } from '../services/ApiService.js';
import { toast } from '../services/NotificationService.js';

const TEXT = {
    loading: '\u6b63\u5728\u52a0\u8f7d\u65e5\u5fd7...',
    empty: '\u6682\u65e0\u65e5\u5fd7',
    loadFailed: '\u52a0\u8f7d\u65e5\u5fd7\u5931\u8d25',
    cleared: '\u65e5\u5fd7\u5df2\u6e05\u7a7a',
    clearFailed: '\u6e05\u7a7a\u65e5\u5fd7\u5931\u8d25',
    copied: '\u65e5\u5fd7\u5df2\u590d\u5236\u5230\u526a\u8d34\u677f',
    copyFailed: '\u590d\u5236\u65e5\u5fd7\u5931\u8d25',
    exported: '\u65e5\u5fd7\u5df2\u5bfc\u51fa',
    lines: '\u884c',
    matched: '\u5339\u914d',
    updated: '\u521a\u521a',
};

function formatNow(date = new Date()) {
    return new Intl.DateTimeFormat('zh-CN', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
    }).format(date);
}

function downloadTextFile(filename, content) {
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 0);
}

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
            this._updateWrapState(!!wrap.checked);
        });
    }

    _syncOptionState() {
        const autoScroll = this.$('#setting-auto-scroll');
        const autoRefresh = this.$('#setting-auto-refresh');
        if (autoScroll) {
            autoScroll.checked = this.getState('logs.autoScroll') !== false;
        }
        if (autoRefresh) {
            autoRefresh.checked = this.getState('logs.autoRefresh') !== false;
        }
        this._updateWrapState(!!this.$('#setting-wrap')?.checked);
    }

    async _refreshLogs(options = {}) {
        const container = this.$('#log-content');
        const { silent = false } = options;

        if (!silent && container) {
            container.textContent = TEXT.loading;
        }

        try {
            const result = await apiService.getLogs(this._lineCount);
            if (!result?.success) {
                throw new Error(result?.message || TEXT.loadFailed);
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
                container.textContent = toast.getErrorMessage(error, TEXT.loadFailed);
            }
            if (!silent) {
                toast.error(toast.getErrorMessage(error, TEXT.loadFailed));
            }
        }
    }

    async _clearLogs() {
        try {
            const result = await apiService.clearLogs();
            if (!result?.success) {
                throw new Error(result?.message || TEXT.clearFailed);
            }
            this._allLogs = [];
            this._visibleLogs = [];
            this._renderLogs();
            this._updateMeta();
            this.emit(Events.LOGS_CLEARED, {});
            toast.success(result?.message || TEXT.cleared);
        } catch (error) {
            console.error('[LogsPage] clear failed:', error);
            toast.error(toast.getErrorMessage(error, TEXT.clearFailed));
        }
    }

    async _copyLogs() {
        const content = this._visibleLogs.join('\n');
        if (!content) {
            toast.info(TEXT.empty);
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
            toast.success(TEXT.copied);
        } catch (error) {
            console.error('[LogsPage] copy failed:', error);
            toast.error(TEXT.copyFailed);
        }
    }

    _exportLogs() {
        const content = this._visibleLogs.join('\n');
        downloadTextFile(`wechat-ai-assistant-logs-${Date.now()}.log`, content || '');
        toast.success(TEXT.exported);
    }

    _applyFilters() {
        const keyword = this._keyword;
        const level = this._level;

        this._visibleLogs = this._allLogs.filter((line) => {
            const content = String(line || '');
            const lower = content.toLowerCase();
            if (keyword && !lower.includes(keyword)) {
                return false;
            }
            if (level) {
                const detected = this._getLogLevel(content);
                if (detected !== level) {
                    return false;
                }
            }
            return true;
        });

        this._renderLogs();
        this._updateMeta();
    }

    _renderLogs() {
        const container = this.$('#log-content');
        if (!container) {
            return;
        }

        container.textContent = '';

        if (this._visibleLogs.length === 0) {
            container.textContent = this._allLogs.length === 0 ? TEXT.empty : '\u6682\u65e0\u5339\u914d\u65e5\u5fd7';
            return;
        }

        const fragment = document.createDocumentFragment();
        for (const line of this._visibleLogs) {
            const item = document.createElement('span');
            const level = this._getLogLevel(line);
            item.className = this._getLogClassName(level);
            item.textContent = String(line);
            fragment.appendChild(item);
        }

        container.appendChild(fragment);
        if (this.getState('logs.autoScroll') !== false) {
            this._scrollToBottom();
        }
    }

    _updateMeta() {
        const total = this.$('#log-count');
        const visible = this.$('#log-visible-count');
        const updated = this.$('#log-updated');

        if (total) {
            total.textContent = `${this._allLogs.length} ${TEXT.lines}`;
        }
        if (visible) {
            visible.textContent = `${this._visibleLogs.length} ${TEXT.matched}`;
        }
        if (updated) {
            updated.textContent = this._allLogs.length > 0 ? formatNow() : '--';
        }
    }

    _setupAutoRefresh() {
        this._clearRefreshTimer();

        if (!this.isActive() || this.getState('logs.autoRefresh') === false) {
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

    _getLogLevel(line) {
        const content = String(line || '').toLowerCase();
        if (content.includes('[error]') || content.includes(' error ') || content.includes('traceback')) {
            return 'error';
        }
        if (content.includes('[warning]') || content.includes(' warning ') || content.includes(' warn ')) {
            return 'warning';
        }
        if (content.includes('[send]') || content.includes(' send ')) {
            return 'send';
        }
        if (content.includes('[receive]') || content.includes(' receive ') || content.includes(' recv ')) {
            return 'receive';
        }
        if (content.includes('[info]') || content.includes(' info ')) {
            return 'info';
        }
        return 'default';
    }

    _getLogClassName(level) {
        switch (level) {
        case 'error':
            return 'log-error';
        case 'warning':
            return 'log-warning';
        case 'send':
            return 'log-send';
        case 'receive':
            return 'log-receive';
        case 'info':
            return 'log-info';
        default:
            return '';
        }
    }
}

export default LogsPage;
