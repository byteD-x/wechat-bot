function isPlainObject(value) {
    return !!value && typeof value === 'object' && !Array.isArray(value);
}

function isSensitiveKey(key = '') {
    const normalized = String(key || '').trim().toLowerCase();
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
        || normalized.endsWith('_token')
        || normalized.endsWith('_secret')
        || normalized.endsWith('_key')
    );
}

const LOG_SECRET_PATTERNS = [
    /(authorization\s*:\s*bearer\s+)[^\s"']+/ig,
    /((?:api[_-]?key|token|secret|password)\s*[=:]\s*)[^\s,;]+/ig,
];

function sanitizeLogLine(value) {
    let text = String(value || '');
    LOG_SECRET_PATTERNS.forEach((pattern) => {
        text = text.replace(pattern, '$1***');
    });
    return text;
}

function sanitizeSnapshotPayload(value) {
    if (Array.isArray(value)) {
        return value.map((item) => sanitizeSnapshotPayload(item));
    }

    if (!isPlainObject(value)) {
        return value;
    }

    const nextValue = {};
    for (const [key, item] of Object.entries(value)) {
        if (isSensitiveKey(key)) {
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

module.exports = {
    buildDiagnosticsSnapshot,
    buildSnapshotFilename,
    sanitizeSnapshotPayload,
};
