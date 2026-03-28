const FEEDBACK_SELECTOR = [
    'button',
    '[role="button"]',
    '.nav-item',
    '.status-badge',
    '.update-badge',
].join(', ');

const KEYBOARD_TRIGGER_KEYS = new Set(['Enter', ' ', 'Spacebar']);

function normalizeEventTarget(target) {
    if (target && typeof target.closest === 'function') {
        return target;
    }
    if (target?.parentElement && typeof target.parentElement.closest === 'function') {
        return target.parentElement;
    }
    return null;
}

function isDisabledTarget(target) {
    if (!target) {
        return true;
    }
    if (target.disabled) {
        return true;
    }
    const ariaDisabled = String(target.getAttribute?.('aria-disabled') || '').trim().toLowerCase();
    if (ariaDisabled === 'true') {
        return true;
    }
    return false;
}

function addTransientClass(target, className, durationMs) {
    if (!target || !className) {
        return;
    }
    if (!target.__feedbackTimers) {
        target.__feedbackTimers = {};
    }
    const previousTimer = target.__feedbackTimers[className];
    if (previousTimer) {
        clearTimeout(previousTimer);
    }
    target.classList.remove(className);
    target.classList.add(className);
    target.__feedbackTimers[className] = setTimeout(() => {
        target.classList.remove(className);
        delete target.__feedbackTimers[className];
    }, durationMs);
}

export function findFeedbackTarget(source) {
    const element = normalizeEventTarget(source);
    if (!element) {
        return null;
    }
    const matched = element.closest(FEEDBACK_SELECTOR);
    if (!matched || isDisabledTarget(matched)) {
        return null;
    }
    return matched;
}

export function setupGlobalButtonFeedback(root = document) {
    if (!root || typeof root.addEventListener !== 'function') {
        return () => {};
    }
    if (typeof root.__buttonFeedbackCleanup === 'function') {
        return root.__buttonFeedbackCleanup;
    }

    const activeTargets = new Set();

    const rememberTarget = (target) => {
        if (target) {
            activeTargets.add(target);
        }
    };

    const clearTargetFeedback = (target) => {
        if (!target) {
            return;
        }
        if (target.__feedbackTimers) {
            for (const timer of Object.values(target.__feedbackTimers)) {
                clearTimeout(timer);
            }
            delete target.__feedbackTimers;
        }
        target.classList.remove('has-button-feedback', 'is-feedback-pressed', 'is-feedback-clicked');
    };

    const pulsePressed = (event) => {
        const target = findFeedbackTarget(event?.target);
        if (!target) {
            return;
        }
        rememberTarget(target);
        target.classList.add('has-button-feedback');
        addTransientClass(target, 'is-feedback-pressed', 140);
    };

    const pulseClicked = (event) => {
        const target = findFeedbackTarget(event?.target);
        if (!target) {
            return;
        }
        rememberTarget(target);
        target.classList.add('has-button-feedback');
        addTransientClass(target, 'is-feedback-clicked', 220);
    };

    const pulseKeyboard = (event) => {
        if (!KEYBOARD_TRIGGER_KEYS.has(String(event?.key || ''))) {
            return;
        }
        pulsePressed(event);
    };

    root.addEventListener('pointerdown', pulsePressed, true);
    root.addEventListener('keydown', pulseKeyboard, true);
    root.addEventListener('click', pulseClicked, true);

    const cleanup = () => {
        root.removeEventListener('pointerdown', pulsePressed, true);
        root.removeEventListener('keydown', pulseKeyboard, true);
        root.removeEventListener('click', pulseClicked, true);
        for (const target of activeTargets) {
            clearTargetFeedback(target);
        }
        activeTargets.clear();
        if (root.__buttonFeedbackCleanup === cleanup) {
            delete root.__buttonFeedbackCleanup;
        }
    };

    root.__buttonFeedbackCleanup = cleanup;
    return cleanup;
}

export default setupGlobalButtonFeedback;
