import { apiService } from '../../services/ApiService.js';
import { toast } from '../../services/NotificationService.js';

function getApiService(deps = {}) {
    return deps.apiService || apiService;
}

function getToast(deps = {}) {
    return deps.toast || toast;
}

function getConfirm(deps = {}) {
    if (typeof deps.confirm === 'function') {
        return deps.confirm;
    }
    return globalThis.window?.confirm || null;
}

function normalizeRevision(value) {
    const parsed = Number.parseInt(String(value || ''), 10);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
}

function asArray(value) {
    return Array.isArray(value) ? value : [];
}

function formatTime(ts) {
    const value = Number(ts || 0);
    if (!value) {
        return '--';
    }
    try {
        return new Date(value * 1000).toLocaleString('zh-CN', { hour12: false });
    } catch (_) {
        return String(value);
    }
}

function revisionLabel(revision, activeRevision = 0) {
    const revisionId = normalizeRevision(revision?.revision);
    const status = String(revision?.status || '').trim() || 'unknown';
    const source = String(revision?.source || '').trim() || 'unknown';
    const activeSuffix = revisionId === activeRevision ? ' · active' : '';
    return `#${revisionId} · ${status}${activeSuffix} · ${source} · ${formatTime(revision?.created_at)}`;
}

function createOption(documentObj, value, label, disabled = false) {
    const option = documentObj.createElement('option');
    option.value = String(value || '');
    option.textContent = label;
    option.disabled = !!disabled;
    return option;
}

export function ensurePromptGovernanceState(page) {
    if (!page._promptGovernanceState || typeof page._promptGovernanceState !== 'object') {
        page._promptGovernanceState = {
            activeRevision: 0,
            selectedRevision: 0,
            previewRevision: 0,
            revisions: [],
            issues: [],
            diff: null,
            feedback: '尚未加载 Prompt 版本历史',
            feedbackState: 'idle',
            loading: false,
            previewing: false,
            rollingBack: false,
        };
    }
    return page._promptGovernanceState;
}

export function getSelectedPromptRevision(page) {
    const select = page.$?.('#settings-prompt-revision-select');
    return normalizeRevision(select?.value || ensurePromptGovernanceState(page).selectedRevision);
}

function setFeedback(page, message, state = 'idle') {
    const governanceState = ensurePromptGovernanceState(page);
    governanceState.feedback = String(message || '').trim();
    governanceState.feedbackState = state;
}

function isConnected(page) {
    return !!page.getState?.('bot.connected');
}

function updateButton(button, disabled, label) {
    if (!button) {
        return;
    }
    button.disabled = !!disabled;
    if (label) {
        const labelNode = button.querySelector?.('span');
        if (labelNode) {
            labelNode.textContent = label;
        } else {
            button.textContent = label;
        }
    }
}

