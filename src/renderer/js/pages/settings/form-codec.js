import {
    FIELD_DEFS,
    LIST_FIELD_DEFS,
    MAP_FIELD_DEFS,
    RANGE_FIELD_DEFS,
} from './schema.js';

export function deepClone(value) {
    return JSON.parse(JSON.stringify(value ?? {}));
}

function getPathValue(target, path) {
    return String(path || '')
        .split('.')
        .filter(Boolean)
        .reduce((cursor, key) => (cursor && key in cursor ? cursor[key] : undefined), target);
}

function setPathValue(target, path, value) {
    const keys = String(path || '').split('.').filter(Boolean);
    let cursor = target;
    while (keys.length > 1) {
        const key = keys.shift();
        if (!cursor[key] || typeof cursor[key] !== 'object') {
            cursor[key] = {};
        }
        cursor = cursor[key];
    }
    cursor[keys[0]] = value;
}

function normalizeListText(value) {
    return String(value || '')
        .split(/\r?\n/)
        .map((item) => item.trim())
        .filter(Boolean);
}

function listToMultiline(value) {
    return Array.isArray(value) ? value.join('\n') : '';
}

function mapToMultiline(value, separator) {
    if (!value || typeof value !== 'object') {
        return '';
    }
    return Object.entries(value)
        .map(([key, next]) => `${key}${separator}${next}`)
        .join('\n');
}

function multilineToMap(value, separator) {
    const result = {};
    for (const line of normalizeListText(value)) {
        const index = line.indexOf(separator);
        if (index <= 0) {
            continue;
        }
        const key = line.slice(0, index).trim();
        const nextValue = line.slice(index + separator.length).trim();
        if (key) {
            result[key] = nextValue;
        }
    }
    return result;
}

export function formatDateTime(value) {
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
        second: '2-digit',
    }).format(date);
}

export function createElement(tag, className, text) {
    const element = document.createElement(tag);
    if (className) {
        element.className = className;
    }
    if (text !== undefined) {
        element.textContent = text;
    }
    return element;
}

function pruneEmptySections(payload) {
    const nextPayload = payload && typeof payload === 'object' ? payload : {};
    Object.keys(nextPayload).forEach((section) => {
        const value = nextPayload[section];
        if (value && typeof value === 'object' && !Array.isArray(value) && Object.keys(value).length === 0) {
            delete nextPayload[section];
        }
    });
    return nextPayload;
}

export function fillSettingsForm(page, config, scope = null) {
    const includeIds = scope?.ids instanceof Set ? scope.ids : null;
    const includeSections = scope?.sections instanceof Set ? scope.sections : null;

    FIELD_DEFS.forEach(([id, section, path, type, options = {}]) => {
        if ((includeSections && !includeSections.has(section)) || (includeIds && !includeIds.has(id))) {
            return;
        }
        const element = page.$(`#${id}`);
        if (!element) {
            return;
        }
        const value = getPathValue(config?.[section] || {}, path);
        if (type === 'checkbox') {
            element.checked = !!value;
        } else if (type === 'number') {
            element.value = value === null || value === undefined ? '' : String(value);
            if (options.nullable && (value === null || value === undefined)) {
                element.placeholder = '留空';
            }
        } else {
            element.value = value ?? '';
        }
    });

    LIST_FIELD_DEFS.forEach(([id, section, path]) => {
        if ((includeSections && !includeSections.has(section)) || (includeIds && !includeIds.has(id))) {
            return;
        }
        const element = page.$(`#${id}`);
        if (element) {
            element.value = listToMultiline(getPathValue(config?.[section] || {}, path));
        }
    });

    MAP_FIELD_DEFS.forEach(([id, section, path, separator]) => {
        if ((includeSections && !includeSections.has(section)) || (includeIds && !includeIds.has(id))) {
            return;
        }
        const element = page.$(`#${id}`);
        if (element) {
            element.value = mapToMultiline(getPathValue(config?.[section] || {}, path), separator);
        }
    });

    RANGE_FIELD_DEFS.forEach(([minId, maxId, section, path]) => {
        if ((includeSections && !includeSections.has(section)) || (includeIds && !includeIds.has(minId) && !includeIds.has(maxId))) {
            return;
        }
        const range = getPathValue(config?.[section] || {}, path);
        const [minValue, maxValue] = Array.isArray(range) ? range : ['', ''];
        const minElement = page.$(`#${minId}`);
        const maxElement = page.$(`#${maxId}`);
        if (minElement) {
            minElement.value = minValue ?? '';
        }
        if (maxElement) {
            maxElement.value = maxValue ?? '';
        }
    });

    const langsmithStatus = document.getElementById('agent-langsmith-key-status');
    if (langsmithStatus) {
        langsmithStatus.value = config?.agent?.langsmith_api_key_configured ? '已配置（已隐藏）' : '未配置';
    }
}

export function collectSettingsPayload(page, scope = null, options = {}) {
    const includeIds = scope?.ids instanceof Set ? scope.ids : null;
    const includeSections = scope?.sections instanceof Set ? scope.sections : null;
    const includeApiPresets = !scope || !!scope.includeApiPresets;
    const payload = {};

    FIELD_DEFS.forEach(([id, section, path, type, fieldOptions = {}]) => {
        if ((includeSections && !includeSections.has(section)) || (includeIds && !includeIds.has(id))) {
            return;
        }
        const element = page.$(`#${id}`);
        if (!element) {
            return;
        }
        let value;
        if (type === 'checkbox') {
            value = !!element.checked;
        } else if (type === 'number') {
            const raw = String(element.value || '').trim();
            if (!raw && fieldOptions.nullable) {
                value = null;
            } else if (!raw) {
                return;
            } else {
                value = Number(raw);
                if (!Number.isFinite(value)) {
                    return;
                }
            }
        } else {
            value = element.value;
        }
        if (!payload[section]) {
            payload[section] = {};
        }
        setPathValue(payload[section], path, value);
    });

    LIST_FIELD_DEFS.forEach(([id, section, path]) => {
        if ((includeSections && !includeSections.has(section)) || (includeIds && !includeIds.has(id))) {
            return;
        }
        const element = page.$(`#${id}`);
        if (element) {
            if (!payload[section]) {
                payload[section] = {};
            }
            setPathValue(payload[section], path, normalizeListText(element.value));
        }
    });

    MAP_FIELD_DEFS.forEach(([id, section, path, separator]) => {
        if ((includeSections && !includeSections.has(section)) || (includeIds && !includeIds.has(id))) {
            return;
        }
        const element = page.$(`#${id}`);
        if (element) {
            if (!payload[section]) {
                payload[section] = {};
            }
            setPathValue(payload[section], path, multilineToMap(element.value, separator));
        }
    });

    RANGE_FIELD_DEFS.forEach(([minId, maxId, section, path]) => {
        if ((includeSections && !includeSections.has(section)) || (includeIds && !includeIds.has(minId) && !includeIds.has(maxId))) {
            return;
        }
        if (!payload[section]) {
            payload[section] = {};
        }
        setPathValue(payload[section], path, [
            Number(page.$(`#${minId}`)?.value || 0),
            Number(page.$(`#${maxId}`)?.value || 0),
        ]);
    });

    if (includeApiPresets) {
        payload.api = {
            ...(payload.api || {}),
            active_preset: options.activePreset || '',
            presets: deepClone(options.presetDrafts || []),
        };
    }

    return pruneEmptySections(payload);
}
