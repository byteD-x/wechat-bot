import test from 'node:test';
import assert from 'node:assert/strict';

import {
    setupGlobalButtonFeedback,
} from '../../src/renderer/js/app/button-feedback.js';

function wait(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

function createClassList() {
    const values = new Set();
    return {
        add(...tokens) {
            tokens.filter(Boolean).forEach((token) => values.add(token));
        },
        remove(...tokens) {
            tokens.filter(Boolean).forEach((token) => values.delete(token));
        },
        contains(token) {
            return values.has(token);
        },
    };
}

function createInteractiveElement({ disabled = false, ariaDisabled = '', kind = 'button' } = {}) {
    const element = {
        disabled: !!disabled,
        classList: createClassList(),
        parentElement: null,
        getAttribute(name) {
            if (name === 'aria-disabled') {
                return ariaDisabled;
            }
            return '';
        },
        closest(selector) {
            if (kind === 'button' && selector.includes('button')) {
                return this;
            }
            if (kind === 'nav-item' && selector.includes('.nav-item')) {
                return this;
            }
            return this.parentElement?.closest?.(selector) || null;
        },
    };
    return element;
}

function createNonInteractiveChild(parent) {
    return {
        parentElement: parent,
    };
}

function createEventRoot() {
    const listeners = new Map();
    return {
        addEventListener(type, handler) {
            const key = String(type || '');
            if (!listeners.has(key)) {
                listeners.set(key, []);
            }
            listeners.get(key).push(handler);
        },
        removeEventListener(type, handler) {
            const key = String(type || '');
            const registered = listeners.get(key) || [];
            listeners.set(
                key,
                registered.filter((item) => item !== handler),
            );
        },
        dispatch(type, payload) {
            for (const handler of listeners.get(String(type || '')) || []) {
                handler(payload || {});
            }
        },
        listenerCount(type) {
            return (listeners.get(String(type || '')) || []).length;
        },
    };
}

test('global button feedback applies click animation and auto-cleans class', async () => {
    const root = createEventRoot();
    setupGlobalButtonFeedback(root);

    const button = createInteractiveElement();
    root.dispatch('click', { target: button });

    assert.equal(button.classList.contains('has-button-feedback'), true);
    assert.equal(button.classList.contains('is-feedback-clicked'), true);

    await wait(260);
    assert.equal(button.classList.contains('is-feedback-clicked'), false);
});

test('global button feedback supports nested targets and keyboard activation', async () => {
    const root = createEventRoot();
    setupGlobalButtonFeedback(root);

    const button = createInteractiveElement({ kind: 'nav-item' });
    const child = createNonInteractiveChild(button);

    root.dispatch('keydown', { key: 'Enter', target: child });
    assert.equal(button.classList.contains('is-feedback-pressed'), true);

    await wait(180);
    assert.equal(button.classList.contains('is-feedback-pressed'), false);
});

test('global button feedback ignores disabled controls and is idempotent', () => {
    const root = createEventRoot();
    const cleanupA = setupGlobalButtonFeedback(root);
    const cleanupB = setupGlobalButtonFeedback(root);

    assert.equal(cleanupA, cleanupB);
    assert.equal(root.listenerCount('click'), 1);
    assert.equal(root.listenerCount('pointerdown'), 1);
    assert.equal(root.listenerCount('keydown'), 1);

    const disabled = createInteractiveElement({ disabled: true });
    const ariaDisabled = createInteractiveElement({ ariaDisabled: 'true' });

    root.dispatch('click', { target: disabled });
    root.dispatch('click', { target: ariaDisabled });

    assert.equal(disabled.classList.contains('has-button-feedback'), false);
    assert.equal(ariaDisabled.classList.contains('has-button-feedback'), false);

    cleanupA();
    assert.equal(root.listenerCount('click'), 0);
    assert.equal(root.listenerCount('pointerdown'), 0);
    assert.equal(root.listenerCount('keydown'), 0);
});

test('global button feedback cleanup clears pending transient state', async () => {
    const root = createEventRoot();
    const cleanup = setupGlobalButtonFeedback(root);

    const button = createInteractiveElement();
    root.dispatch('click', { target: button });

    assert.equal(button.classList.contains('has-button-feedback'), true);
    assert.equal(button.classList.contains('is-feedback-clicked'), true);

    cleanup();
    assert.equal(button.classList.contains('has-button-feedback'), false);
    assert.equal(button.classList.contains('is-feedback-clicked'), false);

    await wait(260);
    assert.equal(button.classList.contains('is-feedback-clicked'), false);
});
