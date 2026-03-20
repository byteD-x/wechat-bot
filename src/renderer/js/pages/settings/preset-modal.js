import { toast } from '../../services/NotificationService.js';
import { deepClone } from './form-codec.js';
import { formatModelOptionLabel } from './preset-meta.js';
import { resolveProviderModels } from './preset-ollama.js';

export function removePreset(page, index) {
    const preset = page._presetDrafts[index];
    page._presetDrafts.splice(index, 1);
    if (preset?.name === page._activePreset) {
        page._activePreset = page._presetDrafts[0]?.name || '';
    }
    page._renderPresetList();
    page._renderHero();
    page._scheduleAutoSave({ immediate: true });
    toast.info('预设已删除');
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
        if (globalThis.window?.electronAPI?.openExternal) {
            await globalThis.window.electronAPI.openExternal(provider.api_key_url);
        } else {
            globalThis.window?.open?.(provider.api_key_url, '_blank', 'noopener,noreferrer');
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
