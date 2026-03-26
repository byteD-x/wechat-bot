export const COST_TEXT = {
    offline: '\u8bf7\u5148\u542f\u52a8 Python \u670d\u52a1\u540e\u67e5\u770b\u6210\u672c\u6570\u636e',
    loading: '\u52a0\u8f7d\u4e2d...',
    loadSummaryFailed: '\u52a0\u8f7d\u6210\u672c\u6982\u89c8\u5931\u8d25',
    loadSessionsFailed: '\u52a0\u8f7d\u4f1a\u8bdd\u6210\u672c\u5931\u8d25',
    loadFailed: '\u52a0\u8f7d\u6210\u672c\u4fe1\u606f\u5931\u8d25',
    refreshPricingFailed: '\u5237\u65b0\u4ef7\u683c\u76ee\u5f55\u5931\u8d25',
    refreshPricingSuccess: '\u4ef7\u683c\u76ee\u5f55\u5df2\u5237\u65b0',
    refreshPricingPartial: '\u4ef7\u683c\u76ee\u5f55\u5df2\u90e8\u5206\u5237\u65b0\uff0c',
    detailLoading: '\u52a0\u8f7d\u4f1a\u8bdd\u660e\u7ec6\u4e2d...',
    detailFailed: '\u52a0\u8f7d\u4f1a\u8bdd\u660e\u7ec6\u5931\u8d25',
    noModelData: '\u5f53\u524d\u7b5b\u9009\u6761\u4ef6\u4e0b\u6ca1\u6709\u6a21\u578b\u6210\u672c\u6570\u636e',
    noSessionData: '\u5f53\u524d\u7b5b\u9009\u6761\u4ef6\u4e0b\u6ca1\u6709\u4f1a\u8bdd\u6210\u672c\u6570\u636e',
    noSessionDetail: '\u5f53\u524d\u4f1a\u8bdd\u6682\u65e0\u53ef\u5c55\u793a\u7684\u6210\u672c\u660e\u7ec6',
    noReviewQueue: '\u5f53\u524d\u7b5b\u9009\u6761\u4ef6\u4e0b\u6ca1\u6709\u201c\u6ca1\u5e2e\u52a9\u201d\u56de\u590d',
    totalCost: '\u603b\u91d1\u989d',
    totalTokens: '\u603b Token',
    pricedReplies: '\u5df2\u5b9a\u4ef7\u56de\u590d',
    unpricedReplies: '\u672a\u5b9a\u4ef7\u56de\u590d',
    helpfulReplies: '\u6709\u5e2e\u52a9',
    unhelpfulReplies: '\u6ca1\u5e2e\u52a9',
    feedbackCoverage: '\u53cd\u9988\u8986\u76d6\u7387',
    mostExpensiveModel: '\u6700\u9ad8\u6d88\u8017\u6a21\u578b',
    groupedByCurrency: '\u6309\u5e01\u79cd\u5206\u522b\u7edf\u8ba1',
    allProviders: '\u5168\u90e8\u670d\u52a1\u65b9',
    allModels: '\u5168\u90e8\u6a21\u578b',
    allSuggestedActions: '\u5168\u90e8\u52a8\u4f5c',
    model: '\u6a21\u578b',
    provider: '\u670d\u52a1\u65b9',
    promptTokens: '\u8f93\u5165 Token',
    completionTokens: '\u8f93\u51fa Token',
    amount: '\u91d1\u989d',
    pendingPricing: '\u5f85\u5b9a\u4ef7',
    unknownModel: '\u672a\u8bc6\u522b\u6a21\u578b',
    aiReplies: '\u6761 AI \u56de\u590d',
    inputLabel: '\u8f93\u5165',
    outputLabel: '\u8f93\u51fa',
    totalLabel: '\u603b\u8ba1',
    estimatedLabel: '\u542b\u4f30\u7b97',
    estimatedData: '\u4f30\u7b97\u6570\u636e',
    providerMetric: '\u670d\u52a1\u65b9\uff1a',
    presetMetric: '\u9884\u8bbe\uff1a',
    feedbackMetric: '\u53cd\u9988\uff1a',
    retrievalMetric: '\u68c0\u7d22\uff1a',
    reviewReasonMetric: '\u590d\u76d8\u539f\u56e0\uff1a',
    suggestedActionMetric: '\u5efa\u8bae\u52a8\u4f5c\uff1a',
    suggestedActionLabel: '\u5904\u7406\u5efa\u8bae',
    playbookTitle: '\u4f18\u5148\u5904\u7406\u5efa\u8bae',
    playbookGuideLabel: '\u6392\u67e5\u6307\u5f15\uff1a',
    affectedRepliesMetric: '\u5f71\u54cd\u56de\u590d\uff1a',
    inputAmountMetric: '\u8f93\u5165\u91d1\u989d\uff1a',
    outputAmountMetric: '\u8f93\u51fa\u91d1\u989d\uff1a',
    reviewContextLabel: '\u4e0a\u4e0b\u6587',
    reviewReplyLabel: '\u56de\u590d',
    localCurrency: '\u672c\u5730',
};

