import { toast } from '../../services/NotificationService.js';
import { deepClone } from './form-codec.js';
import { formatModelOptionLabel } from './preset-meta.js';
import { resolveProviderModels } from './preset-ollama.js';

function getField(id) {
    if (typeof document === 'undefined') {
        return null;
    }
    return document.getElementById(id);
}

function getDraftList(page) {
    if (Array.isArray(page?._presetDrafts)) {
        return page._presetDrafts;
    }
    if (!Array.isArray(page?._apiPresetsSnapshot)) {
        page._apiPresetsSnapshot = [];
    }
    return page._apiPresetsSnapshot;
}

function setActivePresetName(page, value) {
    if ('_activePreset' in page) {
        page._activePreset = value;
    }
    if ('_activePresetName' in page) {
        page._activePresetName = value;
    }
}

function getProvider(page, providerId = '') {
    return page?._providersById?.get?.(String(providerId || '').trim()) || null;
}

function getSelectedModelValue() {
    const selectValue = getField('edit-preset-model-select')?.value || '';
    const customValue = String(getField('edit-preset-model-custom')?.value || '').trim();
    return String(selectValue === '__custom__' ? customValue : selectValue).trim();
}

function setModalState(page, preset = {}) {
    page._modalPresetState = {
        oauth_provider: String(preset.oauth_provider || '').trim(),
        oauth_source: String(preset.oauth_source || '').trim(),
        oauth_binding: preset.oauth_binding ? deepClone(preset.oauth_binding) : null,
        oauth_experimental_ack: !!preset.oauth_experimental_ack,
        pending_flow_id: '',
        pending_provider_id: '',
    };
    return page._modalPresetState;
}

function getSelectedAuthMode() {
    if (getField('edit-preset-auth-mode-oauth')?.checked) {
        return 'oauth';
    }
    return 'api_key';
}

