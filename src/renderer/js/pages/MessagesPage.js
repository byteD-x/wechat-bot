import { PageController } from '../core/PageController.js';
import { Events } from '../core/EventBus.js';
import { apiService } from '../services/ApiService.js';
import { toast } from '../services/NotificationService.js';
import {
    createMessageStateBlock,
    formatMessageTime,
    matchesMessageFilter,
    MESSAGE_TEXT,
    normalizeRealtimeMessage,
} from './messages/formatters.js';
import {
    buildContactProfileDetail,
    buildContactProfileError,
    buildMessageDetail,
    renderMessageChatFilter,
    renderMessageList,
    renderMessageLoadMore,
    renderMessageSummary,
} from './messages/renderers.js';

export class MessagesPage extends PageController {
    constructor() {
        super('MessagesPage', 'page-messages');
        this._messages = [];
        this._chats = [];
        this._limit = 50;
        this._offset = 0;
        this._total = 0;
        this._hasMore = false;
        this._searchKeyword = '';
        this._selectedChatId = '';
        this._searchTimer = null;
        this._detailRequestToken = 0;
    }

    async onInit() {
        await super.onInit();
        this._bindEvents();
        this.watchState('bot.connected', () => {
            if (this.isActive()) {
                void this._refreshMessages();
            }
        });
        this.listenEvent(Events.MESSAGE_RECEIVED, (payload) => {
            this._handleRealtimeMessage(payload);
        });
    }

    async onEnter() {
        await super.onEnter();
        if (!this.getState('bot.connected') || this._messages.length === 0) {
            await this._refreshMessages();
            return;
        }
        this._render();
    }

    async onDestroy() {
        clearTimeout(this._searchTimer);
        await super.onDestroy();
    }

    _bindEvents() {
        this.bindEvent('#btn-refresh-messages', 'click', () => {
            void this._refreshMessages();
        });

        this.bindEvent('#btn-load-more-messages', 'click', () => {
            void this._loadMore();
        });

        const searchInput = this.$('#message-search');
        searchInput?.addEventListener('input', () => {
            clearTimeout(this._searchTimer);
            this._searchTimer = setTimeout(() => {
                this._searchKeyword = String(searchInput.value || '').trim();
                void this._refreshMessages();
            }, 250);
        });

        const chatFilter = this.$('#message-chat-filter');
        chatFilter?.addEventListener('change', () => {
            this._selectedChatId = String(chatFilter.value || '').trim();
            void this._refreshMessages();
        });

        document.getElementById('btn-close-message-detail')?.addEventListener('click', () => {
            this._closeDetailModal();
        });

        document.getElementById('message-detail-modal')?.addEventListener('click', (event) => {
            if (event.target?.id === 'message-detail-modal') {
                this._closeDetailModal();
            }
        });

        this.bindEvent(window, 'keydown', (event) => {
            if (event.key === 'Escape' && document.getElementById('message-detail-modal')?.classList.contains('active')) {
                this._closeDetailModal();
            }
        });
    }

    async _refreshMessages() {
        if (!this.getState('bot.connected')) {
            this._messages = [];
            this._chats = [];
            this._total = 0;
            this._offset = 0;
            this._hasMore = false;
            this._renderChatFilter();
            this._renderSummary();
            this._renderLoadMore();

            const container = this.$('#all-messages');
            if (container) {
                container.textContent = '';
                container.appendChild(createMessageStateBlock(MESSAGE_TEXT.offline, 'empty-state'));
            }
            return;
        }

        this._offset = 0;
        await this._fetchMessages({ append: false });
    }

    async _loadMore() {
        if (!this.getState('bot.connected') || !this._hasMore) {
            return;
        }
        await this._fetchMessages({ append: true });
    }

    async _fetchMessages({ append }) {
        const container = this.$('#all-messages');
        if (!append && container) {
            container.textContent = '';
            container.appendChild(createMessageStateBlock(MESSAGE_TEXT.loading));
        }

        try {
            const result = await apiService.getMessages({
                limit: this._limit,
                offset: this._offset,
                chatId: this._selectedChatId,
                keyword: this._searchKeyword,
            });

            if (!result?.success) {
                throw new Error(result?.message || MESSAGE_TEXT.loadFailed);
            }

            const nextMessages = Array.isArray(result.messages) ? result.messages : [];
            this._messages = append ? [...this._messages, ...nextMessages] : nextMessages;
            this._chats = Array.isArray(result.chats) ? result.chats : [];
            this._total = Number(result.total || 0);
            this._hasMore = Boolean(result.has_more);
            this._offset = this._messages.length;

            this._renderChatFilter();
            this._render();
            this.emit(Events.MESSAGES_LOADED, {
                total: this._total,
                visible: this._messages.length,
                hasMore: this._hasMore,
            });
        } catch (error) {
            console.error('[MessagesPage] load failed:', error);
            if (container) {
                container.textContent = '';
                container.appendChild(
                    createMessageStateBlock(toast.getErrorMessage(error, MESSAGE_TEXT.loadFailed), 'empty-state')
                );
            }
            toast.error(toast.getErrorMessage(error, MESSAGE_TEXT.loadFailed));
        }
    }

