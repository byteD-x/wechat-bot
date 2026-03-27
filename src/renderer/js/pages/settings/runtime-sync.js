import { apiService } from '../../services/ApiService.js';
import { toast } from '../../services/NotificationService.js';
import { deepClone } from './form-codec.js';
import { formatEmailVisibilityText, loadEmailVisibilityPreference } from '../model-auth-display.js';

const UPDATER_STATE_PATHS = [
    'updater.enabled',
    'updater.checking',
    'updater.available',
    'updater.currentVersion',
    'updater.latestVersion',
    'updater.lastCheckedAt',
    'updater.releaseDate',
    'updater.error',
    'updater.skippedVersion',
    'updater.downloading',
    'updater.downloadProgress',
    'updater.readyToInstall',
    'updater.downloadedVersion',
];

function mergePresetLiveFields(localPreset = {}, livePreset = null) {
    if (!livePreset || typeof livePreset !== 'object') {
        return { ...localPreset };
    }
    return {
        ...localPreset,
        ...livePreset,
        api_key: localPreset.api_key,
        _keep_key: localPreset._keep_key,
    };
}

function mergeConfigWithLiveStatus(localConfigResult = {}, liveConfigResult = {}) {
    const nextApi = deepClone(localConfigResult.api || {});
    const liveApi = deepClone(liveConfigResult.api || {});
    const livePresetMap = new Map(
        (liveApi.presets || []).map((preset) => [String(preset?.name || '').trim(), preset]),
    );
    nextApi.presets = (nextApi.presets || []).map((preset) => {
        const presetName = String(preset?.name || '').trim();
        return mergePresetLiveFields(preset, livePresetMap.get(presetName) || null);
    });
    return {
        ...localConfigResult,
        api: {
            ...nextApi,
            auth_mode: liveApi.auth_mode || nextApi.auth_mode,
            oauth_provider: liveApi.oauth_provider || nextApi.oauth_provider,
        },
        local_auth_sync: liveConfigResult.local_auth_sync || localConfigResult.local_auth_sync || null,
        oauth: liveConfigResult.oauth || localConfigResult.oauth || null,
    };
}

function normalizeLocalAuthSyncState(result = {}) {
    const payload = result?.local_auth_sync || {};
    return {
        refreshing: Boolean(payload?.refreshing),
        refreshed_at: Number(payload?.refreshed_at || 0),
        revision: Number(payload?.revision || 0),
        changed_provider_ids: Array.isArray(payload?.changed_provider_ids) ? payload.changed_provider_ids : [],
        message: String(payload?.message || '').trim(),
    };
}

export function clearPendingLocalAuthSyncRefresh(page) {
    if (page?._localAuthSyncRefreshTimer) {
        clearTimeout(page._localAuthSyncRefreshTimer);
        page._localAuthSyncRefreshTimer = null;
    }
    if (page) {
        page._localAuthSyncRefreshAttempt = 0;
    }
}

function scheduleLocalAuthSyncRefresh(page) {
    const syncState = page?._localAuthSyncState || {};
    if (!syncState.refreshing || !page?.isActive?.()) {
        clearPendingLocalAuthSyncRefresh(page);
        return;
    }
    if (page._localAuthSyncRefreshTimer) {
        return;
    }
    const delayMs = Math.min(4000, 600 + (Number(page._localAuthSyncRefreshAttempt || 0) * 600));
    page._localAuthSyncRefreshAttempt = Number(page._localAuthSyncRefreshAttempt || 0) + 1;
    page._localAuthSyncRefreshTimer = setTimeout(() => {
        page._localAuthSyncRefreshTimer = null;
        if (!page.isActive() || page._isSaving) {
            return;
        }
        void page.loadSettings({ silent: true, preserveFeedback: true });
    }, delayMs);
}

export function buildModelSummaryView(modelAuthOverview = null, config = null) {
    const emailVisibilityMode = loadEmailVisibilityPreference();
    const cards = Array.isArray(modelAuthOverview?.cards) ? modelAuthOverview.cards : [];
    const activeProviderId = String(modelAuthOverview?.active_provider_id || '').trim();
    const activeCard = cards.find((card) => String(card?.provider?.id || '').trim() === activeProviderId)
        || cards.find((card) => card?.metadata?.is_active_provider)
        || cards.find((card) => String(card?.selected_label || '').trim())
        || cards[0]
        || null;
    if (activeCard) {
        const providerLabel = String(activeCard?.provider?.label || activeCard?.provider?.id || '当前服务方').trim();
        const modelName = String(activeCard?.metadata?.default_model || activeCard?.provider?.default_model || '--').trim() || '--';
        const authLabel = formatEmailVisibilityText(
            String(activeCard?.selected_label || activeCard?.selected_method_id || '未设置默认认证').trim(),
            emailVisibilityMode,
        );
        const status = String(activeCard?.summary || activeCard?.detail || '状态待同步').trim() || '状态待同步';
        return {
            title: `${providerLabel} · ${modelName}`,
            meta: `${authLabel} · ${status}`,
        };
    }

    const activeName = String(config?.api?.active_preset || '').trim();
    const preset = (config?.api?.presets || []).find((item) => String(item?.name || '').trim() === activeName) || null;
    if (!preset) {
        return {
            title: '尚未配置回复模型',
            meta: '模型配置已迁移到“模型”页；配置中心不再承载模型编辑入口。',
        };
    }
    const providerLabel = preset?.provider_id || '未命名服务方';
    const authMode = preset?.auth_mode === 'oauth' ? 'OAuth' : 'API Key';
    const status = String(preset?.auth_status_summary || '').trim() || '待完善';
    return {
        title: `${activeName} · ${preset?.model || '--'}`,
        meta: `${providerLabel} · ${authMode} · ${status}`,
    };
}

