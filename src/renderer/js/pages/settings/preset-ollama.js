import { apiService } from '../../services/ApiService.js';
import {
    getOllamaBaseUrl,
    isOllamaPreset,
} from './preset-meta.js';

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
    (page._apiPresetsSnapshot || page._presetDrafts || [])
        .filter((preset) => isOllamaPreset(preset))
        .forEach((preset) => candidates.add(getOllamaBaseUrl(preset)));
    if (!candidates.size) {
        return;
    }
    await Promise.allSettled([...candidates].map((baseUrl) => loadOllamaModels(page, baseUrl)));
    if (page.isActive()) {
        page._renderHero();
    }
}

export async function resolveProviderModels(page, provider) {
    const fallbackModels = Array.isArray(provider?.models) ? [...provider.models] : [];
    if (String(provider?.id || '').trim().toLowerCase() !== 'ollama') {
        return fallbackModels;
    }
    const liveModels = await loadOllamaModels(page, getOllamaBaseUrl(provider));
    return liveModels.length ? liveModels : fallbackModels;
}
