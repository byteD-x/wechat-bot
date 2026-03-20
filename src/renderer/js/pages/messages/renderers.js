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
    button.hidden = !hasMore;
    button.disabled = !hasMore;
}

export function buildMessageDetail(message, handlers = {}) {
    const root = document.createElement('div');
    root.className = 'detail-group';

    const title = document.createElement('div');
    title.className = 'detail-group-title';
    title.textContent = MESSAGE_TEXT.detailTitle;
    root.appendChild(title);

    const grid = document.createElement('div');
    grid.className = 'detail-grid';

    const fields = [
        [MESSAGE_TEXT.fieldSender, getMessageSenderDisplayName(message)],
        [MESSAGE_TEXT.fieldChat, getMessageChatDisplayName(message)],
        [MESSAGE_TEXT.fieldTime, formatMessageTime(message.timestamp) || '--'],
        [MESSAGE_TEXT.fieldDirection, message.is_self ? MESSAGE_TEXT.outgoing : MESSAGE_TEXT.incoming],
        [MESSAGE_TEXT.fieldType, String(message.msg_type || message.type || '--')],
    ];

    for (const [label, value] of fields) {
        const wrap = document.createElement('div');
        const span = document.createElement('span');
        span.textContent = label;
        const strong = document.createElement('strong');
        strong.textContent = String(value);
        wrap.appendChild(span);
        wrap.appendChild(strong);
        grid.appendChild(wrap);
    }

    root.appendChild(grid);

    const contentWrap = document.createElement('div');
    contentWrap.className = 'form-group full-width';

    const contentLabel = document.createElement('label');
    contentLabel.className = 'form-label';
    contentLabel.textContent = MESSAGE_TEXT.detailContent;

    const content = document.createElement('pre');
    content.className = 'prompt-preview-output';
    content.textContent = String(message.content || message.text || '');

    contentWrap.appendChild(contentLabel);
    contentWrap.appendChild(content);
    root.appendChild(contentWrap);

    const currentFeedback = String(
        message?.metadata?.reply_quality?.user_feedback || ''
    ).trim().toLowerCase();
    const isAssistantReply = message.is_self || String(message.role || '').trim().toLowerCase() === 'assistant';
    if (isAssistantReply && typeof handlers.onFeedback === 'function') {
        const feedbackWrap = document.createElement('div');
        feedbackWrap.className = 'form-group full-width';

        const feedbackLabel = document.createElement('label');
        feedbackLabel.className = 'form-label';
        feedbackLabel.textContent = MESSAGE_TEXT.feedbackTitle;

        const actions = document.createElement('div');
        actions.className = 'detail-actions';

        const buildFeedbackButton = (label, value) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = `btn ${currentFeedback === value ? 'btn-primary' : 'btn-secondary'} btn-sm`;
            button.textContent = label;
            button.addEventListener('click', async () => {
                const nextFeedback = currentFeedback === value ? '' : value;
                button.disabled = true;
                try {
                    const nextMessage = await handlers.onFeedback?.(message, nextFeedback, currentFeedback);
                    if (nextMessage) {
                        const nextSection = buildMessageDetail(nextMessage, handlers);
                        root.replaceWith(nextSection);
                    }
                } finally {
                    button.disabled = false;
                }
            });
            return button;
        };

        actions.appendChild(buildFeedbackButton(MESSAGE_TEXT.feedbackHelpful, 'helpful'));
        actions.appendChild(buildFeedbackButton(MESSAGE_TEXT.feedbackUnhelpful, 'unhelpful'));

        const hint = document.createElement('div');
        hint.className = 'detail-help';
        hint.textContent = MESSAGE_TEXT.feedbackHint;

        feedbackWrap.appendChild(feedbackLabel);
        feedbackWrap.appendChild(actions);
        feedbackWrap.appendChild(hint);
        root.appendChild(feedbackWrap);
    }

    return root;
}

