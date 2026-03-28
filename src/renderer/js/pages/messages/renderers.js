import {
    createMessageStateBlock,
    formatMessageTime,
    formatPromptSource,
    getMessageChatDisplayName,
    getMessageSenderDisplayName,
    MESSAGE_TEXT,
    truncateMessageText,
} from './formatters.js';
import {
    extractEditableSystemPrompt,
    getSystemPromptFixedBlock,
} from '../settings/form-codec.js';

function getRenderDocument(documentObj) {
    return documentObj || globalThis.document;
}

function buildInlineAction(documentObj, label, handler, tone = 'secondary') {
    const button = documentObj.createElement('button');
    button.type = 'button';
    button.className = `btn btn-${tone} btn-sm`;
    button.textContent = label;
    button.addEventListener('click', handler);
    return button;
}

export function renderMessageChatFilter(page, chats, selectedChatId) {
    const select = page.$('#message-chat-filter');
    if (!select) {
        return;
    }

    select.textContent = '';

    const allOption = document.createElement('option');
    allOption.value = '';
    allOption.textContent = MESSAGE_TEXT.allChats;
    select.appendChild(allOption);

    for (const chat of chats) {
        const option = document.createElement('option');
        const chatId = String(chat.chat_id || '').trim();
        const displayName = String(chat.display_name || chat.chat_id || MESSAGE_TEXT.unnamedChat);
        const count = Number(chat.message_count || 0).toLocaleString('zh-CN');
        option.value = chatId;
        option.textContent = `${displayName} (${count})`;
        select.appendChild(option);
    }

    select.value = selectedChatId;
}

export function renderMessageSummary(page, summaryState) {
    const summary = page.$('#message-filter-summary');
    const totalCount = page.$('#message-total-count');
    const updatedAt = page.$('#message-last-updated');

    if (summary) {
        const parts = [];
        if (summaryState.selectedChatId) {
            parts.push(`${MESSAGE_TEXT.chatLabel}: ${summaryState.selectedChatName || summaryState.selectedChatId}`);
        } else {
            parts.push(MESSAGE_TEXT.allMessages);
        }
        if (summaryState.searchKeyword) {
            parts.push(`${MESSAGE_TEXT.keywordLabel}: "${summaryState.searchKeyword}"`);
        }
        summary.textContent = parts.join(' / ');
    }

    if (totalCount) {
        totalCount.textContent = `${summaryState.messageCount}/${summaryState.total} ${MESSAGE_TEXT.linesSuffix}`;
    }

    if (updatedAt) {
        if (!summaryState.lastLoadedAt) {
            updatedAt.textContent = '尚未刷新';
            return;
        }
        updatedAt.textContent = `更新于 ${new Intl.DateTimeFormat('zh-CN', {
            hour: '2-digit',
            minute: '2-digit',
        }).format(summaryState.lastLoadedAt)}`;
    }
}

export function renderMessageList(page, messages, onOpenDetail) {
    const container = page.$('#all-messages');
    if (!container) {
        return;
    }

    container.textContent = '';

    if (messages.length === 0) {
        container.appendChild(createMessageStateBlock(MESSAGE_TEXT.noMatch, 'empty-state'));
        return;
    }

    const fragment = document.createDocumentFragment();
    messages.forEach((message, index) => {
        const item = document.createElement('button');
        item.type = 'button';
        item.className = `message-item ${message.is_self ? 'is-self' : 'is-user'}`;
        item.style.animationDelay = `${Math.min(index, 12) * 0.03}s`;

        const avatar = document.createElement('div');
        avatar.className = 'message-avatar';
        avatar.textContent = message.is_self ? MESSAGE_TEXT.assistant : MESSAGE_TEXT.user;

        const body = document.createElement('div');
        body.className = 'message-body';

        const meta = document.createElement('div');
        meta.className = 'message-meta';

        const sender = document.createElement('span');
        sender.className = 'message-sender';
        sender.textContent = getMessageSenderDisplayName(message);

        const time = document.createElement('span');
        time.className = 'message-time';
        time.textContent = formatMessageTime(message.timestamp);

        meta.appendChild(sender);
        meta.appendChild(time);

        const text = document.createElement('div');
        text.className = 'message-text';
        text.textContent = truncateMessageText(message.content || message.text || '', 180);

        const chat = document.createElement('div');
        chat.className = 'message-time';
        chat.textContent = `${MESSAGE_TEXT.chatLabel}: ${getMessageChatDisplayName(message)}`;

        body.appendChild(meta);
        body.appendChild(text);
        body.appendChild(chat);
        item.appendChild(avatar);
        item.appendChild(body);
        item.addEventListener('click', () => {
            void onOpenDetail?.(message);
        });
        fragment.appendChild(item);
    });

    container.appendChild(fragment);
}

