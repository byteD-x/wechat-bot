import { apiService } from '../../services/ApiService.js';
import { toast } from '../../services/NotificationService.js';
import { deepClone } from './form-codec.js';

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

            if (!configResult?.success) {
                throw new Error(configResult?.message || text.loadFailed);
            }

            page._config = {
                api: deepClone(configResult.api || {}),
                bot: deepClone(configResult.bot || {}),
                logging: deepClone(configResult.logging || {}),
                agent: deepClone(configResult.agent || {}),
                services: deepClone(configResult.services || {}),
            };
            page._modelCatalog = configResult?.modelCatalog || { providers: [] };
            page._providersById = new Map(
                (page._modelCatalog.providers || []).map((provider) => [provider.id, provider]),
            );
            page._presetDrafts = deepClone(page._config.api.presets || []);
            page._activePreset = String(page._config.api.active_preset || '').trim();
            void page._warmOllamaModels();
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
            page._renderPresetList();
            page._renderHero();
            page._renderUpdatePanel?.();
            page._renderExportRagStatus();
            if (!preserveFeedback) {
                page._hideSaveFeedback();
            }
            page._loaded = true;
            if (page._shouldRefreshAudit() || !silent) {
                void page._loadConfigAudit({ silent: true, force: !silent });
            }
            if (!silent) {
                toast.success('配置已刷新');
            }
        } catch (error) {
            console.error('[SettingsPage] load failed:', error);
            if (!silent) {
                toast.error(toast.getErrorMessage(error, text.loadFailed));
            }
            page._renderLoadError(toast.getErrorMessage(error, text.loadFailed));
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
