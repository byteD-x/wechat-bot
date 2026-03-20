export const LOG_TEXT = {
    loading: '\u6b63\u5728\u52a0\u8f7d\u65e5\u5fd7...',
    empty: '\u6682\u65e0\u65e5\u5fd7',
    noMatch: '\u6682\u65e0\u5339\u914d\u65e5\u5fd7',
    loadFailed: '\u52a0\u8f7d\u65e5\u5fd7\u5931\u8d25',
    cleared: '\u65e5\u5fd7\u5df2\u6e05\u7a7a',
    clearFailed: '\u6e05\u7a7a\u65e5\u5fd7\u5931\u8d25',
    copied: '\u65e5\u5fd7\u5df2\u590d\u5236\u5230\u526a\u8d34\u677f',
    copyFailed: '\u590d\u5236\u65e5\u5fd7\u5931\u8d25',
    exported: '\u65e5\u5fd7\u5df2\u5bfc\u51fa',
    lines: '\u884c',
    matched: '\u5339\u914d',
    offline: '\u8bf7\u5148\u542f\u52a8 Python \u670d\u52a1\u540e\u67e5\u770b\u65e5\u5fd7',
    httpRequest: '\u6a21\u578b\u63a5\u53e3\u8bf7\u6c42',
    traceback: '\u5f02\u5e38\u5806\u6808',
};