export function renderMessageLoadMore(page, hasMore) {
    const button = page.$('#btn-load-more-messages');
    if (!button) {
        return;
    }
    if (!button.dataset.defaultLabel) {
        button.dataset.defaultLabel = String(button.textContent || '').trim() || '加载更多';
    }
    button.hidden = !hasMore;
    button.disabled = !hasMore || !!page._loadingMore;
    button.textContent = page._loadingMore ? '加载中...' : button.dataset.defaultLabel;
}

export function buildMessageDetail(message, handlers = {}) {
    const documentObj = getRenderDocument(handlers.documentObj);
    const root = documentObj.createElement('div');
    root.className = 'detail-group';

    const title = documentObj.createElement('div');
    title.className = 'detail-group-title';
    title.textContent = MESSAGE_TEXT.detailTitle;
    root.appendChild(title);

    const grid = documentObj.createElement('div');
    grid.className = 'detail-grid';

    const fields = [
        [MESSAGE_TEXT.fieldSender, getMessageSenderDisplayName(message)],
        [MESSAGE_TEXT.fieldChat, getMessageChatDisplayName(message)],
        [MESSAGE_TEXT.fieldTime, formatMessageTime(message.timestamp) || '--'],
        [MESSAGE_TEXT.fieldDirection, message.is_self ? MESSAGE_TEXT.outgoing : MESSAGE_TEXT.incoming],
        [MESSAGE_TEXT.fieldType, String(message.msg_type || message.type || '--')],
    ];

    for (const [label, value] of fields) {
        const wrap = documentObj.createElement('div');
        const span = documentObj.createElement('span');
        span.textContent = label;
        const strong = documentObj.createElement('strong');
        strong.textContent = String(value);
        wrap.appendChild(span);
        wrap.appendChild(strong);
        grid.appendChild(wrap);
    }

    root.appendChild(grid);

    const contentWrap = documentObj.createElement('div');
    contentWrap.className = 'form-group full-width';

    const contentLabel = documentObj.createElement('label');
    contentLabel.className = 'form-label';
    contentLabel.textContent = MESSAGE_TEXT.detailContent;

    const content = documentObj.createElement('pre');
    content.className = 'prompt-preview-output';
    content.textContent = String(message.content || message.text || '');

    contentWrap.appendChild(contentLabel);
    contentWrap.appendChild(content);
    if (typeof handlers.onCopy === 'function') {
        const contentActions = documentObj.createElement('div');
        contentActions.className = 'detail-actions';
        contentActions.appendChild(buildInlineAction(documentObj, '复制内容', () => {
            void handlers.onCopy?.(String(message.content || message.text || ''), '消息内容');
        }));
        contentWrap.appendChild(contentActions);
    }
    root.appendChild(contentWrap);

    const currentFeedback = String(
        message?.metadata?.reply_quality?.user_feedback || ''
    ).trim().toLowerCase();
    const isAssistantReply = message.is_self || String(message.role || '').trim().toLowerCase() === 'assistant';
    if (isAssistantReply && typeof handlers.onFeedback === 'function') {
        const feedbackWrap = documentObj.createElement('div');
        feedbackWrap.className = 'form-group full-width';

        const feedbackLabel = documentObj.createElement('label');
        feedbackLabel.className = 'form-label';
        feedbackLabel.textContent = MESSAGE_TEXT.feedbackTitle;

        const actions = documentObj.createElement('div');
        actions.className = 'detail-actions';
        const feedbackButtons = [];
        let feedbackBusy = false;

        const buildFeedbackButton = (label, value) => {
            const button = documentObj.createElement('button');
            button.type = 'button';
            button.className = `btn ${currentFeedback === value ? 'btn-primary' : 'btn-secondary'} btn-sm`;
            button.textContent = label;
            feedbackButtons.push(button);
            button.addEventListener('click', async () => {
                if (feedbackBusy) {
                    return;
                }
                const nextFeedback = currentFeedback === value ? '' : value;
                feedbackBusy = true;
                feedbackButtons.forEach((item) => {
                    item.disabled = true;
                });
                try {
                    const nextMessage = await handlers.onFeedback?.(message, nextFeedback, currentFeedback);
                    if (nextMessage) {
                        const nextSection = buildMessageDetail(nextMessage, handlers);
                        root.replaceWith(nextSection);
                    }
                } finally {
                    feedbackBusy = false;
                    feedbackButtons.forEach((item) => {
                        item.disabled = false;
                    });
                }
            });
            return button;
        };

        actions.appendChild(buildFeedbackButton(MESSAGE_TEXT.feedbackHelpful, 'helpful'));
        actions.appendChild(buildFeedbackButton(MESSAGE_TEXT.feedbackUnhelpful, 'unhelpful'));

        const hint = documentObj.createElement('div');
        hint.className = 'detail-help';
        hint.textContent = MESSAGE_TEXT.feedbackHint;

        feedbackWrap.appendChild(feedbackLabel);
        feedbackWrap.appendChild(actions);
        feedbackWrap.appendChild(hint);
        root.appendChild(feedbackWrap);
    }

    return root;
}

