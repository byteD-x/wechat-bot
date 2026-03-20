import {
    COST_TEXT,
    createCostElement,
    createCostStateBlock,
    formatCostDateTime,
    formatCostGroups,
    formatCostNumber,
    formatCurrencyValue,
    formatFeedbackLabel,
    formatPercent,
    formatReviewReason,
    formatSuggestedAction,
    formatRetrievalSummary,
    normalizeCostModelName,
} from './formatters.js';

export function renderCostLoading(page) {
    ['#cost-overview', '#cost-models', '#cost-review-list', '#cost-sessions'].forEach((selector) => {
        const container = page.$(selector);
        if (!container) {
            return;
        }
        container.textContent = '';
        container.appendChild(createCostStateBlock(COST_TEXT.loading));
    });
}

export function renderCostError(page, message) {
    ['#cost-overview', '#cost-models', '#cost-review-list', '#cost-sessions'].forEach((selector) => {
        const container = page.$(selector);
        if (!container) {
            return;
        }
        container.textContent = '';
        container.appendChild(createCostStateBlock(message, 'empty-state'));
    });
}

export function renderCostOverview(page, overview = {}) {
    const container = page.$('#cost-overview');
    if (!container) {
        return;
    }

    const cards = [
        { label: COST_TEXT.totalCost, value: formatCostGroups(overview.currency_groups) || '--' },
        { label: COST_TEXT.totalTokens, value: formatCostNumber(overview.total_tokens) },
        { label: COST_TEXT.pricedReplies, value: formatCostNumber(overview.priced_reply_count) },
        { label: COST_TEXT.unpricedReplies, value: formatCostNumber(overview.unpriced_reply_count) },
        { label: COST_TEXT.helpfulReplies, value: formatCostNumber(overview.helpful_count) },
        { label: COST_TEXT.unhelpfulReplies, value: formatCostNumber(overview.unhelpful_count) },
        { label: COST_TEXT.feedbackCoverage, value: formatPercent(overview.feedback_coverage) },
        {
            label: COST_TEXT.mostExpensiveModel,
            value: overview.most_expensive_model
                ? `${normalizeCostModelName(overview.most_expensive_model.model)} · ${formatCurrencyValue(
                    overview.most_expensive_model.currency,
                    overview.most_expensive_model.total_cost,
                )}`
                : COST_TEXT.groupedByCurrency,
        },
    ];

    container.textContent = '';
    const fragment = document.createDocumentFragment();
    cards.forEach((item) => {
        const card = createCostElement('article', 'cost-kpi-card');
        card.appendChild(createCostElement('span', 'cost-kpi-label', item.label));
        card.appendChild(createCostElement('strong', 'cost-kpi-value', item.value));
        fragment.appendChild(card);
    });
    container.appendChild(fragment);
}

export function renderCostModelBreakdown(page, models = []) {
    const container = page.$('#cost-models');
    if (!container) {
        return;
    }
    container.textContent = '';

    if (!Array.isArray(models) || models.length === 0) {
        container.appendChild(createCostStateBlock(COST_TEXT.noModelData, 'empty-state'));
        return;
    }

    const table = createCostElement('div', 'cost-model-table');
    const header = createCostElement('div', 'cost-model-row cost-model-row-head');
    [
        COST_TEXT.model,
        COST_TEXT.provider,
        COST_TEXT.promptTokens,
        COST_TEXT.completionTokens,
        COST_TEXT.totalTokens,
        COST_TEXT.amount,
    ].forEach((text) => {
        header.appendChild(createCostElement('span', 'cost-model-cell', text));
    });
    table.appendChild(header);

    models.forEach((item) => {
        const row = createCostElement('div', 'cost-model-row');
        row.appendChild(createCostElement('span', 'cost-model-cell cost-model-main', normalizeCostModelName(item.model)));
        row.appendChild(createCostElement('span', 'cost-model-cell', item.provider_id || '--'));
        row.appendChild(createCostElement('span', 'cost-model-cell', formatCostNumber(item.prompt_tokens)));
        row.appendChild(createCostElement('span', 'cost-model-cell', formatCostNumber(item.completion_tokens)));
        row.appendChild(createCostElement('span', 'cost-model-cell', formatCostNumber(item.total_tokens)));
        row.appendChild(
            createCostElement(
                'span',
                'cost-model-cell',
                formatCostGroups(item.currency_groups) || COST_TEXT.pendingPricing,
            ),
        );
        table.appendChild(row);
    });

    container.appendChild(table);
}

