/**
 * API 鏈嶅姟
 *
 * 灏佽娓叉煋杩涚▼涓庡悗绔?API 鐨勯€氫俊銆? */

import { debugLog } from '../core/Debug.js';

const NODE_NETWORK_ERROR_CODES = new Set([
    'ECONNREFUSED',
    'ECONNRESET',
    'EHOSTUNREACH',
    'ENETUNREACH',
    'ENOTFOUND',
    'EAI_AGAIN',
    'ETIMEDOUT',
]);

class ApiService {
    constructor() {
        this.baseUrl = 'http://127.0.0.1:5000';
        this.initialized = false;
        this.defaultTimeoutMs = 8000;
        this.apiToken = '';
        this.sseTicket = '';
        this.backendRequest = null;
        this.endpointTimeoutMs = Object.freeze({
            '/api/test_connection': 12000,
        });
        this.idempotentPostEndpoints = new Set([
            '/api/send',
            '/api/backups',
            '/api/backups/restore',
            '/api/data_controls/clear',
        ]);
        this.idempotencyNonce = 0;
    }

    async init() {
        try {
            if (window.electronAPI?.getFlaskUrl) {
                this.baseUrl = await window.electronAPI.getFlaskUrl();
            }
            if (window.electronAPI?.getSseTicket) {
                this.sseTicket = String(await window.electronAPI.getSseTicket() || '').trim();
            }
            if (typeof window.electronAPI?.backendRequest === 'function') {
                this.backendRequest = window.electronAPI.backendRequest;
            }
        } catch (error) {
            console.error('[ApiService] 鍒濆鍖栧け璐ワ紝鍥為€€鍒伴粯璁ゅ湴鍧€', error);
        }

        this.initialized = true;
        debugLog('[ApiService] 鍒濆鍖栧畬鎴愶紝baseUrl:', this.baseUrl);
    }

    async request(endpoint, options = {}, retries = undefined) {
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
        const method = String(config.method || 'GET').trim().toUpperCase();
        this._attachIdempotencyKeyIfNeeded(endpoint, method, config);

        if (config.body && typeof config.body === 'object') {
            config.body = JSON.stringify(config.body);
        }

        const retryBudget = Number.isInteger(retries)
            ? Math.max(0, retries)
            : (method === 'GET' || method === 'HEAD' ? 1 : 0);

        let lastError = null;
        for (let attempt = 0; attempt <= retryBudget; attempt += 1) {
            const timeout = timeoutMs ?? this.endpointTimeoutMs[endpoint] ?? this.defaultTimeoutMs;
            let timer = null;

            try {
                if (typeof this.backendRequest === 'function') {
                    let requestPayload = null;
                    if (config.body != null) {
                        if (typeof config.body === 'string') {
                            try {
                                requestPayload = JSON.parse(config.body);
                            } catch (_) {
                                requestPayload = config.body;
                            }
                        } else {
                            requestPayload = config.body;
                        }
                    }

                    const ipcResponse = await this.backendRequest({
                        method,
                        endpoint,
                        payload: requestPayload,
                        timeoutMs: timeout,
                    });
                    if (ipcResponse?.ok) {
                        return ipcResponse.data ?? {};
                    }
                    throw this._createIpcError(ipcResponse?.error, endpoint);
                }

                const controller = new AbortController();
                timer = setTimeout(() => controller.abort(), timeout);
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
                    `[ApiService] 璇锋眰澶辫触 (${attempt + 1}/${retryBudget + 1}): ${endpoint}`,
                    normalized
                );
                lastError = normalized;

                if (normalized?.status >= 400 && normalized?.status < 500) {
                    throw normalized;
                }

                if (attempt < retryBudget) {
                    await new Promise((resolve) => setTimeout(resolve, 1000));
                }
            }
        }