export function buildContactProfileError(errorText, handlers = {}) {
    const documentObj = getRenderDocument(handlers.documentObj);
    const root = documentObj.createElement('div');
    root.className = 'detail-group';

    const title = documentObj.createElement('div');
    title.className = 'detail-group-title';
    title.textContent = MESSAGE_TEXT.profileTitle;
    root.appendChild(title);
    root.appendChild(createMessageStateBlock(errorText, 'empty-state'));
    return root;
}

export function buildContactProfileDetail(message, profile, handlers = {}) {
    const documentObj = getRenderDocument(handlers.documentObj);
    const root = documentObj.createElement('div');
    root.className = 'detail-group';

    const title = documentObj.createElement('div');
    title.className = 'detail-group-title';
    title.textContent = MESSAGE_TEXT.profileTitle;

    const badge = documentObj.createElement('span');
    badge.className = 'message-detail-badge';
    badge.textContent = formatPromptSource(profile.contact_prompt_source);
    title.appendChild(badge);
    root.appendChild(title);

    const grid = documentObj.createElement('div');
    grid.className = 'detail-grid';
    const fields = [
        [MESSAGE_TEXT.fieldRelationship, profile.relationship || '--'],
        [MESSAGE_TEXT.fieldMessageCount, String(profile.message_count ?? '--')],
        [MESSAGE_TEXT.fieldEmotion, profile.last_emotion || '--'],
        [MESSAGE_TEXT.fieldUpdatedAt, formatMessageTime(profile.contact_prompt_updated_at || profile.updated_at) || '--'],
    ];
    for (const [label, value] of fields) {
        const wrap = documentObj.createElement('div');
        const span = documentObj.createElement('span');
        span.textContent = label;
        const strong = documentObj.createElement('strong');
        strong.textContent = String(value);
        wrap.appendChild(span);
        wrap.appendChild(strong);
        grid.appendChild(wrap);
    }
    root.appendChild(grid);

    const summaryWrap = documentObj.createElement('div');
    summaryWrap.className = 'form-group full-width';
    const summaryLabel = documentObj.createElement('label');
    summaryLabel.className = 'form-label';
    summaryLabel.textContent = MESSAGE_TEXT.profileSummary;
    const summaryContent = documentObj.createElement('pre');
    summaryContent.className = 'prompt-preview-output';
    summaryContent.textContent = String(profile.profile_summary || '--');
    summaryWrap.appendChild(summaryLabel);
    summaryWrap.appendChild(summaryContent);
    if (typeof handlers.onCopy === 'function') {
        const summaryActions = documentObj.createElement('div');
        summaryActions.className = 'detail-actions';
        summaryActions.appendChild(buildInlineAction(documentObj, '复制画像摘要', () => {
            void handlers.onCopy?.(String(profile.profile_summary || ''), '画像摘要');
        }));
        summaryWrap.appendChild(summaryActions);
    }
    root.appendChild(summaryWrap);

    const promptWrap = documentObj.createElement('div');
    promptWrap.className = 'form-group full-width';
    const promptLabel = documentObj.createElement('label');
    promptLabel.className = 'form-label';
    promptLabel.textContent = MESSAGE_TEXT.contactPromptEditable;

    const promptInput = documentObj.createElement('textarea');
    promptInput.className = 'detail-textarea';
    promptInput.rows = 12;
    promptInput.value = extractEditableSystemPrompt(String(profile.contact_prompt || ''));
    promptInput.placeholder = MESSAGE_TEXT.contactPromptEmpty;

    const hint = documentObj.createElement('div');
    hint.className = 'detail-help';
    hint.textContent = MESSAGE_TEXT.contactPromptFixedHint;

    const fixedLabel = documentObj.createElement('label');
    fixedLabel.className = 'form-label';
    fixedLabel.textContent = MESSAGE_TEXT.contactPromptFixed;

    const fixedBlock = documentObj.createElement('textarea');
    fixedBlock.className = 'detail-textarea';
    fixedBlock.rows = 8;
    fixedBlock.readOnly = true;
    fixedBlock.value = getSystemPromptFixedBlock();

    const actions = documentObj.createElement('div');
    actions.className = 'detail-actions';
    const saveButton = documentObj.createElement('button');
    saveButton.type = 'button';
    saveButton.className = 'btn btn-primary btn-sm';
    saveButton.textContent = MESSAGE_TEXT.contactPromptSave;
    saveButton.addEventListener('click', async () => {
        const nextPrompt = String(promptInput.value || '').trim();
        if (!nextPrompt) {
            handlers.onEmptyPrompt?.();
            return;
        }
        saveButton.disabled = true;
        try {
            const nextProfile = await handlers.onSavePrompt?.(message, nextPrompt, profile);
            if (nextProfile) {
                const nextSection = buildContactProfileDetail(message, nextProfile, {
                    ...handlers,
                    documentObj,
                });
                root.replaceWith(nextSection);
            }
        } finally {
            saveButton.disabled = false;
        }
    });
    actions.appendChild(saveButton);
    actions.appendChild(buildInlineAction(documentObj, '恢复当前值', () => {
        promptInput.value = extractEditableSystemPrompt(String(profile.contact_prompt || ''));
    }));
    if (typeof handlers.onCopy === 'function') {
        actions.appendChild(buildInlineAction(documentObj, '复制固定注入块', () => {
            void handlers.onCopy?.(getSystemPromptFixedBlock(), '固定注入块');
        }));
    }

    promptWrap.appendChild(promptLabel);
    promptWrap.appendChild(promptInput);
    promptWrap.appendChild(hint);
    promptWrap.appendChild(fixedLabel);
    promptWrap.appendChild(fixedBlock);
    promptWrap.appendChild(actions);
    root.appendChild(promptWrap);

    return root;
}

