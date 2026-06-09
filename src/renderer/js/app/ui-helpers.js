export function formatAppDateTime(value) {
    if (!value) {
        return '--';
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
        return '--';
    }
    return new Intl.DateTimeFormat('zh-CN', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
    }).format(date);
}

export function createAppElement(tag, className, text) {
    const element = document.createElement(tag);
    if (className) {
        element.className = className;
    }
    if (text !== undefined) {
        element.textContent = text;
    }
    return element;
}

export function normalizeRuntimeIdleState(idleState = {}, defaultDelayMs) {
    const delayMs = Number(idleState?.delayMs || defaultDelayMs);
    const remainingMs = Number(idleState?.remainingMs ?? delayMs);
    return {
        state: String(idleState?.state || 'active').trim() || 'active',
        delayMs: Number.isFinite(delayMs) && delayMs > 0 ? delayMs : defaultDelayMs,
        remainingMs: Number.isFinite(remainingMs) ? Math.max(0, Math.floor(remainingMs)) : defaultDelayMs,
        reason: String(idleState?.reason || '').trim(),
        updatedAt: Number.isFinite(Number(idleState?.updatedAt))
            ? Number(idleState.updatedAt)
            : Date.now(),
    };
}

export function buildVersionText(state) {
    const currentVersion = state.currentVersion || '--';
    let suffix = '';
    if (state.checking) {
        suffix = ' · 检查更新中';
    } else if (state.downloading) {
        suffix = ` · 下载中 ${state.downloadProgress}%`;
    } else if (state.readyToInstall) {
        suffix = ` · 已下载 v${state.latestVersion || currentVersion}`;
    } else if (state.manualUpdate && state.available && state.latestVersion) {
        suffix = ` · 可手动更新到 v${state.latestVersion}`;
    } else if (state.available && state.latestVersion) {
        suffix = ` · 可更新到 v${state.latestVersion}`;
    } else if (state.manualUpdate) {
        suffix = ' · 手动更新模式';
    } else if (state.enabled) {
        suffix = ' · 已启用更新检查';
    }
    return `v${currentVersion}${suffix}`;
}

export function buildUpdateBadgeState(state) {
    if (state.readyToInstall) {
        return { hidden: false, text: '安装更新', disabled: false };
    }
    if (state.downloading) {
        return { hidden: false, text: `下载 ${state.downloadProgress}%`, disabled: true };
    }
    if (state.manualUpdate && state.available && state.latestVersion) {
        return { hidden: false, text: `手动更新 v${state.latestVersion}`, disabled: false };
    }
    if (state.available && state.latestVersion) {
        return { hidden: false, text: `新版本 v${state.latestVersion}`, disabled: false };
    }
    if (state.checking) {
        return { hidden: false, text: '检查更新中...', disabled: true };
    }
    return { hidden: true, text: '', disabled: false };
}

