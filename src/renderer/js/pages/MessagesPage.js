import { PageController } from '../core/PageController.js';
import { Events } from '../core/EventBus.js';
import { apiService } from '../services/ApiService.js';
import { toast } from '../services/NotificationService.js';

const TEXT = {
    loading: '\u52a0\u8f7d\u4e2d...',
    loadFailed: '\u52a0\u8f7d\u6d88\u606f\u5931\u8d25',
    offline: '\u8bf7\u5148\u542f\u52a8 Python \u670d\u52a1\u540e\u67e5\u770b\u6d88\u606f',
    allChats: '\u5168\u90e8\u4f1a\u8bdd',
    unnamedChat: '\u672a\u547d\u540d\u4f1a\u8bdd',
    allMessages: '\u5168\u90e8\u6d88\u606f',
    noMatch: '\u6682\u65e0\u5339\u914d\u6d88\u606f',
    user: '\u7528\u6237',
    assistant: 'AI',
    detailTitle: '\u6d88\u606f\u8be6\u60c5',
    detailContent: '\u6d88\u606f\u5185\u5bb9',
    fieldSender: '\u53d1\u9001\u8005',
    fieldChat: '\u4f1a\u8bdd',
    fieldTime: '\u65f6\u95f4',
    fieldDirection: '\u65b9\u5411',
    fieldType: '\u6d88\u606f\u7c7b\u578b',
    outgoing: '\u673a\u5668\u4eba\u56de\u590d',
    incoming: '\u7528\u6237\u6d88\u606f',
    linesSuffix: '\u6761',
    keywordLabel: '\u5173\u952e\u5b57',
    chatLabel: '\u4f1a\u8bdd',
    profileTitle: '\u8054\u7cfb\u4eba\u6210\u957f\u753b\u50cf',
    profileSummary: '\u753b\u50cf\u6458\u8981',
    contactPrompt: '\u4e13\u5c5e Prompt',
    contactPromptEmpty: '\u5f53\u524d\u8fd8\u6ca1\u6709\u751f\u6210\u8054\u7cfb\u4eba\u4e13\u5c5e Prompt\uff0c\u7ee7\u7eed\u804a\u5929\u540e\u7cfb\u7edf\u4f1a\u5728\u540e\u53f0\u9010\u6b65\u751f\u6210\u3002',
    contactPromptLoading: '\u6b63\u5728\u52a0\u8f7d\u8054\u7cfb\u4eba\u753b\u50cf\u4e0e Prompt...',
    contactPromptLoadFailed: '\u52a0\u8f7d\u8054\u7cfb\u4eba\u753b\u50cf\u5931\u8d25',
    contactPromptOffline: '\u8bf7\u5148\u542f\u52a8 Python \u670d\u52a1\u540e\u67e5\u770b\u8054\u7cfb\u4eba\u753b\u50cf\u4e0e Prompt',
    contactPromptSave: '\u4fdd\u5b58 Prompt',
    contactPromptSaveSuccess: '\u8054\u7cfb\u4eba Prompt \u5df2\u4fdd\u5b58',
    contactPromptSaveFailed: '\u4fdd\u5b58\u8054\u7cfb\u4eba Prompt \u5931\u8d25',
    fieldRelationship: '\u5173\u7cfb',
    fieldMessageCount: '\u6d88\u606f\u6570',
    fieldEmotion: '\u6700\u8fd1\u60c5\u7eea',
    fieldUpdatedAt: '\u66f4\u65b0\u65f6\u95f4',
    sourceRecentChat: '\u8fd1\u671f\u5bf9\u8bdd\u6210\u957f',
    sourceExportChat: '\u5bfc\u51fa\u804a\u5929\u589e\u5f3a',
    sourceHybrid: '\u8fd1\u671f\u5bf9\u8bdd + \u5bfc\u51fa\u589e\u5f3a',
    sourceUserEdit: '\u4eba\u5de5\u7f16\u8f91',
    sourceUnknown: '\u7cfb\u7edf\u751f\u6210',
};

