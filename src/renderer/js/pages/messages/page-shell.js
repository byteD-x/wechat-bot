import { Events } from '../../core/EventBus.js';
import {
    handleRealtimeMessage,
    loadMoreMessages,
    refreshMessages,
} from './data-controller.js';
import {
    closeDetailModal,
    openDetailModal,
} from './detail-controller.js';

function getDocument(deps = {}) {
    return deps.documentObj || globalThis.document;
}

function getWindow(deps = {}) {
    return deps.windowObj || globalThis.window;
}

export function bindMessagesPage(page, deps = {}) {
    const runRefreshMessages = deps.refreshMessages || refreshMessages;
    const runLoadMoreMessages = deps.loadMoreMessages || loadMoreMessages;
    const runOpenDetailModal = deps.openDetailModal || openDetailModal;
    const runCloseDetailModal = deps.closeDetailModal || closeDetailModal;
    const runHandleRealtimeMessage = deps.handleRealtimeMessage || handleRealtimeMessage;
    const createOpenDetail = () => (message) => runOpenDetailModal(page, message, deps);

    page.bindEvent('#btn-refresh-messages', 'click', () => {
        void runRefreshMessages(page, {
            ...deps,
            onOpenDetail: createOpenDetail(),
        });
    });

    page.bindEvent('#btn-load-more-messages', 'click', () => {
        void runLoadMoreMessages(page, {
            ...deps,
            onOpenDetail: createOpenDetail(),
        });
    });

    const searchInput = page.$('#message-search');
    searchInput?.addEventListener('input', () => {
        const clearTimeoutFn = deps.clearTimeoutFn || globalThis.clearTimeout;
        const setTimeoutFn = deps.setTimeoutFn || globalThis.setTimeout;
        clearTimeoutFn(page._searchTimer);
        page._searchTimer = setTimeoutFn(() => {
            page._searchKeyword = String(searchInput.value || '').trim();
            void runRefreshMessages(page, {
                ...deps,
                onOpenDetail: createOpenDetail(),
            });
        }, 250);
    });

    const chatFilter = page.$('#message-chat-filter');
    chatFilter?.addEventListener('change', () => {
        page._selectedChatId = String(chatFilter.value || '').trim();
        void runRefreshMessages(page, {
            ...deps,
            onOpenDetail: createOpenDetail(),
        });
    });

    const documentObj = getDocument(deps);
    documentObj.getElementById('btn-close-message-detail')?.addEventListener('click', () => {
        runCloseDetailModal(page, deps);
    });

    documentObj.getElementById('message-detail-modal')?.addEventListener('click', (event) => {
        if (event.target?.id === 'message-detail-modal') {
            runCloseDetailModal(page, deps);
        }
    });

    page.bindEvent(getWindow(deps), 'keydown', (event) => {
        if (event.key === 'Escape' && documentObj.getElementById('message-detail-modal')?.classList.contains('active')) {
            runCloseDetailModal(page, deps);
        }
    });

    page.watchState('bot.connected', () => {
        if (page.isActive()) {
            void runRefreshMessages(page, {
                ...deps,
                onOpenDetail: createOpenDetail(),
            });
        }
    });

    page.listenEvent?.(Events.MESSAGE_RECEIVED, (payload) => {
        runHandleRealtimeMessage(page, payload, {
            ...deps,
            onOpenDetail: createOpenDetail(),
        });
    });
}
