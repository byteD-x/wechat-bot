import { PageController } from '../core/PageController.js';
import { apiService } from '../services/ApiService.js';
import { toast } from '../services/NotificationService.js';
import { COST_TEXT } from './costs/formatters.js';
import {
    renderCostError,
    renderCostFilterOptions,
    renderCostLoading,
    renderCostModelBreakdown,
    renderCostOverview,
    renderCostSessionDetails,
    renderCostSessionError,
    renderCostSessionLoading,
    renderCostSessions,
} from './costs/renderers.js';

export class CostsPage extends PageController {
    constructor() {
        super('CostsPage', 'page-costs');
        this._filters = {
            period: '30d',
            provider_id: '',
            model: '',
            only_priced: false,
            include_estimated: true,
        };
        this._summary = null;
        this._sessions = [];
        this._details = new Map();
        this._loading = false;
    }

    async onInit() {
        await super.onInit();
        this._bindEvents();
        this._syncFiltersToDom();
        this.watchState('bot.connected', () => {
            if (this.isActive()) {
                void this.refresh();
            }
        });
    }

    async onEnter() {
        await super.onEnter();
        await this.refresh();
    }

    _bindEvents() {
        this.bindEvent('#btn-refresh-costs', 'click', () => {
            void this.refresh();
        });
        this.bindEvent('#btn-refresh-pricing', 'click', async () => {
            await this._refreshPricing();
        });

        ['#cost-period', '#cost-provider', '#cost-model'].forEach((selector) => {
            this.bindEvent(selector, 'change', () => {
                this._readFiltersFromDom();
                void this.refresh();
            });
        });

        this.bindEvent('#cost-only-priced', 'change', () => {
            this._readFiltersFromDom();
            void this.refresh();
        });
        this.bindEvent('#cost-include-estimated', 'change', () => {
            this._readFiltersFromDom();
            void this.refresh();
        });
    }

    _readFiltersFromDom() {
        this._filters = {
            period: this.$('#cost-period')?.value || '30d',
            provider_id: this.$('#cost-provider')?.value || '',
            model: this.$('#cost-model')?.value || '',
            only_priced: !!this.$('#cost-only-priced')?.checked,
            include_estimated: !!this.$('#cost-include-estimated')?.checked,
        };
    }

    _syncFiltersToDom() {
        if (this.$('#cost-period')) this.$('#cost-period').value = this._filters.period;
        if (this.$('#cost-provider')) this.$('#cost-provider').value = this._filters.provider_id;
        if (this.$('#cost-model')) this.$('#cost-model').value = this._filters.model;
        if (this.$('#cost-only-priced')) this.$('#cost-only-priced').checked = this._filters.only_priced;
        if (this.$('#cost-include-estimated')) this.$('#cost-include-estimated').checked = this._filters.include_estimated;
    }

    _toApiParams() {
        return {
            period: this._filters.period,
            provider_id: this._filters.provider_id,
            model: this._filters.model,
            only_priced: this._filters.only_priced,
            include_estimated: this._filters.include_estimated,
        };
    }

    async refresh() {
        if (this._loading) {
            return;
        }

        if (!this.getState('bot.connected')) {
            this._summary = null;
            this._sessions = [];
            this._details.clear();
            this._renderError(COST_TEXT.offline);
            this._syncFiltersToDom();
            return;
        }

        this._loading = true;
        this._readFiltersFromDom();
        this._renderLoading();

        try {
            const [summary, sessions] = await Promise.all([
                apiService.getCostSummary(this._toApiParams()),
                apiService.getCostSessions(this._toApiParams()),
            ]);

            if (!summary?.success) {
                throw new Error(summary?.message || COST_TEXT.loadSummaryFailed);
            }
            if (!sessions?.success) {
                throw new Error(sessions?.message || COST_TEXT.loadSessionsFailed);
            }

            this._summary = summary;
            this._sessions = Array.isArray(sessions.sessions) ? sessions.sessions : [];
            this._details.clear();
            this._renderSummary();
            this._renderSessions();
        } catch (error) {
            this._renderError(toast.getErrorMessage(error, COST_TEXT.loadFailed));
        } finally {
            this._syncFiltersToDom();
            this._loading = false;
        }
    }

    async _refreshPricing() {
        if (!this.getState('bot.connected')) {
            toast.info(COST_TEXT.offline);
            return;
        }

        try {
            const result = await apiService.refreshPricing();
            if (!result?.success) {
                throw new Error(result?.message || COST_TEXT.refreshPricingFailed);
            }
            const failures = Object.entries(result.results || {})
                .filter(([, item]) => item?.success === false)
                .map(([providerId, item]) => `${providerId}: ${item?.message || COST_TEXT.refreshPricingFailed}`);
            if (failures.length > 0) {
                toast.warning(`${COST_TEXT.refreshPricingPartial}${failures.join('；')}`);
            } else {
                toast.success(COST_TEXT.refreshPricingSuccess);
            }
            await this.refresh();
        } catch (error) {
            toast.error(toast.getErrorMessage(error, COST_TEXT.refreshPricingFailed));
        }
    }

    _renderLoading() {
        renderCostLoading(this);
    }

    _renderError(message) {
        renderCostError(this, message);
    }

    _renderSummary() {
        this._renderOverview(this._summary?.overview || {});
        this._renderModelBreakdown(this._summary?.models || []);
        this._renderFilterOptions(this._summary?.options || {});
    }

    _renderOverview(overview) {
        renderCostOverview(this, overview);
    }

    _renderModelBreakdown(models) {
        renderCostModelBreakdown(this, models);
    }

    _renderFilterOptions(options) {
        renderCostFilterOptions(this, this._filters, options);
    }

    _renderSessions() {
        renderCostSessions(this, this._sessions, (chatId, item) => this._toggleSession(chatId, item));
    }

    async _toggleSession(chatId, item) {
        const detail = item.querySelector('.cost-session-detail');
        const trigger = item.querySelector('.cost-session-trigger');
        if (!detail || !trigger) {
            return;
        }

        const isOpen = item.classList.contains('is-open');
        item.classList.toggle('is-open', !isOpen);
        detail.hidden = isOpen;
        trigger.setAttribute('aria-expanded', String(!isOpen));
        if (isOpen) {
            return;
        }

        if (this._details.has(chatId)) {
            this._renderSessionDetails(detail, this._details.get(chatId));
            return;
        }

        renderCostSessionLoading(detail);

        try {
            const result = await apiService.getCostSessionDetails(chatId, this._toApiParams());
            if (!result?.success) {
                throw new Error(result?.message || COST_TEXT.detailFailed);
            }
            const records = Array.isArray(result.records) ? result.records : [];
            this._details.set(chatId, records);
            this._renderSessionDetails(detail, records);
        } catch (error) {
            renderCostSessionError(detail, toast.getErrorMessage(error, COST_TEXT.detailFailed));
            trigger.focus();
        }
    }

    _renderSessionDetails(container, records) {
        renderCostSessionDetails(container, records);
    }
}

export default CostsPage;
