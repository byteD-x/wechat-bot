import test from 'node:test';
import assert from 'node:assert/strict';

import {
    fetchMessages,
    handleRealtimeMessage,
    refreshMessages,
    renderMessagesPage,
} from '../../src/renderer/js/pages/messages/data-controller.js';
import {
    closeDetailModal,
    openDetailModal,
} from '../../src/renderer/js/pages/messages/detail-controller.js';
import { bindMessagesPage } from '../../src/renderer/js/pages/messages/page-shell.js';
import { installDomStub } from './dom-stub.mjs';

async function withDom(run) {
    const env = installDomStub();
    try {
        return await run(env);
    } finally {
        env.restore();
    }
}

function createToastRecorder() {
    const calls = [];
    const push = (type, message) => calls.push({ type, message });
    return {
        calls,
        success(message) {
            push('success', message);
        },
        info(message) {
            push('info', message);
        },
        error(message) {
            push('error', message);
        },
        getErrorMessage(error, fallback) {
            return error?.message || fallback;
        },
    };
}

function setStateValue(target, path, value) {
    const parts = String(path || '').split('.').filter(Boolean);
    let cursor = target;
    while (parts.length > 1) {
        const key = parts.shift();
        if (!cursor[key] || typeof cursor[key] !== 'object') {
            cursor[key] = {};
        }
        cursor = cursor[key];
    }
    cursor[parts[0]] = value;
}

function getStateValue(target, path) {
    return String(path || '')
        .split('.')
        .filter(Boolean)
        .reduce((cursor, key) => (cursor && key in cursor ? cursor[key] : undefined), target);
}

function createMessagesPage(initialState = {}, selectors = {}) {
    const state = structuredClone(initialState);
    const emitted = [];
    return {
        _messages: [],
        _chats: [],
        _limit: 50,
        _offset: 0,
        _total: 0,
        _hasMore: false,
        _searchKeyword: '',
        _selectedChatId: '',
        _searchTimer: null,
        _detailRequestToken: 0,
        $: (selector) => selectors[selector] || null,
        getState: (path) => getStateValue(state, path),
        setState: (path, value) => setStateValue(state, path, value),
        emit: (event, payload) => emitted.push({ event, payload }),
        isActive: () => true,
        state,
        emitted,
    };
}

function createInteractiveControl(initial = '') {
    return {
        value: initial,
        checked: false,
        listeners: {},
        addEventListener(type, handler) {
            this.listeners[type] = handler;
        },
    };
}

test('messages data helper resets offline state and renders loaded messages', async () => withDom(async ({ document, registerElement }) => {
    const selectors = {
        '#all-messages': document.createElement('div'),
        '#message-chat-filter': document.createElement('select'),
        '#message-filter-summary': document.createElement('div'),
        '#message-total-count': document.createElement('div'),
        '#btn-load-more-messages': document.createElement('button'),
    };
    const page = createMessagesPage({
        bot: { connected: false },
    }, selectors);

    await refreshMessages(page);
    assert.equal(page._messages.length, 0);
    assert.equal(selectors['#all-messages'].textContent.includes('Python'), true);

    page.state.bot.connected = true;
    await fetchMessages(page, { append: false }, {
        apiService: {
            getMessages: async () => ({
                success: true,
                messages: [
                    { wx_id: 'wx-1', sender: 'A', content: 'hello', timestamp: 1 },
                    { wx_id: 'wx-2', sender: 'B', content: 'world', timestamp: 2 },
                ],
                chats: [
                    { chat_id: 'wx-1', display_name: 'Chat A', message_count: 3 },
                ],
                total: 2,
                has_more: true,
            }),
        },
        onOpenDetail: () => {},
    });

    assert.equal(page._messages.length, 2);
    assert.equal(page._hasMore, true);
    assert.equal(selectors['#message-chat-filter'].children.length, 2);
    assert.equal(selectors['#message-total-count'].textContent.includes('2/2'), true);
    assert.equal(selectors['#btn-load-more-messages'].hidden, false);
    assert.equal(page.emitted.length, 1);
}));

test('messages data helper applies realtime message filter and renders list', async () => withDom(async ({ document }) => {
    const selectors = {
        '#all-messages': document.createElement('div'),
        '#message-filter-summary': document.createElement('div'),
        '#message-total-count': document.createElement('div'),
        '#btn-load-more-messages': document.createElement('button'),
    };
    const page = createMessagesPage({
        bot: { connected: true },
    }, selectors);
    page._messages = [{ wx_id: 'room-a', sender: 'old', content: 'old', timestamp: 1 }];
    page._total = 1;
    page._selectedChatId = 'room-a';
    page._searchKeyword = 'hello';

    handleRealtimeMessage(page, {
        wx_id: 'room-a',
        sender: 'new',
        content: 'hello there',
        timestamp: 2,
    }, {
        onOpenDetail: () => {},
    });
    assert.equal(page._messages.length, 2);
    assert.equal(page._total, 2);

    handleRealtimeMessage(page, {
        wx_id: 'room-b',
        sender: 'skip',
        content: 'hello there',
        timestamp: 3,
    }, {
        onOpenDetail: () => {},
    });
    assert.equal(page._messages.length, 2);
}));

