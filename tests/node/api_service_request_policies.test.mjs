import test from 'node:test';
import assert from 'node:assert/strict';

import { apiService } from '../../src/renderer/js/services/ApiService.js';

test('api service retries GET by default but does not retry POST by default', async () => {
    const previousFetch = globalThis.fetch;
    const previousInitialized = apiService.initialized;
    const previousBaseUrl = apiService.baseUrl;
    const previousToken = apiService.apiToken;
    const previousBackendRequest = apiService.backendRequest;

    apiService.initialized = true;
    apiService.baseUrl = 'http://127.0.0.1:5000';
    apiService.apiToken = '';
    apiService.backendRequest = null;

    let getAttempts = 0;
    globalThis.fetch = async () => {
        getAttempts += 1;
        throw new Error('network down');
    };

    try {
        await assert.rejects(
            apiService.request('/api/status'),
            (error) => ['network', 'timeout'].includes(error?.code),
        );
        assert.equal(getAttempts, 2);

        let postAttempts = 0;
        globalThis.fetch = async () => {
            postAttempts += 1;
            throw new Error('network down');
        };
        await assert.rejects(
            apiService.request('/api/config', { method: 'POST', body: { demo: true } }),
            (error) => ['network', 'timeout'].includes(error?.code),
        );
        assert.equal(postAttempts, 1);
    } finally {
        globalThis.fetch = previousFetch;
        apiService.initialized = previousInitialized;
        apiService.baseUrl = previousBaseUrl;
        apiService.apiToken = previousToken;
        apiService.backendRequest = previousBackendRequest;
    }
});

test('api service uses trusted electron backendRequest bridge when available', async () => {
    const previousFetch = globalThis.fetch;
    const previousInitialized = apiService.initialized;
    const previousBaseUrl = apiService.baseUrl;
    const previousBackendRequest = apiService.backendRequest;

    apiService.initialized = true;
    apiService.baseUrl = 'http://127.0.0.1:5000';
    apiService.backendRequest = async (options) => ({
        ok: true,
        data: { success: true, endpoint: options.endpoint, method: options.method },
    });
    globalThis.fetch = async () => {
        throw new Error('fetch should not be called when backendRequest is available');
    };

    try {
        const result = await apiService.request('/api/status');
        assert.equal(result.success, true);
        assert.equal(result.endpoint, '/api/status');
        assert.equal(result.method, 'GET');
    } finally {
        globalThis.fetch = previousFetch;
        apiService.initialized = previousInitialized;
        apiService.baseUrl = previousBaseUrl;
        apiService.backendRequest = previousBackendRequest;
    }
});

test('api service injects idempotency key for high-side-effect POST endpoints', async () => {
    const previousInitialized = apiService.initialized;
    const previousBaseUrl = apiService.baseUrl;
    const previousBackendRequest = apiService.backendRequest;

    apiService.initialized = true;
    apiService.baseUrl = 'http://127.0.0.1:5000';

    let captured = null;
    apiService.backendRequest = async (options) => {
        captured = options;
        return { ok: true, data: { success: true } };
    };

    try {
        await apiService.request('/api/send', {
            method: 'POST',
            body: { target: 'Alice', content: 'hello' },
        }, 0);
        assert.equal(captured.method, 'POST');
        assert.equal(captured.endpoint, '/api/send');
        assert.equal(typeof captured.payload._idempotency_key, 'string');
        assert.ok(captured.payload._idempotency_key.length > 8);
        assert.equal(captured.payload.target, 'Alice');
    } finally {
        apiService.initialized = previousInitialized;
        apiService.baseUrl = previousBaseUrl;
        apiService.backendRequest = previousBackendRequest;
    }
});

test('api service preserves IPC network failures as network_error', async () => {
    const previousInitialized = apiService.initialized;
    const previousBaseUrl = apiService.baseUrl;
    const previousBackendRequest = apiService.backendRequest;

    apiService.initialized = true;
    apiService.baseUrl = 'http://127.0.0.1:5000';
    let attempts = 0;
    apiService.backendRequest = async () => {
        attempts += 1;
        return {
            ok: false,
            error: {
                code: 'ECONNREFUSED',
                status: 500,
                message: 'connect ECONNREFUSED 127.0.0.1:5000',
            },
        };
    };

    try {
        await assert.rejects(
            apiService.request('/api/status'),
            (error) => error?.code === 'network_error' && error?.status === 0 && error?.transportCode === 'ECONNREFUSED',
        );
        assert.equal(attempts, 2);
    } finally {
        apiService.initialized = previousInitialized;
        apiService.baseUrl = previousBaseUrl;
        apiService.backendRequest = previousBackendRequest;
    }
});

