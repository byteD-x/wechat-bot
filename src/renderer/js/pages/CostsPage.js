import { PageController } from '../core/PageController.js';
import { apiService } from '../services/ApiService.js';
import { toast } from '../services/NotificationService.js';

const OFFLINE_TEXT = '\u8bf7\u5148\u542f\u52a8 Python \u670d\u52a1\u540e\u67e5\u770b\u6210\u672c\u6570\u636e';

function createStateBlock(text, className = 'loading-state') {
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

function createElement(tag, className, text) {
    const elem = document.createElement(tag);
    if (className) {
        elem.className = className;
    }
    if (text !== undefined) {
        elem.textContent = text;
    }
    return elem;
}

function normalizeModelName(value) {
    const text = String(value || '').trim();
    if (!text) {
        return '未识别模型';
    }
    const lower = text.toLowerCase();
    if (lower === 'unknown' || lower === 'unknow') {
        return '未识别模型';
    }
    return text;
}

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
            this._renderError(OFFLINE_TEXT);
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
                throw new Error(summary?.message || '加载成本概览失败');
            }
            if (!sessions?.success) {
                throw new Error(sessions?.message || '加载会话成本失败');
            }

            this._summary = summary;
            this._sessions = Array.isArray(sessions.sessions) ? sessions.sessions : [];
            this._details.clear();
            this._renderSummary();
            this._renderSessions();
        } catch (error) {
            this._renderError(toast.getErrorMessage(error, '加载成本信息失败'));
        } finally {
            this._syncFiltersToDom();
            this._loading = false;
        }
    }

    async _refreshPricing() {
        if (!this.getState('bot.connected')) {
            toast.info(OFFLINE_TEXT);
            return;
        }

        try {
            const result = await apiService.refreshPricing();
            if (!result?.success) {
                throw new Error(result?.message || '刷新价格目录失败');
            }
            const failures = Object.entries(result.results || {})
                .filter(([, item]) => item?.success === false)
                .map(([providerId, item]) => `${providerId}: ${item?.message || '刷新失败'}`);
            if (failures.length > 0) {
                toast.warning(`价格目录已部分刷新，${failures.join('；')}`);
            } else {
                toast.success('价格目录已刷新');
            }
            await this.refresh();
        } catch (error) {
            toast.error(toast.getErrorMessage(error, '刷新价格目录失败'));
        }
    }

    _renderLoading() {
        ['#cost-overview', '#cost-models', '#cost-sessions'].forEach((selector) => {
            const container = this.$(selector);
            if (!container) {
                return;
            }
            container.textContent = '';
            container.appendChild(createStateBlock('加载中...'));
        });
    }

    _renderError(message) {
        ['#cost-overview', '#cost-models', '#cost-sessions'].forEach((selector) => {
            const container = this.$(selector);
            if (!container) {
                return;
            }
            container.textContent = '';
            container.appendChild(createStateBlock(message, 'empty-state'));
        });
    }

    _renderSummary() {
        this._renderOverview(this._summary?.overview || {});
        this._renderModelBreakdown(this._summary?.models || []);
        this._renderFilterOptions(this._summary?.options || {});
    }

    _renderOverview(overview) {
        const container = this.$('#cost-overview');
        if (!container) {
            return;
        }

        const cards = [
            {
                label: '总金额',
                value: this._formatCostGroups(overview.currency_groups) || '--',
            },
            {
                label: '总 Token',
                value: this._formatNumber(overview.total_tokens),
            },
            {
                label: '已定价回复',
                value: this._formatNumber(overview.priced_reply_count),
            },
            {
                label: '未定价回复',
                value: this._formatNumber(overview.unpriced_reply_count),
            },
            {
                label: '最高消耗模型',
                value: overview.most_expensive_model
                    ? `${normalizeModelName(overview.most_expensive_model.model)} · ${this._formatCurrencyValue(
                        overview.most_expensive_model.currency,
                        overview.most_expensive_model.total_cost,
                    )}`
                    : '按币种分别统计',
            },
        ];

        container.textContent = '';
        const fragment = document.createDocumentFragment();
        cards.forEach((item) => {
            const card = createElement('article', 'cost-kpi-card');
            card.appendChild(createElement('span', 'cost-kpi-label', item.label));
            card.appendChild(createElement('strong', 'cost-kpi-value', item.value));
            fragment.appendChild(card);
        });
        container.appendChild(fragment);
    }

    _renderModelBreakdown(models) {
        const container = this.$('#cost-models');
        if (!container) {
            return;
        }
        container.textContent = '';

        if (!Array.isArray(models) || models.length === 0) {
            container.appendChild(createStateBlock('当前筛选条件下没有模型成本数据', 'empty-state'));
            return;
        }

        const table = createElement('div', 'cost-model-table');
        const header = createElement('div', 'cost-model-row cost-model-row-head');
        ['模型', 'Provider', '输入 Token', '输出 Token', '总 Token', '金额'].forEach((text) => {
            header.appendChild(createElement('span', 'cost-model-cell', text));
        });
        table.appendChild(header);

        models.forEach((item) => {
            const row = createElement('div', 'cost-model-row');
            row.appendChild(createElement('span', 'cost-model-cell cost-model-main', normalizeModelName(item.model)));
            row.appendChild(createElement('span', 'cost-model-cell', item.provider_id || '--'));
            row.appendChild(createElement('span', 'cost-model-cell', this._formatNumber(item.prompt_tokens)));
            row.appendChild(createElement('span', 'cost-model-cell', this._formatNumber(item.completion_tokens)));
            row.appendChild(createElement('span', 'cost-model-cell', this._formatNumber(item.total_tokens)));
            row.appendChild(
                createElement(
                    'span',
                    'cost-model-cell',
                    this._formatCostGroups(item.currency_groups) || '待定价',
                ),
            );
            table.appendChild(row);
        });

        container.appendChild(table);
    }

    _renderFilterOptions(options) {
        const providerSelect = this.$('#cost-provider');
        const modelSelect = this.$('#cost-model');
        if (!providerSelect || !modelSelect) {
            return;
        }

        const previousProvider = this._filters.provider_id;
        const previousModel = this._filters.model;

        this._fillSelect(providerSelect, options.providers || [], '全部 Provider');
        this._fillSelect(modelSelect, options.models || [], '全部模型');

        providerSelect.value = previousProvider;
        modelSelect.value = previousModel;
    }

    _fillSelect(select, values, allLabel) {
        select.textContent = '';
        const allOption = document.createElement('option');
        allOption.value = '';
        allOption.textContent = allLabel;
        select.appendChild(allOption);

        (values || []).forEach((value) => {
            const option = document.createElement('option');
            option.value = value;
            option.textContent = value;
            select.appendChild(option);
        });
    }

    _renderSessions() {
        const container = this.$('#cost-sessions');
        if (!container) {
            return;
        }

        container.textContent = '';
        if (!Array.isArray(this._sessions) || this._sessions.length === 0) {
            container.appendChild(createStateBlock('当前筛选条件下没有会话成本数据', 'empty-state'));
            return;
        }

        const fragment = document.createDocumentFragment();
        this._sessions.forEach((session) => {
            const item = createElement('article', 'cost-session-item');
            item.dataset.chatId = session.chat_id;

            const trigger = createElement('button', 'cost-session-trigger');
            trigger.type = 'button';
            trigger.setAttribute('aria-expanded', 'false');
            trigger.addEventListener('click', () => {
                void this._toggleSession(session.chat_id, item);
            });

            const header = createElement('div', 'cost-session-header');
            const titleWrap = createElement('div', 'cost-session-title-wrap');
            titleWrap.appendChild(createElement('strong', 'cost-session-title', session.display_name || session.chat_id));
            titleWrap.appendChild(
                createElement(
                    'span',
                    'cost-session-subtitle',
                    `${this._formatDateTime(session.last_timestamp)} · ${this._formatNumber(session.reply_count)} 条 AI 回复`,
                ),
            );

            const meta = createElement('div', 'cost-session-meta');
            meta.appendChild(createElement('span', 'cost-session-chip', `输入 ${this._formatNumber(session.prompt_tokens)}`));
            meta.appendChild(createElement('span', 'cost-session-chip', `输出 ${this._formatNumber(session.completion_tokens)}`));
            meta.appendChild(createElement('span', 'cost-session-chip', `总计 ${this._formatNumber(session.total_tokens)}`));
            meta.appendChild(
                createElement(
                    'span',
                    `cost-session-chip ${session.priced_reply_count > 0 ? 'is-cost' : 'is-pending'}`,
                    this._formatCostGroups(session.currency_groups) || '待定价',
                ),
            );
            if (session.estimated_reply_count > 0) {
                meta.appendChild(
                    createElement(
                        'span',
                        'cost-session-chip is-estimated',
                        `含估算 ${this._formatNumber(session.estimated_reply_count)}`,
                    ),
                );
            }

            header.appendChild(titleWrap);
            header.appendChild(meta);
            trigger.appendChild(header);
            item.appendChild(trigger);

            const detail = createElement('div', 'cost-session-detail');
            detail.hidden = true;
            item.appendChild(detail);
            fragment.appendChild(item);
        });

        container.appendChild(fragment);
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

        detail.textContent = '';
        detail.appendChild(createStateBlock('加载会话明细中...'));

        try {
            const result = await apiService.getCostSessionDetails(chatId, this._toApiParams());
            if (!result?.success) {
                throw new Error(result?.message || '加载会话明细失败');
            }
            const records = Array.isArray(result.records) ? result.records : [];
            this._details.set(chatId, records);
            this._renderSessionDetails(detail, records);
        } catch (error) {
            detail.textContent = '';
            detail.appendChild(createStateBlock(toast.getErrorMessage(error, '加载会话明细失败'), 'empty-state'));
            trigger.focus();
        }
    }

    _renderSessionDetails(container, records) {
        container.textContent = '';
        if (!Array.isArray(records) || records.length === 0) {
            container.appendChild(createStateBlock('当前会话暂无可展示的成本明细', 'empty-state'));
            return;
        }

        const list = createElement('div', 'cost-reply-list');
        records.forEach((record) => {
            const item = createElement('article', 'cost-reply-item');
            const top = createElement('div', 'cost-reply-top');

            const title = createElement('div', 'cost-reply-title');
            title.appendChild(createElement('strong', '', normalizeModelName(record.model)));
            title.appendChild(createElement('span', 'cost-reply-time', this._formatDateTime(record.timestamp)));
            top.appendChild(title);

            const badges = createElement('div', 'cost-reply-badges');
            badges.appendChild(createElement('span', 'cost-session-chip', `输入 ${this._formatNumber(record.tokens?.user)}`));
            badges.appendChild(createElement('span', 'cost-session-chip', `输出 ${this._formatNumber(record.tokens?.reply)}`));
            badges.appendChild(createElement('span', 'cost-session-chip', `总计 ${this._formatNumber(record.tokens?.total)}`));
            badges.appendChild(
                createElement(
                    'span',
                    `cost-session-chip ${record.pricing_available ? 'is-cost' : 'is-pending'}`,
                    record.pricing_available
                        ? this._formatCurrencyValue(record.currency, record.cost?.total_cost)
                        : '待定价',
                ),
            );
            if (record.estimated?.tokens || record.estimated?.pricing) {
                badges.appendChild(createElement('span', 'cost-session-chip is-estimated', '估算数据'));
            }
            top.appendChild(badges);
            item.appendChild(top);

            const metrics = createElement('div', 'cost-reply-metrics');
            metrics.appendChild(createElement('span', 'cost-reply-metric', `Provider：${record.provider_id || '--'}`));
            metrics.appendChild(createElement('span', 'cost-reply-metric', `预设：${record.preset || '--'}`));
            metrics.appendChild(
                createElement(
                    'span',
                    'cost-reply-metric',
                    `输入金额：${this._formatCurrencyValue(record.currency, record.cost?.input_cost)}`,
                ),
            );
            metrics.appendChild(
                createElement(
                    'span',
                    'cost-reply-metric',
                    `输出金额：${this._formatCurrencyValue(record.currency, record.cost?.output_cost)}`,
                ),
            );
            item.appendChild(metrics);
            item.appendChild(createElement('p', 'cost-reply-preview', record.reply_preview || record.reply_text || ''));
            list.appendChild(item);
        });

        container.appendChild(list);
    }

    _formatNumber(value) {
        const num = Number(value || 0);
        if (!Number.isFinite(num)) {
            return '--';
        }
        return num.toLocaleString('zh-CN');
    }

    _formatCostGroups(groups) {
        if (!Array.isArray(groups) || groups.length === 0) {
            return '';
        }
        return groups
            .map((item) => this._formatCurrencyValue(item.currency, item.total_cost))
            .join(' / ');
    }

    _formatCurrencyValue(currency, amount) {
        const value = Number(amount);
        if (!Number.isFinite(value)) {
            return '--';
        }

        const digits = value >= 100 ? 2 : value >= 1 ? 4 : 6;
        const fixed = value.toFixed(digits);
        if (currency === 'CNY') {
            return `¥${fixed}`;
        }
        if (currency === 'LOCAL') {
            return `本地 ${fixed}`;
        }
        return `$${fixed}`;
    }

    _formatDateTime(timestamp) {
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
}

export default CostsPage;
