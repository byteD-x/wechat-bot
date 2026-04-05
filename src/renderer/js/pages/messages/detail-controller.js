import { apiService } from '../../services/ApiService.js';
import { toast } from '../../services/NotificationService.js';
import {
    createMessageStateBlock,
    MESSAGE_TEXT,
} from './formatters.js';
import {
    buildContactProfileDetail,
    buildMessageDetail,
    buildReplyApprovalDetail,
} from './renderers.js';

function getApiService(deps = {}) {
    return deps.apiService || apiService;
}

function getToast(deps = {}) {
    return deps.toast || toast;
}

function getDocument(deps = {}) {
    return deps.documentObj || globalThis.document;
}

function getMessageChatName(message = {}) {
    return String(
        message.chat_display_name
        || message.display_name
        || message.chat_name
        || message.sender_display_name
        || message.sender
        || ''
    ).trim();
}

function buildRetrySection(documentObj, titleText, messageText, retryLabel, onRetry) {
    const root = documentObj.createElement('div');
    root.className = 'detail-group';

    const title = documentObj.createElement('div');
    title.className = 'detail-group-title';
    title.textContent = titleText;
    root.appendChild(title);

    root.appendChild(createMessageStateBlock(messageText, 'empty-state'));

    const actions = documentObj.createElement('div');
    actions.className = 'detail-actions';
    const retryButton = documentObj.createElement('button');
    retryButton.type = 'button';
    retryButton.className = 'btn btn-secondary btn-sm';
    retryButton.textContent = retryLabel;
    retryButton.addEventListener('click', () => {
        void onRetry?.();
    });
    actions.appendChild(retryButton);
    root.appendChild(actions);
    return root;
}

function syncMessageFeedback(page, messageId, metadata) {
    const nextMetadata = metadata && typeof metadata === 'object' ? metadata : {};
    page._messages = (page._messages || []).map((item) => {
        if (Number(item?.id || 0) !== Number(messageId || 0)) {
            return item;
        }
        return {
            ...item,
            metadata: nextMetadata,
        };
    });
}

