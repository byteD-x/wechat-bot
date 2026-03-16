/**
 * Debug helpers
 *
 * Enable by:
 * - URL query: ?debug=1
 * - localStorage: debug=1 / true
 */

export const DEBUG_ENABLED = (() => {
    try {
        const params = new URLSearchParams(window.location.search);
        const value = String(params.get('debug') || '').trim().toLowerCase();
        if (value === '1' || value === 'true') {
            return true;
        }
    } catch {
        // ignore
    }

    try {
        const value = String(localStorage.getItem('debug') || '').trim().toLowerCase();
        if (value === '1' || value === 'true' || value === 'yes') {
            return true;
        }
    } catch {
        // ignore
    }

    return false;
})();

export function debugLog(...args) {
    if (DEBUG_ENABLED) {
        console.log(...args);
    }
}

export function debugWarn(...args) {
    if (DEBUG_ENABLED) {
        console.warn(...args);
    }
}

