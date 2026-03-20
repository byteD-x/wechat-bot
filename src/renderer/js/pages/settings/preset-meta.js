import { createElement } from './form-codec.js';

export function getPresetByName(page, name) {
    const wanted = String(name || '').trim();
    if (!wanted) {
        return null;
    }
    return page._presetDrafts.find((preset) => String(preset?.name || '').trim() === wanted) || null;
}

export function getRuntimePresetDraft(page) {
    return getPresetByName(page, page.getState('bot.status.runtime_preset') || '');
}

export function getActivePresetDraft(page) {
    return getPresetByName(page, page._activePreset);
}

export function getEffectivePreset(page) {
    return getRuntimePresetDraft(page) || getActivePresetDraft(page) || page._presetDrafts[0] || null;
}

export function getProviderLabel(page, providerId) {
    const provider = page._providersById.get(String(providerId || '').trim()) || null;
    return provider?.label || providerId || '--';
}

export function isOllamaPreset(preset) {
    return String(preset?.provider_id || '').trim().toLowerCase() === 'ollama';
}

export function inferOllamaModelKind(modelName) {
    const model = String(modelName || '').trim();
    const lower = model.toLowerCase();
    if (!lower) {
        return {
            key: 'unknown',
            label: '未设置模型',
            className: 'is-unknown',
            title: '当前预设还没有配置聊天模型。',
        };
    }
    if (
        lower.includes('embed')
        || lower.includes('embedding')
        || lower.startsWith('bge-')
        || lower.startsWith('nomic-embed')
    ) {
        return {
            key: 'embedding',
            label: 'Embedding 模型',
            className: 'is-embedding',
            title: '这个模型更适合向量化或检索任务，不适合作为主聊天模型。',
        };
    }
    if (lower.includes(':cloud')) {
        return {
            key: 'cloud',
            label: '云模型',
            className: 'is-cloud',
            title: '该模型通过本机 Ollama 接入远程云能力，需要稳定外网连接。',
        };
    }
    return {
        key: 'local',
        label: '本地模型',
        className: 'is-local',
        title: '该模型由本机 Ollama 提供推理能力。',
    };
}

export function getPresetModelMeta(_page, preset, overrideModel = '') {
    if (!preset) {
        return null;
    }
    const model = String(overrideModel || preset.model || '').trim();
    if (isOllamaPreset(preset)) {
        return inferOllamaModelKind(model);
    }
    return null;
}

export function createModelKindBadge(meta, extraClassName = '') {
    if (!meta) {
        return null;
    }
    const className = ['model-kind-badge', meta.className, extraClassName].filter(Boolean).join(' ');
    const badge = createElement('span', className, meta.label);
    if (meta.title) {
        badge.title = meta.title;
    }
    return badge;
}

export function setHeroTestFeedback(page, presetName, state, message) {
    page._heroTestFeedback = {
        presetName: String(presetName || '').trim(),
        state: String(state || 'idle').trim(),
        message: String(message || '').trim(),
    };
    if (page.isActive()) {
        page._renderHero();
    }
}

export function getOllamaBaseUrl(providerOrPreset) {
    const explicitBaseUrl = String(providerOrPreset?.base_url || '').trim();
    if (explicitBaseUrl) {
        return explicitBaseUrl;
    }
    return 'http://127.0.0.1:11434/v1';
}

export function formatModelOptionLabel(providerId, modelName) {
    const model = String(modelName || '').trim();
    if (!model) {
        return '-- 选择模型 --';
    }
    if (String(providerId || '').trim().toLowerCase() !== 'ollama') {
        return model;
    }
    const meta = inferOllamaModelKind(model);
    return `${model} · ${meta.label}`;
}
