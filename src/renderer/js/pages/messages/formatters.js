export const MESSAGE_TEXT = {
    loading: '加载中...',
    loadFailed: '加载消息失败',
    offline: '请先启动 Python 服务后查看消息',
    allChats: '全部会话',
    unnamedChat: '未命名会话',
    allMessages: '全部消息',
    noMatch: '暂无匹配消息',
    user: '用户',
    assistant: 'AI',
    detailTitle: '消息详情',
    detailContent: '消息内容',
    fieldSender: '发送者',
    fieldChat: '会话',
    fieldTime: '时间',
    fieldDirection: '方向',
    fieldType: '消息类型',
    fieldFeedback: '人工反馈',
    outgoing: '机器人回复',
    incoming: '用户消息',
    linesSuffix: '条',
    keywordLabel: '关键词',
    chatLabel: '会话',
    profileTitle: '联系人画像',
    profileSummary: '画像摘要',
    contactPrompt: '专属 Prompt',
    contactPromptEditable: '自定义专属 Prompt',
    contactPromptFixed: '固定注入块（只读）',
    contactPromptEmpty: '当前还没有生成联系人专属 Prompt，继续聊天后系统会在后台逐步生成。',
    contactPromptLoading: '正在加载联系人画像与 Prompt...',
    contactPromptLoadFailed: '加载联系人画像失败',
    contactPromptOffline: '请先启动 Python 服务后查看联系人画像与 Prompt',
    contactPromptSave: '保存 Prompt',
    contactPromptSaveSuccess: '联系人 Prompt 已保存',
    contactPromptSaveFailed: '保存联系人 Prompt 失败',
    contactPromptFixedHint: '系统会在运行时自动补齐历史对话、联系人画像、情绪/时间/风格注入块；这里只需要填写这个联系人的额外定制规则。',
    fieldRelationship: '关系',
    fieldMessageCount: '消息数',
    fieldEmotion: '最近情绪',
    fieldUpdatedAt: '更新时间',
    sourceRecentChat: '近期对话成长',
    sourceExportChat: '导出聊天增强',
    sourceHybrid: '近期对话 + 导出增强',
    sourceUserEdit: '人工编辑',
    sourceUnknown: '系统生成',
    feedbackTitle: '回复反馈',
    feedbackHelpful: '有帮助',
    feedbackUnhelpful: '没帮助',
    feedbackHint: '这会记录到回复质量统计里，用于后续优化回复效果。',
    feedbackSaveSuccess: '反馈已保存',
    feedbackSaveFailed: '保存反馈失败',
};

export function createMessageStateBlock(text, className = 'loading-state') {
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

export function normalizeRealtimeMessage(payload) {
    const isSelf = payload.direction === 'outgoing' || payload.is_self === true;
    const chatDisplayName = String(
        payload.chat_display_name
        || payload.display_name
        || payload.chat_name
        || payload.nickname
        || payload.wx_id
        || payload.chat_id
        || payload.chatId
        || ''
    ).trim();
    const senderDisplayName = String(
        isSelf
            ? (payload.sender || MESSAGE_TEXT.assistant)
            : (
                payload.sender_display_name
                || payload.sender_name
                || payload.sender
                || chatDisplayName
                || payload.nickname
                || payload.wx_id
                || MESSAGE_TEXT.user
            )
    ).trim();

    return {
        wx_id: payload.wx_id || payload.chat_id || payload.chatId || '',
        sender: senderDisplayName || MESSAGE_TEXT.user,
        sender_display_name: senderDisplayName || MESSAGE_TEXT.user,
        display_name: chatDisplayName || senderDisplayName || MESSAGE_TEXT.unnamedChat,
        chat_display_name: chatDisplayName || senderDisplayName || MESSAGE_TEXT.unnamedChat,
        content: payload.content || payload.text || '',
        text: payload.text || payload.content || '',
        timestamp: payload.timestamp || Date.now() / 1000,
        is_self: isSelf,
        msg_type: payload.msg_type || payload.type || 'text',
    };
}

export function getMessageChatDisplayName(message = {}) {
    return String(
        message.chat_display_name
        || message.display_name
        || message.chat_name
        || message.sender_display_name
        || message.sender
        || message.wx_id
        || MESSAGE_TEXT.unnamedChat
    ).trim() || MESSAGE_TEXT.unnamedChat;
}

export function getMessageSenderDisplayName(message = {}) {
    if (message.is_self || String(message.role || '').trim().toLowerCase() === 'assistant') {
        return MESSAGE_TEXT.assistant;
    }

    return String(
        message.sender_display_name
        || message.sender
        || message.display_name
        || message.chat_display_name
        || message.wx_id
        || MESSAGE_TEXT.user
    ).trim() || MESSAGE_TEXT.user;
}

export function matchesMessageFilter(message, options = {}) {
    const chatId = String(message.wx_id || message.chat_id || '').trim();
    const keywordSource = [
        getMessageSenderDisplayName(message),
        getMessageChatDisplayName(message),
        message.content || message.text || '',
        message.wx_id || '',
    ].join(' ').toLowerCase();

    if (options.selectedChatId && chatId !== options.selectedChatId) {
        return false;
    }
    if (options.searchKeyword && !keywordSource.includes(String(options.searchKeyword).toLowerCase())) {
        return false;
    }
    return true;
}

export function formatPromptSource(source) {
    switch (String(source || '').trim()) {
    case 'recent_chat':
        return MESSAGE_TEXT.sourceRecentChat;
    case 'export_chat':
        return MESSAGE_TEXT.sourceExportChat;
    case 'hybrid':
        return MESSAGE_TEXT.sourceHybrid;
    case 'user_edit':
        return MESSAGE_TEXT.sourceUserEdit;
    default:
        return MESSAGE_TEXT.sourceUnknown;
    }
}

export function truncateMessageText(text, maxLength) {
    const normalized = String(text || '');
    if (normalized.length <= maxLength) {
        return normalized;
    }
    return `${normalized.slice(0, maxLength)}...`;
}

export function formatMessageTime(timestamp) {
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
