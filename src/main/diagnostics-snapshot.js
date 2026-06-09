function isPlainObject(value) {
    return !!value && typeof value === 'object' && !Array.isArray(value);
}

const REDACTION = Object.freeze({
    sensitiveValue: '[redacted: sensitive value]',
    chatContent: '[redacted: chat content]',
    contactIdentifier: '[redacted: contact identifier]',
    localPath: '[redacted: local path]',
});

function normalizeKey(key = '') {
    return String(key || '').trim().toLowerCase();
}

function isSensitiveKey(key = '') {
    const normalized = normalizeKey(key);
    if (!normalized) {
        return false;
    }

    const safeKeys = new Set([
        'api_key_configured',
        'api_key_masked',
        'api_key_required',
        'langsmith_api_key_configured',
    ]);
    if (safeKeys.has(normalized)) {
        return false;
    }

    return (
        normalized === 'token'
        || normalized === 'api_token'
        || normalized === 'authtoken'
        || normalized === 'authorization'
        || normalized === 'secret'
        || normalized === 'password'
        || normalized === 'passwd'
        || normalized === 'credential'
        || normalized === 'credentials'
        || normalized === 'cookie'
        || normalized === 'session'
        || normalized === 'oauth'
        || normalized === 'client_secret'
        || normalized === 'access_token'
        || normalized === 'refresh_token'
        || normalized === 'id_token'
        || normalized.endsWith('_token')
        || normalized.endsWith('_secret')
        || normalized.endsWith('_key')
        || normalized.endsWith('_password')
        || normalized.endsWith('_credential')
        || normalized.endsWith('_credentials')
        || normalized.endsWith('_cookie')
        || normalized.endsWith('_session')
        || normalized.startsWith('oauth_')
    );
}

function isChatContentKey(key = '') {
    const normalized = normalizeKey(key);
    return new Set([
        'content',
        'raw_content',
        'message_content',
        'message_text',
        'chat_content',
        'chat_text',
        'user_text',
        'reply_text',
        'assistant_reply',
        'last_message',
        'latest_message',
        'message_preview',
        'messages',
        'recent_messages',
        'conversation',
        'chat_history',
        'history_messages',
        'prompt',
        'system_prompt',
    ]).has(normalized);
}

function isContactIdentifierKey(key = '') {
    const normalized = normalizeKey(key);
    return new Set([
        'chat_id',
        'chat_ids',
        'roomid',
        'room_id',
        'wxid',
        'wx_id',
        'sender',
        'sender_id',
        'receiver',
        'receiver_id',
        'from_user',
        'to_user',
        'contact_id',
        'contact_name',
        'contact_display_name',
        'display_name',
        'nickname',
        'remark',
        'alias',
        'user_id',
    ]).has(normalized);
}

function isPathKey(key = '') {
    const normalized = normalizeKey(key);
    return new Set([
        'path',
        'file_path',
        'filepath',
        'file',
        'dir',
        'directory',
        'output_dir',
        'downloadedinstallerpath',
        'downloaded_installer_path',
        'data_path',
        'db_path',
        'config_path',
        'base_path',
        'log_file',
        'memory_db_path',
        'sqlite_db_path',
        'vector_memory_db_path',
        'export_rag_dir',
    ]).has(normalized)
        || normalized.endsWith('_path')
        || normalized.endsWith('_dir')
        || normalized.endsWith('_file');
}