export function renderPromptGovernancePanel(page) {
    const state = ensurePromptGovernanceState(page);
    const select = page.$?.('#settings-prompt-revision-select');
    const feedback = page.$?.('#settings-prompt-governance-feedback');
    const meta = page.$?.('#settings-prompt-governance-meta');
    const issueNode = page.$?.('#settings-prompt-governance-issues');
    const diffNode = page.$?.('#settings-prompt-revision-diff');
    const reasonInput = page.$?.('#settings-prompt-rollback-reason');
    const refreshButton = page.$?.('#btn-refresh-prompt-revisions');
    const previewButton = page.$?.('#btn-preview-prompt-revision-diff');
    const rollbackButton = page.$?.('#btn-rollback-prompt-revision');

    const connected = isConnected(page);

    if (select && typeof document !== 'undefined') {
        const documentObj = select.ownerDocument || document;
        const previousValue = String(select.value || state.selectedRevision || '');
        select.textContent = '';
        const revisions = asArray(state.revisions)
            .slice()
            .sort((a, b) => normalizeRevision(b?.revision) - normalizeRevision(a?.revision));
        if (!revisions.length) {
            select.appendChild(createOption(documentObj, '', '暂无 Prompt revision', true));
        } else {
            revisions.forEach((item) => {
                select.appendChild(createOption(
                    documentObj,
                    normalizeRevision(item?.revision),
                    revisionLabel(item, state.activeRevision),
                ));
            });
        }
        const hasPrevious = revisions.some((item) => String(normalizeRevision(item?.revision)) === previousValue);
        if (hasPrevious) {
            select.value = previousValue;
        } else {
            const firstHistorical = revisions.find((item) => normalizeRevision(item?.revision) !== normalizeRevision(state.activeRevision))
                || revisions[0]
                || null;
            select.value = firstHistorical ? String(normalizeRevision(firstHistorical?.revision)) : '';
        }
        state.selectedRevision = normalizeRevision(select.value);
    }

    const selectedRevision = getSelectedPromptRevision(page);
    state.selectedRevision = selectedRevision;
    const hasSelectedRevision = selectedRevision > 0;
    const isActiveTarget = selectedRevision > 0 && selectedRevision === normalizeRevision(state.activeRevision);
    const hasFreshPreview = !!state.diff && normalizeRevision(state.previewRevision) === selectedRevision;

    if (feedback) {
        feedback.textContent = state.feedback || '尚未加载 Prompt 版本历史';
        feedback.dataset.state = state.feedbackState || 'idle';
    }
    if (meta) {
        const total = asArray(state.revisions).length;
        meta.textContent = total
            ? `共 ${total} 个版本，当前 active revision 为 #${normalizeRevision(state.activeRevision)}`
            : '版本历史会在 Python 服务连接后显示。';
    }
    if (issueNode) {
        const issues = asArray(state.issues).map((item) => String(item || '').trim()).filter(Boolean);
        issueNode.textContent = issues.length ? `账本诊断：${issues.join('、')}` : '';
        issueNode.hidden = issues.length === 0;
    }
    if (diffNode) {
        const diffLines = asArray(state.diff?.diff);
        diffNode.textContent = diffLines.length
            ? diffLines.join('\n')
            : '先选择一个历史版本，再生成差异预览。';
        diffNode.dataset.state = diffLines.length ? 'ready' : 'empty';
    }
    if (reasonInput && !String(reasonInput.placeholder || '').trim()) {
        reasonInput.placeholder = '例如：上一版回复更稳定';
    }

    updateButton(refreshButton, !connected || state.loading, state.loading ? '加载中...' : '刷新版本');
    updateButton(previewButton, !connected || state.loading || state.previewing || !hasSelectedRevision, state.previewing ? '生成中...' : '预览差异');
    updateButton(
        rollbackButton,
        !connected || state.rollingBack || !hasSelectedRevision || isActiveTarget || !hasFreshPreview,
        state.rollingBack ? '回滚中...' : '回滚到所选版本',
    );
}

export function handlePromptRevisionSelection(page) {
    const state = ensurePromptGovernanceState(page);
    state.selectedRevision = getSelectedPromptRevision(page);
    state.previewRevision = 0;
    state.diff = null;
    setFeedback(page, '已切换目标版本，请先预览差异。', 'idle');
    renderPromptGovernancePanel(page);
}

export async function loadPromptRevisions(page, options = {}, text = {}, deps = {}) {
    const state = ensurePromptGovernanceState(page);
    const currentToast = getToast(deps);
    const silent = !!options?.silent;
    if (!isConnected(page)) {
        state.revisions = [];
        state.activeRevision = 0;
        state.selectedRevision = 0;
        state.diff = null;
        state.previewRevision = 0;
        state.issues = [];
        setFeedback(page, '请先启动 Python 服务后查看 Prompt 版本历史。', 'warning');
        renderPromptGovernancePanel(page);
        return null;
    }

    state.loading = true;
    setFeedback(page, '正在加载 Prompt 版本历史...', 'loading');
    renderPromptGovernancePanel(page);
    try {
        const result = await getApiService(deps).getPromptRevisions();
        if (!result?.success) {
            throw new Error(result?.message || text.promptGovernanceLoadFailed || '加载 Prompt 版本历史失败');
        }
        state.revisions = asArray(result.revisions);
        state.activeRevision = normalizeRevision(result.active_revision);
        state.issues = asArray(result.issues);
        state.diff = null;
        state.previewRevision = 0;
        setFeedback(page, state.revisions.length ? '已加载 Prompt 版本历史。' : '暂未发现 Prompt 版本历史。', 'success');
        renderPromptGovernancePanel(page);
        if (!silent) {
            currentToast.success('Prompt 版本历史已刷新');
        }
        return result;
    } catch (error) {
        console.error('[SettingsPage] prompt revisions failed:', error);
        setFeedback(page, currentToast.getErrorMessage(error, text.promptGovernanceLoadFailed || '加载 Prompt 版本历史失败'), 'error');
        renderPromptGovernancePanel(page);
        if (!silent) {
            currentToast.error(state.feedback);
        }
        return null;
    } finally {
        state.loading = false;
        renderPromptGovernancePanel(page);
    }
}

