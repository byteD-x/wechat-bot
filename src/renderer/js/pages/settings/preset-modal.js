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

function normalizeRuntimeBaseUrl(value) {
    return String(value || '').trim().replace(/\/+$/, '');
}

function getProviderAuthMethods(provider = {}) {
    return Array.isArray(provider?.auth_methods)
        ? provider.auth_methods.filter((item) => item && typeof item === 'object')
        : [];
}

function resolveMethodRecommendedBaseUrl(method = {}, preset = {}) {
    let value = normalizeRuntimeBaseUrl(method?.metadata?.recommended_base_url);
    if (!value) {
        return '';
    }
    const projectId = String(preset.oauth_project_id || '').trim();
    const location = String(preset.oauth_location || '').trim();
    if (projectId) {
        value = value.replaceAll('{project}', projectId);
    }
    if (location) {
        value = value.replaceAll('{location}', location);
    }
    return normalizeRuntimeBaseUrl(value);
}

function collectMethodBaseUrlHints(method = {}, preset = {}) {
    const hints = [
        resolveMethodRecommendedBaseUrl(method, preset),
        ...((method?.metadata?.regional_base_urls || []).map((item) => normalizeRuntimeBaseUrl(item))),
    ].filter(Boolean);
    return Array.from(new Set(hints));
}

function matchesMethodBaseUrl(method = {}, baseUrl = '', preset = {}) {
    const wanted = normalizeRuntimeBaseUrl(baseUrl).toLowerCase();
    if (!wanted) {
        return false;
    }
    return collectMethodBaseUrlHints(method, preset).some((candidate) => wanted.startsWith(candidate.toLowerCase()));
}

function shouldUseQwenCodingPlanModel(model = '') {
    const normalized = String(model || '').trim().toLowerCase();
    return normalized.includes('coder')
        || ['minimax-m2.5', 'glm-5', 'glm-4.7', 'kimi-k2.5'].includes(normalized);
}

function resolvePresetAuthMethod(provider = {}, preset = {}) {
    const providerId = String(provider?.id || preset.provider_id || '').trim().toLowerCase();
    const authMode = String(preset.auth_mode || 'api_key').trim().toLowerCase() || 'api_key';
    const model = String(preset.model || '').trim().toLowerCase();
    const oauthProvider = String(preset.oauth_provider || '').trim();
    const methods = getProviderAuthMethods(provider);
    if (authMode === 'oauth') {
        if (oauthProvider) {
            const matched = methods.find((method) => {
                const methodId = String(method?.id || '').trim();
                const methodProviderId = String(method?.provider_id || '').trim();
                return oauthProvider === methodId || oauthProvider === methodProviderId;
            });
            if (matched) {
                return matched;
            }
        }
        return methods.find((method) => String(method?.type || '').trim() === 'oauth')
            || methods.find((method) => String(method?.type || '').trim() === 'local_import')
            || null;
    }

    const codingPlanMethod = methods.find((method) => String(method?.id || '').trim() === 'coding_plan_api_key');
    const genericApiKeyMethod = methods.find((method) => {
        const methodType = String(method?.type || '').trim();
        const methodId = String(method?.id || '').trim();
        return methodType === 'api_key' && methodId !== 'coding_plan_api_key';
    }) || methods.find((method) => String(method?.type || '').trim() === 'api_key') || null;
    const currentBaseUrl = normalizeRuntimeBaseUrl(preset.base_url);
    const providerDefaultBaseUrl = normalizeRuntimeBaseUrl(provider?.base_url);

    if (providerId === 'qwen' && shouldUseQwenCodingPlanModel(model)) {
        return codingPlanMethod || genericApiKeyMethod;
    }
    if (providerId === 'kimi' && (model === 'kimi-for-coding' || normalizeRuntimeBaseUrl(preset.base_url).toLowerCase().includes('/coding/'))) {
        return codingPlanMethod || genericApiKeyMethod;
    }
    if (providerId === 'zhipu' || providerId === 'minimax') {
        return codingPlanMethod || genericApiKeyMethod;
    }
    const matchedByBaseUrl = methods.find((method) => matchesMethodBaseUrl(method, currentBaseUrl, preset));
    if (matchedByBaseUrl && currentBaseUrl && currentBaseUrl !== providerDefaultBaseUrl) {
        return matchedByBaseUrl;
    }
    return genericApiKeyMethod || codingPlanMethod || null;
}