    _handleRealtimeMessage(payload) {
        if (!payload || !this.isActive()) {
            return;
        }

        const message = normalizeRealtimeMessage(payload);

        if (!this._matchesCurrentFilter(message)) {
            return;
        }

        this._messages = [message, ...this._messages].slice(0, Math.max(this._limit, this._messages.length + 1));
        this._total += 1;
        this._render();
    }

    _matchesCurrentFilter(message) {
        return matchesMessageFilter(message, {
            selectedChatId: this._selectedChatId,
            searchKeyword: this._searchKeyword,
        });
    }

    _renderChatFilter() {
        renderMessageChatFilter(this, this._chats, this._selectedChatId);
    }

    _render() {
        this._renderSummary();
        this._renderMessages();
        this._renderLoadMore();
    }

    _renderSummary() {
        renderMessageSummary(this, {
            selectedChatId: this._selectedChatId,
            searchKeyword: this._searchKeyword,
            messageCount: this._messages.length,
            total: this._total,
        });
    }

    _renderMessages() {
        renderMessageList(this, this._messages, (message) => this._openDetailModal(message));
    }

    _renderLoadMore() {
        renderMessageLoadMore(this, this._hasMore);
    }

    async _openDetailModal(message) {
        const modal = document.getElementById('message-detail-modal');
        const body = document.getElementById('message-detail-body');
        if (!modal || !body) {
            return;
        }

        const requestToken = ++this._detailRequestToken;
        body.textContent = '';
        body.appendChild(this._buildMessageDetail(message));
        modal.classList.add('active');

        if (!this.getState('bot.connected')) {
            body.appendChild(createMessageStateBlock(MESSAGE_TEXT.contactPromptOffline, 'empty-state'));
            return;
        }

        body.appendChild(createMessageStateBlock(MESSAGE_TEXT.contactPromptLoading));

        try {
            const result = await apiService.getContactProfile(message.wx_id || '');
            if (requestToken !== this._detailRequestToken) {
                return;
            }
            if (!result?.success) {
                throw new Error(result?.message || MESSAGE_TEXT.contactPromptLoadFailed);
            }
            body.textContent = '';
            body.appendChild(this._buildMessageDetail(message));
            body.appendChild(this._buildContactProfileDetail(message, result.profile || {}));
        } catch (error) {
            if (requestToken !== this._detailRequestToken) {
                return;
            }
            console.error('[MessagesPage] contact profile load failed:', error);
            body.textContent = '';
            body.appendChild(this._buildMessageDetail(message));
            body.appendChild(this._buildContactProfileError(error));
        }
    }

    _closeDetailModal() {
        this._detailRequestToken += 1;
        document.getElementById('message-detail-modal')?.classList.remove('active');
    }

    _buildMessageDetail(message) {
        return buildMessageDetail(message);
    }

    _buildContactProfileError(error) {
        return buildContactProfileError(
            toast.getErrorMessage(error, MESSAGE_TEXT.contactPromptLoadFailed)
        );
    }

    _buildContactProfileDetail(message, profile) {
        return buildContactProfileDetail(message, profile, {
            onEmptyPrompt: () => {
                toast.error(MESSAGE_TEXT.contactPromptEmpty);
            },
            onSavePrompt: async (nextMessage, nextPrompt, previousProfile) => {
                try {
                    const result = await apiService.saveContactPrompt(nextMessage.wx_id || '', nextPrompt);
                    if (!result?.success) {
                        throw new Error(result?.message || MESSAGE_TEXT.contactPromptSaveFailed);
                    }
                    toast.success(MESSAGE_TEXT.contactPromptSaveSuccess);
                    return result.profile || previousProfile;
                } catch (error) {
                    toast.error(toast.getErrorMessage(error, MESSAGE_TEXT.contactPromptSaveFailed));
                    return null;
                }
            },
        });
    }

    _formatTime(timestamp) {
        return formatMessageTime(timestamp);
    }
}

export default MessagesPage;
