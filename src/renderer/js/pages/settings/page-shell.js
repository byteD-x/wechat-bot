import { FIELD_META_BY_ID } from './schema.js';

function getDocument(deps = {}) {
    return deps.documentObj || globalThis.document;
}

function getWindow(deps = {}) {
    return deps.windowObj || globalThis.window;
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
    page.bindEvent('#btn-refresh-config', 'click', () => void page.loadSettings({ silent: false }));
    page.bindEvent('#btn-save-settings', 'click', () => void page._saveSettings());
    page.bindEvent('#btn-preview-prompt', 'click', () => void page._previewPrompt());
    page.bindEvent('#btn-reset-close-behavior', 'click', () => void page._resetCloseBehavior());
    page.bindEvent('#btn-settings-scroll-top', 'click', () => page._scrollToTop());
    page.bindEvent('#btn-add-preset', 'click', () => page._openPresetModal());
    page.bindEvent('#btn-close-modal', 'click', () => page._closePresetModal());
    page.bindEvent('#btn-cancel-modal', 'click', () => page._closePresetModal());
    page.bindEvent('#btn-save-modal', 'click', () => page._commitPresetModal());
    page.bindEvent('#btn-toggle-key', 'click', () => page._togglePresetKeyVisibility());

    page.$('#edit-preset-provider')?.addEventListener('change', () => void page._handlePresetProviderChange());
    page.$('#edit-preset-model-select')?.addEventListener('change', () => page._syncPresetModelInput());

    const documentObj = getDocument(deps);
    documentObj.getElementById('preset-modal')?.addEventListener('click', (event) => {
        if (event.target?.id === 'preset-modal') {
            page._closePresetModal();
        }
    });

    page.bindEvent(getWindow(deps), 'keydown', (event) => {
        if (event.key === 'Escape' && documentObj.getElementById('preset-modal')?.classList.contains('active')) {
            page._closePresetModal();
        }
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
        page._scheduleAutoSave({ immediate });
    };

    root.addEventListener('input', schedule, true);
    root.addEventListener('change', schedule, true);
    page._eventCleanups.push(() => {
        root.removeEventListener?.('input', schedule, true);
        root.removeEventListener?.('change', schedule, true);
    });
}