test('messages detail helper handles offline and success profile flows', async () => withDom(async ({ document, registerElement }) => {
    const modal = registerElement('message-detail-modal', document.createElement('div'));
    const body = registerElement('message-detail-body', document.createElement('div'));
    const page = createMessagesPage({
        bot: { connected: false },
    });

    await openDetailModal(page, {
        wx_id: 'wx-1',
        sender: 'Alice',
        content: 'hello',
        timestamp: 1,
        is_self: false,
    }, {
        documentObj: document,
        toast: createToastRecorder(),
    });

    assert.equal(modal.classList.contains('active'), true);
    assert.equal(body.textContent.includes('Python'), true);

    page.state.bot.connected = true;
    await openDetailModal(page, {
        wx_id: 'wx-1',
        sender: 'Alice',
        content: 'hello',
        timestamp: 1,
        is_self: false,
    }, {
        documentObj: document,
        toast: createToastRecorder(),
        apiService: {
            getContactProfile: async () => ({
                success: true,
                profile: {
                    relationship: 'friend',
                    message_count: 9,
                    last_emotion: 'calm',
                    profile_summary: 'summary',
                    contact_prompt: 'prompt',
                },
            }),
        },
    });

    assert.equal(body.textContent.includes('summary'), true);
    closeDetailModal(page, { documentObj: document });
    assert.equal(modal.classList.contains('active'), false);
}));

test('messages page shell binds controls, debounce search and close modal flows', async () => withDom(async ({ document, registerElement }) => {
    const searchInput = createInteractiveControl();
    const chatFilter = createInteractiveControl();
    const page = {
        bindings: [],
        watchers: [],
        listeners: [],
        _searchKeyword: '',
        _selectedChatId: '',
        _searchTimer: null,
        bindEvent(target, type, handler) {
            this.bindings.push({ target, type, handler });
        },
        watchState(path, handler) {
            this.watchers.push({ path, handler });
        },
        listenEvent(event, handler) {
            this.listeners.push({ event, handler });
        },
        $(selector) {
            return {
                '#message-search': searchInput,
                '#message-chat-filter': chatFilter,
            }[selector] || null;
        },
        isActive() {
            return true;
        },
    };
    const closeBtn = registerElement('btn-close-message-detail', document.createElement('button'));
    const modal = registerElement('message-detail-modal', document.createElement('div'));
    registerElement('message-detail-body', document.createElement('div'));
    const calls = [];

    bindMessagesPage(page, {
        documentObj: document,
        windowObj: {},
        setTimeoutFn: (handler) => {
            handler();
            return 7;
        },
        clearTimeoutFn: () => {},
        refreshMessages: async () => {
            calls.push(['refresh', page._searchKeyword, page._selectedChatId]);
        },
        loadMoreMessages: async () => {
            calls.push(['more']);
        },
        openDetailModal: async (_page, message) => {
            calls.push(['detail', message?.wx_id]);
        },
        closeDetailModal: () => {
            calls.push(['close']);
        },
        handleRealtimeMessage: (_page, payload) => {
            calls.push(['realtime', payload?.wx_id]);
        },
    });

    assert.equal(page.bindings.length, 3);
    assert.equal(page.watchers.length, 1);
    assert.equal(page.listeners.length, 1);

    searchInput.value = ' alice ';
    searchInput.listeners.input();
    chatFilter.value = 'room-1';
    chatFilter.listeners.change();
    assert.deepEqual(calls[0], ['refresh', 'alice', '']);
    assert.deepEqual(calls[1], ['refresh', 'alice', 'room-1']);

    closeBtn.click();
    assert.equal(calls.some((item) => item[0] === 'close'), true);

    modal.classList.add('active');
    const keydown = page.bindings.find((item) => item.type === 'keydown');
    keydown.handler({ key: 'Escape' });
    assert.equal(calls.filter((item) => item[0] === 'close').length >= 2, true);

    page.watchers[0].handler(true);
    assert.equal(calls.some((item) => item[0] === 'refresh'), true);
    page.listeners[0].handler({ wx_id: 'wx-live' });
    assert.equal(calls.at(-1)?.[0], 'realtime');
}));