export async function openDetailModal(page, message, deps = {}) {
    const documentObj = getDocument(deps);
    const currentToast = getToast(deps);
    const currentApi = getApiService(deps);
    const modal = documentObj.getElementById('message-detail-modal');
    const body = documentObj.getElementById('message-detail-body');
    if (!modal || !body) {
        return;
    }

    const requestToken = ++page._detailRequestToken;
    body.textContent = '';
    body.appendChild(buildMessageDetail(message, { documentObj }));
    modal.classList.add('active');

    if (!page.getState('bot.connected')) {
        body.appendChild(createMessageStateBlock(MESSAGE_TEXT.contactPromptOffline, 'empty-state'));
        return;
    }

    body.appendChild(createMessageStateBlock(MESSAGE_TEXT.contactPromptLoading));

    const refreshDetail = async () => {
        await openDetailModal(page, message, deps);
    };

    const copyText = async (value, label) => {
        const text = String(value || '').trim();
        if (!text) {
            currentToast.info(`${label}暂无可复制内容`);
            return;
        }
        try {
            await globalThis.navigator?.clipboard?.writeText?.(text);
            currentToast.success(`${label}已复制`);
        } catch (_error) {
            currentToast.error(`复制${label}失败`);
        }
    };

    const saveFeedback = async (nextMessage, nextFeedback) => {
        try {
            const saveResult = await currentApi.saveMessageFeedback(
                nextMessage.id,
                nextFeedback
            );
            if (!saveResult?.success) {
                throw new Error(saveResult?.message || MESSAGE_TEXT.feedbackSaveFailed);
            }
            const updatedMessage = {
                ...nextMessage,
                metadata: saveResult.metadata || {},
            };
            syncMessageFeedback(page, nextMessage.id, updatedMessage.metadata);
            currentToast.success(MESSAGE_TEXT.feedbackSaveSuccess);
            return updatedMessage;
        } catch (error) {
            currentToast.error(currentToast.getErrorMessage(error, MESSAGE_TEXT.feedbackSaveFailed));
            return null;
        }
    };

    try {
        const chatName = getMessageChatName(message);
        const [profileResult, pendingResult, replyPolicyResult] = await Promise.allSettled([
            currentApi.getContactProfile(message.wx_id || '', chatName),
            currentApi.listPendingReplies({
                chatId: message.wx_id || '',
                chatName,
                status: 'pending',
                limit: 20,
            }),
            currentApi.getReplyPolicies(),
        ]);
        if (requestToken !== page._detailRequestToken) {
            return;
        }

        body.textContent = '';
        body.appendChild(buildMessageDetail(message, {
            documentObj,
            onFeedback: saveFeedback,
            onCopy: copyText,
        }));

        if (profileResult.status === 'fulfilled' && profileResult.value?.success) {
            body.appendChild(buildContactProfileDetail(message, profileResult.value.profile || {}, {
                documentObj,
                onCopy: copyText,
                onEmptyPrompt: () => {
                    currentToast.error(MESSAGE_TEXT.contactPromptEmpty);
                },
                onSavePrompt: async (nextMessage, nextPrompt, previousProfile) => {
                    try {
                        const saveResult = await currentApi.saveContactPrompt(
                            nextMessage.wx_id || '',
                            nextPrompt,
                            getMessageChatName(nextMessage),
                        );
                        if (!saveResult?.success) {
                            throw new Error(saveResult?.message || MESSAGE_TEXT.contactPromptSaveFailed);
                        }
                        currentToast.success(MESSAGE_TEXT.contactPromptSaveSuccess);
                        return saveResult.profile || previousProfile;
                    } catch (error) {
                        currentToast.error(currentToast.getErrorMessage(error, MESSAGE_TEXT.contactPromptSaveFailed));
                        return null;
                    }
                },
            }));
        } else {
            const profileMessage = profileResult.status === 'fulfilled'
                ? currentToast.getErrorMessage(profileResult.value, MESSAGE_TEXT.contactPromptLoadFailed)
                : currentToast.getErrorMessage(profileResult.reason, MESSAGE_TEXT.contactPromptLoadFailed);
            body.appendChild(buildRetrySection(
                documentObj,
                MESSAGE_TEXT.profileTitle,
                profileMessage,
                '重试加载画像',
                refreshDetail,
            ));
        }

        if (
            pendingResult.status === 'fulfilled'
            && replyPolicyResult.status === 'fulfilled'
            && pendingResult.value?.success !== false
            && replyPolicyResult.value?.success !== false
        ) {
            body.appendChild(buildReplyApprovalDetail(message, {
                replyPolicy: replyPolicyResult.value?.reply_policy || {},
                pendingReplies: pendingResult.value?.items || [],
            }, {
                documentObj,
                onSaveOverride: async (nextMessage, mode) => {
                    try {
                        const result = await currentApi.saveReplyPolicies({
                            chat_id: nextMessage.wx_id || nextMessage.chat_id || '',
                            mode,
                        });
                        if (!result?.success) {
                            throw new Error(result?.message || '保存会话审批策略失败');
                        }
                        currentToast.success('会话审批策略已更新');
                    } catch (error) {
                        currentToast.error(currentToast.getErrorMessage(error, '保存会话审批策略失败'));
                    }
                },
                onApprovePending: async (_nextMessage, pendingReply, editedReply) => {
                    try {
                        const result = await currentApi.approvePendingReply(pendingReply.id, editedReply);
                        if (!result?.success) {
                            throw new Error(result?.message || '批准待审批回复失败');
                        }
                        currentToast.success('已批准并发送回复');
                        await refreshDetail();
                    } catch (error) {
                        currentToast.error(currentToast.getErrorMessage(error, '批准待审批回复失败'));
                    }
                },
                onRejectPending: async (_nextMessage, pendingReply) => {
                    try {
                        const result = await currentApi.rejectPendingReply(pendingReply.id);
                        if (!result?.success) {
                            throw new Error(result?.message || '拒绝待审批回复失败');
                        }
                        currentToast.success('已拒绝待审批回复');
                        await refreshDetail();
                    } catch (error) {
                        currentToast.error(currentToast.getErrorMessage(error, '拒绝待审批回复失败'));
                    }
                },
            }));
        } else {
            const policyMessage = pendingResult.status !== 'fulfilled'
                ? currentToast.getErrorMessage(pendingResult.reason, '加载待审批回复失败')
                : (
                    replyPolicyResult.status !== 'fulfilled'
                        ? currentToast.getErrorMessage(replyPolicyResult.reason, '加载回复策略失败')
                        : currentToast.getErrorMessage(replyPolicyResult.value, '加载回复策略失败')
                );
            body.appendChild(buildRetrySection(
                documentObj,
                '回复策略与审批',
                policyMessage,
                '重试加载审批信息',
                refreshDetail,
            ));
        }
    } catch (error) {
        if (requestToken !== page._detailRequestToken) {
            return;
        }
        console.error('[MessagesPage] contact profile load failed:', error);
        body.textContent = '';
        body.appendChild(buildMessageDetail(message, {
            documentObj,
            onFeedback: saveFeedback,
            onCopy: copyText,
        }));
        body.appendChild(buildRetrySection(
            documentObj,
            MESSAGE_TEXT.profileTitle,
            currentToast.getErrorMessage(error, MESSAGE_TEXT.contactPromptLoadFailed),
            '重新加载详情',
            refreshDetail,
        ));
    }
}

export function closeDetailModal(page, deps = {}) {
    const documentObj = getDocument(deps);
    page._detailRequestToken += 1;
    documentObj.getElementById('message-detail-modal')?.classList.remove('active');
}
