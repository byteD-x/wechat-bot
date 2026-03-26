import {
    getReadinessBlockingChecks,
    normalizeReadinessReport,
} from './readiness-helpers.js';

export function pickSuggestedSelfHealAction(readinessReport = null) {
    const report = normalizeReadinessReport(readinessReport);
    if (report.ready || report.blockingCount <= 0) {
        return null;
    }

    const preferredAction = report.suggestedActions.find((item) => item.action && item.action !== 'retry')
        || report.suggestedActions[0]
        || null;

    if (preferredAction) {
        return {
            action: preferredAction.action,
            label: preferredAction.label,
            sourceCheck: preferredAction.sourceCheck || '',
        };
    }

    const fallbackCheck = getReadinessBlockingChecks(report, { limit: 1 })[0];
    if (!fallbackCheck) {
        return null;
    }

    return {
        action: fallbackCheck.action,
        label: fallbackCheck.actionLabel,
        sourceCheck: fallbackCheck.key,
    };
}

export function getRecoveryButtonModel({
    readinessReport = null,
    diagnostics = null,
} = {}) {
    const readinessAction = pickSuggestedSelfHealAction(readinessReport);
    if (readinessAction) {
        return {
            mode: 'readiness',
            action: readinessAction.action,
            label: readinessAction.label,
        };
    }

    if (diagnostics?.recoverable) {
        return {
            mode: 'runtime',
            action: 'recover_runtime',
            label: String(diagnostics.action_label || '').trim() || '一键恢复',
        };
    }

    return {
        mode: 'none',
        action: '',
        label: '',
    };
}
