import {
    createMessageStateBlock,
    formatMessageTime,
    formatPromptSource,
    MESSAGE_TEXT,
    truncateMessageText,
} from './formatters.js';

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
            parts.push(`${MESSAGE_TEXT.chatLabel}：${summaryState.selectedChatId}`);
        } else {
            parts.push(MESSAGE_TEXT.allMessages);
        }
        if (summaryState.searchKeyword) {
            parts.push(`${MESSAGE_TEXT.keywordLabel}：“${summaryState.searchKeyword}”`);
        }
        summary.textContent = parts.join(' · ');
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
        sender.textContent = String(message.sender || message.wx_id || MESSAGE_TEXT.user);

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
        chat.textContent = `${MESSAGE_TEXT.chatLabel}：${message.wx_id || '--'}`;

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

export function buildMessageDetail(message) {
    const root = document.createElement('div');
    root.className = 'detail-group';

    const title = document.createElement('div');
    title.className = 'detail-group-title';
    title.textContent = MESSAGE_TEXT.detailTitle;
    root.appendChild(title);

    const grid = document.createElement('div');
    grid.className = 'detail-grid';

    const fields = [
        [MESSAGE_TEXT.fieldSender, message.sender || '--'],
        [MESSAGE_TEXT.fieldChat, message.wx_id || '--'],
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
    promptLabel.textContent = MESSAGE_TEXT.contactPrompt;

    const promptInput = document.createElement('textarea');
    promptInput.className = 'detail-textarea';
    promptInput.rows = 12;
    promptInput.value = String(profile.contact_prompt || '');
    promptInput.placeholder = MESSAGE_TEXT.contactPromptEmpty;

    const hint = document.createElement('div');
    hint.className = 'detail-help';
    hint.textContent = '你可以直接编辑这份联系人专属 Prompt，后续系统会以当前保存版本为基础继续渐进式更新。';

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
    promptWrap.appendChild(actions);
    root.appendChild(promptWrap);

    return root;
}
