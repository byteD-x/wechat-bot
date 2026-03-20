export function readCostFilters(page) {
    const filters = {
        period: page.$('#cost-period')?.value || '30d',
        provider_id: page.$('#cost-provider')?.value || '',
        model: page.$('#cost-model')?.value || '',
        preset: page.$('#cost-preset')?.value || '',
        review_reason: page.$('#cost-review-reason')?.value || '',
        suggested_action: page.$('#cost-suggested-action')?.value || '',
        only_priced: !!page.$('#cost-only-priced')?.checked,
        include_estimated: !!page.$('#cost-include-estimated')?.checked,
    };
    page._filters = filters;
    return filters;
}

export function syncCostFilters(page) {
    if (page.$('#cost-period')) page.$('#cost-period').value = page._filters.period;
    if (page.$('#cost-provider')) page.$('#cost-provider').value = page._filters.provider_id;
    if (page.$('#cost-model')) page.$('#cost-model').value = page._filters.model;
    if (page.$('#cost-preset')) page.$('#cost-preset').value = page._filters.preset;
    if (page.$('#cost-review-reason')) page.$('#cost-review-reason').value = page._filters.review_reason;
    if (page.$('#cost-suggested-action')) page.$('#cost-suggested-action').value = page._filters.suggested_action;
    if (page.$('#cost-only-priced')) page.$('#cost-only-priced').checked = page._filters.only_priced;
    if (page.$('#cost-include-estimated')) page.$('#cost-include-estimated').checked = page._filters.include_estimated;
}

export function toCostApiParams(filters = {}) {
    return {
        period: filters.period || '30d',
        provider_id: filters.provider_id || '',
        model: filters.model || '',
        preset: filters.preset || '',
        review_reason: filters.review_reason || '',
        suggested_action: filters.suggested_action || '',
        only_priced: !!filters.only_priced,
        include_estimated: filters.include_estimated !== false,
    };
}
