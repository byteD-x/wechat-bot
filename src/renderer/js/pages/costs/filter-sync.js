export function readCostFilters(page) {
    const filters = {
        period: page.$('#cost-period')?.value || '30d',
        provider_id: page.$('#cost-provider')?.value || '',
        model: page.$('#cost-model')?.value || '',
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
    if (page.$('#cost-only-priced')) page.$('#cost-only-priced').checked = page._filters.only_priced;
    if (page.$('#cost-include-estimated')) page.$('#cost-include-estimated').checked = page._filters.include_estimated;
}

export function toCostApiParams(filters = {}) {
    return {
        period: filters.period || '30d',
        provider_id: filters.provider_id || '',
        model: filters.model || '',
        only_priced: !!filters.only_priced,
        include_estimated: filters.include_estimated !== false,
    };
}
