export const GROWTH_TASK_LABELS = {
    emotion: '情绪沉淀',
    contact_prompt: '联系人 Prompt',
    vector_memory: '向量记忆',
    facts: '事实提取',
    export_rag_sync: '导出语料同步',
};

export const GROWTH_MODE_LABELS = {
    deferred_until_batch: '按批处理执行',
    background_only: '仅后台执行',
    immediate: '即时执行',
};

const GROWTH_BATCH_REASON_LABELS = {
    memory_unavailable: '记忆库不可用',
};

const TIMING_LABELS = {
    prepare_total_sec: '总准备耗时',
    load_context_sec: '加载上下文',
    build_prompt_sec: '构建提示词',
    invoke_sec: '调用模型',
    stream_sec: '流式输出',
};

const STARTUP_STAGE_LABELS = {
    loading_config: '加载配置',
    init_memory: '准备记忆',
    init_ai: '初始化 AI',
    connect_wechat: '连接微信',
    ready: '启动完成',
    failed: '启动失败',
    idle: '等待启动',
    stopped: '已停止',
    starting: '启动中',
};

export function formatDurationMs(value) {
    const totalSeconds = Math.max(0, Math.ceil(Number(value || 0) / 1000));
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    if (minutes <= 0) {
        return `${seconds} 秒`;
    }
    if (seconds <= 0) {
        return `${minutes} 分钟`;
    }
    return `${minutes} 分 ${seconds} 秒`;
}

export function formatTime(timestamp) {
    if (!timestamp) {
        return '';
    }

    const raw = Number(timestamp);
    const date = new Date(raw > 1e12 ? raw : raw * 1000);
    if (Number.isNaN(date.getTime())) {
        return '';
    }

    const now = new Date();
    if (date.toDateString() === now.toDateString()) {
        return date.toLocaleTimeString('zh-CN', {
            hour: '2-digit',
            minute: '2-digit'
        });
    }

    return date.toLocaleString('zh-CN', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit'
    });
}

export function getGrowthTaskLabel(taskType) {
    const key = String(taskType || '').trim();
    return GROWTH_TASK_LABELS[key] || key || '未命名任务';
}

export function getGrowthModeLabel(mode) {
    const key = String(mode || '').trim();
    return GROWTH_MODE_LABELS[key] || key || '';
}

export function getGrowthBatchReason(reason) {
    const key = String(reason || '').trim();
    return GROWTH_BATCH_REASON_LABELS[key] || key || '';
}

export function formatGrowthTimestamp(value) {
    if (value === undefined || value === null || value === '') {
        return '--';
    }

    const numeric = Number(value);
    const date = Number.isFinite(numeric)
        ? new Date(numeric > 1e12 ? numeric : numeric * 1000)
        : new Date(value);

    if (Number.isNaN(date.getTime())) {
        return '--';
    }

    return date.toLocaleString('zh-CN', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
    });
}

export function formatDurationSec(value) {
    const sec = Number(value);
    if (!Number.isFinite(sec) || sec <= 0) {
        return '--';
    }

    const ms = sec * 1000;
    if (ms < 1000) {
        return `${Math.round(ms)} ms`;
    }
    if (ms < 10000) {
        return `${(ms / 1000).toFixed(2)} s`;
    }
    return `${(ms / 1000).toFixed(1)} s`;
}

export function formatTimingLabel(key) {
    return TIMING_LABELS[key] || String(key || '');
}

export function getStartupStageLabel(stage) {
    return STARTUP_STAGE_LABELS[stage] || `当前阶段: ${stage || 'starting'}`;
}

export function formatStartupUpdatedAt(timestamp) {
    const value = Number(timestamp || 0);
    if (!Number.isFinite(value) || value <= 0) {
        return '';
    }

    return `更新于 ${new Date(value * 1000).toLocaleTimeString('zh-CN', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
    })}`;
}

export function formatStartupMeta(startup) {
    const progressValue = Number(startup?.progress || 0);
    const stageLabel = getStartupStageLabel(startup?.stage);
    const updatedAt = formatStartupUpdatedAt(startup?.updated_at);
    return updatedAt
        ? `${progressValue}% · ${stageLabel} · ${updatedAt}`
        : `${progressValue}% · ${stageLabel}`;
}

export function formatPercent(value) {
    if (value === undefined || value === null || Number.isNaN(Number(value))) {
        return '--';
    }
    return `${Number(value).toFixed(1)}%`;
}

export function formatMemory(processMemory, systemPercent) {
    const processText =
        processMemory === undefined || processMemory === null || Number.isNaN(Number(processMemory))
            ? '--'
            : `${Number(processMemory).toFixed(0)} MB`;
    const systemText =
        systemPercent === undefined || systemPercent === null || Number.isNaN(Number(systemPercent))
            ? '--'
            : `${Number(systemPercent).toFixed(0)}%`;
    return `${processText} / ${systemText}`;
}