function createStateBlock(text, className = 'loading-state') {
    const wrap = document.createElement('div');
    wrap.className = className;

    if (className === 'loading-state') {
        const spinner = document.createElement('div');
        spinner.className = 'spinner';
        wrap.appendChild(spinner);
    }

    const label = document.createElement('span');
    label.className = className === 'empty-state' ? 'empty-state-text' : '';
    label.textContent = text;
    wrap.appendChild(label);
    return wrap;
}

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
                container.appendChild(createStateBlock(TEXT.offline, 'empty-state'));
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
            container.appendChild(createStateBlock(TEXT.loading));
        }

        try {
            const result = await apiService.getMessages({
                limit: this._limit,
                offset: this._offset,
                chatId: this._selectedChatId,
                keyword: this._searchKeyword,
            });

            if (!result?.success) {
                throw new Error(result?.message || TEXT.loadFailed);
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
                    createStateBlock(toast.getErrorMessage(error, TEXT.loadFailed), 'empty-state')
                );
            }
            toast.error(toast.getErrorMessage(error, TEXT.loadFailed));
        }
    }

    _handleRealtimeMessage(payload) {
        if (!payload || !this.isActive()) {
            return;
        }

        const message = {
            wx_id: payload.wx_id || payload.chat_id || payload.chatId || '',
            sender: payload.sender || payload.nickname || payload.wx_id || TEXT.user,
            content: payload.content || payload.text || '',
            text: payload.text || payload.content || '',
            timestamp: payload.timestamp || Date.now() / 1000,
            is_self: payload.direction === 'outgoing' || payload.is_self === true,
            msg_type: payload.msg_type || payload.type || 'text',
        };

        if (!this._matchesCurrentFilter(message)) {
            return;
        }

        this._messages = [message, ...this._messages].slice(0, Math.max(this._limit, this._messages.length + 1));
        this._total += 1;
        this._render();
    }

    _matchesCurrentFilter(message) {
        const chatId = String(message.wx_id || message.chat_id || '').trim();
        const keywordSource = `${message.sender || ''} ${message.content || message.text || ''}`.toLowerCase();

        if (this._selectedChatId && chatId !== this._selectedChatId) {
            return false;
        }
        if (this._searchKeyword && !keywordSource.includes(this._searchKeyword.toLowerCase())) {
            return false;
        }
        return true;
    }

    _renderChatFilter() {
        const select = this.$('#message-chat-filter');
        if (!select) {
            return;
        }

        const previousValue = this._selectedChatId;
        select.textContent = '';

        const allOption = document.createElement('option');
        allOption.value = '';
        allOption.textContent = TEXT.allChats;
        select.appendChild(allOption);

        for (const chat of this._chats) {
            const option = document.createElement('option');
            const chatId = String(chat.chat_id || '').trim();
            const displayName = String(chat.display_name || chat.chat_id || TEXT.unnamedChat);
            const count = Number(chat.message_count || 0).toLocaleString('zh-CN');
            option.value = chatId;
            option.textContent = `${displayName} (${count})`;
            select.appendChild(option);
        }

        select.value = previousValue;
    }

    _render() {
        this._renderSummary();
        this._renderMessages();
        this._renderLoadMore();
    }

    _renderSummary() {
        const summary = this.$('#message-filter-summary');
        const totalCount = this.$('#message-total-count');

        if (summary) {
            const parts = [];
            if (this._selectedChatId) {
                parts.push(`${TEXT.chatLabel}\uff1a${this._selectedChatId}`);
            } else {
                parts.push(TEXT.allMessages);
            }
            if (this._searchKeyword) {
                parts.push(`${TEXT.keywordLabel}\uff1a\u201c${this._searchKeyword}\u201d`);
            }
            summary.textContent = parts.join(' \u00b7 ');
        }

        if (totalCount) {
            totalCount.textContent = `${this._messages.length}/${this._total} ${TEXT.linesSuffix}`;
        }
    }

    _renderMessages() {
        const container = this.$('#all-messages');
        if (!container) {
            return;
        }

        container.textContent = '';

        if (this._messages.length === 0) {
            container.appendChild(createStateBlock(TEXT.noMatch, 'empty-state'));
            return;
        }

        const fragment = document.createDocumentFragment();

        this._messages.forEach((message, index) => {
            const item = document.createElement('button');
            item.type = 'button';
            item.className = `message-item ${message.is_self ? 'is-self' : 'is-user'}`;
            item.style.animationDelay = `${Math.min(index, 12) * 0.03}s`;

            const avatar = document.createElement('div');
            avatar.className = 'message-avatar';
            avatar.textContent = message.is_self ? TEXT.assistant : TEXT.user;

            const body = document.createElement('div');
            body.className = 'message-body';

            const meta = document.createElement('div');
            meta.className = 'message-meta';

            const sender = document.createElement('span');
            sender.className = 'message-sender';
            sender.textContent = String(message.sender || message.wx_id || TEXT.user);

            const time = document.createElement('span');
            time.className = 'message-time';
            time.textContent = this._formatTime(message.timestamp);

            meta.appendChild(sender);
            meta.appendChild(time);

            const text = document.createElement('div');
            text.className = 'message-text';
            text.textContent = this._truncateText(message.content || message.text || '', 180);

            const chat = document.createElement('div');
            chat.className = 'message-time';
            chat.textContent = `${TEXT.chatLabel}\uff1a${message.wx_id || '--'}`;

            body.appendChild(meta);
            body.appendChild(text);
            body.appendChild(chat);
            item.appendChild(avatar);
            item.appendChild(body);
            item.addEventListener('click', () => {
                void this._openDetailModal(message);
            });
            fragment.appendChild(item);
        });

        container.appendChild(fragment);
    }

    _renderLoadMore() {
        const button = this.$('#btn-load-more-messages');
        if (!button) {
            return;
        }
        button.hidden = !this._hasMore;
        button.disabled = !this._hasMore;
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
            body.appendChild(createStateBlock(TEXT.contactPromptOffline, 'empty-state'));
            return;
        }

        body.appendChild(createStateBlock(TEXT.contactPromptLoading));

        try {
            const result = await apiService.getContactProfile(message.wx_id || '');
            if (requestToken !== this._detailRequestToken) {
                return;
            }
            if (!result?.success) {
                throw new Error(result?.message || TEXT.contactPromptLoadFailed);
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
        const root = document.createElement('div');
        root.className = 'detail-group';

        const title = document.createElement('div');
        title.className = 'detail-group-title';
        title.textContent = TEXT.detailTitle;
        root.appendChild(title);

        const grid = document.createElement('div');
        grid.className = 'detail-grid';

        const fields = [
            [TEXT.fieldSender, message.sender || '--'],
            [TEXT.fieldChat, message.wx_id || '--'],
            [TEXT.fieldTime, this._formatTime(message.timestamp) || '--'],
            [TEXT.fieldDirection, message.is_self ? TEXT.outgoing : TEXT.incoming],
            [TEXT.fieldType, String(message.msg_type || message.type || '--')],
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
        contentLabel.textContent = TEXT.detailContent;

        const content = document.createElement('pre');
        content.className = 'prompt-preview-output';
        content.textContent = String(message.content || message.text || '');

        contentWrap.appendChild(contentLabel);
        contentWrap.appendChild(content);
        root.appendChild(contentWrap);

        return root;
    }

    _buildContactProfileError(error) {
        const root = document.createElement('div');
        root.className = 'detail-group';

        const title = document.createElement('div');
        title.className = 'detail-group-title';
        title.textContent = TEXT.profileTitle;
        root.appendChild(title);

        root.appendChild(
            createStateBlock(
                toast.getErrorMessage(error, TEXT.contactPromptLoadFailed),
                'empty-state'
            )
        );
        return root;
    }

    _buildContactProfileDetail(message, profile) {
        const root = document.createElement('div');
        root.className = 'detail-group';

        const title = document.createElement('div');
        title.className = 'detail-group-title';
        title.textContent = TEXT.profileTitle;

        const badge = document.createElement('span');
        badge.className = 'message-detail-badge';
        badge.textContent = this._formatPromptSource(profile.contact_prompt_source);
        title.appendChild(badge);
        root.appendChild(title);

        const grid = document.createElement('div');
        grid.className = 'detail-grid';
        const fields = [
            [TEXT.fieldRelationship, profile.relationship || '--'],
            [TEXT.fieldMessageCount, String(profile.message_count ?? '--')],
            [TEXT.fieldEmotion, profile.last_emotion || '--'],
            [TEXT.fieldUpdatedAt, this._formatTime(profile.contact_prompt_updated_at || profile.updated_at) || '--'],
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
        summaryLabel.textContent = TEXT.profileSummary;
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
        promptLabel.textContent = TEXT.contactPrompt;

        const promptInput = document.createElement('textarea');
        promptInput.className = 'detail-textarea';
        promptInput.rows = 12;
        promptInput.value = String(profile.contact_prompt || '');
        promptInput.placeholder = TEXT.contactPromptEmpty;

        const hint = document.createElement('div');
        hint.className = 'detail-help';
        hint.textContent = '你可以直接编辑这份联系人专属 Prompt，后续系统会以当前保存版本为基础继续渐进式更新。';

        const actions = document.createElement('div');
        actions.className = 'detail-actions';
        const saveButton = document.createElement('button');
        saveButton.type = 'button';
        saveButton.className = 'btn btn-primary btn-sm';
        saveButton.textContent = TEXT.contactPromptSave;
        saveButton.addEventListener('click', async () => {
            const nextPrompt = String(promptInput.value || '').trim();
            if (!nextPrompt) {
                toast.error(TEXT.contactPromptEmpty);
                return;
            }
            saveButton.disabled = true;
            try {
                const result = await apiService.saveContactPrompt(message.wx_id || '', nextPrompt);
                if (!result?.success) {
                    throw new Error(result?.message || TEXT.contactPromptSaveFailed);
                }
                const nextSection = this._buildContactProfileDetail(message, result.profile || profile);
                root.replaceWith(nextSection);
                toast.success(TEXT.contactPromptSaveSuccess);
            } catch (error) {
                toast.error(toast.getErrorMessage(error, TEXT.contactPromptSaveFailed));
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

    _formatPromptSource(source) {
        switch (String(source || '').trim()) {
        case 'recent_chat':
            return TEXT.sourceRecentChat;
        case 'export_chat':
            return TEXT.sourceExportChat;
        case 'hybrid':
            return TEXT.sourceHybrid;
        case 'user_edit':
            return TEXT.sourceUserEdit;
        default:
            return TEXT.sourceUnknown;
        }
    }

    _truncateText(text, maxLength) {
        const normalized = String(text || '');
        if (normalized.length <= maxLength) {
            return normalized;
        }
        return `${normalized.slice(0, maxLength)}...`;
    }

    _formatTime(timestamp) {
        if (!timestamp) {
            return '--';
        }

        let date = null;
        if (typeof timestamp === 'number') {
            date = new Date(timestamp * 1000);
        } else {
            const numeric = Number(timestamp);
            date = Number.isFinite(numeric) ? new Date(numeric * 1000) : new Date(timestamp);
        }

        if (Number.isNaN(date.getTime())) {
            return '--';
        }

        return new Intl.DateTimeFormat('zh-CN', {
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
        }).format(date);
    }
}

export default MessagesPage;