export function renderCostFilterOptions(page, filters, options = {}) {
    const providerSelect = page.$('#cost-provider');
    const modelSelect = page.$('#cost-model');
    const presetSelect = page.$('#cost-preset');
    const reviewReasonSelect = page.$('#cost-review-reason');
    const suggestedActionSelect = page.$('#cost-suggested-action');
    if (!providerSelect || !modelSelect || !presetSelect || !reviewReasonSelect || !suggestedActionSelect) {
        return;
    }

    fillCostSelect(providerSelect, options.providers || [], COST_TEXT.allProviders);
    fillCostSelect(modelSelect, options.models || [], COST_TEXT.allModels);
    fillCostSelect(presetSelect, options.presets || [], '全部预设');
    fillCostSelect(
        reviewReasonSelect,
        (options.review_reasons || []).map((value) => ({ value, label: formatReviewReason(value) })),
        '全部原因',
    );

    fillCostSelect(
        suggestedActionSelect,
        (options.suggested_actions || []).map((value) => ({ value, label: formatSuggestedAction(value) })),
        COST_TEXT.allSuggestedActions,
    );

    providerSelect.value = filters.provider_id;
    modelSelect.value = filters.model;
    presetSelect.value = filters.preset || '';
    reviewReasonSelect.value = filters.review_reason || '';
    suggestedActionSelect.value = filters.suggested_action || '';
}

function fillCostSelect(select, values, allLabel) {
    select.textContent = '';
    const allOption = document.createElement('option');
    allOption.value = '';
    allOption.textContent = allLabel;
    select.appendChild(allOption);

    (values || []).forEach((value) => {
        const option = document.createElement('option');
        if (value && typeof value === 'object') {
            option.value = value.value || '';
            option.textContent = value.label || value.value || '';
        } else {
            option.value = value;
            option.textContent = value;
        }
        select.appendChild(option);
    });
}

export function renderCostSessions(page, sessions = [], onToggleSession) {
    const container = page.$('#cost-sessions');
    if (!container) {
        return;
    }

    container.textContent = '';
    if (!Array.isArray(sessions) || sessions.length === 0) {
        container.appendChild(createCostStateBlock(COST_TEXT.noSessionData, 'empty-state'));
        return;
    }

    const fragment = document.createDocumentFragment();
    sessions.forEach((session) => {
        const item = createCostElement('article', 'cost-session-item');
        item.dataset.chatId = session.chat_id;

        const trigger = createCostElement('button', 'cost-session-trigger');
        trigger.type = 'button';
        trigger.setAttribute('aria-expanded', 'false');
        trigger.addEventListener('click', () => {
            void onToggleSession?.(session.chat_id, item);
        });

        const header = createCostElement('div', 'cost-session-header');
        const titleWrap = createCostElement('div', 'cost-session-title-wrap');
        titleWrap.appendChild(createCostElement('strong', 'cost-session-title', session.display_name || session.chat_id));
        titleWrap.appendChild(
            createCostElement(
                'span',
                'cost-session-subtitle',
                `${formatCostDateTime(session.last_timestamp)} · ${formatCostNumber(session.reply_count)} ${COST_TEXT.aiReplies}`,
            ),
        );

        const meta = createCostElement('div', 'cost-session-meta');
        meta.appendChild(createCostElement('span', 'cost-session-chip', `${COST_TEXT.inputLabel} ${formatCostNumber(session.prompt_tokens)}`));
        meta.appendChild(createCostElement('span', 'cost-session-chip', `${COST_TEXT.outputLabel} ${formatCostNumber(session.completion_tokens)}`));
        meta.appendChild(createCostElement('span', 'cost-session-chip', `${COST_TEXT.totalLabel} ${formatCostNumber(session.total_tokens)}`));
        meta.appendChild(
            createCostElement(
                'span',
                `cost-session-chip ${session.priced_reply_count > 0 ? 'is-cost' : 'is-pending'}`,
                formatCostGroups(session.currency_groups) || COST_TEXT.pendingPricing,
            ),
        );
        if (session.estimated_reply_count > 0) {
            meta.appendChild(
                createCostElement(
                    'button',
                    'cost-session-chip is-estimated',
                    `${COST_TEXT.estimatedLabel} ${formatCostNumber(session.estimated_reply_count)}`,
                ),
            );
        }
        if (Number(session.helpful_count) > 0) {
            meta.appendChild(
                createCostElement(
                    'span',
                    'cost-session-chip is-cost',
                    `${COST_TEXT.helpfulReplies} ${formatCostNumber(session.helpful_count)}`,
                ),
            );
        }
        if (Number(session.unhelpful_count) > 0) {
            meta.appendChild(
                createCostElement(
                    'span',
                    'cost-session-chip is-pending',
                    `${COST_TEXT.unhelpfulReplies} ${formatCostNumber(session.unhelpful_count)}`,
                ),
            );
        }

        header.appendChild(titleWrap);
        header.appendChild(meta);
        trigger.appendChild(header);
        item.appendChild(trigger);

        const detail = createCostElement('div', 'cost-session-detail');
        detail.hidden = true;
        item.appendChild(detail);
        fragment.appendChild(item);
    });

    container.appendChild(fragment);
}