export function formatQueue(pendingTasks, pendingChats, pendingMessages) {
    const tasks = Number.isFinite(Number(pendingTasks)) ? Number(pendingTasks) : 0;
    const chats = Number.isFinite(Number(pendingChats)) ? Number(pendingChats) : 0;
    const messages = Number.isFinite(Number(pendingMessages)) ? Number(pendingMessages) : 0;
    return `${tasks} 个任务 / ${chats} 个会话 / ${messages} 条消息`;
}

export function formatLatency(value) {
    if (value === undefined || value === null || Number.isNaN(Number(value)) || Number(value) <= 0) {
        return '--';
    }
    return `${Math.round(Number(value))} ms`;
}

export function formatReplyQualitySummary(value) {
    const attempted = Number(value?.attempted || 0);
    const history24h = value?.history_24h || null;
    const historyAttempted = Number(history24h?.attempted || 0);
    const sessionAvailable = Number.isFinite(attempted) && attempted > 0;
    const historyAvailable = Number.isFinite(historyAttempted) && historyAttempted > 0;

    if (!sessionAvailable && !historyAvailable) {
        return '回复质量：暂无样本';
    }

    const extras = [];
    if (sessionAvailable) {
        const successRate = Number(value?.success_rate || 0);
        const delayed = Number(value?.delayed || 0);
        const retrievalAugmented = Number(value?.retrieval_augmented || 0);
        const empty = Number(value?.empty || 0);
        const helpfulCount = Number(value?.helpful_count || 0);
        const unhelpfulCount = Number(value?.unhelpful_count || 0);
        const rateText = Number.isFinite(successRate) ? successRate.toFixed(1) : '0.0';
        extras.push(`本次 ${rateText}%`);
        if (Number.isFinite(delayed) && delayed > 0) {
            extras.push(`超时补发 ${delayed}`);
        }
        if (Number.isFinite(retrievalAugmented) && retrievalAugmented > 0) {
            extras.push(`检索增强 ${retrievalAugmented}`);
        }
        if (Number.isFinite(empty) && empty > 0) {
            extras.push(`空回复 ${empty}`);
        }
        if (Number.isFinite(helpfulCount) && helpfulCount > 0) {
            extras.push(`有帮助 ${helpfulCount}`);
        }
        if (Number.isFinite(unhelpfulCount) && unhelpfulCount > 0) {
            extras.push(`没帮助 ${unhelpfulCount}`);
        }
    }

    if (historyAvailable) {
        const historyRate = Number(history24h?.success_rate || 0);
        const historyHelpful = Number(history24h?.helpful_count || 0);
        const historyUnhelpful = Number(history24h?.unhelpful_count || 0);
        const historyRateText = Number.isFinite(historyRate) ? historyRate.toFixed(1) : '0.0';
        extras.push(`近24h ${historyRateText}%`);
        if (Number.isFinite(historyHelpful) && historyHelpful > 0) {
            extras.push(`近24h 有帮助 ${historyHelpful}`);
        }
        if (Number.isFinite(historyUnhelpful) && historyUnhelpful > 0) {
            extras.push(`近24h 没帮助 ${historyUnhelpful}`);
        }
    }

    return `回复质量：${extras.join(' · ')}`;
}

export function formatNumber(value) {
    if (value === undefined || value === null) {
        return '0';
    }
    return Number(value).toLocaleString('zh-CN');
}

export function formatTokens(value) {
    const num = Number(value || 0);
    if (!Number.isFinite(num) || num <= 0) {
        return '0';
    }
    if (num < 1000) {
        return String(num);
    }
    if (num < 1000000) {
        return `${(num / 1000).toFixed(1)}K`;
    }
    return `${(num / 1000000).toFixed(1)}M`;
}

export function formatCurrencyGroups(groups) {
    if (!Array.isArray(groups) || groups.length === 0) {
        return '';
    }
    return groups
        .map((item) => formatCurrencyValue(item.currency, item.total_cost))
        .join(' / ');
}

export function formatCurrencyValue(currency, amount) {
    const value = Number(amount || 0);
    if (!Number.isFinite(value)) {
        return '--';
    }

    const digits = value >= 100 ? 2 : value >= 1 ? 4 : 6;
    const fixed = value.toFixed(digits);
    if (currency === 'CNY') {
        return `¥${fixed}`;
    }
    if (currency === 'LOCAL') {
        return `本地 ${fixed}`;
    }
    return `$${fixed}`;
}
