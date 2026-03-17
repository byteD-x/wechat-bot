import { PageController } from '../core/PageController.js';
import { Events } from '../core/EventBus.js';
import { apiService } from '../services/ApiService.js';
import { toast } from '../services/NotificationService.js';

const TEXT = {
    loading: '正在加载日志...',
    empty: '暂无日志',
    noMatch: '暂无匹配日志',
    loadFailed: '加载日志失败',
    cleared: '日志已清空',
    clearFailed: '清空日志失败',
    copied: '日志已复制到剪贴板',
    copyFailed: '复制日志失败',
    exported: '日志已导出',
    lines: '行',
    matched: '匹配',
};

const STAGE_SUMMARY = {
    'POLL.RECEIVED': '轮询收到新消息',
    'MERGE.QUEUE': '消息进入合并队列',
    'MERGE.FLUSH': '消息合并完成',
    'MERGE.SKIP': '消息被过滤',
    'MERGE.SKIP_ECHO': '跳过机器人回声',
    'CONV.RECV': '收到消息并进入对话链',
    'CONV.PREPARE_DONE': '对话快路径准备完成',
    'CONV.AI_DONE': '对话生成完成',
    'CONV.SEND_DONE': '微信回复发送完成',
    'CONV.SEND_FAILED': '微信回复发送失败',
    'GROWTH.START': '后台成长任务开始',
    'GROWTH.CONTACT_PROMPT_DONE': '联系人专属 Prompt 更新完成',
    'GROWTH.CONTACT_PROMPT_FAILED': '联系人专属 Prompt 更新失败',
    'GROWTH.EMOTION_DONE': '情绪沉淀完成',
    'GROWTH.EMOTION_FAILED': '情绪沉淀失败',
    'GROWTH.FACTS_DONE': '事实沉淀完成',
    'GROWTH.FACTS_FAILED': '事实沉淀失败',
    'GROWTH.VECTOR_DONE': '向量记忆沉淀完成',
    'GROWTH.VECTOR_FAILED': '向量记忆沉淀失败',
    'GROWTH.EXPORT_RAG_DONE': '导出语料索引同步完成',
    'GROWTH.EXPORT_RAG_FAILED': '导出语料索引同步失败',
    'GROWTH.FAILED': '后台成长任务失败',
    'EVENT.RECEIVED': '收到消息事件',
    'EVENT.PROCESS_START': '开始处理消息',
    'EVENT.SKIP_RESPOND': '当前状态不发送回复',
    'EVENT.SKIP_FILTERED': '消息命中过滤规则',
    'EVENT.SKIP_ECHO': '跳过最近发送回声',
    'EVENT.IMAGE_SAVED': '图片已保存到本地',
    'EVENT.IMAGE_SAVE_FAILED': '图片保存失败',
    'VOICE.TRANSCRIBE_START': '开始语音转文字',
    'VOICE.TRANSCRIBE_DONE': '语音转文字完成',
    'VOICE.TRANSCRIBE_FAILED': '语音转文字失败',
    'CONTROL.MATCHED': '命中控制命令',
    'CONTROL.DONE': '控制命令执行完成',
    'AI.PREPARE_START': '开始准备 AI 请求',
    'AI.PREPARE_DONE': 'AI 请求已准备完成',
    'AI.STREAM_START': '开始流式生成',
    'AI.STREAM_EMPTY_FALLBACK': '流式结果为空，切换普通回复',
    'AI.INVOKE_START': '开始普通生成',
    'AI.INVOKE_DONE': '普通生成完成',
    'AI.REPLY_READY': '回复内容已准备好',
    'AI.REPLY_EMPTY': '回复内容为空',
    'AI.FINALIZE_START': '开始写入记忆与状态',
    'AI.FINALIZE_DONE': '记忆与状态写入完成',
    'AI.FAILED': 'AI 调用失败',
    'SEND.PREPARE': '开始整理待发送回复',
    'SEND.CALL': '开始发送消息',
    'SEND.ATTEMPT': '尝试发送消息',
    'SEND.SUCCESS': '消息发送成功',
    'SEND.FAILED': '消息发送失败',
    'SEND.FALLBACK_CURRENT_CHAT': '改为当前会话窗口发送',
    'SEND.FALLBACK_SUCCESS': '当前会话窗口发送成功',
    'SEND.FALLBACK_FAILED': '当前会话窗口发送失败',
    'SEND.CHUNKS_START': '开始分段发送',
    'SEND.CHUNK_ATTEMPT': '尝试发送分段',
    'SEND.CHUNK_DONE': '分段发送完成',
    'SEND.CHUNK_FAILED': '分段发送失败',
    'SEND.CHUNKS_DONE': '全部分段发送完成',
    'SEND.STREAM_CHUNK': '已发送流式片段',
    'SEND.STREAM_TAIL': '已发送流式尾段',
    'SEND.STREAM_DONE': '流式发送完成',
    'SEND.SUFFIX': '已发送回复后缀',
    'SEND.NATURAL_SEGMENT': '已发送自然分段',
    'SEND.DONE': '回复发送完成',
    'API_SEND.START': '开始通过 API 发送消息',
    'API_SEND.DONE': 'API 发送成功',
    'API_SEND.FAILED': 'API 发送失败',
    'API_SEND.ERROR': 'API 发送异常',
};