export async function previewPromptRevisionDiff(page, text = {}, deps = {}) {
    const state = ensurePromptGovernanceState(page);
    const currentToast = getToast(deps);
    const revision = getSelectedPromptRevision(page);
    if (!revision) {
        setFeedback(page, '请先选择一个历史版本。', 'warning');
        renderPromptGovernancePanel(page);
        return null;
    }

    state.previewing = true;
    state.diff = null;
    state.previewRevision = 0;
    setFeedback(page, `正在生成 #${revision} 的差异预览...`, 'loading');
    renderPromptGovernancePanel(page);
    try {
        const result = await getApiService(deps).getPromptRevisionDiff(revision);
        if (!result?.success) {
            throw new Error(result?.message || text.promptGovernanceDiffFailed || '生成 Prompt 差异失败');
        }
        state.diff = result;
        state.previewRevision = revision;
        state.activeRevision = normalizeRevision(result.active_revision || state.activeRevision);
        state.issues = asArray(result.issues);
        const changed = result?.summary?.changed === false ? '没有内容差异' : '差异预览已生成';
        setFeedback(page, `${changed}，确认后可执行回滚。`, 'success');
        renderPromptGovernancePanel(page);
        return result;
    } catch (error) {
        console.error('[SettingsPage] prompt diff failed:', error);
        setFeedback(page, currentToast.getErrorMessage(error, text.promptGovernanceDiffFailed || '生成 Prompt 差异失败'), 'error');
        renderPromptGovernancePanel(page);
        currentToast.error(state.feedback);
        return null;
    } finally {
        state.previewing = false;
        renderPromptGovernancePanel(page);
    }
}

export async function rollbackPromptRevision(page, text = {}, deps = {}) {
    const state = ensurePromptGovernanceState(page);
    const currentToast = getToast(deps);
    const revision = getSelectedPromptRevision(page);
    if (!revision) {
        setFeedback(page, '请先选择一个历史版本。', 'warning');
        renderPromptGovernancePanel(page);
        return null;
    }
    if (revision === normalizeRevision(state.activeRevision)) {
        setFeedback(page, '当前 active revision 无需回滚。', 'warning');
        renderPromptGovernancePanel(page);
        return null;
    }
    if (!state.diff || normalizeRevision(state.previewRevision) !== revision) {
        setFeedback(page, '请先预览所选版本的差异，再执行回滚。', 'warning');
        renderPromptGovernancePanel(page);
        return null;
    }

    const confirm = getConfirm(deps);
    const confirmMessage = `确认把系统 Prompt 回滚到 revision #${revision} 吗？系统会追加一条新的 active revision，不会覆盖历史记录。`;
    if (confirm && !confirm(confirmMessage)) {
        setFeedback(page, '已取消 Prompt 回滚。', 'idle');
        renderPromptGovernancePanel(page);
        return null;
    }

    const reason = String(page.$?.('#settings-prompt-rollback-reason')?.value || '').trim();
    state.rollingBack = true;
    setFeedback(page, `正在回滚到 #${revision}...`, 'loading');
    renderPromptGovernancePanel(page);
    try {
        const result = await getApiService(deps).rollbackPromptRevision(revision, {
            reason,
            operator: 'settings-ui',
        });
        if (!result?.success) {
            throw new Error(result?.message || text.promptRollbackFailed || 'Prompt 回滚失败');
        }
        state.diff = null;
        state.previewRevision = 0;
        if (page.$?.('#settings-prompt-rollback-reason')) {
            page.$('#settings-prompt-rollback-reason').value = '';
        }
        await page.loadSettings?.({ silent: true, preserveFeedback: true });
        await loadPromptRevisions(page, { silent: true }, text, deps);
        setFeedback(page, `已回滚到 #${revision}，新 active revision 为 #${normalizeRevision(result.active_revision)}。`, 'success');
        renderPromptGovernancePanel(page);
        page._renderWorkbenchState?.();
        currentToast.success(result?.runtime_apply?.message || 'Prompt 回滚已完成');
        return result;
    } catch (error) {
        console.error('[SettingsPage] prompt rollback failed:', error);
        setFeedback(page, currentToast.getErrorMessage(error, text.promptRollbackFailed || 'Prompt 回滚失败'), 'error');
        renderPromptGovernancePanel(page);
        currentToast.error(state.feedback);
        return null;
    } finally {
        state.rollingBack = false;
        renderPromptGovernancePanel(page);
    }
}
