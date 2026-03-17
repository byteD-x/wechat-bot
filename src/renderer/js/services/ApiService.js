/**
 * API 服务
 *
 * 封装渲染进程与后端 API 的通信。
 */

import { debugLog } from '../core/Debug.js';

class ApiService {
    constructor() {
        this.baseUrl = 'http://127.0.0.1:5000';
        this.initialized = false;
        this.defaultTimeoutMs = 8000;
        this.apiToken = '';
    }

    async init() {
        try {
            if (window.electronAPI?.getFlaskUrl) {
                this.baseUrl = await window.electronAPI.getFlaskUrl();
            }
            if (window.electronAPI?.getApiToken) {
                this.apiToken = await window.electronAPI.getApiToken();
            }
        } catch (error) {
            console.error('[ApiService] 初始化失败，回退到默认地址', error);
        }

        this.initialized = true;
        debugLog('[ApiService] 初始化完成，baseUrl:', this.baseUrl);
    }

    async request(endpoint, options = {}, retries = 1) {
        if (!this.initialized) {
            await this.init();
        }

        const url = `${this.baseUrl}${endpoint}`;
        const { timeoutMs, headers, ...fetchOptions } = options;
        const config = {
            headers: {
                'Content-Type': 'application/json',
                ...(headers || {}),
            },
            ...fetchOptions,
        };

        if (this.apiToken) {
            config.headers['X-Api-Token'] = this.apiToken;
        }

        if (config.body && typeof config.body === 'object') {
            config.body = JSON.stringify(config.body);
        }

        let lastError = null;
        for (let attempt = 0; attempt <= retries; attempt += 1) {
            const controller = new AbortController();
            const timeout = timeoutMs ?? this.defaultTimeoutMs;
            const timer = setTimeout(() => controller.abort(), timeout);

            try {
                const response = await fetch(url, {
                    ...config,
                    signal: controller.signal,
                });
                clearTimeout(timer);

                const data = await this._parseResponseData(response);
                if (response.ok) {
                    return data ?? {};
                }
                throw this._createHttpError(response.status, data, endpoint);
            } catch (error) {
                clearTimeout(timer);
                const normalized = this._normalizeError(error, endpoint);
                console.error(
                    `[ApiService] 请求失败 (${attempt + 1}/${retries + 1}): ${endpoint}`,
                    normalized
                );
                lastError = normalized;

                if (normalized?.status >= 400 && normalized?.status < 500) {
                    throw normalized;
                }

                if (attempt < retries) {
                    await new Promise((resolve) => setTimeout(resolve, 1000));
                }
            }
        }

        throw lastError;
    }

    async _parseResponseData(response) {
        const contentType = response.headers.get('content-type') || '';
        if (contentType.includes('application/json')) {
            return response.json();
        }

        const text = await response.text();
        return text ? { message: text } : null;
    }

    _createHttpError(status, data, endpoint) {
        const error = new Error(this._formatHttpErrorMessage(status, data));
        error.status = status;
        error.data = data;
        error.endpoint = endpoint;
        error.code = 'http_error';
        return error;
    }

    _formatHttpErrorMessage(status, data) {
        const detail = data?.message ? `：${data.message}` : '';
        if (status === 401 || status === 403) {
            return `权限验证失败${detail}`;
        }
        if (status === 404) {
            return `接口不存在${detail}`;
        }
        if (status === 429) {
            return `请求过于频繁${detail}`;
        }
        if (status >= 500) {
            return `服务端异常${detail}`;
        }
        return `请求失败 (${status})${detail}`;
    }

    _normalizeError(error, endpoint) {
        if (error?.name === 'AbortError') {
            const timeoutError = new Error('请求超时，请稍后重试');
            timeoutError.code = 'timeout';
            timeoutError.endpoint = endpoint;
            return timeoutError;
        }

        if (error?.code === 'http_error') {
            return error;
        }

        const networkError = new Error('网络异常或服务不可用');
        networkError.code = 'network';
        networkError.endpoint = endpoint;
        return networkError;
    }

    async getStatus() {
        return this.request('/api/status');
    }

    async startBot() {
        return this.request('/api/start', { method: 'POST' });
    }

