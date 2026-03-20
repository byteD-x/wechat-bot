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

function findFirstButtonByText(root, expectedText) {
    const queue = [root];
    while (queue.length > 0) {
        const current = queue.shift();
        if (!current) {
            continue;
        }
        if (String(current.tagName || '').toLowerCase() === 'button' && current.textContent === expectedText) {
            return current;
        }
        if (Array.isArray(current.children)) {
            queue.push(...current.children);
        }
    }
    return null;
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

test('messages list keeps detail click available through page fallback handler', async () => withDom(async ({ document }) => {
    const selectors = {
        '#all-messages': document.createElement('div'),
        '#message-filter-summary': document.createElement('div'),
        '#message-total-count': document.createElement('div'),
        '#btn-load-more-messages': document.createElement('button'),
    };
    const page = createMessagesPage({
        bot: { connected: true },
    }, selectors);
    const opened = [];
    page._openMessageDetail = (message) => {
        opened.push(message?.wx_id || '');
    };

    await fetchMessages(page, { append: false }, {
        apiService: {
            getMessages: async () => ({
                success: true,
                messages: [
                    { wx_id: 'wx-1', sender: 'A', content: 'hello', timestamp: 1 },
                ],
                chats: [],
                total: 1,
                has_more: false,
            }),
        },
    });

    const firstItem = selectors['#all-messages'].querySelector('button');
    firstItem.click();
    assert.deepEqual(opened, ['wx-1']);
}));

test('messages page renders friend display names instead of chat ids', async () => withDom(async ({ document }) => {
    const selectors = {
        '#all-messages': document.createElement('div'),
        '#message-chat-filter': document.createElement('select'),
        '#message-filter-summary': document.createElement('div'),
        '#message-total-count': document.createElement('div'),
        '#btn-load-more-messages': document.createElement('button'),
    };
    const page = createMessagesPage({
        bot: { connected: true },
    }, selectors);
    page._selectedChatId = 'friend:alice';

    await fetchMessages(page, { append: false }, {
        apiService: {
            getMessages: async () => ({
                success: true,
                messages: [
                    {
                        wx_id: 'friend:alice',
                        sender: 'Alice',
                        sender_display_name: 'Alice',
                        display_name: 'Alice',
                        chat_display_name: 'Alice',
                        content: 'hello',
                        timestamp: 1,
                        is_self: false,
                    },
                    {
                        wx_id: 'friend:alice',
                        sender: 'AI',
                        sender_display_name: 'AI',
                        display_name: 'Alice',
                        chat_display_name: 'Alice',
                        content: 'reply',
                        timestamp: 2,
                        is_self: true,
                        role: 'assistant',
                    },
                ],
                chats: [
                    { chat_id: 'friend:alice', display_name: 'Alice', message_count: 2 },
                ],
                total: 2,
                has_more: false,
            }),
        },
    });

    assert.equal(selectors['#message-filter-summary'].textContent.includes('Alice'), true);
    assert.equal(selectors['#message-filter-summary'].textContent.includes('friend:alice'), false);
    assert.equal(selectors['#all-messages'].textContent.includes('Alice'), true);
    assert.equal(selectors['#all-messages'].textContent.includes('friend:alice'), false);
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
    assert.equal(body.textContent.includes('固定注入块（只读）'), true);
    closeDetailModal(page, { documentObj: document });
    assert.equal(modal.classList.contains('active'), false);
}));

test('messages detail helper strips fixed prompt block before editing contact prompt', async () => withDom(async ({ document, registerElement }) => {
    registerElement('message-detail-modal', document.createElement('div'));
    const body = registerElement('message-detail-body', document.createElement('div'));
    const toast = createToastRecorder();
    const saved = [];
    const page = createMessagesPage({
        bot: { connected: true },
    });

    await openDetailModal(page, {
        wx_id: 'friend:alice',
        sender: 'Alice',
        sender_display_name: 'Alice',
        display_name: 'Alice',
        chat_display_name: 'Alice',
        content: 'hello',
        timestamp: 1,
        is_self: false,
    }, {
        documentObj: document,
        toast,
        apiService: {
            getContactProfile: async () => ({
                success: true,
                profile: {
                    relationship: 'friend',
                    message_count: 9,
                    last_emotion: 'calm',
                    profile_summary: 'summary',
                    contact_prompt: [
                        '像老朋友一样回复，少一点解释。',
                        '',
                        '# 系统注入上下文（固定）',
                        '以下内容由系统在运行时自动注入，请勿手动改写：',
                        '# 历史对话',
                        '{history_context}',
                        '',
                        '# 用户画像',
                        '{user_profile}',
                        '',
                        '# 当前情境',
                        '{emotion_hint}{time_hint}{style_hint}',
                    ].join('\n'),
                },
            }),
            saveContactPrompt: async (_chatId, contactPrompt) => {
                saved.push(contactPrompt);
                return {
                    success: true,
                    profile: {
                        relationship: 'friend',
                        message_count: 9,
                        last_emotion: 'calm',
                        profile_summary: 'summary',
                        contact_prompt,
                    },
                };
            },
        },
    });

    const textareas = Array.from(body.querySelectorAll('textarea'));
    const editable = textareas.find((item) => item.readOnly !== true);
    const fixed = textareas.find((item) => item.readOnly === true && item.value.includes('{history_context}'));
    assert.equal(editable.value, '像老朋友一样回复，少一点解释。');
    assert.equal(fixed.value.includes('{history_context}'), true);

    editable.value = '保留熟悉感，但别太长。';
    const saveButton = findFirstButtonByText(body, '保存 Prompt');
    saveButton.click();

    await Promise.resolve();
    assert.deepEqual(saved, ['保留熟悉感，但别太长。']);
}));

test('messages detail helper prefers friend display name over chat id', async () => withDom(async ({ document, registerElement }) => {
    registerElement('message-detail-modal', document.createElement('div'));
    const body = registerElement('message-detail-body', document.createElement('div'));
    const page = createMessagesPage({
        bot: { connected: true },
    });

    await openDetailModal(page, {
        wx_id: 'friend:alice',
        sender: 'Alice',
        sender_display_name: 'Alice',
        display_name: 'Alice',
        chat_display_name: 'Alice',
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

    assert.equal(body.textContent.includes('Alice'), true);
    assert.equal(body.textContent.includes('friend:alice'), false);
}));

test('messages detail helper saves assistant feedback and updates local metadata', async () => withDom(async ({ document, registerElement }) => {
    const modal = registerElement('message-detail-modal', document.createElement('div'));
    const body = registerElement('message-detail-body', document.createElement('div'));
    const toast = createToastRecorder();
    const message = {
        id: 7,
        wx_id: 'wx-1',
        sender: 'Bot',
        content: 'hello',
        timestamp: 1,
        is_self: true,
        role: 'assistant',
        metadata: {},
    };
    const page = createMessagesPage({
        bot: { connected: true },
    });
    page._messages = [message];

    await openDetailModal(page, message, {
        documentObj: document,
        toast,
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
            saveMessageFeedback: async (_messageId, feedback) => ({
                success: true,
                metadata: {
                    reply_quality: {
                        user_feedback: feedback,
                    },
                },
            }),
        },
    });

    const buttons = Array.from(body.querySelectorAll('button'));
    const helpfulButton = buttons.find((item) => item.textContent === '有帮助');
    helpfulButton.click();
    await Promise.resolve();
    await Promise.resolve();

    assert.equal(modal.classList.contains('active'), true);
    assert.equal(page._messages[0].metadata.reply_quality.user_feedback, 'helpful');
    assert.equal(toast.calls.some((item) => item.type === 'success'), true);
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
