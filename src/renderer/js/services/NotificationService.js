/**
 * Notification service for toast feedback.
 */

import { eventBus, Events } from '../core/EventBus.js';

class NotificationService {
    constructor() {
        this.container = null;
        this.defaultDuration = 3000;
        this.hoverResumeDuration = 1400;
    }

    init() {
        this.container = document.getElementById('toast-container');
        if (!this.container) {
            this.container = this._createFallbackContainer();
        }
        if (!this.container) {
            console.warn('[NotificationService] Toast container is missing');
        }
    }

    show(message, type = 'info', duration = this.defaultDuration) {
        if (!this.container) {
            this.init();
        }

        if (!this.container) {
            return;
        }

        const toast = document.createElement('div');
        toast.className = `toast ${type}`;

        const iconWrap = document.createElement('span');
        iconWrap.className = 'toast-icon';
        iconWrap.appendChild(this._getIconSvgElement(type));

        const msgWrap = document.createElement('span');
        msgWrap.className = 'toast-message';
        msgWrap.textContent = String(message ?? '');

        const closeButton = document.createElement('button');
        closeButton.type = 'button';
        closeButton.className = 'toast-close';
        closeButton.setAttribute('aria-label', '关闭提示');
        closeButton.appendChild(this._getIconSvgElement('x'));

        toast.appendChild(iconWrap);
        toast.appendChild(msgWrap);
        toast.appendChild(closeButton);
        this.container.appendChild(toast);

        eventBus.emit(Events.TOAST_SHOW, { message, type });

        const setTimer = typeof globalThis.setTimeout === 'function'
            ? globalThis.setTimeout.bind(globalThis)
            : (typeof globalThis.window?.setTimeout === 'function'
                ? globalThis.window.setTimeout.bind(globalThis.window)
                : (callback) => {
                    callback();
                    return 0;
                });
        const clearTimer = typeof globalThis.clearTimeout === 'function'
            ? globalThis.clearTimeout.bind(globalThis)
            : (typeof globalThis.window?.clearTimeout === 'function'
                ? globalThis.window.clearTimeout.bind(globalThis.window)
                : () => {});

        let timeoutId = null;
        const dismiss = () => {
            if (!toast.isConnected || toast.classList.contains('is-leaving')) {
                return;
            }
            if (timeoutId) {
                clearTimer(timeoutId);
                timeoutId = null;
            }
            toast.classList.add('is-leaving');
            toast.classList.remove('is-visible');
            setTimer(() => {
                if (toast.isConnected) {
                    toast.remove();
                }
            }, 220);
        };

        const scheduleDismiss = (delay) => {
            if (timeoutId) {
                clearTimer(timeoutId);
            }
            timeoutId = setTimer(dismiss, delay);
        };

        closeButton.addEventListener('click', dismiss);
        toast.addEventListener('mouseenter', () => {
            if (timeoutId) {
                clearTimer(timeoutId);
                timeoutId = null;
            }
        });
        toast.addEventListener('mouseleave', () => {
            scheduleDismiss(this.hoverResumeDuration);
        });

        const runOnNextFrame = typeof globalThis.requestAnimationFrame === 'function'
            ? globalThis.requestAnimationFrame.bind(globalThis)
            : (callback) => setTimer(callback, 0);
        runOnNextFrame(() => {
            toast.classList.add('is-visible');
        });
        scheduleDismiss(Math.max(1200, Number(duration) || this.defaultDuration));
    }

    success(message, duration) {
        this.show(message, 'success', duration);
    }

    error(message, duration) {
        this.show(message, 'error', duration);
    }

    warning(message, duration) {
        this.show(message, 'warning', duration);
    }

    info(message, duration) {
        this.show(message, 'info', duration);
    }

    getErrorMessage(error, fallback = '操作失败') {
        if (!error) {
            return fallback;
        }
        if (typeof error === 'string') {
            return error;
        }
        if (error.message) {
            return error.message;
        }
        return fallback;
    }

    _getIconSvgElement(type) {
        const map = {
            success: 'check',
            error: 'x',
            warning: 'alert-circle',
            info: 'info',
            x: 'x',
        };
        const iconName = map[type] || 'info';

        const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.setAttribute('class', 'icon');

        const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
        const href = `#icon-${iconName}`;
        use.setAttribute('href', href);
        use.setAttributeNS('http://www.w3.org/1999/xlink', 'href', href);
        svg.appendChild(use);

        return svg;
    }

    _createFallbackContainer() {
        if (!globalThis.document?.body || typeof document.createElement !== 'function') {
            return null;
        }
        const container = document.createElement('div');
        container.setAttribute('id', 'toast-container');
        container.setAttribute('aria-live', 'polite');
        container.setAttribute('aria-atomic', 'false');
        container.setAttribute('role', 'status');
        document.body.appendChild(container);
        return container;
    }
}

export const notificationService = new NotificationService();
export default notificationService;
export const toast = notificationService;