const STAGE_LEVEL = {
    'CONV.SEND_FAILED': 'error',
    'GROWTH.CONTACT_PROMPT_FAILED': 'warning',
    'GROWTH.EMOTION_FAILED': 'warning',
    'GROWTH.FACTS_FAILED': 'warning',
    'GROWTH.VECTOR_FAILED': 'warning',
    'GROWTH.EXPORT_RAG_FAILED': 'warning',
    'GROWTH.FAILED': 'warning',
    'SEND.CHUNK_FAILED': 'error',
    'SEND.FAILED': 'error',
    'SEND.FALLBACK_FAILED': 'error',
    'AI.STREAM_EMPTY_FALLBACK': 'warning',
    'AI.REPLY_EMPTY': 'warning',
    'AI.FAILED': 'error',
    'VOICE.TRANSCRIBE_FAILED': 'warning',
    'EVENT.IMAGE_SAVE_FAILED': 'error',
    'EVENT.SKIP_RESPOND': 'warning',
    'EVENT.SKIP_FILTERED': 'warning',
    'MERGE.SKIP': 'warning',
};

const NOISE_LOG_PATTERN = /(127\.0\.0\.1|::1|localhost).*GET \/api\/(status|logs|messages)\b/i;

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

function cleanValue(value) {
    return String(value || '')
        .replace(/^\[|\]$/g, '')
        .replace(/_/g, ' ')
        .trim();
}