function renderModelSummary(page) {
    const title = page.$('#settings-model-summary-title');
    const meta = page.$('#settings-model-summary-meta');
    const button = page.$('#btn-open-models');
    if (!title || !meta) {
        return;
    }
    const summary = buildModelSummaryView(page._modelAuthOverview, page._config);
    title.textContent = summary.title;
    meta.textContent = summary.meta;
    if (button) {
        button.disabled = false;
    }
}

export function watchConfigChanges(page) {
    if (!window.electronAPI?.onConfigChanged || page._removeConfigListener) {
        return;
    }
    const subscription = window.electronAPI.configSubscribe?.();
    if (subscription?.catch) {
        subscription.catch(() => {});
    }
    page._removeConfigListener = window.electronAPI.onConfigChanged(() => {
        if (page._isSaving) {
            return;
        }
        if (!page.isActive()) {
            page._pendingConfigReload = true;
            return;
        }
        void page.loadSettings({ silent: true, preserveFeedback: true });
    });
}

export function scheduleAutoSave(page, options = {}) {
    if (!page._loaded) {
        return;
    }
    const { immediate = false } = options;
    if (page._autoSaveTimer) {
        clearTimeout(page._autoSaveTimer);
        page._autoSaveTimer = null;
    }
    const trigger = () => {
        page._autoSaveTimer = null;
        void page._saveSettings({ silentToast: true });
    };
    if (immediate) {
        trigger();
        return;
    }
    page._renderSaveFeedback({ success: true, save_state: 'saving' });
    page._autoSaveTimer = setTimeout(trigger, 700);
}

export function watchUpdatePanelState(page, render = () => page._renderUpdatePanel?.()) {
    UPDATER_STATE_PATHS.forEach((path) => {
        page.watchState(path, () => {
            if (page.isActive()) {
                render();
            }
        });
    });
}

export function watchUpdaterState(page) {
    watchUpdatePanelState(page);
    page.watchState('bot.status', () => {
        if (page.isActive()) {
            page._renderHero();
        }
        page._maybeRefreshForRuntimeConfigChange();
    });
    page.watchState('bot.connected', () => {
        if (!page._loaded) {
            if (page.isActive()) {
                page._renderHero();
            }
            return;
        }
        if (!page.getState('bot.connected')) {
            page._auditRequestId += 1;
            page._auditPromise = null;
            page._configAudit = null;
            page._auditStatus = 'offline';
            page._auditMessage = '';
            if (page.isActive()) {
                page._renderHero();
            }
            return;
        }
        if (page.isActive()) {
            page._renderHero();
        }
        if (page._shouldRefreshAudit()) {
            void page._loadConfigAudit({ silent: true });
        }
    });
}

