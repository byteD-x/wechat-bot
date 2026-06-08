import { Events } from '../../core/EventBus.js';
import { FIELD_META_BY_ID } from './schema.js';

const EXPLICIT_SAVE_FIELD_IDS = new Set([
    'setting-reload-ai-client-on-change',
    'setting-reload-ai-client-module',
    'setting-whitelist-enabled',
    'setting-usage-tracking-enabled',
    'setting-agent-langsmith-enabled',
    'setting-log-message-content',
    'setting-log-reply-content',
]);

function getDocument(deps = {}) {
    return deps.documentObj || globalThis.document;
}

function isInputElement(target, deps = {}) {
    const InputClass = deps.HTMLInputElementClass || globalThis.HTMLInputElement;
    if (typeof InputClass === 'function') {
        return target instanceof InputClass;
    }
    return String(target?.tagName || '').toUpperCase() === 'INPUT';
}

function isSelectElement(target, deps = {}) {
    const SelectClass = deps.HTMLSelectElementClass || globalThis.HTMLSelectElement;
    if (typeof SelectClass === 'function') {
        return target instanceof SelectClass;
    }
    return String(target?.tagName || '').toUpperCase() === 'SELECT';
}

export function shouldSaveSettingsChangeImmediately(target, eventType = '', deps = {}) {
    const id = String(target?.id || '').trim();
    if (!FIELD_META_BY_ID.has(id) || EXPLICIT_SAVE_FIELD_IDS.has(id)) {
        return false;
    }
    const normalizedEventType = String(eventType || '').trim();
    if (isSelectElement(target, deps)) {
        return normalizedEventType === 'change';
    }
    if (!isInputElement(target, deps)) {
        return false;
    }
    return target.type === 'checkbox' && normalizedEventType === 'change';
}

export function bindSettingsEvents(page, deps = {}) {
    const bindOptional = (selectorOrTarget, eventName, handler) => {
        const element = typeof selectorOrTarget === 'string' ? page.$(selectorOrTarget) : selectorOrTarget;
        if (!element) {
            return;
        }
        page.bindEvent(element, eventName, handler);
    };

    bindOptional('#btn-refresh-config', 'click', () => void page.loadSettings({ silent: false }));
    bindOptional('#btn-save-settings', 'click', () => void page._saveSettings());
    bindOptional('#btn-preview-prompt', 'click', () => void page._previewPrompt());
    bindOptional('#btn-refresh-prompt-revisions', 'click', () => void page._loadPromptRevisions?.({ silent: false }));
    bindOptional('#settings-prompt-revision-select', 'change', () => page._handlePromptRevisionSelection?.());
    bindOptional('#btn-preview-prompt-revision-diff', 'click', () => void page._previewPromptRevisionDiff?.());
    bindOptional('#btn-rollback-prompt-revision', 'click', () => void page._rollbackPromptRevision?.());
    bindOptional('#btn-reset-close-behavior', 'click', () => void page._resetCloseBehavior());
    bindOptional('#btn-settings-scroll-top', 'click', () => page._scrollToTop());
    bindOptional('#btn-create-quick-backup', 'click', () => void page._createWorkspaceBackup('quick'));
    bindOptional('#btn-create-full-backup', 'click', () => void page._createWorkspaceBackup('full'));
    bindOptional('#btn-restore-backup-dry-run', 'click', () => void page._restoreWorkspaceBackup(true));
    bindOptional('#btn-restore-backup-apply', 'click', () => void page._restoreWorkspaceBackup(false));
    bindOptional('#btn-cleanup-backup-dry-run', 'click', () => void page._cleanupWorkspaceBackups(true));
    bindOptional('#btn-cleanup-backup-apply', 'click', () => void page._cleanupWorkspaceBackups(false));
    bindOptional('#btn-data-control-dry-run', 'click', () => void page._runDataControls(true));
    bindOptional('#btn-data-control-apply', 'click', () => void page._runDataControls(false));
    bindOptional('#btn-knowledge-base-select-file', 'click', () => void page._selectKnowledgeBaseFile?.());
    bindOptional('#btn-knowledge-base-refresh', 'click', () => void page._refreshKnowledgeBaseStatus?.({ silent: false }));
    bindOptional('#btn-knowledge-base-dry-run', 'click', () => void page._previewKnowledgeBaseDocument?.());
    bindOptional('#btn-knowledge-base-ingest', 'click', () => void page._ingestKnowledgeBaseDocument?.());
    bindOptional('#btn-knowledge-base-rebuild', 'click', () => void page._rebuildKnowledgeBaseDocument?.());
    bindOptional('#btn-knowledge-base-batch-dry-run', 'click', () => void page._previewKnowledgeBaseDocuments?.());
    bindOptional('#btn-knowledge-base-batch-ingest', 'click', () => void page._ingestKnowledgeBaseDocuments?.());
    bindOptional('#btn-knowledge-base-batch-rebuild', 'click', () => void page._rebuildKnowledgeBaseDocuments?.());
    bindOptional('#btn-check-updates', 'click', () => void page._checkUpdates?.());
    bindOptional('#btn-open-update-download', 'click', () => void page._openUpdateDownload?.());
    bindOptional('#btn-open-models', 'click', () => page.emit(Events.PAGE_CHANGE, 'models'));
    bindOptional('#btn-open-export-center', 'click', () => page.emit(Events.PAGE_CHANGE, 'exports'));
    bindOptional('#settings-data-control-scope', 'change', () => page._renderBackupPanel?.());
    [
        '#settings-knowledge-base-content',
        '#settings-knowledge-base-content-type',
        '#settings-knowledge-base-doc-id',
        '#settings-knowledge-base-version',
        '#settings-knowledge-base-source-file',
        '#settings-knowledge-base-url',
        '#settings-knowledge-base-page',
    ].forEach((selector) => {
        bindOptional(selector, 'input', () => page._resetKnowledgeBasePreview?.());
        bindOptional(selector, 'change', () => page._resetKnowledgeBasePreview?.());
    });
    bindOptional('#settings-knowledge-base-batch-json', 'input', () => page._resetKnowledgeBaseBatchPreview?.());
    bindOptional('#settings-knowledge-base-batch-json', 'change', () => page._resetKnowledgeBaseBatchPreview?.());
    bindOptional('#settings-section-nav', 'click', (event) => {
        const button = event?.target?.closest?.('[data-settings-section]');
        if (!button) {
            return;
        }
        page._setSettingsSection?.(button.dataset.settingsSection || 'all');
    });
}

export function bindSettingsAutoSave(page, deps = {}) {
    const documentObj = getDocument(deps);
    const root = deps.rootElement || documentObj.getElementById(page.containerId);
    if (!root) {
        return;
    }

    const schedule = (event) => {
        const target = event?.target;
        if (!target || typeof target !== 'object') {
            return;
        }
        const id = target.id || '';
        if (!FIELD_META_BY_ID.has(id)) {
            return;
        }
        const immediate = shouldSaveSettingsChangeImmediately(target, event?.type, deps);
        page._scheduleAutoSave({ immediate, target });
    };

    root.addEventListener('input', schedule, true);
    root.addEventListener('change', schedule, true);
    page._eventCleanups.push(() => {
        root.removeEventListener?.('input', schedule, true);
        root.removeEventListener?.('change', schedule, true);
    });
}
