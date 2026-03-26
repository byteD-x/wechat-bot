export const EMAIL_VISIBILITY_STORAGE_KEY = 'model-center:email-visibility:v1';
export const EMAIL_VISIBILITY_MODES = {
    full: 'full',
    masked: 'masked',
};

const EMAIL_PATTERN = /[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi;

export function getSafeStorage() {
    try {
        if (globalThis?.localStorage) {
            return globalThis.localStorage;
        }
        if (globalThis?.window?.localStorage) {
            return globalThis.window.localStorage;
        }
    } catch (_error) {
        return null;
    }
    return null;
}

export function normalizeEmailVisibilityMode(value) {
    return String(value || '').trim() === EMAIL_VISIBILITY_MODES.masked
        ? EMAIL_VISIBILITY_MODES.masked
        : EMAIL_VISIBILITY_MODES.full;
}

export function loadEmailVisibilityPreference() {
    const storage = getSafeStorage();
    if (!storage) {
        return EMAIL_VISIBILITY_MODES.full;
    }
    try {
        return normalizeEmailVisibilityMode(storage.getItem(EMAIL_VISIBILITY_STORAGE_KEY));
    } catch (_error) {
        return EMAIL_VISIBILITY_MODES.full;
    }
}

export function saveEmailVisibilityPreference(mode) {
    const storage = getSafeStorage();
    if (!storage) {
        return;
    }
    try {
        storage.setItem(EMAIL_VISIBILITY_STORAGE_KEY, normalizeEmailVisibilityMode(mode));
    } catch (_error) {
        // Ignore persistence failures in renderer.
    }
}

export function toggleEmailVisibilityMode(mode) {
    return normalizeEmailVisibilityMode(mode) === EMAIL_VISIBILITY_MODES.masked
        ? EMAIL_VISIBILITY_MODES.full
        : EMAIL_VISIBILITY_MODES.masked;
}

export function getEmailVisibilityButtonLabel(mode) {
    return normalizeEmailVisibilityMode(mode) === EMAIL_VISIBILITY_MODES.masked
        ? '显示完整邮箱'
        : '显示脱敏邮箱';
}

function maskSegment(value = '', visibleCount = 2) {
    const raw = String(value || '').trim();
    if (!raw) {
        return '';
    }
    if (raw.length === 1) {
        return '*';
    }
    if (raw.length === 2) {
        return `${raw[0]}*`;
    }
    const kept = raw.slice(0, Math.min(visibleCount, raw.length - 1));
    const hiddenLength = Math.max(2, Math.min(4, raw.length - kept.length));
    return `${kept}${'*'.repeat(hiddenLength)}`;
}

export function maskEmailAddress(email = '') {
    const raw = String(email || '').trim();
    if (!raw || !raw.includes('@')) {
        return raw;
    }
    const [localPart, domainPart] = raw.split('@');
    if (!localPart || !domainPart) {
        return raw;
    }
    const domainSegments = domainPart.split('.').filter(Boolean);
    if (!domainSegments.length) {
        return raw;
    }
    const [rootDomain, ...suffixes] = domainSegments;
    const suffix = suffixes.length ? `.${suffixes.join('.')}` : '';
    return `${maskSegment(localPart)}@${maskSegment(rootDomain)}${suffix}`;
}

export function formatEmailVisibilityText(value = '', mode = EMAIL_VISIBILITY_MODES.full) {
    const raw = String(value ?? '');
    if (normalizeEmailVisibilityMode(mode) === EMAIL_VISIBILITY_MODES.full) {
        return raw;
    }
    return raw.replace(EMAIL_PATTERN, (email) => maskEmailAddress(email));
}