export function renderCostSessionLoading(container) {
    container.textContent = '';
    container.appendChild(createCostStateBlock(COST_TEXT.detailLoading));
}

export function renderCostSessionError(container, message) {
    container.textContent = '';
    container.appendChild(createCostStateBlock(message, 'empty-state'));
}

export function renderCostReviewQueue(page, reviewQueue = [], playbook = {}) {
    const container = page.$('#cost-review-list');
    if (!container) {
        return;
    }

    container.textContent = '';
    if (!Array.isArray(reviewQueue) || reviewQueue.length === 0) {
        container.appendChild(createCostStateBlock(COST_TEXT.noReviewQueue, 'empty-state'));
        return;
    }

    const actionRows = Array.isArray(playbook.actions) ? playbook.actions : [];
    if (actionRows.length > 0) {
        const summary = createCostElement('div', 'cost-reply-playbook');
        summary.appendChild(createCostElement('div', 'cost-reply-playbook-title', COST_TEXT.playbookTitle));
        const metrics = createCostElement('div', 'cost-reply-metrics');
        actionRows.slice(0, 3).forEach((item) => {
            const reasonText = Array.isArray(item.review_reasons) && item.review_reasons.length > 0
                ? ` / ${item.review_reasons.map((reason) => formatReviewReason(reason)).join('、')}`
                : '';
            metrics.appendChild(
                createCostElement(
                    'span',
                    'cost-reply-metric',
                    `${formatSuggestedAction(item.action)} · ${COST_TEXT.affectedRepliesMetric}${formatCostNumber(item.count)}${reasonText}`,
                ),
            );
            const chip = metrics.children[metrics.children.length - 1];
            if (chip) {
                chip.tabIndex = 0;
                chip.setAttribute('role', 'button');
                chip.addEventListener('click', () => {
                    page._applySuggestedActionFilter?.(item.action);
                });
            }
            const guidanceSummary = String(item?.guidance?.summary || '').trim();
            if (guidanceSummary) {
                summary.appendChild(
                    createCostElement(
                        'p',
                        'cost-reply-preview',
                        `${COST_TEXT.playbookGuideLabel}${guidanceSummary}`,
                    ),
                );
            }
        });
        summary.appendChild(metrics);
        container.appendChild(summary);
    }

    const list = createCostElement('div', 'cost-reply-list');
    reviewQueue.forEach((record) => {
        const item = createCostElement('article', 'cost-reply-item');
        const top = createCostElement('div', 'cost-reply-top');

        const title = createCostElement('div', 'cost-reply-title');
        title.appendChild(
            createCostElement(
                'strong',
                '',
                `${record.display_name || record.chat_id} · ${normalizeCostModelName(record.model)}`,
            ),
        );
        title.appendChild(createCostElement('span', 'cost-reply-time', formatCostDateTime(record.timestamp)));
        top.appendChild(title);

        const badges = createCostElement('div', 'cost-reply-badges');
        badges.appendChild(createCostElement('span', 'cost-session-chip is-pending', COST_TEXT.unhelpfulReplies));
        if (record.provider_id) {
            badges.appendChild(createCostElement('span', 'cost-session-chip', record.provider_id));
        }
        if (record.cost?.total_cost !== undefined && record.cost?.total_cost !== null) {
            badges.appendChild(
                createCostElement(
                    'span',
                    'cost-session-chip is-cost',
                    formatCurrencyValue(record.currency, record.cost?.total_cost),
                ),
            );
        }
        top.appendChild(badges);
        item.appendChild(top);

        const metrics = createCostElement('div', 'cost-reply-metrics');
        metrics.appendChild(createCostElement('span', 'cost-reply-metric', `${COST_TEXT.presetMetric}${record.preset || '--'}`));
        metrics.appendChild(
            createCostElement(
                'span',
                'cost-reply-metric',
                `${COST_TEXT.reviewReasonMetric}${formatReviewReason(record.review_reason)}`,
            ),
        );
        metrics.appendChild(
            createCostElement(
                'span',
                'cost-reply-metric',
                `${COST_TEXT.suggestedActionMetric}${formatSuggestedAction(record.suggested_action)}`,
            ),
        );
        metrics.appendChild(
            createCostElement(
                'span',
                'cost-reply-metric',
                `${COST_TEXT.retrievalMetric}${formatRetrievalSummary(record.retrieval) || '--'}`,
            ),
        );
        item.appendChild(metrics);
        item.appendChild(
            createCostElement(
                'p',
                'cost-reply-preview',
                `${COST_TEXT.reviewContextLabel}: ${record.user_preview || '--'}`,
            ),
        );
        item.appendChild(
            createCostElement(
                'p',
                'cost-reply-preview',
                `${COST_TEXT.reviewReplyLabel}: ${record.reply_preview || '--'}`,
            ),
        );
        list.appendChild(item);
    });

    container.appendChild(list);
}

