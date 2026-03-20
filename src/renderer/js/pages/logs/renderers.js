import {
    formatLogDisplayLine,
    formatLogNow,
    getLogClassName,
    LOG_TEXT,
    parseLogEntry,
} from './formatters.js';

export function renderLogList(page, allLogs, visibleLogs) {
    const container = page.$('#log-content');
    if (!container) {
        return;
    }

    container.textContent = '';

    if (visibleLogs.length === 0) {
        container.textContent = allLogs.length === 0 ? LOG_TEXT.empty : LOG_TEXT.noMatch;
        return;
    }

    const fragment = document.createDocumentFragment();
    for (const line of visibleLogs) {
        const entry = parseLogEntry(line);
        const item = document.createElement('span');
        item.className = getLogClassName(entry.level);
        item.textContent = formatLogDisplayLine(entry);
        item.title = entry.raw;
        fragment.appendChild(item);
    }

    container.appendChild(fragment);
}

export function updateLogMeta(page, totalCount, visibleCount) {
    const total = page.$('#log-count');
    const visible = page.$('#log-visible-count');
    const updated = page.$('#log-updated');

    if (total) {
        total.textContent = `${totalCount} ${LOG_TEXT.lines}`;
    }
    if (visible) {
        visible.textContent = `${visibleCount} ${LOG_TEXT.matched}`;
    }
    if (updated) {
        updated.textContent = totalCount > 0 ? formatLogNow() : '--';
    }
}
