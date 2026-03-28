import { PageController } from '../core/PageController.js';
import { refreshCosts, refreshPricingCatalog } from './costs/data-controller.js';
import { syncCostFilters } from './costs/filter-sync.js';
import { bindCostsPage } from './costs/page-shell.js';
import { toggleCostSession } from './costs/session-controller.js';
import { renderCostsPageShell } from '../app-shell/pages/index.js';

export class CostsPage extends PageController {
    constructor() {
        super('CostsPage', 'page-costs');
        this._filters = {
            period: '30d',
            provider_id: '',
            model: '',
            preset: '',
            review_reason: '',
            suggested_action: '',
            only_priced: false,
            include_estimated: true,
        };
        this._summary = null;
        this._sessions = [];
        this._details = new Map();
        this._loading = false;
        this._pendingRefresh = false;
        this._lastLoadedAt = 0;
    }

    async onInit() {
        await super.onInit();
        const container = this.container || (typeof document !== 'undefined' ? this.getContainer() : null);
        if (container) {
            container.innerHTML = renderCostsPageShell();
        }
        bindCostsPage(this, {
            refreshCosts: (page) => refreshCosts(page, {
                onToggleSession: (chatId, item) => toggleCostSession(page, chatId, item),
            }),
            refreshPricingCatalog,
        });
        syncCostFilters(this);
    }

    async onEnter() {
        await super.onEnter();
        await this.refresh();
    }

    async refresh() {
        await refreshCosts(this, {
            onToggleSession: (chatId, item) => toggleCostSession(this, chatId, item),
        });
    }
}

export default CostsPage;
