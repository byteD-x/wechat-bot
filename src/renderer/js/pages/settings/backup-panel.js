import { createElement } from './form-codec.js';

export function formatBackupSize(sizeBytes) {
    const numeric = Number(sizeBytes || 0);
    if (!Number.isFinite(numeric) || numeric <= 0) {
        return '0 B';
    }
    if (numeric >= 1024 * 1024) {
        return `${(numeric / (1024 * 1024)).toFixed(1)} MB`;
    }
    if (numeric >= 1024) {
        return `${(numeric / 1024).toFixed(1)} KB`;
    }
    return `${Math.round(numeric)} B`;
}

function formatBackupTime(value) {
    const numeric = Number(value || 0);
    if (!Number.isFinite(numeric) || numeric <= 0) {
        return '--';
    }
    return new Date(numeric * 1000).toLocaleString('zh-CN', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
    });
}

export function getBackupModeMeta(mode, backupId = '') {
    const normalizedMode = String(mode || '').trim().toLowerCase();
    const normalizedId = String(backupId || '').trim().toLowerCase();

    if (normalizedId.includes('pre-restore')) {
        return {
            label: '保险备份',
            description: '恢复前自动保留，便于需要时回退到恢复前状态',
        };
    }

    if (normalizedMode === 'full') {
        return {
            label: '完整备份',
            description: '包含工作区关键文件和聊天资料，适合迁移或大改前留档',
        };
    }

    return {
        label: '快速备份',
        description: '保存当前配置和核心运行数据，适合日常留档',
    };
}

function formatEvalSummary(latestEval) {
    if (!latestEval?.summary) {
        return '最近还没有质量检查记录';
    }

    const evalSummary = latestEval.summary || {};
    return [
        evalSummary.passed ? '最近一次质量检查已通过' : '最近一次质量检查需要关注',
        `覆盖 ${evalSummary.total_cases || 0} 条用例`,
        `检索命中率 ${(Number(evalSummary.retrieval_hit_rate || 0) * 100).toFixed(1)}%`,
    ].join(' / ');
}

function renderBackupList(container, backups = []) {
    container.textContent = '';
    if (!Array.isArray(backups) || backups.length === 0) {
        container.appendChild(createElement('div', 'empty-state compact-empty'));
        container.firstChild.appendChild(createElement('span', 'empty-state-text', '暂无备份'));
        return;
    }

    const fragment = document.createDocumentFragment();
    backups.forEach((backup) => {
        const meta = getBackupModeMeta(backup.mode, backup.id);
        const row = createElement('div', 'dashboard-model-item backup-history-item');
        const main = createElement('div', 'dashboard-model-main');
        main.appendChild(createElement('strong', '', `${formatBackupTime(backup.created_at)} · ${meta.label}`));
        main.appendChild(createElement('span', '', `${meta.description} · ${formatBackupSize(backup.size_bytes)}`));

        const side = createElement('div', 'backup-history-meta');
        side.appendChild(createElement('span', 'dashboard-model-cost', `${backup.included_files?.length || 0} 个文件`));
        side.appendChild(createElement('span', 'backup-history-id', String(backup.id || '--')));

        row.appendChild(main);
        row.appendChild(side);
        fragment.appendChild(row);
    });
    container.appendChild(fragment);
}

function populateBackupSelect(select, backups = []) {
    select.textContent = '';
    if (!Array.isArray(backups) || backups.length === 0) {
        const option = document.createElement('option');
        option.value = '';
        option.textContent = '暂无可恢复时间点';
        select.appendChild(option);
        return;
    }

    backups.forEach((backup, index) => {
        const option = document.createElement('option');
        const meta = getBackupModeMeta(backup.mode, backup.id);
        option.value = backup.id || '';
        option.textContent = `${formatBackupTime(backup.created_at)} · ${meta.label}${backup.id ? ` · ${backup.id}` : ` · backup-${index + 1}`}`;
        select.appendChild(option);
    });
}

export function renderBackupPanel(page) {
    const summaryElem = page.$('#settings-backup-summary');
    const evalElem = page.$('#settings-eval-summary');
    const selectElem = page.$('#settings-backup-select');
    const feedbackElem = page.$('#settings-backup-restore-feedback');
    const listElem = page.$('#settings-backup-list');
    if (!summaryElem || !evalElem || !selectElem || !feedbackElem || !listElem) {
        return;
    }

    const state = page._backupState || {};
    const backups = Array.isArray(state.backups) ? state.backups : [];
    const summary = state.summary || {};
    const latestEval = state.latestEval || null;
    const lastRestore = summary.last_restore_result || null;

    summaryElem.textContent = [
        `最近快速备份：${formatBackupTime(summary.latest_quick_backup_at)}`,
        `最近完整备份：${formatBackupTime(summary.latest_full_backup_at)}`,
    ].join(' / ');

    evalElem.textContent = formatEvalSummary(latestEval);

    if (lastRestore) {
        feedbackElem.textContent = lastRestore.success
            ? `最近一次恢复已完成，恢复前自动保留的保险备份：${lastRestore.pre_restore_backup?.id || '--'}`
            : `最近一次恢复未完成：${lastRestore.message || '--'}`;
    } else if (!state.restoreFeedback) {
        feedbackElem.textContent = '恢复前会自动留一份保险备份，避免恢复后找不回当前状态。';
    } else {
        feedbackElem.textContent = state.restoreFeedback;
    }

    populateBackupSelect(selectElem, backups);
    renderBackupList(listElem, backups);
}
