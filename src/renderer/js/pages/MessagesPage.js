import { PageController } from '../core/PageController.js';
import {
    refreshMessages,
    renderMessagesPage,
} from './messages/data-controller.js';
import { openDetailModal } from './messages/detail-controller.js';
import { bindMessagesPage } from './messages/page-shell.js';

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
        bindMessagesPage(this);
    }

    async onEnter() {
        await super.onEnter();
        if (!this.getState('bot.connected') || this._messages.length === 0) {
            await refreshMessages(this);
            return;
        }
        renderMessagesPage(this, {
            onOpenDetail: (message) => openDetailModal(this, message),
        });
    }

    async onDestroy() {
        clearTimeout(this._searchTimer);
        await super.onDestroy();
    }
}

export default MessagesPage;
