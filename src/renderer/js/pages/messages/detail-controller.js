import { apiService } from '../../services/ApiService.js';
import { toast } from '../../services/NotificationService.js';
import {
    createMessageStateBlock,
    MESSAGE_TEXT,
} from './formatters.js';
import {
    buildContactProfileDetail,
    buildContactProfileError,
    buildMessageDetail,
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
    const modal = documentObj.getElementById('message-detail-modal');
    const body = documentObj.getElementById('message-detail-body');
    if (!modal || !body) {
        return;
    }

    const requestToken = ++page._detailRequestToken;
    body.textContent = '';
    body.appendChild(buildMessageDetail(message));
    modal.classList.add('active');

    if (!page.getState('bot.connected')) {
        body.appendChild(createMessageStateBlock(MESSAGE_TEXT.contactPromptOffline, 'empty-state'));
        return;
    }

    body.appendChild(createMessageStateBlock(MESSAGE_TEXT.contactPromptLoading));

    const saveFeedback = async (nextMessage, nextFeedback) => {
        try {
            const saveResult = await getApiService(deps).saveMessageFeedback(
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
        const result = await getApiService(deps).getContactProfile(message.wx_id || '');
        if (requestToken !== page._detailRequestToken) {
            return;
        }
        if (!result?.success) {
            throw new Error(result?.message || MESSAGE_TEXT.contactPromptLoadFailed);
        }
        body.textContent = '';
        body.appendChild(buildMessageDetail(message, {
            onFeedback: saveFeedback,
        }));
        body.appendChild(buildContactProfileDetail(message, result.profile || {}, {
            onEmptyPrompt: () => {
                currentToast.error(MESSAGE_TEXT.contactPromptEmpty);
            },
            onSavePrompt: async (nextMessage, nextPrompt, previousProfile) => {
                try {
                    const saveResult = await getApiService(deps).saveContactPrompt(nextMessage.wx_id || '', nextPrompt);
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
    } catch (error) {
        if (requestToken !== page._detailRequestToken) {
            return;
        }
        console.error('[MessagesPage] contact profile load failed:', error);
        body.textContent = '';
        body.appendChild(buildMessageDetail(message, {
            onFeedback: saveFeedback,
        }));
        body.appendChild(buildContactProfileError(
            currentToast.getErrorMessage(error, MESSAGE_TEXT.contactPromptLoadFailed)
        ));
    }
}

export function closeDetailModal(page, deps = {}) {
    const documentObj = getDocument(deps);
    page._detailRequestToken += 1;
    documentObj.getElementById('message-detail-modal')?.classList.remove('active');
}
