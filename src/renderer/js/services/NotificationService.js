/**
 * 通知服务
 *
 * 提供 Toast 通知能力。
 */

import { eventBus, Events } from '../core/EventBus.js';

class NotificationService {
    constructor() {
        this.container = null;
        this.defaultDuration = 3000;
    }

    init() {
        this.container = document.getElementById('toast-container');
        if (!this.container) {
            console.warn('[NotificationService] Toast 容器未找到');
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

        toast.appendChild(iconWrap);
        toast.appendChild(msgWrap);
        this.container.appendChild(toast);

        eventBus.emit(Events.TOAST_SHOW, { message, type });

        setTimeout(() => {
            toast.style.animation = 'toastEnter 0.25s ease reverse';
            setTimeout(() => toast.remove(), 250);
        }, duration);
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
            info: 'info'
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
}

export const notificationService = new NotificationService();
export default notificationService;
export const toast = notificationService;
