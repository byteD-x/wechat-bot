/**
 * 状态管理器
 *
 * 提供统一的状态管理，支持订阅式更新。
 */

import { debugLog } from './Debug.js';

class StateManager {
    constructor() {
        this._state = {
            bot: {
                running: false,
                paused: false,
                connected: false,
                status: null
            },
            backend: {
                idle: {
                    state: 'active',
                    delayMs: 15 * 60 * 1000,
                    remainingMs: 15 * 60 * 1000,
                    reason: '',
                    updatedAt: 0,
                }
            },
            updater: {
                enabled: false,
                checking: false,
                available: false,
                currentVersion: '',
                latestVersion: '',
                lastCheckedAt: '',
                releaseDate: '',
                downloadUrl: '',
                releasePageUrl: '',
                notes: [],
                error: '',
                skippedVersion: '',
                downloading: false,
                downloadProgress: 0,
                readyToInstall: false,
                downloadedVersion: '',
                downloadedInstallerPath: ''
            },
            currentPage: 'dashboard',
            logs: {
                autoScroll: true,
                autoRefresh: true,
                wrap: true
            },
            intervals: {
                status: null,
                logs: null
            }
        };

        this._subscribers = new Map();
        this._history = [];
    }

    getState() {
        return { ...this._state };
    }

    get(path) {
        const keys = path.split('.');
        let value = this._state;
        for (const key of keys) {
            if (value === undefined || value === null) {
                return undefined;
            }
            value = value[key];
        }
        return value;
    }

    set(path, value) {
        const keys = path.split('.');
        const lastKey = keys.pop();
        let target = this._state;

        for (const key of keys) {
            if (target[key] === undefined) {
                target[key] = {};
            }
            target = target[key];
        }

        const oldValue = target[lastKey];
        if (Object.is(oldValue, value)) {
            return;
        }

        target[lastKey] = value;
        // Avoid storing high-frequency large payloads (e.g. bot.status) in history.
        if (path !== 'bot.status') {
            this._history.push({
                path,
                oldValue,
                newValue: value,
                timestamp: Date.now()
            });

            if (this._history.length > 100) {
                this._history.shift();
            }
        }

        this._notifySubscribers(path, value, oldValue);
        debugLog(`[StateManager] 状态更新: ${path}`, { oldValue, newValue: value });
    }

    batchUpdate(updates) {
        for (const [path, value] of Object.entries(updates)) {
            this.set(path, value);
        }
    }

    subscribe(path, callback) {
        if (!this._subscribers.has(path)) {
            this._subscribers.set(path, new Set());
        }
        this._subscribers.get(path).add(callback);

        return () => {
            const set = this._subscribers.get(path);
            if (!set) {
                return;
            }
            set.delete(callback);
            if (set.size === 0) {
                this._subscribers.delete(path);
            }
        };
    }

    _notifySubscribers(path, newValue, oldValue) {
        if (this._subscribers.has(path)) {
            for (const callback of this._subscribers.get(path)) {
                try {
                    callback(newValue, oldValue, path);
                } catch (error) {
                    console.error('[StateManager] 订阅者回调错误:', error);
                }
            }
        }

        if (this._subscribers.has('*')) {
            for (const callback of this._subscribers.get('*')) {
                try {
                    callback(newValue, oldValue, path);
                } catch (error) {
                    console.error('[StateManager] 订阅者回调错误:', error);
                }
            }
        }

        const parts = path.split('.');
        for (let index = 1; index < parts.length; index += 1) {
            const wildcardPath = `${parts.slice(0, index).join('.')}.*`;
            if (this._subscribers.has(wildcardPath)) {
                for (const callback of this._subscribers.get(wildcardPath)) {
                    try {
                        callback(newValue, oldValue, path);
                    } catch (error) {
                        console.error('[StateManager] 订阅者回调错误:', error);
                    }
                }
            }
        }
    }

    getHistory() {
        return [...this._history];
    }

    clearHistory() {
        this._history = [];
    }
}

export const stateManager = new StateManager();
export default stateManager;
