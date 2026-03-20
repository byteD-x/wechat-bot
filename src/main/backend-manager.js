function createBackendManager({
    http,
    spawn,
    iconv,
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
                console.log('[Backend] 服务已在运行');
                updateSplashStatus('后端服务已就绪，正在加载界面...', 60);
                return;
            }

            if (GLOBAL_STATE.pythonProcess) {
                console.log('[Backend] 后端正在启动');
                updateSplashStatus('后端服务启动中...', 50);
                return;
            }

            const { cmd, args, options } = getBackendCommand([
                'web',
                '--host',
                '127.0.0.1',
                '--port',
                GLOBAL_STATE.flaskPort.toString(),
            ]);

            console.log(`[Backend] 启动: ${cmd} ${args.join(' ')}`);
            updateSplashStatus('正在启动后端服务...', 35);

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
            throw new Error('Python 服务启动超时');
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

            const decodeSafe = (data) => {
                try {
                    const buffer = Buffer.isBuffer(data) ? data : Buffer.from(String(data));
                    const utf8 = iconv.decode(buffer, 'utf-8');
                    if (!utf8.includes('\ufffd')) {
                        return utf8;
                    }
                    return iconv.decode(buffer, 'cp936');
                } catch (_) {
                    try {
                        return Buffer.isBuffer(data) ? data.toString('utf8') : String(data);
                    } catch (_) {
                        return '';
                    }
                }
            };

            if (proc.stdout && typeof proc.stdout.on === 'function') {
                proc.stdout.on('error', (err) => {
                    console.warn('[Backend Stdout Error]', err?.message || err);
                });
                proc.stdout.on('data', (data) => {
                    const str = decodeSafe(data);
                    console.log(`[Backend] ${str.trim()}`);
                    updateSplashStatus('后端服务启动中...', 50);
                });
            }

            if (proc.stderr && typeof proc.stderr.on === 'function') {
                proc.stderr.on('error', (err) => {
                    console.warn('[Backend Stderr Error]', err?.message || err);
                });
                proc.stderr.on('data', (data) => {
                    const str = decodeSafe(data);
                    console.error(`[Backend Err] ${str.trim()}`);
                });
            }

            proc.on('exit', (code) => {
                console.log(`[Backend] 退出代码: ${code}`);
                GLOBAL_STATE.pythonProcess = null;
                runtimeIdleController.setServiceStopped(proc.__backendStopReason || 'process_exit');
            });
        },

        requestJson(method, endpoint, payload = null, timeoutMs = 10000) {
            return new Promise((resolve, reject) => {
                const body = payload == null ? null : JSON.stringify(payload);
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
                                    reject(new Error(`后端返回了无效 JSON: ${raw.slice(0, 200)}`));
                                    return;
                                }
                            }
                            if ((res.statusCode || 500) >= 400) {
                                reject(new Error(data?.message || `后端请求失败 (${res.statusCode})`));
                                return;
                            }
                            resolve(data);
                        });
                    }
                );
                req.on('error', reject);
                req.on('timeout', () => req.destroy(new Error('请求超时')));
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