const LOG_SECRET_PATTERNS = [
    /(authorization\s*:\s*bearer\s+)[^\s"']+/ig,
    /((?:api[_-]?key|token|secret|password)\s*[=:]\s*)[^\s,;]+/ig,
    /((?:content|raw_content|message_content|user_text|reply_text|chat_text)\s*[=:]\s*)("[^"]*"|'[^']*'|[^\s,;]+)/ig,
    /((?:发送了|收到消息|消息内容|聊天正文|原文|正文)\s*[:：]\s*)[^\r\n]+/g,
    /\bwxid_[a-z0-9_-]+\b/ig,
    /\b[a-z0-9_-]+@chatroom\b/ig,
];

const LOCAL_PATH_PATTERNS = [
    /\b[A-Za-z]:\\(?:[^\\/:*?"<>|\r\n]+\\)*[^\\/:*?"<>|\s\r\n]*/g,
    /\b[A-Za-z]:\/(?:[^/:"<>|\s\r\n]+\/)*[^/:"<>|\s\r\n]*/g,
    /(^|[\s"'(])\/(?:Users|home|var|tmp|private|mnt|Volumes|opt|etc)\/[^\s"',;)]+/g,
];

function redactLocalPaths(value) {
    let text = String(value || '');
    text = text.replace(LOCAL_PATH_PATTERNS[0], REDACTION.localPath);
    text = text.replace(LOCAL_PATH_PATTERNS[1], REDACTION.localPath);
    text = text.replace(
        LOCAL_PATH_PATTERNS[2],
        (_match, prefix = '') => `${prefix}${REDACTION.localPath}`,
    );
    return text;
}

function sanitizeLogLine(value) {
    let text = String(value || '');
    LOG_SECRET_PATTERNS.forEach((pattern) => {
        text = text.replace(pattern, (...args) => {
            if (args.length > 2 && typeof args[1] === 'string') {
                return `${args[1]}${REDACTION.sensitiveValue}`;
            }
            return REDACTION.contactIdentifier;
        });
    });
    return redactLocalPaths(text);
}

function sanitizePathPayload(value) {
    if (typeof value === 'string') {
        return sanitizeLogLine(value);
    }
    if (Array.isArray(value)) {
        return value.map((item) => sanitizePathPayload(item));
    }
    if (isPlainObject(value)) {
        const nextValue = {};
        for (const [key, item] of Object.entries(value)) {
            nextValue[key] = sanitizePathPayload(item);
        }
        return nextValue;
    }
    return value;
}

function sanitizeSnapshotPayload(value) {
    if (Array.isArray(value)) {
        return value.map((item) => sanitizeSnapshotPayload(item));
    }

    if (typeof value === 'string') {
        return sanitizeLogLine(value);
    }

    if (!isPlainObject(value)) {
        return value;
    }

    const nextValue = {};
    for (const [key, item] of Object.entries(value)) {
        if (isSensitiveKey(key)) {
            continue;
        }
        if (isChatContentKey(key)) {
            nextValue[key] = REDACTION.chatContent;
            continue;
        }
        if (isContactIdentifierKey(key)) {
            nextValue[key] = REDACTION.contactIdentifier;
            continue;
        }
        if (isPathKey(key)) {
            nextValue[key] = sanitizePathPayload(item);
            continue;
        }
        nextValue[key] = sanitizeSnapshotPayload(item);
    }
    return nextValue;
}

function pickSafeConfig(configPayload = {}) {
    return {
        api: configPayload.api || {},
        bot: configPayload.bot || {},
        logging: configPayload.logging || {},
        agent: configPayload.agent || {},
        services: configPayload.services || {},
    };
}

function normalizeBackendProcessIssue(issue = null) {
    if (!isPlainObject(issue)) {
        return null;
    }
    const happenedAt = String(issue.happenedAt || issue.happened_at || '').trim();
    const codeValue = issue.code;
    const code = codeValue === null || codeValue === undefined || codeValue === ''
        ? null
        : Number(codeValue);
    return {
        type: String(issue.type || 'backend_process_issue').trim() || 'backend_process_issue',
        reason: String(issue.reason || '').trim(),
        code: Number.isFinite(code) ? code : null,
        signal: issue.signal ? String(issue.signal).trim() : null,
        happened_at: happenedAt || null,
    };
}

function buildSnapshotFilename(now = new Date()) {
    const date = now instanceof Date ? now : new Date(now);
    const yyyy = String(date.getFullYear());
    const mm = String(date.getMonth() + 1).padStart(2, '0');
    const dd = String(date.getDate()).padStart(2, '0');
    const hh = String(date.getHours()).padStart(2, '0');
    const mi = String(date.getMinutes()).padStart(2, '0');
    const ss = String(date.getSeconds()).padStart(2, '0');
    return `wechat-ai-assistant-diagnostics-${yyyy}${mm}${dd}-${hh}${mi}${ss}.json`;
}

function buildDiagnosticId(now = new Date(), randomSource = Math.random) {
    const date = now instanceof Date ? now : new Date(now);
    const yyyy = String(date.getFullYear());
    const mm = String(date.getMonth() + 1).padStart(2, '0');
    const dd = String(date.getDate()).padStart(2, '0');
    const hh = String(date.getHours()).padStart(2, '0');
    const mi = String(date.getMinutes()).padStart(2, '0');
    const ss = String(date.getSeconds()).padStart(2, '0');
    const randomValue = Number(randomSource());
    const suffix = Math.abs(Math.floor((Number.isFinite(randomValue) ? randomValue : 0) * 0xffffffff))
        .toString(16)
        .padStart(8, '0')
        .slice(0, 8);
    return `diag-${yyyy}${mm}${dd}-${hh}${mi}${ss}-${suffix}`;
}

function buildSupportPackageFilename(diagnosticId = '', now = new Date()) {
    const safeId = String(diagnosticId || buildDiagnosticId(now))
        .trim()
        .toLowerCase()
        .replace(/[^a-z0-9-]+/g, '-')
        .replace(/^-+|-+$/g, '');
    return `wechat-ai-assistant-support-${safeId || buildDiagnosticId(now)}.json`;
}

function buildSupportPackageManifest({
    diagnosticId,
    generatedAt,
    appName,
    appVersion,
} = {}) {
    return {
        schema_version: 1,
        package_type: 'diagnostics_support_package',
        diagnostic_id: diagnosticId,
        generated_at: generatedAt,
        app: {
            name: appName || 'wechat-ai-assistant',
            version: String(appVersion || ''),
        },
        export_mode: 'local_json',
        automatic_upload: false,
        full_logs_included: false,
        sections: [
            {
                json_pointer: '/manifest',
                description: 'Package identity, schema, section list, and local-only export flags.',
            },
            {
                json_pointer: '/privacy_notice',
                description: 'Redaction policy, sensitive data warning, and log authorization boundary.',
            },
            {
                json_pointer: '/field_reference',
                description: 'Human-readable notes for the main diagnostic fields.',
            },
            {
                json_pointer: '/support_request_template',
                description: 'Copyable support request template that references the local Diagnostic ID.',
            },
            {
                json_pointer: '/snapshot',
                description: 'Redacted runtime, readiness, config audit, update, backup, and sampled log data.',
            },
        ],
    };
}

function buildPrivacyNotice() {
    return {
        local_only: true,
        automatic_upload: false,
        user_preview_required: true,
        full_logs_included: false,
        full_logs_note: 'Full raw logs are not included. Export or share full logs only after separate explicit authorization.',
        redacted_categories: [
            'API keys, tokens, secrets, passwords, cookies, OAuth and session values',
            'Raw chat message bodies and prompt-like message content fields',
            'Contact names, WeChat IDs, room IDs, sender and receiver identifiers',
            'Complete local filesystem paths',
        ],
        warning: 'Review this local JSON before sharing. Do not attach chat exports, databases, full logs, or credentials unless support explicitly asks and you approve.',
    };
}

function buildFieldReference() {
    return {
        diagnostic_id: 'Local identifier for matching this file with a support request. It is not uploaded automatically.',
        manifest: 'Support package schema, generated time, export mode, and included sections.',
        privacy_notice: 'Privacy boundary and redaction categories applied before writing the file.',
        support_request_template: 'Template text the user can copy into an issue or support conversation.',
        'snapshot.app': 'Application name, version, platform, and architecture.',
        'snapshot.runtime': 'Backend status, readiness, idle state, health checks, and diagnostics summary.',
        'snapshot.update': 'Updater state and checksum summary with local installer paths redacted.',
        'snapshot.operations.backup': 'Recent backup and restore summary without backup file contents.',
        'snapshot.config.audit': 'Configuration audit result from the backend.',
        'snapshot.config.effective': 'Selected safe config sections with credentials removed and masked/configured flags kept.',
        'snapshot.logs': 'Small sampled log excerpt with secret, contact, chat-content, and local-path redaction. Full logs are excluded.',
        'snapshot.collection_errors': 'Collection failures encountered while building the package.',
    };
}

function buildSupportRequestTemplate({
    diagnosticId,
    generatedAt,
    appVersion,
} = {}) {
    return {
        subject: `[wechat-ai-assistant] Support request ${diagnosticId}`,
        body: [
            `Diagnostic ID: ${diagnosticId}`,
            `Generated at: ${generatedAt}`,
            `App version: ${appVersion || '<unknown>'}`,
            '',
            'Problem summary:',
            '- ',
            '',
            'Steps already tried:',
            '- ',
            '',
            'Expected result:',
            '- ',
            '',
            'Actual result:',
            '- ',
            '',
            'Privacy confirmation:',
            '- I reviewed the local diagnostics support package before sharing.',
            '- I did not attach full logs, chat exports, databases, or credentials unless separately authorized.',
        ].join('\n'),
    };
}

function buildDiagnosticsSnapshot({
    appVersion = '',
    appName = 'wechat-ai-assistant',
    now = new Date(),
    status = null,
    readiness = null,
    configAudit = null,
    configPayload = {},
    logs = [],
    updateState = {},
    backupSummary = null,
    idleState = {},
    backendProcessIssue = null,
    platform = {},
    collectionErrors = [],
} = {}) {
    const timestamp = now instanceof Date ? now.toISOString() : new Date(now).toISOString();
    const payload = {
        generated_at: timestamp,
        app: {
            name: appName,
            version: appVersion,
            platform,
        },
        runtime: {
            status,
            readiness,
            idle_state: idleState,
            backend_process_issue: normalizeBackendProcessIssue(backendProcessIssue),
        },
        update: {
            ...(updateState || {}),
            integrity: {
                checksum_verified: !!updateState?.checksumVerified,
                checksum_expected: String(updateState?.checksumExpected || ''),
                checksum_actual: String(updateState?.checksumActual || ''),
                downloaded_version: String(updateState?.downloadedVersion || ''),
            },
        },
        operations: {
            backup: {
                latest_quick_backup_at: backupSummary?.latest_quick_backup_at ?? null,
                latest_full_backup_at: backupSummary?.latest_full_backup_at ?? null,
                last_restore_result: backupSummary?.last_restore_result || null,
            },
        },
        config: {
            audit: configAudit,
            effective: pickSafeConfig(configPayload),
        },
        logs: Array.isArray(logs) ? logs.slice(0, 200).map((item) => sanitizeLogLine(item)) : [],
        collection_errors: Array.isArray(collectionErrors)
            ? collectionErrors.filter(Boolean).map((item) => String(item))
            : [],
    };
    return sanitizeSnapshotPayload(payload);
}

function buildDiagnosticsSupportPackage(options = {}) {
    const now = options.now || new Date();
    const generatedAt = now instanceof Date ? now.toISOString() : new Date(now).toISOString();
    const diagnosticId = String(options.diagnosticId || buildDiagnosticId(now)).trim();
    const appName = options.appName || 'wechat-ai-assistant';
    const appVersion = options.appVersion || '';
    const snapshot = buildDiagnosticsSnapshot({
        ...options,
        appName,
        appVersion,
        now,
    });

    return sanitizeSnapshotPayload({
        diagnostic_id: diagnosticId,
        generated_at: generatedAt,
        manifest: buildSupportPackageManifest({
            diagnosticId,
            generatedAt,
            appName,
            appVersion,
        }),
        privacy_notice: buildPrivacyNotice(),
        field_reference: buildFieldReference(),
        support_request_template: buildSupportRequestTemplate({
            diagnosticId,
            generatedAt,
            appVersion,
        }),
        snapshot,
    });
}

module.exports = {
    buildDiagnosticId,
    buildDiagnosticsSnapshot,
    buildDiagnosticsSupportPackage,
    buildSnapshotFilename,
    buildSupportPackageFilename,
    sanitizeSnapshotPayload,
};
