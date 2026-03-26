const FIRST_RUN_FOCUS_KEYS = [
    'admin_permission',
    'wechat_process',
    'wechat_compatibility',
    'api_config',
];

function toTrimmedString(value, fallback = '') {
    const text = String(value ?? '').trim();
    return text || fallback;
}

function buildSummary(ready, blockingCount, summary = {}) {
    const title = toTrimmedString(summary?.title);
    const detail = toTrimmedString(summary?.detail);

    if (title && detail) {
        return { title, detail };
    }

    if (ready) {
        return {
            title: title || '运行准备已通过',
            detail: detail || '环境与配置检查均已通过，可以直接启动机器人。',
        };
    }

    return {
        title: title || `还有 ${blockingCount} 项准备未完成`,
        detail: detail || '先处理这些阻塞项，再启动机器人会更稳妥。',
    };
}

function normalizeActionName(action = '', key = '') {
    const nextAction = toTrimmedString(action, '');
    if (nextAction) {
        return nextAction;
    }
    if (key === 'admin_permission') {
        return 'restart_as_admin';
    }
    return 'retry';
}

function getDefaultActionLabel(action, key = '') {
    if (action === 'open_settings') {
        return '前往设置';
    }
    if (action === 'open_wechat') {
        return '打开微信';
    }
    if (action === 'restart_as_admin' || key === 'admin_permission') {
        return '以管理员身份重启';
    }
    return '重新检查';
}

function normalizeAction(action = {}, index = 0) {
    const sourceCheck = toTrimmedString(action?.source_check, '');
    const nextAction = normalizeActionName(action?.action, sourceCheck);
    const defaultLabel = getDefaultActionLabel(nextAction, sourceCheck);
    return {
        key: `${nextAction || 'action'}:${index}`,
        action: nextAction,
        label: nextAction === 'restart_as_admin'
            ? defaultLabel
            : toTrimmedString(action?.label, defaultLabel),
        sourceCheck,
    };
}

function normalizeCheck(check = {}, index = 0) {
    const status = ['passed', 'failed', 'skipped'].includes(check?.status)
        ? check.status
        : 'skipped';
    const key = toTrimmedString(check?.key, `check_${index}`);
    const action = normalizeActionName(check?.action, key);
    const defaultActionLabel = getDefaultActionLabel(action, key);
    return {
        key,
        label: toTrimmedString(check?.label, '环境检查'),
        status,
        blocking: Boolean(check?.blocking && status === 'failed'),
        message: toTrimmedString(check?.message, '暂无更多信息'),
        hint: toTrimmedString(check?.hint, ''),
        action,
        actionLabel: action === 'restart_as_admin'
            ? defaultActionLabel
            : toTrimmedString(check?.action_label, defaultActionLabel),
    };
}

function buildUnavailableReport(detail = '') {
    return {
        success: false,
        ready: false,
        blockingCount: 1,
        checkedAt: 0,
        summary: {
            title: '暂时无法读取运行准备度',
            detail: toTrimmedString(detail, '本地服务暂时不可用，请稍后重新检查。'),
        },
        checks: [
            {
                key: 'service_unavailable',
                label: '本地服务',
                status: 'failed',
                blocking: true,
                message: toTrimmedString(detail, '未能连接本地服务，请稍后重新检查。'),
                hint: '如果问题持续存在，请查看日志页，或导出诊断快照后再排查。',
                action: 'retry',
                actionLabel: '重新检查',
            },
        ],
        suggestedActions: [
            {
                key: 'retry:0',
                action: 'retry',
                label: '重新检查',
                sourceCheck: 'service_unavailable',
            },
        ],
    };
}

export function buildUnavailableReadinessReport(detail = '') {
    return buildUnavailableReport(detail);
}

export function normalizeReadinessReport(report = null) {
    if (!report || typeof report !== 'object') {
        return buildUnavailableReport();
    }

    const checks = Array.isArray(report.checks)
        ? report.checks.map((check, index) => normalizeCheck(check, index))
        : [];
    const derivedBlockingCount = checks.filter((check) => check.blocking).length;
    const blockingCount = Number.isFinite(Number(report.blocking_count))
        ? Math.max(0, Number(report.blocking_count))
        : derivedBlockingCount;
    const ready = Boolean(report.ready) && blockingCount === 0;

    return {
        success: report.success !== false,
        ready,
        blockingCount,
        checkedAt: Number(report.checked_at || 0),
        summary: buildSummary(ready, blockingCount, report.summary),
        checks,
        suggestedActions: Array.isArray(report.suggested_actions)
            ? report.suggested_actions.map((action, index) => normalizeAction(action, index))
            : [],
    };
}

export function getReadinessBlockingChecks(report, options = {}) {
    const normalized = normalizeReadinessReport(report);
    const onlyFirstRun = options.onlyFirstRun === true;
    const limit = Number.isFinite(Number(options.limit))
        ? Math.max(0, Number(options.limit))
        : null;

    let checks = normalized.checks.filter((check) => check.blocking);
    if (onlyFirstRun) {
        const focused = checks.filter((check) => FIRST_RUN_FOCUS_KEYS.includes(check.key));
        checks = focused.length > 0 ? focused : checks;
    }

    return limit === null ? checks : checks.slice(0, limit);
}

export function getReadinessDisplayChecks(report, options = {}) {
    const normalized = normalizeReadinessReport(report);
    const limit = Number.isFinite(Number(options.limit))
        ? Math.max(0, Number(options.limit))
        : 4;
    const blockingChecks = getReadinessBlockingChecks(normalized, options);
    if (blockingChecks.length > 0) {
        return blockingChecks.slice(0, limit);
    }

    let passedChecks = normalized.checks.filter((check) => check.status === 'passed');
    if (options.onlyFirstRun) {
        const focused = passedChecks.filter((check) => FIRST_RUN_FOCUS_KEYS.includes(check.key));
        passedChecks = focused.length > 0 ? focused : passedChecks;
    }
    return passedChecks.slice(0, limit);
}

export function shouldShowFirstRunGuide({
    firstRunPending = false,
    dismissed = false,
    report = null,
} = {}) {
    if (!firstRunPending || dismissed) {
        return false;
    }
    return !normalizeReadinessReport(report).ready;
}

export function shouldCompleteFirstRun({
    firstRunPending = false,
    report = null,
} = {}) {
    return Boolean(firstRunPending) && normalizeReadinessReport(report).ready;
}

export {
    FIRST_RUN_FOCUS_KEYS,
};
