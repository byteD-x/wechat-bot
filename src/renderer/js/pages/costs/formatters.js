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
    totalCost: '\u603b\u91d1\u989d',
    totalTokens: '\u603b Token',
    pricedReplies: '\u5df2\u5b9a\u4ef7\u56de\u590d',
    unpricedReplies: '\u672a\u5b9a\u4ef7\u56de\u590d',
    mostExpensiveModel: '\u6700\u9ad8\u6d88\u8017\u6a21\u578b',
    groupedByCurrency: '\u6309\u5e01\u79cd\u5206\u522b\u7edf\u8ba1',
    allProviders: '\u5168\u90e8 Provider',
    allModels: '\u5168\u90e8\u6a21\u578b',
    model: '\u6a21\u578b',
    provider: 'Provider',
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
    providerMetric: 'Provider\uff1a',
    presetMetric: '\u9884\u8bbe\uff1a',
    inputAmountMetric: '\u8f93\u5165\u91d1\u989d\uff1a',
    outputAmountMetric: '\u8f93\u51fa\u91d1\u989d\uff1a',
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
