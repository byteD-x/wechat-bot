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
        lastLoadedAt: page._lastLoadedAt,
    });
}

function renderMessages(page, deps = {}) {
    const onOpenDetail = deps.onOpenDetail || page._openMessageDetail || (() => {});
    renderMessageList(page, page._messages, (message) => onOpenDetail(message));
}

function renderLoadMore(page) {
    renderMessageLoadMore(page, page._hasMore);
}

function renderRefreshButton(page) {
    const button = page.$('#btn-refresh-messages');
    if (!button) {
        return;
    }
    if (!button.dataset.defaultLabel) {
        button.dataset.defaultLabel = String(button.textContent || '').trim() || '刷新';
    }
    button.disabled = !!page._refreshing;
    button.textContent = page._refreshing ? '刷新中...' : button.dataset.defaultLabel;
}

function markMessagesRequest(page) {
    const nextSeq = Number(page._messagesRequestSeq || 0) + 1;
    page._messagesRequestSeq = nextSeq;
    page._latestMessagesRequestSeq = nextSeq;
    return nextSeq;
}

function isLatestMessagesRequest(page, seq) {
    return Number(page._latestMessagesRequestSeq || 0) === Number(seq || 0);
}

function renderMessageFailureState(page, message, deps = {}) {
    const container = page.$('#all-messages');
    if (!container) {
        return;
    }
    container.textContent = '';
    container.appendChild(createMessageStateBlock(message, 'empty-state'));

    const actions = document.createElement('div');
    actions.className = 'state-actions';

    const retryButton = document.createElement('button');
    retryButton.type = 'button';
    retryButton.className = 'btn btn-primary btn-sm';
    retryButton.textContent = '重试';
    retryButton.addEventListener('click', () => {
        void refreshMessages(page, deps);
    });
    actions.appendChild(retryButton);

    if (page._searchKeyword || page._selectedChatId) {
        const resetButton = document.createElement('button');
        resetButton.type = 'button';
        resetButton.className = 'btn btn-secondary btn-sm';
        resetButton.textContent = '清空筛选';
        resetButton.addEventListener('click', () => {
            page._searchKeyword = '';
            page._selectedChatId = '';
            const searchInput = page.$('#message-search');
            const chatFilter = page.$('#message-chat-filter');
            if (searchInput) {
                searchInput.value = '';
            }
            if (chatFilter) {
                chatFilter.value = '';
            }
            void refreshMessages(page, deps);
        });
        actions.appendChild(resetButton);
    }

    container.appendChild(actions);
}

export function renderMessagesPage(page, deps = {}) {
    renderSummary(page);
    renderMessages(page, deps);
    renderLoadMore(page);
    renderRefreshButton(page);
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
        page._refreshing = false;
        page._pendingRefresh = false;
        renderRefreshButton(page);
        return;
    }

    if (page._refreshing) {
        page._pendingRefresh = true;
        return;
    }

    page._refreshing = true;
    page._pendingRefresh = false;
    renderRefreshButton(page);
    page._offset = 0;
    const requestSeq = markMessagesRequest(page);
    try {
        await fetchMessages(page, { append: false, requestSeq }, deps);
    } finally {
        page._refreshing = false;
        renderRefreshButton(page);
        if (page._pendingRefresh) {
            page._pendingRefresh = false;
            void refreshMessages(page, deps);
        }
    }
}

export async function loadMoreMessages(page, deps = {}) {
    if (!page.getState('bot.connected') || !page._hasMore || page._loadingMore || page._refreshing) {
        return;
    }
    page._loadingMore = true;
    renderLoadMore(page);
    const requestSeq = markMessagesRequest(page);
    try {
        await fetchMessages(page, { append: true, requestSeq }, deps);
    } finally {
        page._loadingMore = false;
        renderLoadMore(page);
    }
}

export async function fetchMessages(page, { append, requestSeq }, deps = {}) {
    const activeRequestSeq = Number(requestSeq || markMessagesRequest(page));
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
        if (!isLatestMessagesRequest(page, activeRequestSeq)) {
            return;
        }

        const nextMessages = Array.isArray(result.messages) ? result.messages : [];
        page._messages = append ? [...page._messages, ...nextMessages] : nextMessages;
        page._chats = Array.isArray(result.chats) ? result.chats : [];
        page._total = Number(result.total || 0);
        page._hasMore = Boolean(result.has_more);
        page._offset = page._messages.length;
        page._lastLoadedAt = Date.now();

        renderChatFilter(page);
        renderMessagesPage(page, deps);
        page.emit(Events.MESSAGES_LOADED, {
            total: page._total,
            visible: page._messages.length,
            hasMore: page._hasMore,
        });
    } catch (error) {
        if (!isLatestMessagesRequest(page, activeRequestSeq)) {
            return;
        }
        console.error('[MessagesPage] load failed:', error);
        renderMessageFailureState(page, currentToast.getErrorMessage(error, MESSAGE_TEXT.loadFailed), deps);
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

    const normalizeKey = (item) => {
        if (!item || typeof item !== 'object') {
            return '';
        }
        const explicitId = item.id ?? item.message_id;
        if (explicitId !== undefined && explicitId !== null && explicitId !== '') {
            return `id:${String(explicitId)}`;
        }
        return [
            String(item.wx_id || ''),
            String(item.timestamp || ''),
            String(item.role || ''),
            String(item.content || ''),
        ].join('|');
    };

    const incomingKey = normalizeKey(message);
    if (incomingKey && (page._messages || []).some((item) => normalizeKey(item) === incomingKey)) {
        return;
    }

    page._messages = [message, ...page._messages];
    page._total += 1;
    page._offset = Math.max(0, Number(page._offset || 0) + 1);
    renderMessagesPage(page, deps);
}