export const LOG_STAGE_SUMMARY = {
    'POLL.RECEIVED': '\u8f6e\u8be2\u6536\u5230\u65b0\u6d88\u606f',
    'MERGE.QUEUE': '\u6d88\u606f\u8fdb\u5165\u5408\u5e76\u961f\u5217',
    'MERGE.FLUSH': '\u6d88\u606f\u5408\u5e76\u5b8c\u6210',
    'MERGE.SKIP': '\u6d88\u606f\u88ab\u8fc7\u6ee4',
    'MERGE.SKIP_ECHO': '\u8df3\u8fc7\u673a\u5668\u4eba\u56de\u58f0',
    'CONV.RECV': '\u6536\u5230\u6d88\u606f\u5e76\u8fdb\u5165\u5bf9\u8bdd\u94fe',
    'CONV.PREPARE_DONE': '\u5bf9\u8bdd\u5feb\u8def\u5f84\u51c6\u5907\u5b8c\u6210',
    'CONV.AI_DONE': '\u5bf9\u8bdd\u751f\u6210\u5b8c\u6210',
    'CONV.SEND_DONE': '\u5fae\u4fe1\u56de\u590d\u53d1\u9001\u5b8c\u6210',
    'CONV.SEND_FAILED': '\u5fae\u4fe1\u56de\u590d\u53d1\u9001\u5931\u8d25',
    'GROWTH.START': '\u540e\u53f0\u6210\u957f\u4efb\u52a1\u5f00\u59cb',
    'GROWTH.CONTACT_PROMPT_DONE': '\u8054\u7cfb\u4eba\u4e13\u5c5e Prompt \u66f4\u65b0\u5b8c\u6210',
    'GROWTH.CONTACT_PROMPT_FAILED': '\u8054\u7cfb\u4eba\u4e13\u5c5e Prompt \u66f4\u65b0\u5931\u8d25',
    'GROWTH.EMOTION_DONE': '\u60c5\u7eea\u6c89\u6dc0\u5b8c\u6210',
    'GROWTH.EMOTION_FAILED': '\u60c5\u7eea\u6c89\u6dc0\u5931\u8d25',
    'GROWTH.FACTS_DONE': '\u4e8b\u5b9e\u6c89\u6dc0\u5b8c\u6210',
    'GROWTH.FACTS_FAILED': '\u4e8b\u5b9e\u6c89\u6dc0\u5931\u8d25',
    'GROWTH.VECTOR_DONE': '\u5411\u91cf\u8bb0\u5fc6\u6c89\u6dc0\u5b8c\u6210',
    'GROWTH.VECTOR_FAILED': '\u5411\u91cf\u8bb0\u5fc6\u6c89\u6dc0\u5931\u8d25',
    'GROWTH.EXPORT_RAG_DONE': '\u5bfc\u51fa\u8bed\u6599\u7d22\u5f15\u540c\u6b65\u5b8c\u6210',
    'GROWTH.EXPORT_RAG_FAILED': '\u5bfc\u51fa\u8bed\u6599\u7d22\u5f15\u540c\u6b65\u5931\u8d25',
    'GROWTH.FAILED': '\u540e\u53f0\u6210\u957f\u4efb\u52a1\u5931\u8d25',
    'EVENT.RECEIVED': '\u6536\u5230\u6d88\u606f\u4e8b\u4ef6',
    'EVENT.PROCESS_START': '\u5f00\u59cb\u5904\u7406\u6d88\u606f',
    'EVENT.SKIP_RESPOND': '\u5f53\u524d\u72b6\u6001\u4e0d\u53d1\u9001\u56de\u590d',
    'EVENT.SKIP_FILTERED': '\u6d88\u606f\u547d\u4e2d\u8fc7\u6ee4\u89c4\u5219',
    'EVENT.SKIP_ECHO': '\u8df3\u8fc7\u6700\u8fd1\u53d1\u9001\u56de\u58f0',
    'EVENT.IMAGE_SAVED': '\u56fe\u7247\u5df2\u4fdd\u5b58\u5230\u672c\u5730',
    'EVENT.IMAGE_SAVE_FAILED': '\u56fe\u7247\u4fdd\u5b58\u5931\u8d25',
    'VOICE.TRANSCRIBE_START': '\u5f00\u59cb\u8bed\u97f3\u8f6c\u6587\u5b57',
    'VOICE.TRANSCRIBE_DONE': '\u8bed\u97f3\u8f6c\u6587\u5b57\u5b8c\u6210',
    'VOICE.TRANSCRIBE_FAILED': '\u8bed\u97f3\u8f6c\u6587\u5b57\u5931\u8d25',
    'CONTROL.MATCHED': '\u547d\u4e2d\u63a7\u5236\u547d\u4ee4',
    'CONTROL.DONE': '\u63a7\u5236\u547d\u4ee4\u6267\u884c\u5b8c\u6210',
    'AI.PREPARE_START': '\u5f00\u59cb\u51c6\u5907 AI \u8bf7\u6c42',
    'AI.PREPARE_DONE': 'AI \u8bf7\u6c42\u5df2\u51c6\u5907\u5b8c\u6210',
    'AI.STREAM_START': '\u5f00\u59cb\u6d41\u5f0f\u751f\u6210',
    'AI.STREAM_EMPTY_FALLBACK': '\u6d41\u5f0f\u7ed3\u679c\u4e3a\u7a7a\uff0c\u5207\u6362\u666e\u901a\u56de\u590d',
    'AI.INVOKE_START': '\u5f00\u59cb\u666e\u901a\u751f\u6210',
    'AI.INVOKE_DONE': '\u666e\u901a\u751f\u6210\u5b8c\u6210',
    'AI.REPLY_READY': '\u56de\u590d\u5185\u5bb9\u5df2\u51c6\u5907\u597d',
    'AI.REPLY_EMPTY': '\u56de\u590d\u5185\u5bb9\u4e3a\u7a7a',
    'AI.FINALIZE_START': '\u5f00\u59cb\u5199\u5165\u8bb0\u5fc6\u4e0e\u72b6\u6001',
    'AI.FINALIZE_DONE': '\u8bb0\u5fc6\u4e0e\u72b6\u6001\u5199\u5165\u5b8c\u6210',
    'AI.FAILED': 'AI \u8c03\u7528\u5931\u8d25',
    'SEND.PREPARE': '\u5f00\u59cb\u6574\u7406\u5f85\u53d1\u9001\u56de\u590d',
    'SEND.CALL': '\u5f00\u59cb\u53d1\u9001\u6d88\u606f',
    'SEND.ATTEMPT': '\u5c1d\u8bd5\u53d1\u9001\u6d88\u606f',
    'SEND.SUCCESS': '\u6d88\u606f\u53d1\u9001\u6210\u529f',
    'SEND.FAILED': '\u6d88\u606f\u53d1\u9001\u5931\u8d25',
    'SEND.FALLBACK_CURRENT_CHAT': '\u6539\u4e3a\u5f53\u524d\u4f1a\u8bdd\u7a97\u53e3\u53d1\u9001',
    'SEND.FALLBACK_SUCCESS': '\u5f53\u524d\u4f1a\u8bdd\u7a97\u53e3\u53d1\u9001\u6210\u529f',
    'SEND.FALLBACK_FAILED': '\u5f53\u524d\u4f1a\u8bdd\u7a97\u53e3\u53d1\u9001\u5931\u8d25',
    'SEND.CHUNKS_START': '\u5f00\u59cb\u5206\u6bb5\u53d1\u9001',
    'SEND.CHUNK_ATTEMPT': '\u5c1d\u8bd5\u53d1\u9001\u5206\u6bb5',
    'SEND.CHUNK_DONE': '\u5206\u6bb5\u53d1\u9001\u5b8c\u6210',
    'SEND.CHUNK_FAILED': '\u5206\u6bb5\u53d1\u9001\u5931\u8d25',
    'SEND.CHUNKS_DONE': '\u5168\u90e8\u5206\u6bb5\u53d1\u9001\u5b8c\u6210',
    'SEND.STREAM_CHUNK': '\u5df2\u53d1\u9001\u6d41\u5f0f\u7247\u6bb5',
    'SEND.STREAM_TAIL': '\u5df2\u53d1\u9001\u6d41\u5f0f\u5c3e\u6bb5',
    'SEND.STREAM_DONE': '\u6d41\u5f0f\u53d1\u9001\u5b8c\u6210',
    'SEND.SUFFIX': '\u5df2\u53d1\u9001\u56de\u590d\u540e\u7f00',
    'SEND.NATURAL_SEGMENT': '\u5df2\u53d1\u9001\u81ea\u7136\u5206\u6bb5',
    'SEND.DONE': '\u56de\u590d\u53d1\u9001\u5b8c\u6210',
    'API_SEND.START': '\u5f00\u59cb\u901a\u8fc7 API \u53d1\u9001\u6d88\u606f',
    'API_SEND.DONE': 'API \u53d1\u9001\u6210\u529f',
    'API_SEND.FAILED': 'API \u53d1\u9001\u5931\u8d25',
    'API_SEND.ERROR': 'API \u53d1\u9001\u5f02\u5e38',
};