function pushUnique(parts, value) {
    const text = cleanValue(value);
    if (!text || parts.includes(text)) {
        return;
    }
    parts.push(text);
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
        const container = this.$('#log-content');
        if (!container) {
            return;
        }

        container.textContent = '';

        if (this._visibleLogs.length === 0) {
            container.textContent = this._allLogs.length === 0 ? TEXT.empty : TEXT.noMatch;
            return;
        }

        const fragment = document.createDocumentFragment();
        for (const line of this._visibleLogs) {
            const entry = this._parseLogEntry(line);
            const item = document.createElement('span');
            item.className = this._getLogClassName(entry.level);
            item.textContent = this._formatDisplayLine(entry);
            item.title = entry.raw;
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

    _isNoiseLine(line) {
        return NOISE_LOG_PATTERN.test(String(line || ''));
    }

    _parseLogEntry(line) {
        const raw = String(line || '').trim();
        const stage = this._extractStage(raw);
        const fields = this._extractStructuredFields(raw, stage);
        const access = this._parseAccessLog(raw);
        const time = this._extractTime(raw);
        const level = this._detectLevel(raw, stage, access);
        return {
            raw,
            stage,
            fields,
            access,
            time,
            level,
            summary: this._buildSummary(raw, stage, access),
            context: this._buildContext(fields, access),
        };
    }

    _extractTime(raw) {
        const match = String(raw || '').match(/(\d{2}:\d{2}:\d{2})/);
        return match ? match[1] : '';
    }

    _extractStage(raw) {
        const matches = [...String(raw || '').matchAll(/\[([A-Z][A-Z0-9_.-]+)\]/g)]
            .map((item) => item[1]);
        return matches.find((item) => item.includes('.')) || '';
    }

    _extractStructuredFields(raw, stage) {
        if (!stage) {
            return {};
        }

        const marker = `[${stage}]`;
        const markerIndex = raw.indexOf(marker);
        if (markerIndex < 0) {
            return {};
        }

        const detail = raw.slice(markerIndex + marker.length).trim();
        const fields = {};
        for (const part of detail.split(' | ')) {
            const index = part.indexOf('=');
            if (index <= 0) {
                continue;
            }
            const key = part.slice(0, index).trim();
            const value = part.slice(index + 1).trim();
            if (key) {
                fields[key] = value;
            }
        }
        return fields;
    }

    _parseAccessLog(raw) {
        const match = String(raw || '').match(
            /\b(GET|POST|PUT|DELETE|PATCH)\s+(\/api\/[^\s]+)\s+[0-9.]+\s+(\d{3})\s+(\d+)\s+(\d+)/
        );
        if (!match) {
            return null;
        }
        return {
            method: match[1],
            path: match[2],
            status: match[3],
            bytes: Number(match[4] || 0),
            durationMs: Number(match[5] || 0),
        };
    }

    _buildSummary(raw, stage, access) {
        if (access) {
            return `接口 ${access.method} ${access.path}`;
        }
        if (stage && STAGE_SUMMARY[stage]) {
            return STAGE_SUMMARY[stage];
        }
        if (raw.includes('HTTP Request: POST')) {
            return '模型接口请求';
        }
        if (raw.toLowerCase().includes('traceback')) {
            return '异常堆栈';
        }
        return raw;
    }

    _buildContext(fields, access) {
        if (access) {
            return `状态 ${access.status} · ${access.durationMs} ms`;
        }

        const parts = [];
        pushUnique(parts, fields.chat || fields.target || fields.chat_id);
        if (fields.sender) {
            pushUnique(parts, `发送者 ${fields.sender}`);
        }
        if (fields.trace) {
            pushUnique(parts, `追踪 ${fields.trace}`);
        }
        if (fields.chunk_index) {
            const total = fields.chunk_total || fields.chunk_count || '';
            pushUnique(parts, total ? `分段 ${fields.chunk_index}/${total}` : `分段 ${fields.chunk_index}`);
        }
        if (fields.segment_index) {
            const total = fields.segment_count || '';
            pushUnique(parts, total ? `自然分段 ${fields.segment_index}/${total}` : `自然分段 ${fields.segment_index}`);
        }
        if (fields.merged_count) {
            pushUnique(parts, `合并 ${fields.merged_count} 条`);
        }
        if (fields.queued) {
            pushUnique(parts, `队列 ${fields.queued}`);
        }
        if (fields.mode) {
            pushUnique(parts, `模式 ${fields.mode}`);
        }
        if (fields.step) {
            pushUnique(parts, `步骤 ${fields.step}`);
        }
        if (fields.receiver) {
            pushUnique(parts, `接收方 ${fields.receiver}`);
        }
        if (fields.deadline_sec) {
            pushUnique(parts, `预算 ${fields.deadline_sec}s`);
        }
        if (fields.duration_ms) {
            pushUnique(parts, `耗时 ${fields.duration_ms} ms`);
        }
        if (fields.emotion) {
            pushUnique(parts, `情绪 ${fields.emotion}`);
        }
        if (fields.reason) {
            pushUnique(parts, `原因 ${fields.reason}`);
        }
        if (fields.error) {
            pushUnique(parts, `错误 ${fields.error}`);
        }
        if (fields.transport_backend) {
            pushUnique(parts, `后端 ${fields.transport_backend}`);
        }
        if (fields.path) {
            pushUnique(parts, fields.path);
        }
        return parts.slice(0, 4).join(' · ');
    }

    _formatDisplayLine(entry) {
        const prefix = entry.time ? `${entry.time}  ` : '';
        if (entry.summary === entry.raw && !entry.context) {
            return `${prefix}${entry.raw}`;
        }
        return [prefix + entry.summary, entry.context].filter(Boolean).join(' | ');
    }

    _detectLevel(raw, stage, access) {
        const content = String(raw || '').toLowerCase();
        if (stage && STAGE_LEVEL[stage]) {
            return STAGE_LEVEL[stage];
        }
        if (content.includes('[error]') || content.includes(' error ') || content.includes('traceback')) {
            return 'error';
        }
        if (content.includes('[warning]') || content.includes(' warning ') || content.includes(' warn ')) {
            return 'warning';
        }
        if (access) {
            const status = Number(access.status || 0);
            if (status >= 500) {
                return 'error';
            }
            if (status >= 400) {
                return 'warning';
            }
            return 'info';
        }
        if (stage.startsWith('SEND.')) {
            return 'send';
        }
        if (stage.startsWith('CONV.')) {
            return stage.endsWith('FAILED') ? 'error' : 'receive';
        }
        if (stage.startsWith('GROWTH.')) {
            return stage.endsWith('FAILED') ? 'warning' : 'info';
        }
        if (stage.startsWith('EVENT.') || stage.startsWith('MERGE.') || stage.startsWith('POLL.')) {
            return 'receive';
        }
        if (stage.startsWith('AI.') || stage.startsWith('VOICE.') || stage.startsWith('CONTROL.')) {
            return 'info';
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
