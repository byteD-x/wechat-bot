import { apiService } from '../../services/ApiService.js';
import { toast } from '../../services/NotificationService.js';
import { createElement, deepClone } from './form-codec.js';

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
            label: 'embedding 模型',
            className: 'is-embedding',
            title: '这个模型更适合向量化或检索任务，不适合作为主聊天模型。',
        };
    }
    if (lower.includes(':cloud')) {
        return {
            key: 'cloud',
            label: '云模型',
            className: 'is-cloud',
            title: '该模型通过本机 Ollama 接入远端云能力，需要稳定外网连接。',
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

export async function loadOllamaModels(page, baseUrl) {
    const key = getOllamaBaseUrl({ base_url: baseUrl });
    if (page._ollamaModelCache.has(key)) {
        return page._ollamaModelCache.get(key);
    }
    if (page._ollamaModelPromise.has(key)) {
        return page._ollamaModelPromise.get(key);
    }
    const promise = (async () => {
        try {
            const result = await apiService.getOllamaModels(key);
            const models = Array.isArray(result?.models)
                ? Array.from(new Set(result.models.map((item) => String(item || '').trim()).filter(Boolean)))
                : [];
            if (models.length) {
                page._ollamaModelCache.set(key, models);
            }
            return models;
        } catch (error) {
            console.warn('[SettingsPage] load ollama models failed:', error);
            return [];
        } finally {
            page._ollamaModelPromise.delete(key);
        }
    })();
    page._ollamaModelPromise.set(key, promise);
    return promise;
}

export async function warmOllamaModels(page) {
    const candidates = new Set();
    const provider = page._providersById.get('ollama');
    if (provider) {
        candidates.add(getOllamaBaseUrl(provider));
    }
    page._presetDrafts
        .filter((preset) => isOllamaPreset(preset))
        .forEach((preset) => candidates.add(getOllamaBaseUrl(preset)));
    if (!candidates.size) {
        return;
    }
    await Promise.allSettled([...candidates].map((baseUrl) => loadOllamaModels(page, baseUrl)));
    if (page.isActive()) {
        page._renderPresetList();
        page._renderHero();
    }
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

export async function testPresetByName(page, presetName, detailElement = null) {
    const preset = getPresetByName(page, presetName);
    if (!preset?.name) {
        toast.warning('请先选择一个有效预设');
        return;
    }
    await runPresetConnectionTest(page, preset, detailElement);
}

export async function runPresetConnectionTest(page, preset, detailElement) {
    const pendingText = '连接测试中...';
    setHeroTestFeedback(page, preset.name, 'pending', pendingText);
    try {
        if (detailElement) {
            detailElement.className = 'ping-result pending';
            detailElement.textContent = pendingText;
        }
        const result = window.electronAPI?.testConfigConnection
            ? await window.electronAPI.testConfigConnection({
                presetName: preset.name,
                patch: {
                    api: {
                        active_preset: page._activePreset,
                        presets: deepClone(page._presetDrafts),
                    },
                },
            })
            : await apiService.testConnection(preset.name);
        if (!result?.success) {
            throw new Error(result?.message || '连接测试失败');
        }
        const successMessage = result.message || '连接测试成功';
        if (detailElement) {
            detailElement.className = 'ping-result success';
            detailElement.textContent = successMessage;
        }
        setHeroTestFeedback(page, preset.name, 'success', successMessage);
        toast.success(`${preset.name} 连接测试成功`);
    } catch (error) {
        const errorMessage = toast.getErrorMessage(error, '连接测试失败');
        if (detailElement) {
            detailElement.className = 'ping-result error';
            detailElement.textContent = errorMessage;
        }
        setHeroTestFeedback(page, preset.name, 'error', errorMessage);
        toast.error(`${preset.name}：${errorMessage}`);
    }
}

export async function testPreset(page, index, detailElement) {
    const preset = page._presetDrafts[index];
    if (!preset?.name) {
        return;
    }
    await runPresetConnectionTest(page, preset, detailElement);
}

export function removePreset(page, index) {
    const preset = page._presetDrafts[index];
    page._presetDrafts.splice(index, 1);
    if (preset?.name === page._activePreset) {
        page._activePreset = page._presetDrafts[0]?.name || '';
    }
    page._renderPresetList();
    page._renderHero();
    page._scheduleAutoSave({ immediate: true });
    toast.info('预设已移除');
}

export function openPresetModal(page, index = -1) {
    const modal = document.getElementById('preset-modal');
    if (!modal) {
        return;
    }
    page._selectedPresetIndex = index;
    const preset = index >= 0 ? deepClone(page._presetDrafts[index]) : createDefaultPreset(page);
    populateProviderOptions(page, preset.provider_id);
    fillPresetModal(page, preset);
    modal.classList.add('active');
}

export function closePresetModal(page) {
    document.getElementById('preset-modal')?.classList.remove('active');
    page._selectedPresetIndex = -1;
}

export function createDefaultPreset(page) {
    const firstProvider = page._modelCatalog?.providers?.[0] || { id: '', default_model: '' };
    return {
        name: '',
        provider_id: firstProvider.id || '',
        alias: '',
        base_url: firstProvider.base_url || '',
        api_key: '',
        model: firstProvider.default_model || '',
        embedding_model: '',
        allow_empty_key: !!firstProvider.allow_empty_key,
        timeout_sec: 10,
        max_retries: 2,
        temperature: 0.6,
        max_tokens: 512,
    };
}

export function populateProviderOptions(page, selectedId) {
    const select = page.$('#edit-preset-provider');
    if (!select) {
        return;
    }
    select.textContent = '';
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = '-- 选择服务商 --';
    select.appendChild(placeholder);
    (page._modelCatalog?.providers || []).forEach((provider) => {
        const option = document.createElement('option');
        option.value = provider.id;
        option.textContent = provider.label;
        select.appendChild(option);
    });
    select.value = selectedId || '';
}

export function fillPresetModal(page, preset) {
    if (page.$('#edit-preset-original-name')) {
        page.$('#edit-preset-original-name').value = page._selectedPresetIndex >= 0 ? String(preset.name || '') : '';
    }
    if (page.$('#edit-preset-name')) {
        page.$('#edit-preset-name').value = preset.name || '';
    }
    if (page.$('#edit-preset-provider')) {
        page.$('#edit-preset-provider').value = preset.provider_id || '';
    }
    if (page.$('#edit-preset-alias')) {
        page.$('#edit-preset-alias').value = preset.alias || '';
    }
    if (page.$('#edit-preset-embedding-model')) {
        page.$('#edit-preset-embedding-model').value = preset.embedding_model || '';
    }
    if (page.$('#edit-preset-key')) {
        page.$('#edit-preset-key').type = 'password';
        page.$('#edit-preset-key').value = '';
        page.$('#edit-preset-key').placeholder = preset.api_key_configured ? '已配置，留空则保持不变' : '输入 API Key';
    }
    updatePresetHelpLink(page, preset.provider_id);
    void populateModelOptions(page, preset.provider_id, preset.model);
}

export async function handlePresetProviderChange(page) {
    const providerId = page.$('#edit-preset-provider')?.value || '';
    const provider = page._providersById.get(providerId) || {};
    updatePresetHelpLink(page, providerId);
    await populateModelOptions(page, providerId, provider.default_model || '');
}

export async function resolveProviderModels(page, provider) {
    const fallbackModels = Array.isArray(provider?.models) ? [...provider.models] : [];
    if (String(provider?.id || '').trim().toLowerCase() !== 'ollama') {
        return fallbackModels;
    }
    const liveModels = await loadOllamaModels(page, getOllamaBaseUrl(provider));
    return liveModels.length ? liveModels : fallbackModels;
}

export async function populateModelOptions(page, providerId, selectedModel) {
    const select = page.$('#edit-preset-model-select');
    if (!select) {
        return;
    }
    const resolvedProvider = page._providersById.get(providerId) || null;
    const resolvedModels = Array.from(
        new Set((await resolveProviderModels(page, resolvedProvider)).map((item) => String(item || '').trim()).filter(Boolean))
    );
    select.textContent = '';
    [['', '-- 选择模型 --'], ...resolvedModels.map((item) => [item, formatModelOptionLabel(providerId, item)]), ['__custom__', '自定义模型']].forEach(([value, label]) => {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = label;
        select.appendChild(option);
    });
    select.value = selectedModel && resolvedModels.includes(selectedModel) ? selectedModel : (selectedModel ? '__custom__' : '');
    if (page.$('#edit-preset-model-custom')) {
        page.$('#edit-preset-model-custom').value = !resolvedModels.includes(selectedModel) ? (selectedModel || '') : '';
    }
    syncPresetModelInput(page);
}

export function syncPresetModelInput(page) {
    const select = page.$('#edit-preset-model-select');
    const customInput = page.$('#edit-preset-model-custom');
    if (!select || !customInput) {
        return;
    }
    customInput.style.display = select.value === '__custom__' ? 'block' : 'none';
    if (select.value !== '__custom__') {
        customInput.value = '';
    }
}

export function updatePresetHelpLink(page, providerId) {
    const provider = page._providersById.get(providerId) || null;
    const help = document.getElementById('api-key-help');
    const link = document.getElementById('api-key-help-link');
    if (!help || !link || !provider?.api_key_url) {
        if (help) {
            help.style.display = 'none';
        }
        return;
    }
    help.style.display = 'block';
    link.href = provider.api_key_url;
    link.onclick = async (event) => {
        event.preventDefault();
        if (window.electronAPI?.openExternal) {
            await window.electronAPI.openExternal(provider.api_key_url);
        } else {
            window.open(provider.api_key_url, '_blank', 'noopener,noreferrer');
        }
    };
}

export function togglePresetKeyVisibility(page) {
    if (page.$('#edit-preset-key')) {
        page.$('#edit-preset-key').type = page.$('#edit-preset-key').type === 'password' ? 'text' : 'password';
    }
}

export function commitPresetModal(page, text) {
    const name = String(page.$('#edit-preset-name')?.value || '').trim();
    const providerId = String(page.$('#edit-preset-provider')?.value || '').trim();
    const alias = String(page.$('#edit-preset-alias')?.value || '').trim();
    const embeddingModel = String(page.$('#edit-preset-embedding-model')?.value || '').trim();
    const key = String(page.$('#edit-preset-key')?.value || '').trim();
    const originalName = String(page.$('#edit-preset-original-name')?.value || '').trim();
    const selectValue = page.$('#edit-preset-model-select')?.value || '';
    const customModel = String(page.$('#edit-preset-model-custom')?.value || '').trim();
    const model = (selectValue === '__custom__' ? customModel : selectValue).trim();

    if (!name) {
        toast.error(text.presetNameMissing);
        return;
    }
    if (!model) {
        toast.error(text.presetModelMissing);
        return;
    }

    const provider = page._providersById.get(providerId) || {};
    const existing = page._selectedPresetIndex >= 0
        ? deepClone(page._presetDrafts[page._selectedPresetIndex])
        : createDefaultPreset(page);
    if (page._selectedPresetIndex >= 0 && originalName && originalName !== name && existing.api_key_configured && !key) {
        toast.error('重命名已配置 Key 的预设时，请重新填写 API Key');
        return;
    }

    const nextPreset = {
        ...existing,
        name,
        provider_id: providerId,
        alias,
        base_url: provider.base_url || '',
        model,
        embedding_model: embeddingModel,
        allow_empty_key: !!provider.allow_empty_key,
    };
    if (key) {
        nextPreset.api_key = key;
    } else if (existing.api_key_configured) {
        nextPreset._keep_key = true;
    }

    if (page._selectedPresetIndex >= 0) {
        page._presetDrafts[page._selectedPresetIndex] = nextPreset;
    } else {
        page._presetDrafts.push(nextPreset);
    }
    if (!page._activePreset || originalName === page._activePreset) {
        page._activePreset = name;
    }

    page._renderPresetList();
    page._renderHero();
    closePresetModal(page);
    page._scheduleAutoSave({ immediate: true });
    toast.success(text.presetSaveSuccess);
}