export function renderCostSessionDetails(container, records = []) {
    container.textContent = '';
    if (!Array.isArray(records) || records.length === 0) {
        container.appendChild(createCostStateBlock(COST_TEXT.noSessionDetail, 'empty-state'));
        return;
    }

    const list = createCostElement('div', 'cost-reply-list');
    records.forEach((record) => {
        const item = createCostElement('article', 'cost-reply-item');
        const top = createCostElement('div', 'cost-reply-top');

        const title = createCostElement('div', 'cost-reply-title');
        title.appendChild(createCostElement('strong', '', normalizeCostModelName(record.model)));
        title.appendChild(createCostElement('span', 'cost-reply-time', formatCostDateTime(record.timestamp)));
        top.appendChild(title);

        const badges = createCostElement('div', 'cost-reply-badges');
        badges.appendChild(createCostElement('span', 'cost-session-chip', `${COST_TEXT.inputLabel} ${formatCostNumber(record.tokens?.user)}`));
        badges.appendChild(createCostElement('span', 'cost-session-chip', `${COST_TEXT.outputLabel} ${formatCostNumber(record.tokens?.reply)}`));
        badges.appendChild(createCostElement('span', 'cost-session-chip', `${COST_TEXT.totalLabel} ${formatCostNumber(record.tokens?.total)}`));
        badges.appendChild(
            createCostElement(
                'span',
                `cost-session-chip ${record.pricing_available ? 'is-cost' : 'is-pending'}`,
                record.pricing_available
                    ? formatCurrencyValue(record.currency, record.cost?.total_cost)
                    : COST_TEXT.pendingPricing,
            ),
        );
        if (record.estimated?.tokens || record.estimated?.pricing) {
            badges.appendChild(createCostElement('span', 'cost-session-chip is-estimated', COST_TEXT.estimatedData));
        }
        if (record.reply_quality?.feedback) {
            badges.appendChild(
                createCostElement(
                    'span',
                    `cost-session-chip ${record.reply_quality.feedback === 'helpful' ? 'is-cost' : 'is-pending'}`,
                    formatFeedbackLabel(record.reply_quality.feedback),
                ),
            );
        }
        top.appendChild(badges);
        item.appendChild(top);

        const metrics = createCostElement('div', 'cost-reply-metrics');
        metrics.appendChild(createCostElement('span', 'cost-reply-metric', `${COST_TEXT.providerMetric}${record.provider_id || '--'}`));
        metrics.appendChild(createCostElement('span', 'cost-reply-metric', `${COST_TEXT.presetMetric}${record.preset || '--'}`));
        metrics.appendChild(
            createCostElement(
                'span',
                'cost-reply-metric',
                `${COST_TEXT.feedbackMetric}${formatFeedbackLabel(record.reply_quality?.feedback)}`,
            ),
        );
        metrics.appendChild(
            createCostElement(
                'span',
                'cost-reply-metric',
                `${COST_TEXT.retrievalMetric}${formatRetrievalSummary(record.retrieval) || '--'}`,
            ),
        );
        metrics.appendChild(
            createCostElement(
                'span',
                'cost-reply-metric',
                `${COST_TEXT.inputAmountMetric}${formatCurrencyValue(record.currency, record.cost?.input_cost)}`,
            ),
        );
        metrics.appendChild(
            createCostElement(
                'span',
                'cost-reply-metric',
                `${COST_TEXT.outputAmountMetric}${formatCurrencyValue(record.currency, record.cost?.output_cost)}`,
            ),
        );
        item.appendChild(metrics);
        if (record.user_preview) {
            item.appendChild(createCostElement('p', 'cost-reply-preview', `${COST_TEXT.reviewContextLabel}: ${record.user_preview}`));
        }
        item.appendChild(createCostElement('p', 'cost-reply-preview', record.reply_preview || record.reply_text || ''));
        list.appendChild(item);
    });

    container.appendChild(list);
}