export const LOG_STAGE_LEVEL = {
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

export function formatLogNow(date = new Date()) {
    return new Intl.DateTimeFormat('zh-CN', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
    }).format(date);
}

export function downloadLogTextFile(filename, content) {
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

export function isNoiseLogLine(line) {
    return NOISE_LOG_PATTERN.test(String(line || ''));
}

export function parseLogEntry(line) {
    const raw = String(line || '').trim();
    const stage = extractLogStage(raw);
    const fields = extractStructuredFields(raw, stage);
    const access = parseAccessLog(raw);
    const time = extractLogTime(raw);
    const level = detectLogLevel(raw, stage, access);
    return {
        raw,
        stage,
        fields,
        access,
        time,
        level,
        summary: buildLogSummary(raw, stage, access),
        context: buildLogContext(fields, access),
    };
}

export function formatLogDisplayLine(entry) {
    const prefix = entry.time ? `${entry.time}  ` : '';
    if (entry.summary === entry.raw && !entry.context) {
        return `${prefix}${entry.raw}`;
    }
    return [prefix + entry.summary, entry.context].filter(Boolean).join(' | ');
}

export function getLogClassName(level) {
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

function cleanLogValue(value) {
    return String(value || '')
        .replace(/^\[|\]$/g, '')
        .replace(/_/g, ' ')
        .trim();
}

function pushUniqueLogPart(parts, value) {
    const text = cleanLogValue(value);
    if (!text || parts.includes(text)) {
        return;
    }
    parts.push(text);
}

function extractLogTime(raw) {
    const match = String(raw || '').match(/(\d{2}:\d{2}:\d{2})/);
    return match ? match[1] : '';
}

function extractLogStage(raw) {
    const matches = [...String(raw || '').matchAll(/\[([A-Z][A-Z0-9_.-]+)\]/g)]
        .map((item) => item[1]);
    return matches.find((item) => item.includes('.')) || '';
}

function extractStructuredFields(raw, stage) {
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

function parseAccessLog(raw) {
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

function buildLogSummary(raw, stage, access) {
    if (access) {
        return `\u63a5\u53e3 ${access.method} ${access.path}`;
    }
    if (stage && LOG_STAGE_SUMMARY[stage]) {
        return LOG_STAGE_SUMMARY[stage];
    }
    if (raw.includes('HTTP Request: POST')) {
        return LOG_TEXT.httpRequest;
    }
    if (raw.toLowerCase().includes('traceback')) {
        return LOG_TEXT.traceback;
    }
    return raw;
}

function buildLogContext(fields, access) {
    if (access) {
        return `\u72b6\u6001 ${access.status} \u00b7 ${access.durationMs} ms`;
    }

    const parts = [];
    pushUniqueLogPart(parts, fields.chat || fields.target || fields.chat_id);
    if (fields.sender) {
        pushUniqueLogPart(parts, `\u53d1\u9001\u8005 ${fields.sender}`);
    }
    if (fields.trace) {
        pushUniqueLogPart(parts, `\u8ffd\u8e2a ${fields.trace}`);
    }
    if (fields.chunk_index) {
        const total = fields.chunk_total || fields.chunk_count || '';
        pushUniqueLogPart(parts, total ? `\u5206\u6bb5 ${fields.chunk_index}/${total}` : `\u5206\u6bb5 ${fields.chunk_index}`);
    }
    if (fields.segment_index) {
        const total = fields.segment_count || '';
        pushUniqueLogPart(parts, total ? `\u81ea\u7136\u5206\u6bb5 ${fields.segment_index}/${total}` : `\u81ea\u7136\u5206\u6bb5 ${fields.segment_index}`);
    }
    if (fields.merged_count) {
        pushUniqueLogPart(parts, `\u5408\u5e76 ${fields.merged_count} \u6761`);
    }
    if (fields.queued) {
        pushUniqueLogPart(parts, `\u961f\u5217 ${fields.queued}`);
    }
    if (fields.mode) {
        pushUniqueLogPart(parts, `\u6a21\u5f0f ${fields.mode}`);
    }
    if (fields.step) {
        pushUniqueLogPart(parts, `\u6b65\u9aa4 ${fields.step}`);
    }
    if (fields.receiver) {
        pushUniqueLogPart(parts, `\u63a5\u6536\u65b9 ${fields.receiver}`);
    }
    if (fields.deadline_sec) {
        pushUniqueLogPart(parts, `\u9884\u7b97 ${fields.deadline_sec}s`);
    }
    if (fields.duration_ms) {
        pushUniqueLogPart(parts, `\u8017\u65f6 ${fields.duration_ms} ms`);
    }
    if (fields.emotion) {
        pushUniqueLogPart(parts, `\u60c5\u7eea ${fields.emotion}`);
    }
    if (fields.reason) {
        pushUniqueLogPart(parts, `\u539f\u56e0 ${fields.reason}`);
    }
    if (fields.error) {
        pushUniqueLogPart(parts, `\u9519\u8bef ${fields.error}`);
    }
    if (fields.transport_backend) {
        pushUniqueLogPart(parts, `\u540e\u7aef ${fields.transport_backend}`);
    }
    if (fields.path) {
        pushUniqueLogPart(parts, fields.path);
    }
    return parts.slice(0, 4).join(' \u00b7 ');
}

function detectLogLevel(raw, stage, access) {
    const content = String(raw || '').toLowerCase();
    if (stage && LOG_STAGE_LEVEL[stage]) {
        return LOG_STAGE_LEVEL[stage];
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
