/**
 * 页面控制器基类
 * 
 * 提供统一的页面生命周期管理
 */

import { stateManager } from './StateManager.js';
import { eventBus, Events } from './EventBus.js';

export class PageController {
    /**
     * @param {string} name - 页面名称
     * @param {string} containerId - 容器元素ID
     */
    constructor(name, containerId) {
        this.name = name;
        this.containerId = containerId;
        this.container = null;
        this._eventCleanups = [];
        this._stateCleanups = [];
        this._isActive = false;
    }

    /**
     * 获取容器元素
     */
    getContainer() {
        if (!this.container) {
            this.container = document.getElementById(this.containerId);
        }
        return this.container;
    }

    /**
     * 查询容器内的元素
     * @param {string} selector - CSS 选择器
     */
    $(selector) {
        return this.getContainer()?.querySelector(selector);
    }

    /**
     * 查询容器内的所有匹配元素
     * @param {string} selector - CSS 选择器
     */
    $$(selector) {
        return this.getContainer()?.querySelectorAll(selector) || [];
    }

    // ═══════════════════════════════════════════════════════════════════════
    //                           生命周期方法
    // ═══════════════════════════════════════════════════════════════════════

    /**
     * 初始化（应用启动时调用一次）
     * 子类应重写此方法
     */
    async onInit() {
        console.log(`[${this.name}] 初始化`);
    }

    /**
     * 进入页面
     * 子类应重写此方法
     */
    async onEnter() {
        console.log(`[${this.name}] 进入页面`);
        this._isActive = true;
    }

    /**
     * 离开页面
     * 子类应重写此方法
     */
    async onLeave() {
        console.log(`[${this.name}] 离开页面`);
        this._isActive = false;
    }

    /**
     * 销毁页面
     * 子类应重写此方法
     */
    async onDestroy() {
        console.log(`[${this.name}] 销毁`);
        this.cleanup();
    }

    // ═══════════════════════════════════════════════════════════════════════
    //                           事件绑定辅助
    // ═══════════════════════════════════════════════════════════════════════

    /**
     * 绑定 DOM 事件（自动管理清理）
     * @param {string|Element} target - 选择器或元素
     * @param {string} event - 事件类型
     * @param {Function} handler - 处理函数
     */
    bindEvent(target, event, handler) {
        let element = target;
        if (typeof target === 'string') {
            element = this.$(target);
        }

        if (!element) {
            console.warn(`[${this.name}] 元素未找到: ${target}`);
            return;
        }

        element.addEventListener(event, handler);

        // 保存清理函数
        this._eventCleanups.push(() => {
            element.removeEventListener(event, handler);
        });
    }

    /**
     * 订阅事件总线事件（自动管理清理）
     * @param {string} event - 事件名称
     * @param {Function} handler - 处理函数
     */
    listenEvent(event, handler) {
        const cleanup = eventBus.on(event, handler);
        this._eventCleanups.push(cleanup);
    }

    /**
     * 订阅状态变更（自动管理清理）
     * @param {string} path - 状态路径
     * @param {Function} handler - 处理函数
     */
    watchState(path, handler) {
        const cleanup = stateManager.subscribe(path, handler);
        this._stateCleanups.push(cleanup);
    }

    /**
     * 清理所有事件绑定和状态订阅
     */
    cleanup() {
        this._runCleanupGroup(this._eventCleanups, 'event');
        this._eventCleanups = [];

        this._runCleanupGroup(this._stateCleanups, 'state');
        this._stateCleanups = [];
    }

    _runCleanupGroup(cleanups, type) {
        for (const cleanup of cleanups || []) {
            try {
                cleanup();
            } catch (error) {
                console.warn(`[${this.name}] ${type} cleanup failed:`, error);
            }
        }
    }

    // ═══════════════════════════════════════════════════════════════════════
    //                           工具方法
    // ═══════════════════════════════════════════════════════════════════════

    /**
     * 是否为活动页面
     */
    isActive() {
        return this._isActive;
    }

    /**
     * 触发事件总线事件
     */
    emit(event, data) {
        eventBus.emit(event, data);
    }

    /**
     * 获取状态
     */
    getState(path) {
        return stateManager.get(path);
    }

    /**
     * 设置状态
     */
    setState(path, value) {
        stateManager.set(path, value);
    }
}

export default PageController;
