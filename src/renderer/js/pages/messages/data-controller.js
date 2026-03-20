import { Events } from '../../core/EventBus.js';
import { apiService } from '../../services/ApiService.js';
import { toast } from '../../services/NotificationService.js';
import {
    createMessageStateBlock,
    matchesMessageFilter,
    MESSAGE_TEXT,
    normalizeRealtimeMessage,
} from './formatters.js';
import {
    renderMessageChatFilter,
    renderMessageList,
    renderMessageLoadMore,
    renderMessageSummary,
} from './renderers.js';

function getApiService(deps = {}) {
    return deps.apiService || apiService;
}

function getToast(deps = {}) {
    return deps.toast || toast;
}

function renderChatFilter(page) {
    renderMessageChatFilter(page, page._chats, page._selectedChatId);
}

function renderSummary(page) {
    const selectedChat = (page._chats || []).find(
        (chat) => String(chat?.chat_id || '').trim() === String(page._selectedChatId || '').trim()
    );
    renderMessageSummary(page, {
        selectedChatId: page._selectedChatId,
        selectedChatName: String(selectedChat?.display_name || '').trim(),
        searchKeyword: page._searchKeyword,
        messageCount: page._messages.length,
        total: page._total,
    });
}

function renderMessages(page, deps = {}) {
    const onOpenDetail = deps.onOpenDetail || page._openMessageDetail || (() => {});
    renderMessageList(page, page._messages, (message) => onOpenDetail(message));
}

function renderLoadMore(page) {
    renderMessageLoadMore(page, page._hasMore);
}

export function renderMessagesPage(page, deps = {}) {
    renderSummary(page);
    renderMessages(page, deps);
    renderLoadMore(page);
}

export async function refreshMessages(page, deps = {}) {
    if (!page.getState('bot.connected')) {
        page._messages = [];
        page._chats = [];
        page._total = 0;
        page._offset = 0;
        page._hasMore = false;
        renderChatFilter(page);
        renderSummary(page);
        renderLoadMore(page);

        const container = page.$('#all-messages');
        if (container) {
            container.textContent = '';
            container.appendChild(createMessageStateBlock(MESSAGE_TEXT.offline, 'empty-state'));
        }
        return;
    }

    page._offset = 0;
    await fetchMessages(page, { append: false }, deps);
}

export async function loadMoreMessages(page, deps = {}) {
    if (!page.getState('bot.connected') || !page._hasMore) {
        return;
    }
    await fetchMessages(page, { append: true }, deps);
}

export async function fetchMessages(page, { append }, deps = {}) {
    const currentToast = getToast(deps);
    const container = page.$('#all-messages');
    if (!append && container) {
        container.textContent = '';
        container.appendChild(createMessageStateBlock(MESSAGE_TEXT.loading));
    }

    try {
        const result = await getApiService(deps).getMessages({
            limit: page._limit,
            offset: page._offset,
            chatId: page._selectedChatId,
            keyword: page._searchKeyword,
        });

        if (!result?.success) {
            throw new Error(result?.message || MESSAGE_TEXT.loadFailed);
        }

        const nextMessages = Array.isArray(result.messages) ? result.messages : [];
        page._messages = append ? [...page._messages, ...nextMessages] : nextMessages;
        page._chats = Array.isArray(result.chats) ? result.chats : [];
        page._total = Number(result.total || 0);
        page._hasMore = Boolean(result.has_more);
        page._offset = page._messages.length;

        renderChatFilter(page);
        renderMessagesPage(page, deps);
        page.emit(Events.MESSAGES_LOADED, {
            total: page._total,
            visible: page._messages.length,
            hasMore: page._hasMore,
        });
    } catch (error) {
        console.error('[MessagesPage] load failed:', error);
        if (container) {
            container.textContent = '';
            container.appendChild(
                createMessageStateBlock(currentToast.getErrorMessage(error, MESSAGE_TEXT.loadFailed), 'empty-state')
            );
        }
        currentToast.error(currentToast.getErrorMessage(error, MESSAGE_TEXT.loadFailed));
    }
}

export function handleRealtimeMessage(page, payload, deps = {}) {
    if (!payload || !page.isActive()) {
        return;
    }

    const message = normalizeRealtimeMessage(payload);

    if (!matchesMessageFilter(message, {
        selectedChatId: page._selectedChatId,
        searchKeyword: page._searchKeyword,
    })) {
        return;
    }

    page._messages = [message, ...page._messages].slice(0, Math.max(page._limit, page._messages.length + 1));
    page._total += 1;
    renderMessagesPage(page, deps);
}
