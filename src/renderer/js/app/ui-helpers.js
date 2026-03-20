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
    } else if (state.available && state.latestVersion) {
        suffix = ` · 可更新到 v${state.latestVersion}`;
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
    if (state.available && state.latestVersion) {
        return { hidden: false, text: `新版本 v${state.latestVersion}`, disabled: false };
    }
    if (state.checking) {
        return { hidden: false, text: '检查更新中...', disabled: true };
    }
    return { hidden: true, text: '', disabled: false };
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

    const currentVersion = state.currentVersion || '--';
    const latestVersion = state.latestVersion || '';
    const releaseDate = state.releaseDate;
    const checkedAt = state.lastCheckedAt;
    const error = state.error;
    const readyToInstall = !!state.readyToInstall;
    const downloading = !!state.downloading;
    const downloadProgress = Math.min(100, Math.max(0, Number(state.downloadProgress || 0)));
    const available = !!state.available;
    const noteItems = Array.isArray(state.notes) ? state.notes : [];

    if (readyToInstall) {
        statusText.textContent = `更新已准备好：v${latestVersion || currentVersion}`;
    } else if (downloading) {
        statusText.textContent = `正在下载 v${latestVersion}...`;
    } else if (error) {
        statusText.textContent = error;
    } else if (available && latestVersion) {
        statusText.textContent = `发现新版本 v${latestVersion}`;
    } else {
        statusText.textContent = '当前已经是最新版本';
    }

    meta.textContent = [
        `当前版本：v${currentVersion}`,
        latestVersion ? `最新版本：v${latestVersion}` : '',
        releaseDate ? `发布日期：${formatAppDateTime(releaseDate)}` : '',
        checkedAt ? `最近检查：${formatAppDateTime(checkedAt)}` : '',
    ].filter(Boolean).join(' · ');

    notes.textContent = '';
    const renderedNotes = noteItems.length > 0 ? noteItems : ['暂无更新说明。'];
    renderedNotes.forEach((item) => {
        notes.appendChild(createAppElement('li', 'update-modal-note-item', item));
    });

    progress.hidden = !downloading;
    progressFill.style.width = `${downloadProgress}%`;
    progressText.textContent = downloading ? `下载进度 ${downloadProgress}%` : '';

    btnSkip.style.display = readyToInstall ? 'none' : 'inline-flex';
    btnSkip.disabled = downloading || !latestVersion;

    if (readyToInstall) {
        btnAction.textContent = '立即安装并重启';
        btnAction.disabled = false;
    } else if (downloading) {
        btnAction.textContent = `下载中 ${downloadProgress}%`;
        btnAction.disabled = true;
    } else {
        btnAction.textContent = '下载更新';
        btnAction.disabled = !latestVersion;
    }
}

export function buildDisconnectedStatus(previousStatus = null, idleState = {}, nowMs = Date.now()) {
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
        diagnostics: null,
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