export async function loadSettings(page, options = {}, text = {}) {
    if (page._loadingPromise) {
        return page._loadingPromise;
    }

    const { silent = true, preserveFeedback = false } = options;
    const hero = page.$('#current-config-hero');
    if (hero && !page._loaded) {
        hero.innerHTML = `<div class="config-hero-card" style="opacity:0.7;"><div class="hero-content"><div class="hero-title"><span class="hero-name">${text.loading}</span></div></div></div>`;
    }

    page._loadingPromise = (async () => {
        try {
            const configResult = window.electronAPI?.configGet
                ? await window.electronAPI.configGet()
                : await apiService.getConfig();
            let mergedResult = configResult;
            try {
                const liveConfigResult = await apiService.getConfig();
                if (liveConfigResult?.success) {
                    mergedResult = mergeConfigWithLiveStatus(configResult, liveConfigResult);
                }
            } catch (_) {}
            if (!mergedResult?.success) {
                throw new Error(mergedResult?.message || text.loadFailed);
            }

            page._config = {
                api: deepClone(mergedResult.api || {}),
                bot: deepClone(mergedResult.bot || {}),
                logging: deepClone(mergedResult.logging || {}),
                agent: deepClone(mergedResult.agent || {}),
                services: deepClone(mergedResult.services || {}),
            };
            page._localAuthSyncState = normalizeLocalAuthSyncState(mergedResult);
            const modelCatalog = deepClone(mergedResult.modelCatalog || page._modelCatalog || { providers: [] });
            if (!Array.isArray(modelCatalog.providers)) {
                modelCatalog.providers = [];
            }
            page._modelCatalog = modelCatalog;
            page._providersById = new Map(
                modelCatalog.providers
                    .map((provider) => [String(provider?.id || '').trim(), provider])
                    .filter(([providerId]) => providerId),
            );
            const runtimeVersion = Number(page.getState('bot.status.config_snapshot.version') || 0);
            if (!page.getState('bot.connected')) {
                page._configAudit = null;
                page._auditStatus = 'offline';
                page._auditMessage = '';
            } else if (!page._configAudit) {
                page._auditStatus = 'idle';
                page._auditMessage = '';
            }
            page._lastConfigVersion = Number(page._configAudit?.version || runtimeVersion || 0);

            page._fillForm();
            page._renderHero();
            page._renderUpdatePanel?.();
            page._renderExportRagStatus();
            page._commitSettingsBaseline?.();
            if (!preserveFeedback) {
                page._hideSaveFeedback();
            }
            page._pendingConfigReload = false;
            page._loaded = true;
            page._resetDirtyState?.();
            if (page._shouldRefreshAudit() || !silent) {
                void page._loadConfigAudit({ silent: true, force: !silent });
            }
            scheduleLocalAuthSyncRefresh(page);
            if (!silent) {
                toast.success('配置已刷新');
            }
        } catch (error) {
            console.error('[SettingsPage] load failed:', error);
            if (!silent) {
                toast.error(toast.getErrorMessage(error, text.loadFailed));
            }
            page._renderLoadError(toast.getErrorMessage(error, text.loadFailed));
            page._renderWorkbenchState?.();
        } finally {
            page._loadingPromise = null;
        }
    })();

    return page._loadingPromise;
}

export function shouldRefreshAudit(page) {
    if (!page._loaded || !page.getState('bot.connected')) {
        return false;
    }
    if (page._auditPromise) {
        return false;
    }
    const runtimeVersion = Number(page.getState('bot.status.config_snapshot.version') || 0);
    const auditVersion = Number(page._configAudit?.version || 0);
    return !page._configAudit
        || page._auditStatus === 'idle'
        || page._auditStatus === 'error'
        || (runtimeVersion > 0 && runtimeVersion > auditVersion);
}

export async function loadConfigAudit(page, options = {}, text = {}) {
    if (!page._config || !page._loaded) {
        return null;
    }
    if (!page.getState('bot.connected')) {
        page._auditRequestId += 1;
        page._auditPromise = null;
        page._auditStatus = 'offline';
        page._auditMessage = '';
        if (page.isActive()) {
            page._renderHero();
        }
        return { success: false, message: text.noAudit };
    }

    const { silent = true, force = false } = options;
    if (page._auditPromise && !force) {
        return page._auditPromise;
    }

    const requestId = ++page._auditRequestId;
    page._auditStatus = 'loading';
    page._auditMessage = '';
    if (page.isActive()) {
        page._renderHero();
    }

    page._auditPromise = (async () => {
        try {
            const result = await apiService.getConfigAudit();
            if (requestId !== page._auditRequestId) {
                return result;
            }
            if (!result?.success) {
                throw new Error(result?.message || text.noAudit);
            }
            page._configAudit = result;
            page._auditStatus = 'ready';
            page._auditMessage = '';
            page._lastConfigVersion = Number(result.version || page._lastConfigVersion || 0);
            if (page.isActive()) {
                page._renderHero();
            }
            return result;
        } catch (error) {
            if (requestId !== page._auditRequestId) {
                return null;
            }
            console.warn('[SettingsPage] audit unavailable:', error);
            page._auditStatus = 'error';
            page._auditMessage = toast.getErrorMessage(error, text.noAudit);
            if (page.isActive()) {
                page._renderHero();
            }
            if (!silent) {
                toast.warning(page._auditMessage);
            }
            return { success: false, message: page._auditMessage };
        } finally {
            if (requestId === page._auditRequestId) {
                page._auditPromise = null;
            }
        }
    })();

    return page._auditPromise;
}

export function maybeRefreshForRuntimeConfigChange(page) {
    if (!page.isActive() || page._loadingPromise || page._isSaving) {
        return;
    }

    const runtimeVersion = Number(page.getState('bot.status.config_snapshot.version') || 0);
    if (!runtimeVersion || runtimeVersion <= page._lastConfigVersion) {
        return;
    }

    page._lastConfigVersion = runtimeVersion;
    void page.loadSettings({ silent: true, preserveFeedback: true });
}