    async stopBot() {
        return this.request('/api/stop', { method: 'POST' });
    }

    async restartBot() {
        return this.request('/api/restart', { method: 'POST' });
    }

    async recoverBot() {
        return this.request('/api/recover', { method: 'POST' });
    }

    async pauseBot(reason = '用户暂停') {
        return this.request('/api/pause', {
            method: 'POST',
            body: { reason }
        });
    }

    async resumeBot() {
        return this.request('/api/resume', { method: 'POST' });
    }

    async testConnection(presetName = null) {
        return this.request('/api/test_connection', {
            method: 'POST',
            body: { preset_name: presetName }
        });
    }

    connectSSE(onMessage, onError, onOpen) {
        const tokenParam = this.apiToken
            ? `?token=${encodeURIComponent(this.apiToken)}`
            : '';
        const url = `${this.baseUrl}/api/events${tokenParam}`;

        debugLog('[ApiService] 连接 SSE:', `${this.baseUrl}/api/events`);

        const eventSource = new EventSource(url);
        eventSource.onopen = () => {
            debugLog('[ApiService] SSE 已连接');
            if (onOpen) {
                onOpen();
            }
        };

        eventSource.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                if (onMessage) {
                    onMessage(data);
                }
            } catch (error) {
                console.error('[ApiService] SSE 消息解析失败:', error);
            }
        };

        eventSource.onerror = (error) => {
            console.error('[ApiService] SSE 连接异常:', error);
            if (onError) {
                onError(error);
            }
        };

        return eventSource;
    }

    _buildQueryString(params = {}) {
        const searchParams = new URLSearchParams();
        Object.entries(params || {}).forEach(([key, value]) => {
            if (value === undefined || value === null || value === '') {
                return;
            }
            searchParams.set(key, String(value));
        });
        const query = searchParams.toString();
        return query ? `?${query}` : '';
    }

    async getMessages(params = {}) {
        return this.request(`/api/messages${this._buildQueryString({
            limit: params.limit,
            offset: params.offset,
            chat_id: params.chatId,
            keyword: params.keyword,
        })}`);
    }

    async getContactProfile(chatId) {
        const encoded = encodeURIComponent(String(chatId || '').trim());
        return this.request(`/api/contact_profile?chat_id=${encoded}`);
    }

    async saveContactPrompt(chatId, contactPrompt) {
        return this.request('/api/contact_prompt', {
            method: 'POST',
            body: {
                chat_id: chatId,
                contact_prompt: contactPrompt
            }
        });
    }

    async sendMessage(target, content) {
        return this.request('/api/send', {
            method: 'POST',
            body: { target, content }
        });
    }

    async getConfig() {
        return this.request('/api/config');
    }

    async getConfigAudit() {
        return this.request('/api/config/audit');
    }

    async getModelCatalog() {
        return this.request('/api/model_catalog');
    }

    async saveConfig(config) {
        return this.request('/api/config', {
            method: 'POST',
            body: config,
            timeoutMs: 20000
        });
    }

    async previewPrompt(payload) {
        return this.request('/api/preview_prompt', {
            method: 'POST',
            body: payload,
            timeoutMs: 12000
        });
    }

    async getLogs(lines = 200) {
        return this.request(`/api/logs?lines=${lines}`);
    }

    async clearLogs() {
        return this.request('/api/logs/clear', { method: 'POST' });
    }

    async getUsage() {
        return this.request('/api/usage');
    }

    async getPricing() {
        return this.request('/api/pricing');
    }

    async refreshPricing(providers = []) {
        return this.request('/api/pricing/refresh', {
            method: 'POST',
            body: { providers }
        });
    }

    async getCostSummary(params = {}) {
        return this.request(`/api/costs/summary${this._buildQueryString(params)}`);
    }

    async getCostSessions(params = {}) {
        return this.request(`/api/costs/sessions${this._buildQueryString(params)}`);
    }

    async getCostSessionDetails(chatId, params = {}) {
        return this.request(`/api/costs/session_details${this._buildQueryString({
            chat_id: chatId,
            ...params,
        })}`);
    }
}

export const apiService = new ApiService();
export default apiService;