export function buildContactProfileError(errorText) {
    const root = document.createElement('div');
    root.className = 'detail-group';

    const title = document.createElement('div');
    title.className = 'detail-group-title';
    title.textContent = MESSAGE_TEXT.profileTitle;
    root.appendChild(title);
    root.appendChild(createMessageStateBlock(errorText, 'empty-state'));
    return root;
}

export function buildContactProfileDetail(message, profile, handlers = {}) {
    const root = document.createElement('div');
    root.className = 'detail-group';

    const title = document.createElement('div');
    title.className = 'detail-group-title';
    title.textContent = MESSAGE_TEXT.profileTitle;

    const badge = document.createElement('span');
    badge.className = 'message-detail-badge';
    badge.textContent = formatPromptSource(profile.contact_prompt_source);
    title.appendChild(badge);
    root.appendChild(title);

    const grid = document.createElement('div');
    grid.className = 'detail-grid';
    const fields = [
        [MESSAGE_TEXT.fieldRelationship, profile.relationship || '--'],
        [MESSAGE_TEXT.fieldMessageCount, String(profile.message_count ?? '--')],
        [MESSAGE_TEXT.fieldEmotion, profile.last_emotion || '--'],
        [MESSAGE_TEXT.fieldUpdatedAt, formatMessageTime(profile.contact_prompt_updated_at || profile.updated_at) || '--'],
    ];
    for (const [label, value] of fields) {
        const wrap = document.createElement('div');
        const span = document.createElement('span');
        span.textContent = label;
        const strong = document.createElement('strong');
        strong.textContent = String(value);
        wrap.appendChild(span);
        wrap.appendChild(strong);
        grid.appendChild(wrap);
    }
    root.appendChild(grid);

    const summaryWrap = document.createElement('div');
    summaryWrap.className = 'form-group full-width';
    const summaryLabel = document.createElement('label');
    summaryLabel.className = 'form-label';
    summaryLabel.textContent = MESSAGE_TEXT.profileSummary;
    const summaryContent = document.createElement('pre');
    summaryContent.className = 'prompt-preview-output';
    summaryContent.textContent = String(profile.profile_summary || '--');
    summaryWrap.appendChild(summaryLabel);
    summaryWrap.appendChild(summaryContent);
    root.appendChild(summaryWrap);

    const promptWrap = document.createElement('div');
    promptWrap.className = 'form-group full-width';
    const promptLabel = document.createElement('label');
    promptLabel.className = 'form-label';
    promptLabel.textContent = MESSAGE_TEXT.contactPromptEditable;

    const promptInput = document.createElement('textarea');
    promptInput.className = 'detail-textarea';
    promptInput.rows = 12;
    promptInput.value = extractEditableSystemPrompt(String(profile.contact_prompt || ''));
    promptInput.placeholder = MESSAGE_TEXT.contactPromptEmpty;

    const hint = document.createElement('div');
    hint.className = 'detail-help';
    hint.textContent = MESSAGE_TEXT.contactPromptFixedHint;

    const fixedLabel = document.createElement('label');
    fixedLabel.className = 'form-label';
    fixedLabel.textContent = MESSAGE_TEXT.contactPromptFixed;

    const fixedBlock = document.createElement('textarea');
    fixedBlock.className = 'detail-textarea';
    fixedBlock.rows = 8;
    fixedBlock.readOnly = true;
    fixedBlock.value = getSystemPromptFixedBlock();

    const actions = document.createElement('div');
    actions.className = 'detail-actions';
    const saveButton = document.createElement('button');
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
                const nextSection = buildContactProfileDetail(message, nextProfile, handlers);
                root.replaceWith(nextSection);
            }
        } finally {
            saveButton.disabled = false;
        }
    });
    actions.appendChild(saveButton);

    promptWrap.appendChild(promptLabel);
    promptWrap.appendChild(promptInput);
    promptWrap.appendChild(hint);
    promptWrap.appendChild(fixedLabel);
    promptWrap.appendChild(fixedBlock);
    promptWrap.appendChild(actions);
    root.appendChild(promptWrap);

    return root;
}