        throw lastError;
    }

    _requiresIdempotencyKey(endpoint, method) {
        return String(method || '').toUpperCase() === 'POST' && this.idempotentPostEndpoints.has(String(endpoint || ''));
    }

    _generateIdempotencyKey(endpoint) {
        const prefix = String(endpoint || '').replace(/[^a-zA-Z0-9]/g, '').toLowerCase().slice(0, 24) || 'api';
        if (globalThis.crypto?.randomUUID) {
            return `${prefix}-${globalThis.crypto.randomUUID()}`;
        }
        this.idempotencyNonce = (Number(this.idempotencyNonce || 0) + 1) % 1_000_000;
        return `${prefix}-${Date.now().toString(36)}-${this.idempotencyNonce.toString(36)}`;
    }

    _attachIdempotencyKeyIfNeeded(endpoint, method, config) {
        if (!this._requiresIdempotencyKey(endpoint, method)) {
            return;
        }
        if (!config || typeof config !== 'object') {
            return;
        }
        if (!config.headers || typeof config.headers !== 'object') {
            config.headers = {};
        }

        const existingHeader = config.headers['Idempotency-Key'] || config.headers['idempotency-key'];
        const idempotencyKey = String(existingHeader || this._generateIdempotencyKey(endpoint)).trim();
        config.headers['Idempotency-Key'] = idempotencyKey;

        if (config.body == null) {
            config.body = { _idempotency_key: idempotencyKey };
            return;
        }
        if (typeof config.body === 'object') {
            config.body = {
                ...config.body,
                _idempotency_key: String(config.body?._idempotency_key || idempotencyKey),
            };
            return;
        }
        if (typeof config.body === 'string') {
            try {
                const parsed = JSON.parse(config.body);
                if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
                    config.body = {
                        ...parsed,
                        _idempotency_key: String(parsed._idempotency_key || idempotencyKey),
                    };
                }
            } catch (_) {
                // Keep original string body and rely on Idempotency-Key header for fetch path.
            }
        }
    }

    async _parseResponseData(response) {
        const contentType = response.headers.get('content-type') || '';
        if (contentType.includes('application/json')) {
            try {
                return await response.json();
            } catch (_) {
                const parseError = new Error('鏈嶅姟绔繑鍥炰簡鏃犳晥 JSON');
                parseError.code = 'invalid_json';
                parseError.status = Number(response.status || 500);
                parseError.data = { contentType };
                throw parseError;
            }
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

    _createIpcError(payload, endpoint) {
        const status = Number(payload?.status || 0);
        const message = String(payload?.message || 'backend request failed');
        const data = payload?.data && typeof payload.data === 'object' ? payload.data : {};
        const rawCode = String(payload?.code || (status >= 400 ? 'http_error' : 'backend_error'));
        const upperCode = rawCode.toUpperCase();
        const isNodeNetworkCode = NODE_NETWORK_ERROR_CODES.has(upperCode);
        const passthroughCodes = new Set(['timeout', 'network', 'network_error', 'invalid_json']);
        const error = new Error(message);
        error.status = isNodeNetworkCode ? 0 : status;
        error.data = data;
        error.endpoint = endpoint;
        error.transportCode = rawCode;
        if (passthroughCodes.has(rawCode)) {
            error.code = rawCode;
        } else if (isNodeNetworkCode) {
            error.code = 'network_error';
        } else {
            error.code = status >= 400 ? 'http_error' : rawCode;
        }
        return error;
    }

    _formatHttpErrorMessage(status, data) {
        const detail = data?.message ? `锛?{data.message}` : '';
        if (status === 401 || status === 403) {
            return `鏉冮檺楠岃瘉澶辫触${detail}`;
        }
        if (status === 404) {
            return `鎺ュ彛涓嶅瓨鍦?{detail}`;
        }
        if (status === 429) {
            return `璇锋眰杩囦簬棰戠箒${detail}`;
        }
        if (status >= 500) {
            return `鏈嶅姟绔紓甯?{detail}`;
        }
        return `璇锋眰澶辫触 (${status})${detail}`;
    }

    _normalizeError(error, endpoint) {
        if (error?.name === 'AbortError') {
            const timeoutError = new Error('璇锋眰瓒呮椂锛岃绋嶅悗閲嶈瘯');
            timeoutError.code = 'timeout';
            timeoutError.endpoint = endpoint;
            return timeoutError;
        }

        const upperCode = String(error?.code || '').toUpperCase();
        if (NODE_NETWORK_ERROR_CODES.has(upperCode)) {
            const networkError = error instanceof Error ? error : new Error('缃戠粶寮傚父鎴栨湇鍔′笉鍙敤');
            networkError.code = 'network_error';
            networkError.endpoint = endpoint;
            networkError.status = 0;
            return networkError;
        }

        if (
            error?.code === 'http_error'
            || error?.code === 'invalid_json'
            || error?.code === 'timeout'
            || error?.code === 'network'
            || error?.code === 'network_error'
        ) {
            return error;
        }

        const networkError = new Error('缃戠粶寮傚父鎴栨湇鍔′笉鍙敤');
        networkError.code = 'network';
        networkError.endpoint = endpoint;
        return networkError;
    }

    async getStatus() {
        return this.request('/api/status');
    }

    async getReadiness(forceRefresh = false) {
        return this.request(`/api/readiness${this._buildQueryString({
            refresh: forceRefresh ? 'true' : '',
        })}`);
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

    async pauseBot(reason = '鐢ㄦ埛鏆傚仠') {
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

    async getOllamaModels(baseUrl = 'http://127.0.0.1:11434/v1') {
        return this.request(`/api/ollama/models${this._buildQueryString({
            base_url: baseUrl,
        })}`, {
            timeoutMs: 5000,
        }, 0);
    }

    async getGrowthTasks() {
        return this.request('/api/growth/tasks', {}, 0);
    }

    async clearGrowthTask(taskType) {
        const encoded = encodeURIComponent(String(taskType || '').trim());
        return this.request(`/api/growth/tasks/${encoded}/clear`, { method: 'POST' }, 0);
    }

    async runGrowthTaskNow(taskType) {
        const encoded = encodeURIComponent(String(taskType || '').trim());
        return this.request(`/api/growth/tasks/${encoded}/run`, { method: 'POST', timeoutMs: 20000 }, 0);
    }

    async pauseGrowthTask(taskType) {
        const encoded = encodeURIComponent(String(taskType || '').trim());
        return this.request(`/api/growth/tasks/${encoded}/pause`, { method: 'POST' }, 0);
    }

    async resumeGrowthTask(taskType) {
        const encoded = encodeURIComponent(String(taskType || '').trim());
        return this.request(`/api/growth/tasks/${encoded}/resume`, { method: 'POST' }, 0);
    }

    connectSSE(onMessage, onError, onOpen) {
        const query = this.sseTicket ? `?ticket=${encodeURIComponent(this.sseTicket)}` : '';
        const url = `${this.baseUrl}/api/events${query}`;

        debugLog('[ApiService] Connecting SSE:', url);

        const eventSource = new EventSource(url);
        eventSource.onopen = () => {
            debugLog('[ApiService] SSE connected');
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
                console.error('[ApiService] SSE message parse failed:', error);
            }
        };

        eventSource.onerror = (error) => {
            console.error('[ApiService] SSE error:', error);
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

    async saveMessageFeedback(messageId, feedback) {
        return this.request('/api/message_feedback', {
            method: 'POST',
            body: {
                message_id: messageId,
                feedback,
            }
        });
    }

    async sendMessage(target, content) {
        return this.request('/api/send', {
            method: 'POST',
            body: { target, content }
        });
    }

    async getReplyPolicies() {
        return this.request('/api/reply_policies');
    }

    async saveReplyPolicies(payload) {
        return this.request('/api/reply_policies', {
            method: 'POST',
            body: payload,
        });
    }

    async listPendingReplies(params = {}) {
        return this.request(`/api/pending_replies${this._buildQueryString({
            chat_id: params.chatId,
            status: params.status,
            limit: params.limit,
        })}`);
    }

    async approvePendingReply(pendingId, editedReply = '') {
        return this.request(`/api/pending_replies/${encodeURIComponent(String(pendingId || ''))}/approve`, {
            method: 'POST',
            body: {
                edited_reply: editedReply,
            },
            timeoutMs: 20000,
        });
    }

    async rejectPendingReply(pendingId) {
        return this.request(`/api/pending_replies/${encodeURIComponent(String(pendingId || ''))}/reject`, {
            method: 'POST',
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

    async getModelAuthOverview() {
        return this.request('/api/model_auth/overview');
    }

    async runModelAuthAction(action, payload = {}) {
        return this.request('/api/model_auth/action', {
            method: 'POST',
            body: {
                action,
                payload,
            },
            timeoutMs: 30000,
        });
    }

    async getAuthProviders() {
        return this.getModelAuthOverview();
    }

    async startAuthProvider(providerKey, payload = {}) {
        throw new Error('Legacy auth-provider browser flow has been removed. Use /api/model_auth/action instead.');
    }

    async cancelAuthProvider(providerKey, flowId) {
        throw new Error('Legacy auth-provider flow cancellation has been removed. Use /api/model_auth/action instead.');
    }

    async submitAuthProviderCallback(providerKey, flowId, payload = {}) {
        throw new Error('Legacy auth-provider callback submission has been removed. Use /api/model_auth/action instead.');
    }

    async logoutAuthProviderSource(providerKey, payload = {}) {
        throw new Error('Legacy auth-provider source logout has been removed. Use /api/model_auth/action instead.');
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

    async getBackups(limit = 20) {
        return this.request(`/api/backups${this._buildQueryString({ limit })}`);
    }

    async createBackup(mode, label = '') {
        return this.request('/api/backups', {
            method: 'POST',
            body: { mode, label },
            timeoutMs: 300000,
        });
    }

    async cleanupBackups(payload = {}) {
        return this.request('/api/backups/cleanup', {
            method: 'POST',
            body: payload,
            timeoutMs: 300000,
        });
    }

    async restoreBackup(payload) {
        return this.request('/api/backups/restore', {
            method: 'POST',
            body: payload,
            timeoutMs: 300000,
        });
    }

    async getDataControls() {
        return this.request('/api/data_controls');
    }

    async clearDataControls(payload = {}) {
        return this.request('/api/data_controls/clear', {
            method: 'POST',
            body: payload,
            timeoutMs: 300000,
        });
    }

    async getLatestEvalReport() {
        return this.request('/api/evals/latest', {}, 0);
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

    async exportCostReviewQueue(params = {}) {
        return this.request(`/api/costs/review_queue_export${this._buildQueryString(params)}`);
    }
}

export const apiService = new ApiService();
export default apiService;