test('api service maintenance endpoints use long timeout budget', async () => {
    const previousRequest = apiService.request;
    const calls = [];
    apiService.request = async (endpoint, options = {}, retries = undefined) => {
        calls.push({ endpoint, options, retries });
        return { success: true };
    };

    try {
        await apiService.createBackup('quick');
        await apiService.cleanupBackups({ dry_run: false });
        await apiService.restoreBackup({ backup_id: 'b1', dry_run: false });
        await apiService.clearDataControls({ scopes: ['memory'], dry_run: false });
    } finally {
        apiService.request = previousRequest;
    }

    assert.deepEqual(
        calls.map((item) => ({ endpoint: item.endpoint, timeoutMs: item.options.timeoutMs })),
        [
            { endpoint: '/api/backups', timeoutMs: 300000 },
            { endpoint: '/api/backups/cleanup', timeoutMs: 300000 },
            { endpoint: '/api/backups/restore', timeoutMs: 300000 },
            { endpoint: '/api/data_controls/clear', timeoutMs: 300000 },
        ],
    );
});

test('api service knowledge base helpers use fixed governance endpoints', async () => {
    const previousRequest = apiService.request;
    const calls = [];
    apiService.request = async (endpoint, options = {}, retries = undefined) => {
        calls.push({ endpoint, options, retries });
        return { success: true };
    };

    try {
        await apiService.getKnowledgeBaseStatus();
        await apiService.previewKnowledgeBaseInbox();
        await apiService.dryRunKnowledgeDocument({
            content: 'release notes',
            content_type: 'markdown',
            doc_id: 'release',
        });
        await apiService.dryRunKnowledgeDocuments({
            documents: [{ content: 'release notes' }],
        });
        await apiService.ingestKnowledgeDocument({
            content: 'release notes',
            doc_id: 'release',
        });
        await apiService.ingestKnowledgeDocuments({
            documents: [{ content: 'release notes', doc_id: 'release' }],
        });
        await apiService.rebuildKnowledgeDocument({
            content: 'release notes v2',
            doc_id: 'release',
            version: 'v2',
        });
        await apiService.rebuildKnowledgeDocuments({
            documents: [{ content: 'release notes v2', doc_id: 'release', version: 'v2' }],
        });
    } finally {
        apiService.request = previousRequest;
    }

    assert.deepEqual(calls, [
        {
            endpoint: '/api/knowledge_base/status',
            options: {},
            retries: 0,
        },
        {
            endpoint: '/api/knowledge_base/auto-index/preview',
            options: {},
            retries: 0,
        },
        {
            endpoint: '/api/knowledge_base/dry-run',
            options: {
                method: 'POST',
                body: {
                    content: 'release notes',
                    content_type: 'markdown',
                    doc_id: 'release',
                },
                timeoutMs: 20000,
            },
            retries: 0,
        },
        {
            endpoint: '/api/knowledge_base/batch-dry-run',
            options: {
                method: 'POST',
                body: {
                    documents: [{ content: 'release notes' }],
                },
                timeoutMs: 20000,
            },
            retries: 0,
        },
        {
            endpoint: '/api/knowledge_base/ingest',
            options: {
                method: 'POST',
                body: {
                    content: 'release notes',
                    doc_id: 'release',
                },
                timeoutMs: 60000,
            },
            retries: 0,
        },
        {
            endpoint: '/api/knowledge_base/batch-ingest',
            options: {
                method: 'POST',
                body: {
                    documents: [{ content: 'release notes', doc_id: 'release' }],
                },
                timeoutMs: 60000,
            },
            retries: 0,
        },
        {
            endpoint: '/api/knowledge_base/rebuild',
            options: {
                method: 'POST',
                body: {
                    content: 'release notes v2',
                    doc_id: 'release',
                    version: 'v2',
                },
                timeoutMs: 60000,
            },
            retries: 0,
        },
        {
            endpoint: '/api/knowledge_base/batch-rebuild',
            options: {
                method: 'POST',
                body: {
                    documents: [{ content: 'release notes v2', doc_id: 'release', version: 'v2' }],
                },
                timeoutMs: 60000,
            },
            retries: 0,
        },
    ]);
});

test('api service prompt governance helpers use trusted endpoints and idempotent rollback', async () => {
    const previousRequest = apiService.request;
    const calls = [];
    apiService.request = async (endpoint, options = {}, retries = undefined) => {
        calls.push({ endpoint, options, retries });
        return { success: true };
    };

    try {
        await apiService.getPromptRevisions();
        await apiService.getPromptRevisionDiff('12');
        await apiService.rollbackPromptRevision('12', { reason: 'restore stable prompt' });
    } finally {
        apiService.request = previousRequest;
    }

    assert.deepEqual(calls, [
        {
            endpoint: '/api/v1/admin/prompts/revisions',
            options: {},
            retries: 0,
        },
        {
            endpoint: '/api/v1/admin/prompts/12/diff',
            options: {},
            retries: 0,
        },
        {
            endpoint: '/api/v1/admin/prompts/12/rollback',
            options: {
                method: 'POST',
                body: {
                    reason: 'restore stable prompt',
                    operator: 'settings-ui',
                },
                timeoutMs: 20000,
            },
            retries: 0,
        },
    ]);

    assert.equal(apiService._requiresIdempotencyKey('/api/v1/admin/prompts/12/rollback', 'POST'), true);
    assert.equal(apiService._requiresIdempotencyKey('/api/v1/admin/prompts/abc/rollback', 'POST'), false);
    await assert.rejects(
        apiService.getPromptRevisionDiff('abc'),
        /positive integer/,
    );
});