export function buildUpdateExperience(state = {}) {
    const currentVersion = state.currentVersion || '--';
    const latestVersion = state.latestVersion || '';
    const releaseDate = state.releaseDate;
    const checkedAt = state.lastCheckedAt;
    const error = String(state.error || '').trim();
    const readyToInstall = !!state.readyToInstall;
    const downloading = !!state.downloading;
    const downloadProgress = Math.min(100, Math.max(0, Number(state.downloadProgress || 0)));
    const available = !!state.available;
    const enabled = state.enabled !== false;
    const manualUpdate = !!state.manualUpdate;
    const skippedVersion = state.skippedVersion || '';
    const noteItems = Array.isArray(state.notes) ? state.notes.filter(Boolean) : [];
    const metaItems = [
        `当前版本：v${currentVersion}`,
        latestVersion ? `最新版本：v${latestVersion}` : '',
        releaseDate ? `发布日期：${formatAppDateTime(releaseDate)}` : '',
        checkedAt ? `最近检查：${formatAppDateTime(checkedAt)}` : '',
        skippedVersion && skippedVersion === latestVersion ? `已跳过：v${latestVersion}` : '',
    ].filter(Boolean);

    if (manualUpdate) {
        return {
            statusText: available && latestVersion
                ? `发现新版本 v${latestVersion}，请手动下载更新包`
                : '当前为手动更新模式',
            metaItems,
            noteItems: available && latestVersion
                ? [
                    ...noteItems,
                    '便携版不会在应用内自动下载或安装更新。',
                    '打开 GitHub Releases 后，请下载适合当前版本的安装包或便携版文件并手动替换。',
                ]
                : [
                    '便携版不会在应用内自动下载或安装更新。',
                    '可以打开 GitHub Releases 查看最新发布版本。',
                ],
            actionText: '打开发布页',
            actionDisabled: false,
            skipVisible: available && !!latestVersion,
            skipDisabled: !latestVersion,
            progressHidden: true,
            progressText: '',
            progressWidth: '0%',
        };
    }

    if (!enabled) {
        return {
            statusText: '当前环境不支持应用内更新',
            metaItems: [`当前版本：v${currentVersion}`],
            noteItems: [
                '可以打开 GitHub Releases 获取完整安装包。',
                '便携版或开发环境不会自动启动安装器。',
            ],
            actionText: '打开发布页',
            actionDisabled: false,
            skipVisible: false,
            skipDisabled: true,
            progressHidden: true,
            progressText: '',
            progressWidth: '0%',
        };
    }

    if (readyToInstall) {
        return {
            statusText: `更新已下载并通过校验：v${latestVersion || currentVersion}`,
            metaItems,
            noteItems: [
                ...noteItems,
                '安装前会停止本地运行态并启动已校验的安装包。',
            ],
            actionText: '立即安装并重启',
            actionDisabled: false,
            skipVisible: false,
            skipDisabled: true,
            progressHidden: true,
            progressText: '',
            progressWidth: '100%',
        };
    }

    if (downloading) {
        return {
            statusText: `正在下载 v${latestVersion}...`,
            metaItems,
            noteItems: noteItems.length ? noteItems : ['下载完成后会进行 SHA256 校验。'],
            actionText: `下载中 ${downloadProgress}%`,
            actionDisabled: true,
            skipVisible: true,
            skipDisabled: true,
            progressHidden: false,
            progressText: `下载进度 ${downloadProgress}%`,
            progressWidth: `${downloadProgress}%`,
        };
    }

    if (error) {
        const checksumBlocked = /(sha256|checksum|sha256sums|校验)/i.test(error);
        return {
            statusText: checksumBlocked
                ? '发现新版本，但应用内安装被安全校验阻断'
                : error,
            metaItems,
            noteItems: checksumBlocked
                ? [
                    error,
                    '为避免安装包被篡改，应用内下载需要可信 SHA256 校验清单。',
                    '可以打开发布页手动下载完整安装包。',
                ]
                : [error],
            actionText: checksumBlocked ? '打开发布页' : '下载更新',
            actionDisabled: checksumBlocked ? false : !available,
            skipVisible: true,
            skipDisabled: !latestVersion,
            progressHidden: true,
            progressText: '',
            progressWidth: '0%',
        };
    }

    if (available && latestVersion) {
        return {
            statusText: `发现新版本 v${latestVersion}`,
            metaItems,
            noteItems: noteItems.length
                ? noteItems
                : ['下载后会校验 SHA256，并在你确认后启动安装。'],
            actionText: '下载更新',
            actionDisabled: false,
            skipVisible: true,
            skipDisabled: false,
            progressHidden: true,
            progressText: '',
            progressWidth: '0%',
        };
    }

    return {
        statusText: '当前已经是最新版本',
        metaItems,
        noteItems: ['没有需要处理的更新。'],
        actionText: '下载更新',
        actionDisabled: true,
        skipVisible: false,
        skipDisabled: true,
        progressHidden: true,
        progressText: '',
        progressWidth: '0%',
    };
}

export function renderUpdateModalContent(state, elements) {
    const {
        statusText,
        meta,
        notes,
        progress,
        progressFill,
        progressText,
        btnSkip,
        btnAction,
    } = elements;
    if (!statusText || !meta || !notes || !progress || !progressFill || !progressText || !btnSkip || !btnAction) {
        return;
    }

    const view = buildUpdateExperience(state);
    statusText.textContent = view.statusText;
    meta.textContent = view.metaItems.join(' · ');

    notes.textContent = '';
    view.noteItems.forEach((item) => {
        notes.appendChild(createAppElement('li', 'update-modal-note-item', item));
    });

    progress.hidden = view.progressHidden;
    progressFill.style.width = view.progressWidth;
    progressText.textContent = view.progressText;

    btnSkip.style.display = view.skipVisible ? 'inline-flex' : 'none';
    btnSkip.disabled = view.skipDisabled;
    btnAction.textContent = view.actionText;
    btnAction.disabled = view.actionDisabled;
}

