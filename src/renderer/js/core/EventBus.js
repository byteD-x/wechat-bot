/**
 * 事件总线
 * 
 * 提供模块间松耦合通信机制
 */

import { debugLog } from './Debug.js';

class EventBus {
    constructor() {
        // 事件 -> 处理器集合
        this._handlers = new Map();

        // 一次性事件处理器
        this._onceHandlers = new Map();
    }

    /**
     * 订阅事件
     * @param {string} event - 事件名称
     * @param {Function} handler - 处理函数
     * @returns {Function} 取消订阅函数
     */
    on(event, handler) {
        if (!this._handlers.has(event)) {
            this._handlers.set(event, new Set());
        }
        this._handlers.get(event).add(handler);

        // 返回取消订阅函数
        return () => this.off(event, handler);
    }

    /**
     * 取消订阅
     * @param {string} event - 事件名称
     * @param {Function} handler - 处理函数
     */
    off(event, handler) {
        if (handler) {
            const regular = this._handlers.get(event);
            if (regular) {
                regular.delete(handler);
                if (regular.size === 0) {
                    this._handlers.delete(event);
                }
            }

            const once = this._onceHandlers.get(event);
            if (once) {
                once.delete(handler);
                if (once.size === 0) {
                    this._onceHandlers.delete(event);
                }
            }
        } else {
            // 如果没有指定处理器，移除该事件的所有处理器
            this._handlers.delete(event);
            this._onceHandlers.delete(event);
        }
    }

    /**
     * 只订阅一次
     * @param {string} event - 事件名称
     * @param {Function} handler - 处理函数
     * @returns {Function} 取消订阅函数
     */
    once(event, handler) {
        if (!this._onceHandlers.has(event)) {
            this._onceHandlers.set(event, new Set());
        }
        this._onceHandlers.get(event).add(handler);

        return () => this._onceHandlers.get(event)?.delete(handler);
    }

    /**
     * 触发事件
     * @param {string} event - 事件名称
     * @param {*} data - 事件数据
     */
    emit(event, data) {
        if (!this._handlers.has(event) && !this._onceHandlers.has(event)) {
            return;
        }
        debugLog(`[EventBus] 触发事件: ${event}`, data);

        // 触发普通处理器
        const regularHandlers = this._handlers.get(event);
        if (regularHandlers && regularHandlers.size > 0) {
            // Copy to prevent handler mutation (on/off) from affecting iteration order.
            for (const handler of Array.from(regularHandlers)) {
                try {
                    handler(data);
                } catch (error) {
                    console.error(`[EventBus] 事件处理错误 (${event}):`, error);
                }
            }
        }

        // 触发一次性处理器
        const onceHandlers = this._onceHandlers.get(event);
        if (onceHandlers && onceHandlers.size > 0) {
            for (const handler of Array.from(onceHandlers)) {
                try {
                    handler(data);
                } catch (error) {
                    console.error(`[EventBus] 事件处理错误 (${event}):`, error);
                }
            }
            // 清空一次性处理器
            this._onceHandlers.delete(event);
        }
    }

    /**
     * 清空所有事件处理器
     */
    clear() {
        this._handlers.clear();
        this._onceHandlers.clear();
    }

    /**
     * 获取事件的处理器数量
     * @param {string} event - 事件名称
     */
    getHandlerCount(event) {
        const regular = this._handlers.get(event)?.size || 0;
        const once = this._onceHandlers.get(event)?.size || 0;
        return regular + once;
    }
}

// 预定义事件常量
export const Events = {
    // 页面事件
    PAGE_CHANGE: 'page:change',
    PAGE_ENTER: 'page:enter',
    PAGE_LEAVE: 'page:leave',

    // 机器人事件
    BOT_START: 'bot:start',
    BOT_STOP: 'bot:stop',
    BOT_PAUSE: 'bot:pause',
    BOT_RESUME: 'bot:resume',
    BOT_RESTART: 'bot:restart',
    BOT_STATUS_CHANGE: 'bot:status-change',

    // 连接事件
    BACKEND_CONNECTED: 'backend:connected',
    BACKEND_DISCONNECTED: 'backend:disconnected',

    // 消息事件
    MESSAGES_LOADED: 'messages:loaded',
    MESSAGE_RECEIVED: 'message:received',

    // 配置事件
    CONFIG_LOADED: 'config:loaded',
    CONFIG_SAVED: 'config:saved',

    // 日志事件
    LOGS_LOADED: 'logs:loaded',
    LOGS_CLEARED: 'logs:cleared',

    // 通知事件
    TOAST_SHOW: 'toast:show',

    // 窗口事件
    WINDOW_MINIMIZE: 'window:minimize',
    WINDOW_MAXIMIZE: 'window:maximize',
    WINDOW_CLOSE: 'window:close'
};

// 导出单例
export const eventBus = new EventBus();
export default eventBus;