function resolvePresetRuntimeSelection(provider = {}, preset = {}) {
    const method = resolvePresetAuthMethod(provider, preset);
    const authMode = String(preset.auth_mode || 'api_key').trim().toLowerCase() || 'api_key';
    const providerDefaultModel = String(provider?.default_model || '').trim();
    const providerDefaultBaseUrl = normalizeRuntimeBaseUrl(provider?.base_url);
    const currentModel = String(preset.model || '').trim();
    const currentBaseUrl = normalizeRuntimeBaseUrl(preset.base_url || providerDefaultBaseUrl || '');
    const recommendedModel = String(method?.metadata?.recommended_model || '').trim();
    const recommendedBaseUrl = resolveMethodRecommendedBaseUrl(method, preset);
    const nextModel = recommendedModel && (!currentModel || currentModel === providerDefaultModel)
        ? recommendedModel
        : currentModel;
    const nextBaseUrl = recommendedBaseUrl && (!currentBaseUrl || currentBaseUrl === providerDefaultBaseUrl)
        ? recommendedBaseUrl
        : currentBaseUrl;
    return {
        method,
        model: nextModel || currentModel || providerDefaultModel || '',
        base_url: nextBaseUrl || currentBaseUrl || providerDefaultBaseUrl || '',
        oauth_provider: authMode === 'oauth'
            ? String(method?.provider_id || preset.oauth_provider || '').trim()
            : String(preset.oauth_provider || '').trim(),
    };
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
        try {
            if (globalThis.window?.electronAPI?.openExternal) {
                const result = await globalThis.window.electronAPI.openExternal(provider.api_key_url);
                if (!result?.success) {
                    throw new Error(result?.error || 'open_external_failed');
                }
                return;
            }
            globalThis.window?.open?.(provider.api_key_url, '_blank', 'noopener,noreferrer');
        } catch (error) {
            toast.error('打开链接失败，请稍后重试');
        }
    };
}

export function fillPresetModal(page, preset) {
    const provider = getProvider(page, preset.provider_id) || {};
    setModalState(page, preset);
    const runtime = resolvePresetRuntimeSelection(provider, preset);
    if (page._modalPresetState && !page._modalPresetState.oauth_provider && runtime.oauth_provider) {
        page._modalPresetState.oauth_provider = runtime.oauth_provider;
    }
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
    void populateModelOptions(page, preset.provider_id || provider.id || '', runtime.model || preset.model || provider.default_model || '');
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
    const runtime = resolvePresetRuntimeSelection(provider, {
        provider_id: providerId,
        auth_mode: getSelectedAuthMode(),
        model: getSelectedModelValue() || provider.default_model || '',
        base_url: provider.base_url || '',
        oauth_provider: page._modalPresetState?.oauth_provider || '',
        oauth_project_id: String(getField('edit-preset-oauth-project-id')?.value || '').trim(),
        oauth_location: String(getField('edit-preset-oauth-location')?.value || '').trim(),
    });
    if (page._modalPresetState && !page._modalPresetState.oauth_provider && runtime.oauth_provider) {
        page._modalPresetState.oauth_provider = runtime.oauth_provider;
    }
    updatePresetHelpLink(page, providerId);
    await populateModelOptions(page, providerId, runtime.model || provider.default_model || '');
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
    const authMode = getSelectedAuthMode();

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
        auth_mode: authMode,
        oauth_provider: page._modalPresetState?.oauth_provider || existing.oauth_provider || '',
        oauth_source: page._modalPresetState?.oauth_source || existing.oauth_source || '',
        oauth_binding: page._modalPresetState?.oauth_binding ? deepClone(page._modalPresetState.oauth_binding) : (existing.oauth_binding || null),
        oauth_experimental_ack: !!page._modalPresetState?.oauth_experimental_ack,
        oauth_project_id: String(getField('edit-preset-oauth-project-id')?.value || '').trim(),
        oauth_location: String(getField('edit-preset-oauth-location')?.value || '').trim(),
        allow_empty_key: !!provider.allow_empty_key,
    };
    const runtime = resolvePresetRuntimeSelection(provider, nextPreset);
    nextPreset.base_url = runtime.base_url || nextPreset.base_url || '';
    nextPreset.model = runtime.model || nextPreset.model || '';
    nextPreset.oauth_provider = runtime.oauth_provider || nextPreset.oauth_provider || '';

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
