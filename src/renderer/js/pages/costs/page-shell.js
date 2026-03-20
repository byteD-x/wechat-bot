import {
    refreshCosts,
    refreshPricingCatalog,
} from './data-controller.js';

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

    ['#cost-period', '#cost-provider', '#cost-model'].forEach((selector) => {
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
