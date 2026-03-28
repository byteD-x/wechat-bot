import { Events } from '../../core/EventBus.js';
import { FIELD_META_BY_ID } from './schema.js';

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
    bindOptional('#btn-open-models', 'click', () => page.emit(Events.PAGE_CHANGE, 'models'));
    bindOptional('#settings-data-control-scope', 'change', () => page._renderBackupPanel?.());
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
        const immediate = isInputElement(target, deps)
            ? target.type === 'checkbox'
            : isSelectElement(target, deps);
        page._scheduleAutoSave({ immediate, target });
    };

    root.addEventListener('input', schedule, true);
    root.addEventListener('change', schedule, true);
    page._eventCleanups.push(() => {
        root.removeEventListener?.('input', schedule, true);
        root.removeEventListener?.('change', schedule, true);
    });
}