export function buildBackendProcessIssueDiagnostics(issue = {}) {
    const type = String(issue?.type || 'backend_process_issue').trim() || 'backend_process_issue';
    const reason = String(issue?.reason || '').trim();
    const code = Number.isFinite(Number(issue?.code)) ? Number(issue.code) : null;
    const signal = String(issue?.signal || '').trim();
    const suffixParts = [
        reason ? `原因：${reason}` : '',
        code !== null ? `退出码：${code}` : '',
        signal ? `信号：${signal}` : '',
    ].filter(Boolean);

    return {
        level: type === 'spawn_error' ? 'error' : 'warning',
        code: `backend_process_${type}`,
        title: type === 'spawn_error' ? '后端服务启动失败' : '后端服务已停止',
        detail: suffixParts.length
            ? `检测到 Python 后端进程异常。${suffixParts.join('，')}。`
            : '检测到 Python 后端进程异常停止。',
        recoverable: false,
        action_label: '重新启动服务',
        suggestions: [
            '点击左上角状态重新启动后端服务。',
            '如果问题重复出现，请导出诊断快照并查看最近一次后端进程异常。',
            '确认没有被安全软件、权限或端口占用阻止 Python 后端运行。',
        ],
    };
}

export function buildDisconnectedStatus(previousStatus = null, idleState = {}, nowMs = Date.now(), options = {}) {
    const baseStatus = previousStatus && typeof previousStatus === 'object'
        ? previousStatus
        : {};
    const previousStartup = baseStatus.startup && typeof baseStatus.startup === 'object'
        ? baseStatus.startup
        : {};
    const isIdleStopped = idleState?.state === 'stopped_by_idle';
    const disconnectedMessage = isIdleStopped ? '后端已休眠' : '服务未启动';

    return {
        ...baseStatus,
        service_running: false,
        running: false,
        bot_running: false,
        growth_running: false,
        growth_enabled: false,
        is_paused: false,
        background_backlog_count: 0,
        last_background_batch: null,
        diagnostics: options.diagnostics || null,
        startup: {
            ...previousStartup,
            stage: 'stopped',
            message: disconnectedMessage,
            progress: 0,
            active: false,
            updated_at: nowMs / 1000,
        },
    };
}

export function getConnectionStatusView(options = {}) {
    const connected = !!options.connected;
    const running = !!options.running;
    const paused = !!options.paused;
    const status = options.status || {};
    const idleState = options.idleState || {};
    const startupActive = !!status?.startup?.active;
    const growthRunning = !!status?.growth_running;
    const serviceRunning = !!status?.service_running;
    const isIdleStandby = idleState.state === 'standby' || idleState.state === 'countdown';
    const isIdleStopped = idleState.state === 'stopped_by_idle';
    const canWake = !!options.canWake;

    let labelText = '服务已就绪';
    let dotClass = 'status-dot offline';
    let titleText = 'Python 服务已启动，机器人未启动';

    if (!connected && isIdleStopped) {
        labelText = '后端已休眠';
        dotClass = 'status-dot sleeping';
        titleText = 'Python 服务已因空闲自动休眠，点击唤醒';
    } else if (!connected) {
        labelText = '服务未连接';
        dotClass = 'status-dot offline';
        titleText = canWake
            ? 'Python 服务未连接，点击启动'
            : 'Python 服务未连接';
    } else if (!running && startupActive) {
        labelText = '机器人启动中';
        dotClass = 'status-dot warning';
        titleText = 'Python 服务已启动，机器人正在启动';
    } else if (running) {
        if (paused) {
            labelText = '机器人已暂停';
            dotClass = 'status-dot warning';
            titleText = 'Python 服务已启动，机器人当前处于暂停状态';
        } else {
            labelText = '机器人运行中';
            dotClass = 'status-dot online';
            titleText = 'Python 服务已启动，机器人正在运行';
        }
    } else if (growthRunning) {
        labelText = '成长任务运行中';
        dotClass = 'status-dot online';
        titleText = 'Python 服务已启动，成长任务正在运行';
    } else if (isIdleStandby) {
        labelText = '后端待机中';
        dotClass = 'status-dot standby';
        titleText = 'Python 服务在线，隐藏到托盘后会进入自动休眠倒计时';
    } else if (serviceRunning || connected) {
        labelText = '服务已就绪';
        dotClass = 'status-dot ready';
        titleText = 'Python 服务已启动，机器人未启动';
    }

    return {
        labelText,
        dotClass,
        titleText,
    };
}
