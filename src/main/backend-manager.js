const { StringDecoder } = require('node:string_decoder');
const { decodeBufferText } = require('./text-codec');

function createBackendManager({
    http,
    spawn,
    GLOBAL_STATE,
    getBackendCommand,
    getMainWindowVisible,
    updateSplashStatus,
    runtimeIdleController,
}) {
    return {
        checkServer() {
            return new Promise((resolve) => {
                const req = http.get({
                    hostname: '127.0.0.1',
                    port: GLOBAL_STATE.flaskPort,
                    path: '/api/ping',
                    headers: GLOBAL_STATE.apiToken ? { 'X-Api-Token': GLOBAL_STATE.apiToken } : {},
                }, (res) => {
                    resolve(res.statusCode === 200);
                });
                req.on('error', () => resolve(false));
                req.setTimeout(1000, () => {
                    req.destroy();
                    resolve(false);
                });
            });
        },

        async start() {
            if (await this.checkServer()) {
                runtimeIdleController.setWindowVisible(getMainWindowVisible());
                runtimeIdleController.setServiceRunning(true);
                console.log('[Backend] service already running');
                updateSplashStatus('Backend service is ready. Loading interface...', 60);
                return;
            }

            if (GLOBAL_STATE.pythonProcess) {
                console.log('[Backend] backend is starting');
                updateSplashStatus('Starting backend service...', 50);
                return;
            }

            const { cmd, args, options } = getBackendCommand([
                'web',
                '--host',
                '127.0.0.1',
                '--port',
                GLOBAL_STATE.flaskPort.toString(),
            ]);

            console.log(`[Backend] start command: ${cmd} ${args.join(' ')}`);
            updateSplashStatus('Launching backend service...', 35);

            GLOBAL_STATE.pythonProcess = spawn(cmd, args, options);
            this._setupProcessListeners(GLOBAL_STATE.pythonProcess);
        },

        async ensureReady(timeoutMs = 20000) {
            await this.start();
            const startedAt = Date.now();
            while ((Date.now() - startedAt) < timeoutMs) {
                if (await this.checkServer()) {
                    runtimeIdleController.setWindowVisible(getMainWindowVisible());
                    runtimeIdleController.setServiceRunning(true);
                    return true;
                }
                await new Promise((resolve) => setTimeout(resolve, 400));
            }
            throw new Error('Python service startup timed out');
        },

        stop(reason = 'manual') {
            const proc = GLOBAL_STATE.pythonProcess;
            if (!proc) return Promise.resolve();
            return new Promise((resolve) => {
                let resolved = false;
                const done = () => {
                    if (resolved) return;
                    resolved = true;
                    resolve();
                };
                console.log('[Backend] 正在停止...');
                proc.__backendStopReason = reason;
                proc.once('exit', done);
                try {
                    proc.kill('SIGTERM');
                } catch (_) {
                    done();
                }
                const pid = proc.pid;
                setTimeout(() => {
                    try { process.kill(pid, 0) && process.kill(pid, 'SIGKILL'); } catch (_) {}
                }, 3000);
                setTimeout(done, 3500);
                GLOBAL_STATE.pythonProcess = null;
            });
        },

        _setupProcessListeners(proc) {
            if (!proc) {
                return;
            }
            proc.on('error', (err) => {
                console.error(`[Backend Spawn Error] ${err.message}`);
                GLOBAL_STATE.pythonProcess = null;
                runtimeIdleController.setServiceStopped('spawn_error');
            });

            const stdoutDecoder = new StringDecoder('utf8');
            const stderrDecoder = new StringDecoder('utf8');

            const decodeSafe = (data, decoder) => {
                const buffer = Buffer.isBuffer(data) ? data : Buffer.from(data || '');
                if (!buffer.length) {
                    return '';
                }
                const utf8 = decoder.write(buffer);
                if (utf8 && !utf8.includes('\ufffd')) {
                    return utf8;
                }
                return decodeBufferText(buffer);
            };

            const flushDecoder = (decoder) => {
                try {
                    const trailing = decoder.end();
                    if (trailing && !trailing.includes('\ufffd')) {
                        return trailing;
                    }
                } catch (_) {
                    // Ignore decoder flush errors and fallback to empty trailing output.
                }
                return '';
            };

            if (proc.stdout && typeof proc.stdout.on === 'function') {
                proc.stdout.on('error', (err) => {
                    console.warn('[Backend Stdout Error]', err?.message || err);
                });
                proc.stdout.on('data', (data) => {
                    const str = decodeSafe(data, stdoutDecoder);
                    if (str && str.trim()) {
                        console.log(`[Backend] ${str.trim()}`);
                    }
                    updateSplashStatus('Starting backend service...', 50);
                });
                proc.stdout.on('end', () => {
                    const tail = flushDecoder(stdoutDecoder);
                    if (tail && tail.trim()) {
                        console.log(`[Backend] ${tail.trim()}`);
                    }
                });
            }

            if (proc.stderr && typeof proc.stderr.on === 'function') {
                proc.stderr.on('error', (err) => {
                    console.warn('[Backend Stderr Error]', err?.message || err);
                });
                proc.stderr.on('data', (data) => {
                    const str = decodeSafe(data, stderrDecoder);
                    if (str && str.trim()) {
                        console.error(`[Backend Err] ${str.trim()}`);
                    }
                });
                proc.stderr.on('end', () => {
                    const tail = flushDecoder(stderrDecoder);
                    if (tail && tail.trim()) {
                        console.error(`[Backend Err] ${tail.trim()}`);
                    }
                });
            }

            proc.on('exit', (code) => {
                console.log(`[Backend] process exited with code ${code}`);
                GLOBAL_STATE.pythonProcess = null;
                runtimeIdleController.setServiceStopped(proc.__backendStopReason || 'process_exit');
            });
        },

        requestJson(method, endpoint, payload = null, timeoutMs = 10000) {
            return new Promise((resolve, reject) => {
                const body = payload == null ? null : JSON.stringify(payload);
                const buildHttpError = (status, data, fallbackMessage) => {
                    const error = new Error(data?.message || fallbackMessage || `后端请求失败 (${status})`);
                    error.status = Number(status || 500);
                    error.code = data?.code || 'http_error';
                    error.endpoint = endpoint;
                    error.data = data || {};
                    return error;
                };
                const req = http.request(
                    {
                        hostname: '127.0.0.1',
                        port: GLOBAL_STATE.flaskPort,
                        path: endpoint,
                        method,
                        headers: {
                            'Content-Type': 'application/json',
                            'X-Api-Token': GLOBAL_STATE.apiToken,
                            ...(body ? { 'Content-Length': Buffer.byteLength(body) } : {}),
                        },
                        timeout: timeoutMs,
                    },
                    (res) => {
                        const chunks = [];
                        res.on('data', (chunk) => chunks.push(chunk));
                        res.on('end', () => {
                            const raw = Buffer.concat(chunks).toString('utf8');
                            let data = {};
                            if (raw.trim()) {
                                try {
                                    data = JSON.parse(raw);
                                } catch (_) {
                                    const error = new Error(`后端返回了无效 JSON: ${raw.slice(0, 200)}`);
                                    error.status = Number(res.statusCode || 500);
                                    error.code = 'invalid_json';
                                    error.endpoint = endpoint;
                                    error.data = { raw: raw.slice(0, 200) };
                                    reject(error);
                                    return;
                                }
                            }
                            if ((res.statusCode || 500) >= 400) {
                                reject(buildHttpError(res.statusCode || 500, data, `后端请求失败 (${res.statusCode})`));
                                return;
                            }
                            resolve(data);
                        });
                    }
                );
                req.on('error', (error) => {
                    const requestError = error || new Error('后端请求失败');
                    if (!requestError.code) {
                        requestError.code = 'network_error';
                    }
                    requestError.endpoint = requestError.endpoint || endpoint;
                    reject(requestError);
                });
                req.on('timeout', () => {
                    const timeoutError = new Error('请求超时');
                    timeoutError.code = 'timeout';
                    timeoutError.status = 504;
                    timeoutError.endpoint = endpoint;
                    req.destroy(timeoutError);
                });
                if (body) {
                    req.write(body);
                }
                req.end();
            });
        },
    };
}

module.exports = {
    createBackendManager,
};

