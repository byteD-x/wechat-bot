import { FIELD_META_BY_ID } from './schema.js';
import { createElement } from './form-codec.js';
import {
    renderExportRagStatus,
    renderPresetList,
    renderSaveFeedback,
    renderSettingsHero,
} from './renderers.js';

export function initModuleSaveButtons(page) {
    page.$$('.settings-card').forEach((card) => {
        const meta = getCardConfigMeta(card);
        if (!meta) {
            return;
        }
        ensureCardSaveButton(page, card, meta);
    });
}

export function getCardConfigMeta(card) {
    if (!card) {
        return null;
    }

    const ids = new Set(
        Array.from(card.querySelectorAll('[id]'))
            .map((element) => element.id)
            .filter((id) => FIELD_META_BY_ID.has(id)),
    );
    const includeApiPresets = !!card.querySelector('#preset-list');
    const sections = new Set();
    ids.forEach((id) => {
        const meta = FIELD_META_BY_ID.get(id);
        if (meta?.section) {
            sections.add(meta.section);
        }
    });
    if (includeApiPresets) {
        sections.add('api');
    }
    if (!ids.size && !includeApiPresets) {
        return null;
    }

    return {
        title: card.querySelector('.settings-card-title')?.textContent?.trim() || '当前模块',
        ids,
        sections,
        includeApiPresets,
    };
}

function ensureCardSaveButton(page, card, meta) {
    if (card.querySelector('[data-card-save-button]')) {
        return;
    }

    let header = card.querySelector('.settings-card-header');
    const title = card.querySelector('.settings-card-title');
    if (!header && title) {
        header = createElement('div', 'settings-card-header');
        card.insertBefore(header, title);
        title.style.marginBottom = '0';
        header.appendChild(title);
    }
    if (!header) {
        return;
    }

    let actions = header.querySelector('.settings-card-header-actions');
    if (!actions) {
        actions = createElement('div', 'settings-card-header-actions');
        header.appendChild(actions);
    }

    const button = createElement('button', 'btn btn-primary btn-sm', '\u4fdd\u5b58\u672c\u6a21\u5757');
    button.type = 'button';
    button.dataset.cardSaveButton = 'true';
    button.dataset.cardTitle = meta.title;
    button.addEventListener('click', () => {
        void page._saveSettings({ scope: meta, triggerButton: button });
    });
    actions.appendChild(button);
}

export function initScrollControls(page) {
    page._mainContent = document.querySelector('.main-content');
    page._scrollTopButton = page.$('#btn-settings-scroll-top');
    if (!page._mainContent) {
        return;
    }

    const onScroll = () => handleMainScroll(page);
    page._mainContent.addEventListener('scroll', onScroll);
    page._eventCleanups.push(() => {
        page._mainContent?.removeEventListener('scroll', onScroll);
    });
}

export function handleMainScroll(page) {
    if (!page._mainContent || !page._scrollTopButton) {
        return;
    }
    const visible = page.isActive() && page._mainContent.scrollTop > 240;
    page._scrollTopButton.classList.toggle('visible', visible);
}

export function scrollToTop(page) {
    page._mainContent?.scrollTo({ top: 0, behavior: 'smooth' });
}

function setButtonLabel(button, label) {
    if (!button) {
        return;
    }
    const textNode = button.querySelector('span');
    if (textNode) {
        textNode.textContent = label;
        return;
    }
    button.textContent = label;
}

export function setSavingState(page, isSaving, triggerButton = null) {
    page._isSaving = isSaving;
    const buttons = [page.$('#btn-save-settings'), ...page.$$('[data-card-save-button]')].filter(Boolean);
    buttons.forEach((button) => {
        if (!button.dataset.originalLabel) {
            button.dataset.originalLabel = button.querySelector('span')?.textContent
                || button.textContent
                || '\u4fdd\u5b58';
        }
        button.disabled = isSaving;
        if (button === triggerButton) {
            button.classList.toggle('is-loading', isSaving);
            setButtonLabel(button, isSaving ? '\u4fdd\u5b58\u4e2d...' : button.dataset.originalLabel);
        } else if (!isSaving) {
            button.classList.remove('is-loading');
            setButtonLabel(button, button.dataset.originalLabel);
        }
    });
}

export function renderLoadError(page, message) {
    const hero = page.$('#current-config-hero');
    if (hero) {
        hero.textContent = '';
        const card = createElement('div', 'config-hero-card');
        const content = createElement('div', 'hero-content');
        const title = createElement('div', 'hero-title');
        const name = createElement('span', 'hero-name', String(message || ''));
        title.appendChild(name);
        content.appendChild(title);
        card.appendChild(content);
        hero.appendChild(card);
    }
}

export function renderHero(page, highlight = false) {
    renderSettingsHero(page, highlight);
}

export function renderPresetCards(page) {
    renderPresetList(page);
}

export function renderPageSaveFeedback(page, result, fallbackText) {
    renderSaveFeedback(page, result, fallbackText);
}

export function hideSaveFeedback(page) {
    if (page.$('#config-save-feedback')) {
        page.$('#config-save-feedback').hidden = true;
    }
}

export function renderPageExportRagStatus(page) {
    renderExportRagStatus(page);
}
