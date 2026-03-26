import {
    refreshCosts,
    exportCostReviewQueue,
    refreshPricingCatalog,
} from './data-controller.js';
import { syncCostFilters } from './filter-sync.js';

const DEFAULT_COST_FILTERS = Object.freeze({
    period: '30d',
    provider_id: '',
    model: '',
    preset: '',
    review_reason: '',
    suggested_action: '',
    only_priced: false,
    include_estimated: true,
});

export function bindCostsPage(page, deps = {}) {
    const runRefreshCosts = deps.refreshCosts || ((targetPage) => refreshCosts(targetPage, deps));
    const runRefreshPricingCatalog = deps.refreshPricingCatalog || ((targetPage) => refreshPricingCatalog(targetPage, {
        ...deps,
        refreshCosts: runRefreshCosts,
    }));

    page.bindEvent('#btn-refresh-costs', 'click', () => {
        void runRefreshCosts(page);
    });

    page.bindEvent('#btn-refresh-pricing', 'click', () => {
        void runRefreshPricingCatalog(page);
    });

    page.bindEvent('#btn-export-cost-review', 'click', () => {
        void (deps.exportCostReviewQueue || ((targetPage) => exportCostReviewQueue(targetPage, deps)))(page);
    });

    page.bindEvent('#btn-reset-cost-filters', 'click', () => {
        page._filters = { ...DEFAULT_COST_FILTERS };
        if (typeof page.$ === 'function') {
            syncCostFilters(page);
        }
        void runRefreshCosts(page);
    });

    page._applySuggestedActionFilter = (action) => {
        const select = page.$('#cost-suggested-action');
        if (select) {
            select.value = action || '';
        }
        page._filters = {
            ...(page._filters || {}),
            suggested_action: action || '',
        };
        void runRefreshCosts(page);
    };

    ['#cost-period', '#cost-provider', '#cost-model', '#cost-preset', '#cost-review-reason', '#cost-suggested-action'].forEach((selector) => {
        page.bindEvent(selector, 'change', () => {
            void runRefreshCosts(page);
        });
    });

    page.bindEvent('#cost-only-priced', 'change', () => {
        void runRefreshCosts(page);
    });

    page.bindEvent('#cost-include-estimated', 'change', () => {
        void runRefreshCosts(page);
    });

    page.watchState('bot.connected', () => {
        if (page.isActive()) {
            void runRefreshCosts(page);
        }
    });
}