test('api service tool workflow helper uses controlled endpoint without retries', async () => {
    const previousRequest = apiService.request;
    const calls = [];
    apiService.request = async (endpoint, options = {}, retries = undefined) => {
        calls.push({ endpoint, options, retries });
        return { success: true };
    };

    try {
        await apiService.runToolWorkflow({
            dry_run: true,
            steps: [
                {
                    tool: 'prompt_preview',
                    payload: {
                        sample: {
                            message: 'hello',
                        },
                    },
                    continue_on_error: true,
                },
            ],
            ignored: 'not-forwarded',
        });
    } finally {
        apiService.request = previousRequest;
    }

    assert.deepEqual(calls, [
        {
            endpoint: '/api/v1/agents/tool-workflow',
            options: {
                method: 'POST',
                body: {
                    dry_run: true,
                    steps: [
                        {
                            tool: 'prompt_preview',
                            payload: {
                                sample: {
                                    message: 'hello',
                                },
                            },
                            continue_on_error: true,
                        },
                    ],
                },
                timeoutMs: 60000,
            },
            retries: 0,
        },
    ]);
});

test('api service SSE connection does not leak token in URL', async () => {
    const previousEventSource = globalThis.EventSource;
    const previousInitialized = apiService.initialized;
    const previousBaseUrl = apiService.baseUrl;
    const previousToken = apiService.apiToken;
    const previousSseTicket = apiService.sseTicket;

    let capturedUrl = '';
    globalThis.EventSource = class {
        constructor(url) {
            capturedUrl = String(url || '');
        }
        close() {}
    };

    apiService.initialized = true;
    apiService.baseUrl = 'http://127.0.0.1:5000';
    apiService.apiToken = 'secret-token-should-not-be-in-url';
    apiService.sseTicket = 'sse-ticket-demo';

    try {
        const source = apiService.connectSSE(() => {}, () => {}, () => {});
        assert.equal(typeof source.close, 'function');
        assert.equal(capturedUrl, 'http://127.0.0.1:5000/api/events?ticket=sse-ticket-demo');
        assert.equal(capturedUrl.includes('token='), false);
    } finally {
        globalThis.EventSource = previousEventSource;
        apiService.initialized = previousInitialized;
        apiService.baseUrl = previousBaseUrl;
        apiService.apiToken = previousToken;
        apiService.sseTicket = previousSseTicket;
    }
});

test('api service test_connection endpoint uses extended timeout policy', async () => {
    const previousFetch = globalThis.fetch;
    const previousSetTimeout = globalThis.setTimeout;
    const previousClearTimeout = globalThis.clearTimeout;
    const previousInitialized = apiService.initialized;
    const previousBaseUrl = apiService.baseUrl;

    apiService.initialized = true;
    apiService.baseUrl = 'http://127.0.0.1:5000';

    const observedTimeouts = [];
    globalThis.setTimeout = (handler, timeout) => {
        observedTimeouts.push(Number(timeout || 0));
        if (typeof handler === 'function') {
            // Keep behavior deterministic and avoid pending timers in tests.
        }
        return 1;
    };
    globalThis.clearTimeout = () => {};
    globalThis.fetch = async () => ({
        ok: true,
        headers: { get: () => 'application/json' },
        json: async () => ({ success: true }),
    });

    try {
        const result = await apiService.testConnection('demo');
        assert.equal(result.success, true);
        assert.equal(observedTimeouts.includes(12000), true);
    } finally {
        globalThis.fetch = previousFetch;
        globalThis.setTimeout = previousSetTimeout;
        globalThis.clearTimeout = previousClearTimeout;
        apiService.initialized = previousInitialized;
        apiService.baseUrl = previousBaseUrl;
    }
});

test('api service surfaces invalid_json errors without downgrading to network error', async () => {
    const previousFetch = globalThis.fetch;
    const previousInitialized = apiService.initialized;
    const previousBaseUrl = apiService.baseUrl;

    apiService.initialized = true;
    apiService.baseUrl = 'http://127.0.0.1:5000';
    globalThis.fetch = async () => ({
        ok: true,
        status: 200,
        headers: { get: () => 'application/json' },
        json: async () => {
            throw new SyntaxError('unexpected token');
        },
    });

    try {
        await assert.rejects(
            apiService.request('/api/status'),
            (error) => error?.code === 'invalid_json' && error?.status === 200,
        );
    } finally {
        globalThis.fetch = previousFetch;
        apiService.initialized = previousInitialized;
        apiService.baseUrl = previousBaseUrl;
    }
});