export function createDefaultPreset(page) {
    const firstProvider = page?._modelCatalog?.providers?.[0] || { id: '', default_model: '' };
    return {
        name: '',
        provider_id: firstProvider.id || '',
        alias: '',
        base_url: firstProvider.base_url || '',
        api_key: '',
        auth_mode: 'api_key',
        oauth_provider: '',
        oauth_source: '',
        oauth_binding: null,
        oauth_experimental_ack: false,
        oauth_project_id: '',
        oauth_location: '',
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
    const select = getField('edit-preset-provider');
    if (!select) {
        return;
    }
    select.textContent = '';
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = '-- 选择服务商 --';
    select.appendChild(placeholder);
    (page?._modelCatalog?.providers || []).forEach((provider) => {
        const option = document.createElement('option');
        option.value = provider.id;
        option.textContent = provider.label;
        select.appendChild(option);
    });
    select.value = selectedId || '';
}

export async function populateModelOptions(page, providerId, selectedModel) {
    const select = getField('edit-preset-model-select');
    if (!select) {
        return;
    }
    const provider = getProvider(page, providerId) || page?._modelCatalog?.providers?.find?.((item) => item.id === providerId) || null;
    const models = Array.from(
        new Set((await resolveProviderModels(page, provider)).map((item) => String(item || '').trim()).filter(Boolean)),
    );
    select.textContent = '';
    [
        ['', '-- 选择模型 --'],
        ...models.map((item) => [item, formatModelOptionLabel(providerId, item)]),
        ['__custom__', '自定义模型'],
    ].forEach(([value, label]) => {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = label;
        select.appendChild(option);
    });
    select.value = selectedModel && models.includes(selectedModel) ? selectedModel : (selectedModel ? '__custom__' : '');
    const customInput = getField('edit-preset-model-custom');
    if (customInput) {
        customInput.value = !models.includes(selectedModel) ? (selectedModel || '') : '';
    }
    syncPresetModelInput();
}

export function syncPresetModelInput() {
    const select = getField('edit-preset-model-select');
    const customInput = getField('edit-preset-model-custom');
    if (!select || !customInput) {
        return;
    }
    customInput.style.display = select.value === '__custom__' ? 'block' : 'none';
    if (select.value !== '__custom__') {
        customInput.value = '';
    }
}

export function updatePresetHelpLink(page, providerId) {
    const provider = getProvider(page, providerId);
    const help = getField('api-key-help');
    const link = getField('api-key-help-link');
    if (!help || !link || !provider?.api_key_url) {
        if (help) {
            help.style.display = 'none';
        }
        return;
    }
    help.style.display = getSelectedAuthMode() === 'api_key' ? 'block' : 'none';
    link.href = provider.api_key_url;
    link.onclick = async (event) => {
        event.preventDefault();
        if (globalThis.window?.electronAPI?.openExternal) {
            await globalThis.window.electronAPI.openExternal(provider.api_key_url);
            return;
        }
        globalThis.window?.open?.(provider.api_key_url, '_blank', 'noopener,noreferrer');
    };
}

export function fillPresetModal(page, preset) {
    const provider = getProvider(page, preset.provider_id) || {};
    setModalState(page, preset);
    if (getField('edit-preset-original-name')) {
        getField('edit-preset-original-name').value = page._selectedPresetIndex >= 0 ? String(preset.name || '') : '';
    }
    if (getField('edit-preset-name')) {
        getField('edit-preset-name').value = preset.name || '';
    }
    if (getField('edit-preset-provider')) {
        getField('edit-preset-provider').value = preset.provider_id || '';
    }
    if (getField('edit-preset-alias')) {
        getField('edit-preset-alias').value = preset.alias || '';
    }
    if (getField('edit-preset-embedding-model')) {
        getField('edit-preset-embedding-model').value = preset.embedding_model || '';
    }
    if (getField('edit-preset-key')) {
        getField('edit-preset-key').type = 'password';
        getField('edit-preset-key').value = '';
        getField('edit-preset-key').placeholder = preset.api_key_configured ? '已配置，留空则保持不变' : '输入 API Key';
    }
    if (getField('edit-preset-oauth-project-id')) {
        getField('edit-preset-oauth-project-id').value = preset.oauth_project_id || '';
    }
    if (getField('edit-preset-oauth-location')) {
        getField('edit-preset-oauth-location').value = preset.oauth_location || '';
    }
    if (getField('edit-preset-auth-mode-api-key')) {
        getField('edit-preset-auth-mode-api-key').checked = (preset.auth_mode || 'api_key') !== 'oauth';
    }
    if (getField('edit-preset-auth-mode-oauth')) {
        getField('edit-preset-auth-mode-oauth').checked = (preset.auth_mode || 'api_key') === 'oauth';
    }
    updatePresetHelpLink(page, preset.provider_id);
    void populateModelOptions(page, preset.provider_id || provider.id || '', preset.model || provider.default_model || '');
}

export function openPresetModal(page, index = -1) {
    const modal = getField('preset-modal');
    if (!modal) {
        return;
    }
    const drafts = getDraftList(page);
    page._selectedPresetIndex = index;
    const preset = index >= 0 ? deepClone(drafts[index]) : createDefaultPreset(page);
    populateProviderOptions(page, preset.provider_id);
    fillPresetModal(page, preset);
    modal.classList.add('active');
}

export function closePresetModal(page) {
    getField('preset-modal')?.classList.remove('active');
    page._selectedPresetIndex = -1;
    page._modalPresetState = null;
}

export async function handlePresetProviderChange(page) {
    const providerId = getField('edit-preset-provider')?.value || '';
    const provider = getProvider(page, providerId) || {};
    updatePresetHelpLink(page, providerId);
    await populateModelOptions(page, providerId, provider.default_model || '');
}

export function togglePresetKeyVisibility() {
    const field = getField('edit-preset-key');
    if (field) {
        field.type = field.type === 'password' ? 'text' : 'password';
    }
}

export function removePreset(page, index) {
    const drafts = getDraftList(page);
    const preset = drafts[index];
    drafts.splice(index, 1);
    if ((page._activePreset || page._activePresetName) === preset?.name) {
        setActivePresetName(page, drafts[0]?.name || '');
    }
    page._renderPresetList?.();
    page._renderHero?.();
    page._scheduleAutoSave?.({ immediate: true });
    toast.info('预设已删除');
}

export function commitPresetModal(page, text) {
    const drafts = getDraftList(page);
    const name = String(getField('edit-preset-name')?.value || '').trim();
    const providerId = String(getField('edit-preset-provider')?.value || '').trim();
    const alias = String(getField('edit-preset-alias')?.value || '').trim();
    const embeddingModel = String(getField('edit-preset-embedding-model')?.value || '').trim();
    const key = String(getField('edit-preset-key')?.value || '').trim();
    const originalName = String(getField('edit-preset-original-name')?.value || '').trim();
    const model = getSelectedModelValue();
    const provider = getProvider(page, providerId) || {};
    const existing = page._selectedPresetIndex >= 0
        ? deepClone(drafts[page._selectedPresetIndex])
        : createDefaultPreset(page);

    if (!name) {
        toast.error(text.presetNameMissing);
        return;
    }
    if (!model) {
        toast.error(text.presetModelMissing);
        return;
    }

    const nextPreset = {
        ...existing,
        name,
        provider_id: providerId,
        alias,
        base_url: provider.base_url || existing.base_url || '',
        model,
        embedding_model: embeddingModel,
        api_key: key || existing.api_key || '',
        auth_mode: getSelectedAuthMode(),
        oauth_provider: page._modalPresetState?.oauth_provider || existing.oauth_provider || '',
        oauth_source: page._modalPresetState?.oauth_source || existing.oauth_source || '',
        oauth_binding: page._modalPresetState?.oauth_binding ? deepClone(page._modalPresetState.oauth_binding) : (existing.oauth_binding || null),
        oauth_experimental_ack: !!page._modalPresetState?.oauth_experimental_ack,
        oauth_project_id: String(getField('edit-preset-oauth-project-id')?.value || '').trim(),
        oauth_location: String(getField('edit-preset-oauth-location')?.value || '').trim(),
        allow_empty_key: !!provider.allow_empty_key,
    };

    if (page._selectedPresetIndex >= 0) {
        drafts[page._selectedPresetIndex] = nextPreset;
    } else {
        drafts.push(nextPreset);
    }

    if (!(page._activePreset || page._activePresetName) || originalName === (page._activePreset || page._activePresetName)) {
        setActivePresetName(page, name);
    }

    page._renderPresetList?.();
    page._renderHero?.();
    page._scheduleAutoSave?.({ immediate: true });
    closePresetModal(page);
    toast.success(text.presetSaveSuccess || '预设已保存');
}