function findPerChatOverride(policy = {}, chatId = '') {
    const target = String(chatId || '').trim();
    const items = Array.isArray(policy?.per_chat_overrides) ? policy.per_chat_overrides : [];
    return items.find((item) => String(item?.chat_id || '').trim() === target) || null;
}

function buildPolicyOption(documentObj, value, label) {
    const option = documentObj.createElement('option');
    option.value = value;
    option.textContent = label;
    return option;
}

export function buildReplyApprovalDetail(message, context = {}, handlers = {}) {
    const documentObj = getRenderDocument(handlers.documentObj);
    const root = documentObj.createElement('div');
    root.className = 'detail-group';

    const title = documentObj.createElement('div');
    title.className = 'detail-group-title';
    title.textContent = '回复策略与审批';
    root.appendChild(title);

    const policy = context.replyPolicy || {};
    const pendingReplies = Array.isArray(context.pendingReplies) ? context.pendingReplies : [];
    const chatId = String(message.wx_id || message.chat_id || '').trim();
    const chatOverride = findPerChatOverride(policy, chatId);
    const currentMode = String(chatOverride?.mode || '').trim().toLowerCase();

    const grid = documentObj.createElement('div');
    grid.className = 'detail-grid';
    [
        ['默认模式', String(policy.default_mode || 'auto')],
        ['新联系人', String(policy.new_contact_mode || 'manual')],
        ['群聊模式', String(policy.group_mode || 'whitelist_only')],
        ['待审批数', String(pendingReplies.length)],
    ].forEach(([label, value]) => {
        const wrap = documentObj.createElement('div');
        const span = documentObj.createElement('span');
        span.textContent = label;
        const strong = documentObj.createElement('strong');
        strong.textContent = value;
        wrap.appendChild(span);
        wrap.appendChild(strong);
        grid.appendChild(wrap);
    });
    root.appendChild(grid);

    const overrideWrap = documentObj.createElement('div');
    overrideWrap.className = 'form-group full-width';

    const overrideLabel = documentObj.createElement('label');
    overrideLabel.className = 'form-label';
    overrideLabel.textContent = '当前会话审批模式';

    const overrideSelect = documentObj.createElement('select');
    overrideSelect.className = 'detail-textarea';
    overrideSelect.appendChild(buildPolicyOption(documentObj, '', '跟随默认策略'));
    overrideSelect.appendChild(buildPolicyOption(documentObj, 'auto', '始终自动发送'));
    overrideSelect.appendChild(buildPolicyOption(documentObj, 'manual', '始终进入审批'));
    overrideSelect.value = currentMode;

    const overrideHint = documentObj.createElement('div');
    overrideHint.className = 'detail-help';
    overrideHint.textContent = '这里只覆盖当前会话，优先级高于敏感词、静音时段和默认规则。';

    const overrideActions = documentObj.createElement('div');
    overrideActions.className = 'detail-actions';
    const overrideButton = documentObj.createElement('button');
    overrideButton.type = 'button';
    overrideButton.className = 'btn btn-secondary btn-sm';
    overrideButton.textContent = '保存会话策略';
    overrideButton.addEventListener('click', async () => {
        overrideButton.disabled = true;
        try {
            await handlers.onSaveOverride?.(message, overrideSelect.value);
        } finally {
            overrideButton.disabled = false;
        }
    });
    overrideActions.appendChild(overrideButton);
    overrideActions.appendChild(buildInlineAction(documentObj, '恢复默认', () => {
        overrideSelect.value = '';
    }));

    overrideWrap.appendChild(overrideLabel);
    overrideWrap.appendChild(overrideSelect);
    overrideWrap.appendChild(overrideHint);
    overrideWrap.appendChild(overrideActions);
    root.appendChild(overrideWrap);

    const pendingWrap = documentObj.createElement('div');
    pendingWrap.className = 'form-group full-width';

    const pendingLabel = documentObj.createElement('label');
    pendingLabel.className = 'form-label';
    pendingLabel.textContent = '待审批回复';
    pendingWrap.appendChild(pendingLabel);

    if (pendingReplies.length === 0) {
        pendingWrap.appendChild(createMessageStateBlock('当前没有待审批回复。', 'empty-state'));
        root.appendChild(pendingWrap);
        return root;
    }

    pendingReplies.forEach((pendingReply) => {
        const item = documentObj.createElement('div');
        item.className = 'detail-group';

        const itemTitle = documentObj.createElement('div');
        itemTitle.className = 'detail-group-title';
        itemTitle.textContent = `待审批 #${pendingReply.id}`;

        const badge = documentObj.createElement('span');
        badge.className = 'message-detail-badge';
        badge.textContent = String(pendingReply.trigger_reason || 'manual_review');
        itemTitle.appendChild(badge);
        item.appendChild(itemTitle);

        const textarea = documentObj.createElement('textarea');
        textarea.className = 'detail-textarea';
        textarea.rows = 5;
        textarea.value = String(pendingReply.draft_reply || '');
        item.appendChild(textarea);

        const meta = documentObj.createElement('div');
        meta.className = 'detail-help';
        meta.textContent = `创建时间：${formatMessageTime(pendingReply.created_at) || '--'}`;
        item.appendChild(meta);

        const actions = documentObj.createElement('div');
        actions.className = 'detail-actions';

        const approveButton = documentObj.createElement('button');
        approveButton.type = 'button';
        approveButton.className = 'btn btn-primary btn-sm';
        approveButton.textContent = '批准并发送';
        approveButton.addEventListener('click', async () => {
            approveButton.disabled = true;
            rejectButton.disabled = true;
            try {
                await handlers.onApprovePending?.(message, pendingReply, textarea.value);
            } finally {
                approveButton.disabled = false;
                rejectButton.disabled = false;
            }
        });

        const rejectButton = documentObj.createElement('button');
        rejectButton.type = 'button';
        rejectButton.className = 'btn btn-secondary btn-sm';
        rejectButton.textContent = '拒绝';
        rejectButton.addEventListener('click', async () => {
            approveButton.disabled = true;
            rejectButton.disabled = true;
            try {
                await handlers.onRejectPending?.(message, pendingReply);
            } finally {
                approveButton.disabled = false;
                rejectButton.disabled = false;
            }
        });

        actions.appendChild(approveButton);
        actions.appendChild(rejectButton);
        item.appendChild(actions);
        pendingWrap.appendChild(item);
    });

    root.appendChild(pendingWrap);
    return root;
}
