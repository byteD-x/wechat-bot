const FIRST_RUN_FOCUS_KEYS = [
    'admin_permission',
    'wechat_process',
    'wechat_compatibility',
    'api_config',
];

const FIRST_RUN_STEP_DEFINITIONS = Object.freeze([
    {
        key: 'environment',
        title: '环境检查',
        shortTitle: '环境',
        checkKeys: ['service_unavailable', 'python_version', 'dependencies', 'admin_permission'],
        detail: '确认 Python、依赖和管理员权限，保证桌面端能稳定接管微信运行环境。',
        readyMessage: '基础运行环境已通过。',
        pendingMessage: '先完成环境检查，再继续后续配置。',
    },
    {
        key: 'model_auth',
        title: '模型认证',
        shortTitle: '模型',
        checkKeys: ['api_config'],
        detail: '确认至少有一个可用模型预设，后续测试运行才能拿到回复。',
        readyMessage: '已检测到可用模型预设。',
        pendingMessage: '请先完成模型认证。',
        fallbackAction: 'open_settings',
        fallbackActionLabel: '前往设置',
    },
    {
        key: 'wechat_connection',
        title: '微信连接',
        shortTitle: '微信',
        checkKeys: ['wechat_installation', 'wechat_compatibility', 'wechat_process', 'transport_config'],
        detail: '确认微信客户端、版本兼容性和传输配置，避免启动后再失败。',
        readyMessage: '微信连接准备已通过。',
        pendingMessage: '请先完成微信连接准备。',
        fallbackAction: 'open_wechat',
        fallbackActionLabel: '打开微信',
    },
    {
        key: 'test_run',
        title: '测试运行',
        shortTitle: '测试',
        checkKeys: [],
        detail: '前面步骤通过后，回到仪表盘启动机器人并观察一次真实运行状态。',
        readyMessage: '准备度已通过，可以进行测试运行。',
        pendingMessage: '完成前面步骤后再进行测试运行。',
    },
]);

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

function normalizeStepKeySet(value) {
    if (value instanceof Set) {
        return new Set([...value].map((item) => toTrimmedString(item, '')).filter(Boolean));
    }
    if (Array.isArray(value)) {
        return new Set(value.map((item) => toTrimmedString(item, '')).filter(Boolean));
    }
    return new Set();
}

function getStatusLabel(status) {
    if (status === 'failed') {
        return '待修复';
    }
    if (status === 'skipped') {
        return '已跳过';
    }
    if (status === 'pending') {
        return '待完成';
    }
    if (status === 'ready') {
        return '可测试';
    }
    return '已完成';
}

function pickStepAction(blockingChecks, definition) {
    const actionableCheck = blockingChecks.find((check) => check.action)
        || blockingChecks[0]
        || null;
    if (actionableCheck) {
        return {
            action: actionableCheck.action,
            label: actionableCheck.actionLabel,
            sourceCheck: actionableCheck.key,
        };
    }

    if (definition?.fallbackAction) {
        return {
            action: definition.fallbackAction,
            label: definition.fallbackActionLabel || getDefaultActionLabel(definition.fallbackAction),
            sourceCheck: '',
        };
    }

    return null;
}

function buildTaskStep(definition, checks, report, skippedStepKeys, index) {
    const blockingChecks = checks.filter((check) => check.blocking);
    const skipped = skippedStepKeys.has(definition.key);
    let status = 'passed';

    if (definition.key === 'test_run') {
        status = report.ready ? 'ready' : 'pending';
    } else if (blockingChecks.length > 0) {
        status = 'failed';
    }

    if (skipped && status !== 'passed' && status !== 'ready') {
        status = 'skipped';
    }

    const primaryAction = pickStepAction(blockingChecks, definition);
    const message = blockingChecks[0]?.message
        || (status === 'passed' || status === 'ready'
            ? definition.readyMessage
            : definition.pendingMessage);

    return {
        key: definition.key,
        index,
        title: definition.title,
        shortTitle: definition.shortTitle || definition.title,
        detail: definition.detail,
        status,
        statusLabel: getStatusLabel(status),
        skipped,
        complete: status === 'passed' || status === 'ready',
        canSkip: status === 'failed' || status === 'pending',
        message,
        checks,
        blockingChecks,
        primaryAction,
    };
}

function pickDefaultActiveStep(steps) {
    return steps.find((step) => step.status === 'failed' && !step.skipped)
        || steps.find((step) => step.status === 'pending' && !step.skipped)
        || steps.find((step) => step.status === 'skipped')
        || steps[steps.length - 1]
        || null;
}

function pickNextStep(steps, activeStep) {
    return steps.find((step) => step.status === 'failed' && !step.skipped)
        || steps.find((step) => step.status === 'pending' && !step.skipped)
        || activeStep
        || steps[0]
        || null;
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

export function buildReadinessTaskFlow(report = null, options = {}) {
    const normalized = normalizeReadinessReport(report);
    const skippedStepKeys = normalizeStepKeySet(options.skippedStepKeys);
    const assignedKeys = new Set(FIRST_RUN_STEP_DEFINITIONS.flatMap((definition) => definition.checkKeys));
    const extraChecks = normalized.checks.filter((check) => !assignedKeys.has(check.key));

    const steps = FIRST_RUN_STEP_DEFINITIONS.map((definition, index) => {
        let checks = normalized.checks.filter((check) => definition.checkKeys.includes(check.key));
        if (index === 0 && extraChecks.length > 0) {
            checks = [...checks, ...extraChecks];
        }
        return buildTaskStep(definition, checks, normalized, skippedStepKeys, index);
    });

    const requestedActiveStepKey = toTrimmedString(options.activeStepKey, '');
    const requestedActiveStep = steps.find((step) => step.key === requestedActiveStepKey) || null;
    const activeStep = requestedActiveStep || pickDefaultActiveStep(steps);
    const nextStep = pickNextStep(steps, activeStep);

    steps.forEach((step) => {
        step.active = step.key === activeStep?.key;
    });

    return {
        ready: normalized.ready,
        blockingCount: normalized.blockingCount,
        summary: normalized.summary,
        steps,
        activeStep,
        nextStep,
        nextAction: nextStep?.primaryAction || null,
        skippedStepKeys: [...skippedStepKeys],
    };
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
    FIRST_RUN_STEP_DEFINITIONS,
};