export function createCostStateBlock(text, className = 'loading-state') {
    const wrap = document.createElement('div');
    wrap.className = className;
    if (className === 'loading-state') {
        const spinner = document.createElement('div');
        spinner.className = 'spinner';
        wrap.appendChild(spinner);
    }

    const label = document.createElement('span');
    if (className === 'empty-state') {
        label.className = 'empty-state-text';
    }
    label.textContent = text;
    wrap.appendChild(label);
    return wrap;
}

export function createCostElement(tag, className, text) {
    const element = document.createElement(tag);
    if (className) {
        element.className = className;
    }
    if (text !== undefined) {
        element.textContent = text;
    }
    return element;
}

export function normalizeCostModelName(value) {
    const text = String(value || '').trim();
    if (!text) {
        return COST_TEXT.unknownModel;
    }
    const lower = text.toLowerCase();
    if (lower === 'unknown' || lower === 'unknow') {
        return COST_TEXT.unknownModel;
    }
    return text;
}

export function formatCostNumber(value) {
    const num = Number(value || 0);
    if (!Number.isFinite(num)) {
        return '--';
    }
    return num.toLocaleString('zh-CN');
}

export function formatCurrencyValue(currency, amount) {
    const value = Number(amount);
    if (!Number.isFinite(value)) {
        return '--';
    }

    const digits = value >= 100 ? 2 : value >= 1 ? 4 : 6;
    const fixed = value.toFixed(digits);
    if (currency === 'CNY') {
        return `\u00a5${fixed}`;
    }
    if (currency === 'LOCAL') {
        return `${COST_TEXT.localCurrency} ${fixed}`;
    }
    return `$${fixed}`;
}

export function formatCostGroups(groups) {
    if (!Array.isArray(groups) || groups.length === 0) {
        return '';
    }
    return groups
        .map((item) => formatCurrencyValue(item.currency, item.total_cost))
        .join(' / ');
}

export function formatCostDateTime(timestamp) {
    const value = Number(timestamp || 0);
    if (!Number.isFinite(value) || value <= 0) {
        return '--';
    }
    const date = new Date(value * 1000);
    if (Number.isNaN(date.getTime())) {
        return '--';
    }
    return date.toLocaleString('zh-CN', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
    });
}

export function formatFeedbackLabel(feedback) {
    const normalized = String(feedback || '').trim().toLowerCase();
    if (normalized === 'helpful') {
        return COST_TEXT.helpfulReplies;
    }
    if (normalized === 'unhelpful') {
        return COST_TEXT.unhelpfulReplies;
    }
    return '--';
}

export function formatPercent(value) {
    const num = Number(value);
    if (!Number.isFinite(num)) {
        return '--';
    }
    return `${num.toFixed(1)}%`;
}

export function formatRetrievalSummary(retrieval = {}) {
    if (retrieval?.summary_text) {
        return String(retrieval.summary_text);
    }

    const parts = [];
    if (retrieval?.augmented) {
        parts.push('\u5df2\u542f\u7528\u68c0\u7d22\u589e\u5f3a');
    }
    const runtimeHits = Number(retrieval?.runtime_hit_count || 0);
    if (Number.isFinite(runtimeHits) && runtimeHits > 0) {
        parts.push(`\u8fd0\u884c\u671f\u547d\u4e2d ${runtimeHits}`);
    }
    return parts.join('\uff0c');
}

export function formatReviewReason(reason) {
    switch (String(reason || '').trim()) {
        case 'retrieval_not_used':
            return '\u672a\u542f\u7528\u68c0\u7d22\u589e\u5f3a';
        case 'retrieval_weak':
            return '\u68c0\u7d22\u547d\u4e2d\u504f\u5f31';
        case 'reply_too_short':
            return '\u56de\u590d\u8fc7\u77ed';
        case 'context_thin':
            return '\u4e0a\u4e0b\u6587\u504f\u8584';
        case 'needs_manual_review':
            return '\u9700\u8981\u4eba\u5de5\u590d\u76d8';
        default:
            return '--';
    }
}

export function formatSuggestedAction(action) {
    switch (String(action || '').trim()) {
        case 'check_retrieval_toggle':
            return '\u68c0\u67e5\u68c0\u7d22\u589e\u5f3a\u5f00\u5173';
        case 'tune_retrieval_threshold':
            return '\u8c03\u6574\u68c0\u7d22\u9608\u503c\u6216\u53ec\u56de\u6570';
        case 'review_prompt_constraints':
            return '\u68c0\u67e5\u63d0\u793a\u8bcd\u7ea6\u675f\u4e0e\u56de\u590d\u957f\u5ea6';
        case 'enrich_context_sources':
            return '\u8865\u5145\u4e0a\u4e0b\u6587\u6216\u8bb0\u5fc6\u6765\u6e90';
        case 'manual_review_required':
            return '\u8fdb\u884c\u4eba\u5de5\u590d\u76d8';
        default:
            return '--';
    }
}
