import { PageController } from '../core/PageController.js';
import { apiService } from '../services/ApiService.js';
import { toast } from '../services/NotificationService.js';
import { resolveProviderModels } from './settings/preset-ollama.js';
import { renderModelsPageShell } from '../app-shell/pages/index.js';
import {
    getEmailVisibilityButtonLabel,
    getSafeStorage,
    loadEmailVisibilityPreference,
    saveEmailVisibilityPreference,
    formatEmailVisibilityText,
    toggleEmailVisibilityMode,
} from './model-auth-display.js';

const READY_STATES = new Set(['connected', 'following_local_auth', 'imported']);
const LOCAL_READY_STATES = new Set(['available_to_import', 'following_local_auth']);
const ATTENTION_STATES = new Set(['expired', 'invalid', 'error']);
const MODAL_FORM_ID = 'model-auth-workflow-form';
const ONBOARDING_STORAGE_KEY = 'model-center:onboarding:v1';

const ACTION_LABELS = {
    bind_local_auth: '同步本机登录',
    complete_browser_auth: '我已登录，继续',
    disconnect_profile: '移除当前认证',
    import_local_auth_copy: '导入认证副本',
    logout_source: '退出本机登录',
    refresh_status: '重新检查',
    set_active_provider: '设为当前回复模型',
    set_default_profile: '设为默认认证',
    show_api_key_form: '配置 API Key',
    show_session_form: '导入会话',
    start_browser_auth: '前往登录页',
    test_profile: '测试连接',
};

const STATE_LABELS = {
    available_to_import: '可同步',
    connected: '已连接',
    connecting: '待完成',
    error: '异常',
    expired: '已过期',
    following_local_auth: '已跟随',
    imported: '已导入',
    invalid: '无效',
    not_configured: '未配置',
};

const FILTER_OPTIONS = [
    { value: 'all', label: '全部' },
    { value: 'ready', label: '可用' },
    { value: 'attention', label: '待处理' },
    { value: 'local', label: '可同步' },
];

const EXTRA_FIELD_META = {
    oauth_project_id: {
        label: '项目 ID',
        placeholder: '例如 my-gcp-project',
    },
    oauth_location: {
        label: '地区',
        placeholder: '例如 us-central1',
    },
};

const MODEL_CENTER_MESSAGE_LOCALIZATIONS = new Map([
    [
        'A local auth source was detected, but it cannot be projected into runtime requests yet',
        '已检测到本机认证来源，但暂时还不能直接用于运行时请求。',
    ],
    [
        'Local authorization detected but not yet bound',
        '已检测到本机授权，但尚未完成绑定。',
    ],
    [
        'Detected local authorization source',
        '已检测到本机授权来源。',
    ],
    [
        'Imported auth copy ready',
        '已就绪，可直接使用导入的认证副本。',
    ],
    [
        'OAuth ready',
        'OAuth 已就绪。',
    ],
    [
        'Awaiting experimental-risk acknowledgment',
        '等待确认实验性能力提示。',
    ],
    [
        'OAuth authorization required',
        '需要先完成 OAuth 授权。',
    ],
    [
        'API Key ready',
        'API Key 已就绪。',
    ],
    [
        'API Key required',
        '需要填写 API Key。',
    ],
]);

const ONBOARDING_CONTENT = {
    api_key: {
        kicker: 'API Key',
        title: '填入 API Key',
        subtitle: '有 Key 就用这个。',
        points: [
            { title: '1. 粘贴 Key', text: '填进去就行。' },
            { title: '2. 保存', text: '保存后就能用。' },
        ],
        confirmLabel: '去填写',
    },
    browser_auth: {
        kicker: '网页登录',
        title: '去网页登录',
        subtitle: '登录后回来继续。',
        points: [
            { title: '1. 打开登录页', text: '先在官网完成登录。' },
            { title: '2. 回来继续', text: '再点“我已登录，继续”。' },
        ],
        confirmLabel: '去登录',
    },
    local_auth: {
        kicker: '本机同步',
        title: '同步这台电脑上的账号',
        subtitle: '这台电脑登过就优先用这个。',
        points: [
            { title: '直接同步', text: '少填一步。' },
            { title: '导入副本', text: '需要独立凭据时再用。' },
        ],
        confirmLabel: '去同步',
    },
    session_import: {
        kicker: '会话导入',
        title: '导入现有会话',
        subtitle: '粘贴后就能用。',
        points: [
            { title: '支持内容', text: 'Cookie、Session、Header。' },
            { title: '会话过期', text: '过期后再更新。' },
        ],
        confirmLabel: '去导入',
    },
};

function escapeHtml(value) {
    return String(value ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
}

function buildDatasetAttributes(payload = {}) {
    return Object.entries(payload)
        .map(([key, value]) => `${key}="${escapeHtml(value)}"`)
        .join(' ');
}

function parseSessionPayload(rawValue) {
    const raw = String(rawValue || '').trim();
    if (!raw) {
        return '';
    }
    if ((raw.startsWith('{') && raw.endsWith('}')) || (raw.startsWith('[') && raw.endsWith(']'))) {
        try {
            return JSON.parse(raw);
        } catch (_error) {
            return raw;
        }
    }
    return raw;
}

function localizeModelCenterMessage(message) {
    const raw = String(message || '').trim();
    if (!raw) {
        return '';
    }
    const normalized = raw.replace(/[.。]+$/, '').trim();
    const localized = MODEL_CENTER_MESSAGE_LOCALIZATIONS.get(normalized);
    if (localized) {
        return localized;
    }
    const missingFieldsMatch = normalized.match(/^Missing fields:\s*(.+)$/i);
    if (missingFieldsMatch) {
        return `缺少字段：${missingFieldsMatch[1].trim()}`;
    }
    return raw;
}

export function parseCallbackPayload(rawValue) {
    const raw = String(rawValue || '').trim();
    if (!raw) {
        return {};
    }
    if ((raw.startsWith('{') && raw.endsWith('}')) || (raw.startsWith('[') && raw.endsWith(']'))) {
        try {
            const parsed = JSON.parse(raw);
            if (parsed && typeof parsed === 'object') {
                return parsed;
            }
        } catch (_error) {
            return { raw_payload: raw };
        }
    }
    return { raw_payload: raw };
}

export function summarizeCards(cards = []) {
    const summary = {
        connected: 0,
        localReady: 0,
        attention: 0,
    };
    cards.forEach((card) => {
        const state = String(card?.state || '');
        if (READY_STATES.has(state)) {
            summary.connected += 1;
        }
        if (LOCAL_READY_STATES.has(state)) {
            summary.localReady += 1;
        }
        if (ATTENTION_STATES.has(state)) {
            summary.attention += 1;
        }
    });
    return summary;
}

export function resolveCardViewMode(card = {}) {
    return card?.metadata?.can_set_active_provider ? 'workbench' : 'wizard';
}

export function getLocalizedActionLabel(actionId) {
    return ACTION_LABELS[String(actionId || '').trim()] || String(actionId || '').trim();
}

function loadOnboardingState() {
    const storage = getSafeStorage();
    if (!storage) {
        return {
            api_key: false,
            browser_auth: false,
            local_auth: false,
            session_import: false,
        };
    }
    try {
        const raw = storage.getItem(ONBOARDING_STORAGE_KEY);
        const parsed = raw ? JSON.parse(raw) : {};
        return {
            api_key: !!parsed?.api_key,
            browser_auth: !!parsed?.browser_auth,
            local_auth: !!parsed?.local_auth,
            session_import: !!parsed?.session_import,
        };
    } catch (_error) {
        return {
            api_key: false,
            browser_auth: false,
            local_auth: false,
            session_import: false,
        };
    }
}

function saveOnboardingState(state) {
    const storage = getSafeStorage();
    if (!storage) {
        return;
    }
    try {
        storage.setItem(ONBOARDING_STORAGE_KEY, JSON.stringify(state));
    } catch (_error) {
        // Ignore persistence failures in renderer.
    }
}

function formatTimestamp(timestampSec) {
    const value = Number(timestampSec || 0);
    if (!value) {
        return '';
    }
    return new Date(value * 1000).toLocaleString();
}

function getStateLabel(status) {
    return STATE_LABELS[String(status || '').trim()] || '未配置';
}

function getStateTone(status) {
    const key = String(status || '').trim();
    if (READY_STATES.has(key)) {
        return 'ready';
    }
    if (LOCAL_READY_STATES.has(key)) {
        return 'local';
    }
    if (ATTENTION_STATES.has(key)) {
        return 'attention';
    }
    if (key === 'connecting') {
        return 'progress';
    }
    return 'neutral';
}

function resolveCardPriority(card) {
    if (card?.metadata?.is_active_provider) {
        return 0;
    }
    if (hasReady(card)) {
        return 1;
    }
    if (hasLocalReady(card)) {
        return 2;
    }
    if (hasAttention(card)) {
        return 3;
    }
    return 4;
}

function getProviderSortLabel(card = {}) {
    const provider = card?.provider || {};
    return String(provider?.label || provider?.id || '').trim().toLowerCase();
}

function compareCardsForDisplay(left = {}, right = {}) {
    const priorityDelta = resolveCardPriority(left) - resolveCardPriority(right);
    if (priorityDelta !== 0) {
        return priorityDelta;
    }

    const labelDelta = getProviderSortLabel(left).localeCompare(getProviderSortLabel(right), 'zh-Hans-CN');
    if (labelDelta !== 0) {
        return labelDelta;
    }

    return String(left?.provider?.id || '').localeCompare(String(right?.provider?.id || ''), 'zh-Hans-CN');
}

export function sortCardsForDisplay(cards = []) {
    return [...cards]
        .map((card, index) => ({ card, index }))
        .sort((left, right) => {
            const rank = compareCardsForDisplay(left.card, right.card);
            if (rank !== 0) {
                return rank;
            }
            return left.index - right.index;
        })
        .map((entry) => entry.card);
}

function pickDefaultProvider(cards = []) {
    return sortCardsForDisplay(cards)[0] || null;
}

function hasAttention(card) {
    if (ATTENTION_STATES.has(String(card?.state || ''))) {
        return true;
    }
    return (card?.auth_states || []).some((state) => ATTENTION_STATES.has(String(state?.status || '')));
}

function hasLocalReady(card) {
    if (LOCAL_READY_STATES.has(String(card?.state || ''))) {
        return true;
    }
    return (card?.auth_states || []).some((state) => LOCAL_READY_STATES.has(String(state?.status || '')));
}

function hasReady(card) {
    if (card?.metadata?.can_set_active_provider) {
        return true;
    }
    if (READY_STATES.has(String(card?.state || ''))) {
        return true;
    }
    return (card?.auth_states || []).some((state) => READY_STATES.has(String(state?.status || '')));
}

function normalizeStateActions(state = {}) {
    const actions = Array.isArray(state?.actions) ? state.actions : [];
    if (actions.length) {
        return actions.map((action) => ({
            ...action,
            label: action?.label || getLocalizedActionLabel(action?.id),
        }));
    }
    return (state?.available_actions || []).map((actionId) => ({
        id: actionId,
        kind: actionId === 'refresh_status' ? 'refresh' : 'invoke',
        label: getLocalizedActionLabel(actionId),
    }));
}

function getMethodType(method = {}) {
    const type = String(method?.type || '').trim().toLowerCase();
    if (type) {
        return type;
    }
    const id = String(method?.id || '').trim().toLowerCase();
    if (id.includes('api_key')) {
        return 'api_key';
    }
    if (id.includes('session')) {
        return 'web_session';
    }
    if (id.includes('oauth')) {
        return 'oauth';
    }
    return 'local_import';
}

function getWorkflowTypeForMethod(method = {}) {
    const type = getMethodType(method);
    if (type === 'api_key') {
        return 'api_key';
    }
    if (type === 'web_session') {
        return 'session';
    }
    if (type === 'oauth') {
        return 'browser';
    }
    return 'local';
}

const ACTION_WORKFLOW_KIND = {
    bind_local_auth: 'local',
    complete_browser_auth: 'browser',
    import_local_auth_copy: 'local',
    show_api_key_form: 'api_key',
    show_session_form: 'session',
    start_browser_auth: 'browser',
};

const WORKFLOW_ENTRY_ACTION_IDS = new Set(Object.keys(ACTION_WORKFLOW_KIND));

const WORKFLOW_ENTRY_ACTION_ORDER = {
    complete_browser_auth: 10,
    show_api_key_form: 20,
    bind_local_auth: 30,
    show_session_form: 40,
    start_browser_auth: 50,
    import_local_auth_copy: 60,
};

export function getActionWorkflowKind(actionId, method = {}) {
    const wanted = String(actionId || '').trim();
    return ACTION_WORKFLOW_KIND[wanted] || getWorkflowTypeForMethod(method);
}

function isWorkflowEntryAction(actionId) {
    return WORKFLOW_ENTRY_ACTION_IDS.has(String(actionId || '').trim());
}

function compareWorkflowEntryActions(left = {}, right = {}) {
    const leftId = String(left?.id || '').trim();
    const rightId = String(right?.id || '').trim();
    const leftOrder = WORKFLOW_ENTRY_ACTION_ORDER[leftId] ?? 999;
    const rightOrder = WORKFLOW_ENTRY_ACTION_ORDER[rightId] ?? 999;
    if (leftOrder !== rightOrder) {
        return leftOrder - rightOrder;
    }
    return leftId.localeCompare(rightId);
}

function getOnboardingTypeForWorkflow(workflow = {}) {
    if (workflow.kind === 'api_key') {
        return 'api_key';
    }
    if (workflow.kind === 'session') {
        return 'session_import';
    }
    if (workflow.kind === 'browser') {
        return 'browser_auth';
    }
    if (workflow.kind === 'local') {
        return 'local_auth';
    }
    return '';
}

function getMethodHint(method = {}, state = {}) {
    const type = getMethodType(method);
    state = {
        ...state,
        profile_id: state?.metadata?.profile_id || state?.profile_id || '',
    };
    if (type === 'api_key') {
        return state?.profile_id ? '已保存' : '手动填写';
    }
    if (type === 'web_session') {
        if (LOCAL_READY_STATES.has(String(state?.status || ''))) {
            return '检测到本机会话';
        }
        return '登录后导入';
    }
    if (type === 'oauth') {
        if (String(state?.status || '') === 'connecting') {
            return '等你完成登录';
        }
        if (LOCAL_READY_STATES.has(String(state?.status || ''))) {
            return '检测到本机登录';
        }
        return '去网页登录';
    }
    if (LOCAL_READY_STATES.has(String(state?.status || ''))) {
        return '检测到本机登录';
    }
    return '同步本机账号';
}

function getProviderListSubtitle(card = {}) {
    const selectedLabel = String(card?.selected_label || '').trim();
    if (selectedLabel) {
        return `${selectedLabel} · ${getStateLabel(card?.state)}`;
    }
    return getStateLabel(card?.state);
}

function shouldOpenQuickActions(card = {}) {
    return !!card?.metadata?.is_active_provider || !!card?.metadata?.can_set_active_provider;
}

function shouldOpenAuthSection(card = {}) {
    return !card?.metadata?.can_set_active_provider || hasAttention(card);
}

function shouldOpenRuntimeSection(card = {}) {
    const syncCode = String(card?.metadata?.provider_sync?.code || '').trim();
    const healthCode = String(card?.metadata?.provider_health?.code || '').trim();
    return ['warning', 'attention', 'blocked'].includes(healthCode)
        || ['error', 'unsupported'].includes(syncCode);
}

function renderBadge(text, tone = 'neutral', extraClass = '') {
    const classes = ['model-center-badge', `tone-${tone}`];
    if (extraClass) {
        classes.push(extraClass);
    }
    return `<span class="${classes.join(' ')}">${escapeHtml(text)}</span>`;
}

function renderLinkChips(links = []) {
    const items = links.filter((item) => item?.label && item?.url);
    if (!items.length) {
        return '';
    }
    return `
        <div class="model-center-link-row">
            ${items.map((item) => `
                <a class="models-chip model-center-link-chip" href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer">
                    ${escapeHtml(item.label)}
                </a>
            `).join('')}
        </div>
    `;
}

function renderWorkflowCard(point = {}) {
    return `
        <article class="model-center-tip-card">
            <div class="model-center-tip-title">${escapeHtml(point.title || '')}</div>
            <div class="model-center-tip-text">${escapeHtml(point.text || '')}</div>
        </article>
    `;
}

function renderAdvancedInfoBlock(title, items = []) {
    const lines = (Array.isArray(items) ? items : [items])
        .map((item) => String(item || '').trim())
        .filter(Boolean);
    if (!lines.length) {
        return '';
    }
    return `
        <div class="model-center-advanced-note">
            <strong>${escapeHtml(title)}</strong>
            <div>
                ${lines.map((item) => `<div>${escapeHtml(item)}</div>`).join('')}
            </div>
        </div>
    `;
}

function getSelectedRuntimeState(card = {}) {
    const states = Array.isArray(card?.auth_states) ? card.auth_states : [];
    return states.find((state) => state?.default_selected)
        || states.find((state) => String(state?.method_id || '').trim() === String(card?.selected_method_id || '').trim())
        || states[0]
        || null;
}

function getAccountDisplayValue(state = {}, method = {}) {
    return String(
        state?.account_email
        || state?.account_label
        || state?.metadata?.account_email
        || method?.label
        || '',
    ).trim();
}

function getGroupedStateRank(state = {}) {
    if (state?.default_selected) {
        return 0;
    }
    const status = String(state?.status || '').trim();
    if (READY_STATES.has(status)) {
        return 1;
    }
    if (LOCAL_READY_STATES.has(status)) {
        return 2;
    }
    if (status === 'connecting') {
        return 3;
    }
    if (ATTENTION_STATES.has(status)) {
        return 4;
    }
    return 5;
}

function getNormalizedSourceGroup(state = {}, method = {}, index = 0) {
    const metadata = state?.metadata?.source_group || {};
    const sharedAuthProviderId = String(
        metadata?.shared_auth_provider_id
        || method?.auth_provider_id
        || method?.id
        || state?.method_id
        || '',
    ).trim();
    const rawAccountKey = String(
        metadata?.account_key
        || state?.account_email
        || state?.metadata?.account_email
        || state?.metadata?.profile_id
        || state?.profile_id
        || `slot-${index}`
    ).trim();
    const accountKey = rawAccountKey.toLowerCase();
    const id = String(metadata?.id || `${sharedAuthProviderId || method?.id || state?.method_id || 'auth'}:${accountKey}`).trim();
    return {
        id,
        label: String(metadata?.label || method?.label || state?.method_id || '').trim(),
        kind: String(metadata?.kind || (metadata?.shared_auth_provider_id ? 'shared_auth_provider' : 'auth_method')).trim(),
        shared_auth_provider_id: String(metadata?.shared_auth_provider_id || sharedAuthProviderId).trim(),
        account_key: accountKey,
    };
}

function getCurrentModel(card = {}, provider = {}) {
    const runtimeModel = String(getSelectedRuntimeState(card)?.metadata?.model || '').trim();
    return runtimeModel || String(card?.metadata?.default_model || provider?.default_model || '').trim();
}

function getCurrentBaseUrl(card = {}, provider = {}) {
    const runtimeBaseUrl = String(getSelectedRuntimeState(card)?.metadata?.base_url || '').trim();
    return runtimeBaseUrl || String(card?.metadata?.default_base_url || provider?.default_base_url || '').trim();
}

function normalizeRuntimeBaseUrl(value) {
    return String(value || '')
        .trim()
        .replace(/\/(chat\/completions|responses|messages)$/i, '');
}

function getCurrentProfileLabel(card = {}, state = {}, method = {}) {
    return String(card?.selected_label || state?.account_email || state?.account_label || method?.label || '').trim();
}

function canStateTestConnection(state = {}) {
    const profileId = String(state?.metadata?.profile_id || '').trim();
    if (!profileId) {
        return false;
    }
    return normalizeStateActions(state).some((action) => action?.id === 'test_profile')
        || state?.metadata?.runtime_ready !== false;
}

function getLegacyPresetTestTarget(card = {}) {
    if (!card?.metadata?.is_active_provider) {
        return null;
    }
    return {
        kind: 'preset',
        providerId: String(card?.provider?.id || '').trim(),
        presetName: String(card?.metadata?.legacy_preset_name || '').trim(),
    };
}

export function groupAuthStates(card = {}, provider = {}) {
    const methodMap = new Map((provider?.auth_methods || []).map((item) => [String(item?.id || ''), item]));
    const groups = [];
    const groupsById = new Map();
    const authStates = Array.isArray(card?.auth_states) ? card.auth_states : [];

    authStates.forEach((state, index) => {
        const method = methodMap.get(String(state?.method_id || '')) || {};
        const sourceGroup = getNormalizedSourceGroup(state, method, index);
        if (!groupsById.has(sourceGroup.id)) {
            const bucket = {
                sourceGroup,
                states: [],
                methods: new Map(),
                firstIndex: index,
            };
            groupsById.set(sourceGroup.id, bucket);
            groups.push(bucket);
        }
        const bucket = groupsById.get(sourceGroup.id);
        bucket.states.push(state);
        if (method?.id) {
            bucket.methods.set(String(method.id), method);
        }
    });

    return groups.map((bucket) => {
        const rankedStates = [...bucket.states]
            .map((state, index) => ({ state, index }))
            .sort((left, right) => {
                const rankDelta = getGroupedStateRank(left.state) - getGroupedStateRank(right.state);
                if (rankDelta !== 0) {
                    return rankDelta;
                }
                return left.index - right.index;
            });
        const primaryState = rankedStates[0]?.state || {};
        const primaryMethod = methodMap.get(String(primaryState?.method_id || ''))
            || bucket.methods.values().next().value
            || {};
        const groupedMethods = Array.from(bucket.methods.values());
        const groupedMethodLabels = Array.from(
            new Set(
                groupedMethods
                    .map((item) => String(item?.label || '').trim())
                    .filter(Boolean),
            ),
        );
        const mergedActions = [];
        const actionIds = new Set();
        rankedStates.forEach(({ state }) => {
            const sourceMethod = methodMap.get(String(state?.method_id || '')) || {};
            normalizeStateActions(state).forEach((action) => {
                const actionId = String(action?.id || '').trim();
                if (!actionId || actionIds.has(actionId)) {
                    return;
                }
                actionIds.add(actionId);
                mergedActions.push({
                    ...action,
                    source_state: state,
                    source_method: sourceMethod,
                });
            });
        });

        return {
            ...primaryState,
            method_id: String(primaryState?.method_id || primaryMethod?.id || '').trim(),
            default_selected: bucket.states.some((state) => !!state?.default_selected),
            source_group: bucket.sourceGroup,
            grouped_states: bucket.states,
            grouped_methods: groupedMethods,
            grouped_method_labels: groupedMethodLabels,
            primary_state: primaryState,
            primary_method: primaryMethod,
            group_label: String(
                bucket.sourceGroup.label
                || groupedMethodLabels[0]
                || primaryMethod?.label
                || primaryState?.method_id
                || ''
            ).trim(),
            account_display: getAccountDisplayValue(primaryState, primaryMethod),
            actions: mergedActions,
            available_actions: mergedActions.map((item) => item.id),
        };
    });
}

function mergeProviderModels(...sources) {
    const values = [];
    sources.forEach((source) => {
        if (!source || typeof source !== 'object') {
            return;
        }
        const directModels = Array.isArray(source.models) ? source.models : [];
        const supportedModels = Array.isArray(source.supported_models) ? source.supported_models : [];
        [...directModels, ...supportedModels].forEach((item) => {
            const normalized = String(item || '').trim();
            if (normalized && !values.includes(normalized)) {
                values.push(normalized);
            }
        });
    });
    return values;
}

function mergeProviderDefinitions(catalogProvider = null, overviewProvider = null) {
    if (!catalogProvider && !overviewProvider) {
        return null;
    }
    const merged = {
        ...(overviewProvider || {}),
        ...(catalogProvider || {}),
        metadata: {
            ...((catalogProvider && catalogProvider.metadata) || {}),
            ...((overviewProvider && overviewProvider.metadata) || {}),
        },
    };
    const overviewMethods = Array.isArray(overviewProvider?.auth_methods) ? overviewProvider.auth_methods : [];
    const catalogMethods = Array.isArray(catalogProvider?.auth_methods) ? catalogProvider.auth_methods : [];
    merged.auth_methods = overviewMethods.length >= catalogMethods.length ? overviewMethods : catalogMethods;
    const mergedModels = mergeProviderModels(catalogProvider, overviewProvider);
    if (mergedModels.length) {
        merged.models = mergedModels;
        merged.supported_models = mergedModels;
    }
    const mergedTags = Array.from(new Set([
        ...((catalogProvider && Array.isArray(catalogProvider.tags)) ? catalogProvider.tags : []),
        ...((overviewProvider && Array.isArray(overviewProvider.tags)) ? overviewProvider.tags : []),
    ].map((item) => String(item || '').trim()).filter(Boolean)));
    if (mergedTags.length) {
        merged.tags = mergedTags;
    }
    return merged;
}

function getModelValueFromFormData(formData) {
    const selected = String(formData.get('default_model_select') || '').trim();
    const custom = String(formData.get('custom_model') || '').trim();
    return selected === '__custom__' ? custom : selected;
}

function getModelStepDescription(card = {}) {
    if (card?.metadata?.is_active_provider) {
        return '保存后立即生效';
    }
    if (card?.metadata?.can_set_active_provider) {
        return '保存后可直接切换';
    }
    return '先选一个默认模型';
}

function getModelApplyLabel(card = {}) {
    if (card?.metadata?.is_active_provider) {
        return '保存并切换当前回复';
    }
    if (card?.metadata?.can_set_active_provider) {
        return '保存并用于回复';
    }
    return '';
}

function getFormBoolean(formData, name) {
    return String(formData.get(name) || '').trim() === 'on';
}

function getFormBooleanWithDefault(formData, name, fallback = true) {
    return formData.get(name) === null ? fallback : getFormBoolean(formData, name);
}

function shouldKeepWorkflowOpen(result) {
    return result?.action_result?.completed === false;
}

export class ModelsPage extends PageController {
    constructor() {
        super('ModelsPage', 'page-models');
        this._overview = null;
        this._modelCatalog = { providers: [] };
        this._providersById = new Map();
        this._providerModelOptions = new Map();
        this._providerModelPromise = new Map();
        this._ollamaModelCache = new Map();
        this._ollamaModelPromise = new Map();
        this._selectedProviderId = '';
        this._searchQuery = '';
        this._listFilter = 'all';
        this._loadingPromise = null;
        this._localAuthSyncRefreshTimer = null;
        this._localAuthSyncRefreshAttempt = 0;
        this._activeWorkflow = null;
        this._onboardingSeen = loadOnboardingState();
        this._emailVisibilityMode = loadEmailVisibilityPreference();
        this._confirmState = {
            resolver: null,
        };
    }

    async onInit() {
        await super.onInit();
        const container = this.container || (typeof document !== 'undefined' ? this.getContainer() : null);
        if (container) {
            container.innerHTML = renderModelsPageShell();
        }
        this.bindEvent('#btn-model-auth-refresh', 'click', () => void this.loadOverview());
        this.bindEvent('#btn-model-auth-scan', 'click', () => void this.runAction('scan', {}, { preserveSelection: true }));
        this.bindEvent('#btn-model-auth-scroll-top', 'click', () => {
            this.getContainer()?.scrollTo?.({ top: 0, behavior: 'smooth' });
        });
        this.bindEvent(this.getContainer(), 'click', (event) => {
            const button = event.target?.closest?.('[data-model-auth-action],[data-model-auth-ui]');
            if (!button) {
                return;
            }
            event.preventDefault();
            void this.handleButtonAction(button);
        });
        this.bindEvent(this.getContainer(), 'submit', (event) => {
            const form = event.target?.closest?.('[data-model-auth-form]');
            if (!form) {
                return;
            }
            event.preventDefault();
            void this.handleFormSubmit(form, event.submitter || null);
        });
        this.bindEvent(this.getContainer(), 'input', (event) => this.handleInputChange(event));
        this.bindEvent(this.getContainer(), 'change', (event) => this.handleFieldChange(event));
        this._bindConfirmModal();
        this._bindWorkflowModal();
    }

    async onEnter() {
        await super.onEnter();
        await this.loadOverview({ preserveSelection: true });
    }

    async onLeave() {
        this._clearPendingOverviewRefresh();
        await super.onLeave();
    }

    async onDestroy() {
        this._clearPendingOverviewRefresh();
        await super.onDestroy();
    }

    _clearPendingOverviewRefresh() {
        if (this._localAuthSyncRefreshTimer) {
            clearTimeout(this._localAuthSyncRefreshTimer);
            this._localAuthSyncRefreshTimer = null;
        }
        this._localAuthSyncRefreshAttempt = 0;
    }

    _schedulePendingOverviewRefresh(overview = null) {
        const syncState = overview?.local_auth_sync || {};
        const isRefreshing = Boolean(syncState?.refreshing);
        if (!isRefreshing || !this.isActive()) {
            this._clearPendingOverviewRefresh();
            return;
        }
        if (this._localAuthSyncRefreshTimer) {
            return;
        }
        const delayMs = Math.min(4000, 600 + (this._localAuthSyncRefreshAttempt * 600));
        this._localAuthSyncRefreshAttempt += 1;
        this._localAuthSyncRefreshTimer = setTimeout(() => {
            this._localAuthSyncRefreshTimer = null;
            if (!this.isActive()) {
                return;
            }
            void this.loadOverview({ preserveSelection: true });
        }, delayMs);
    }

    async loadOverview(options = {}) {
        if (this._loadingPromise) {
            return this._loadingPromise;
        }
        this._loadingPromise = (async () => {
            try {
                const requests = [
                    apiService.getModelAuthOverview(),
                    this._modelCatalog?.providers?.length
                        ? Promise.resolve(null)
                        : apiService.getModelCatalog(),
                ];
                const [overviewResult, catalogResult] = await Promise.allSettled(requests);
                if (overviewResult.status !== 'fulfilled') {
                    throw overviewResult.reason;
                }
                if (catalogResult.status === 'fulfilled' && catalogResult.value?.providers) {
                    this.applyModelCatalog(catalogResult.value);
                }
                const overview = overviewResult.value?.overview || null;
                this.applyOverview(overview, options);
                this._schedulePendingOverviewRefresh(overview);
                await this._ensureProviderModels(this._selectedProviderId);
                if (this.isActive()) {
                    this.render();
                }
            } catch (error) {
                if (!this.isActive()) {
                    return;
                }
                console.error('[ModelsPage] load overview failed:', error);
                toast.error(error?.message || '加载模型中心失败');
                this.renderError(error?.message || '加载模型中心失败');
            } finally {
                this._loadingPromise = null;
            }
        })();
        return this._loadingPromise;
    }

    applyModelCatalog(result) {
        this._modelCatalog = result || { providers: [] };
        this._providersById = new Map(
            (this._modelCatalog?.providers || [])
                .filter((item) => item?.id)
                .map((item) => [String(item.id), item]),
        );
    }

    applyOverview(overview, options = {}) {
        this._overview = overview || { cards: [], active_provider_id: '' };
        const cards = Array.isArray(this._overview.cards) ? this._overview.cards : [];
        const wanted = options.preserveSelection ? this._selectedProviderId : '';
        const hasWanted = cards.some((card) => String(card?.provider?.id || '') === wanted);
        if (hasWanted) {
            this._selectedProviderId = wanted;
            return;
        }
        const picked = pickDefaultProvider(cards);
        this._selectedProviderId = String(picked?.provider?.id || '');
    }

    getCards() {
        return Array.isArray(this._overview?.cards) ? this._overview.cards : [];
    }

    getCardByProviderId(providerId) {
        const wanted = String(providerId || '').trim();
        return this.getCards().find((card) => String(card?.provider?.id || '').trim() === wanted) || null;
    }

    getSelectedCard(cards = this.getCards()) {
        const wanted = String(this._selectedProviderId || '').trim();
        return cards.find((card) => String(card?.provider?.id || '').trim() === wanted) || null;
    }

    getProvider(providerId, fallback = null) {
        const wanted = String(providerId || '').trim();
        return mergeProviderDefinitions(
            this._providersById.get(wanted) || null,
            fallback,
        );
    }

    async _ensureProviderModels(providerId) {
        const wanted = String(providerId || '').trim();
        if (!wanted) {
            return [];
        }
        if (this._providerModelOptions.has(wanted)) {
            return this._providerModelOptions.get(wanted);
        }
        if (this._providerModelPromise.has(wanted)) {
            return this._providerModelPromise.get(wanted);
        }
        const provider = this.getProvider(wanted, this.getCardByProviderId(wanted)?.provider || null);
        const promise = (async () => {
            try {
                const options = Array.from(
                    new Set(
                        (await resolveProviderModels(this, provider))
                            .map((item) => String(item || '').trim())
                            .filter(Boolean),
                    ),
                );
                this._providerModelOptions.set(wanted, options);
                return options;
            } catch (error) {
                console.warn('[ModelsPage] resolve provider models failed:', wanted, error);
                const fallback = Array.from(new Set((provider?.models || []).map((item) => String(item || '').trim()).filter(Boolean)));
                this._providerModelOptions.set(wanted, fallback);
                return fallback;
            } finally {
                this._providerModelPromise.delete(wanted);
            }
        })();
        this._providerModelPromise.set(wanted, promise);
        return promise;
    }

    getProviderModelOptions(providerId, currentModel = '') {
        const provider = this.getProvider(providerId, this.getCardByProviderId(providerId)?.provider || null);
        const fallback = Array.isArray(provider?.models) ? provider.models : [];
        return Array.from(
            new Set([
                ...fallback.map((item) => String(item || '').trim()).filter(Boolean),
                ...(this._providerModelOptions.get(String(providerId || '').trim()) || []),
                String(currentModel || '').trim(),
                String(provider?.default_model || '').trim(),
            ].filter(Boolean)),
        );
    }

    getSelectedAuthState(card = {}) {
        return getSelectedRuntimeState(card);
    }

    getTestableAuthState(card = {}, preferredState = null) {
        const selectedState = preferredState || this.getSelectedAuthState(card);
        if (canStateTestConnection(selectedState)) {
            return selectedState;
        }
        const states = Array.isArray(card?.auth_states) ? card.auth_states : [];
        return states.find((state) => canStateTestConnection(state)) || null;
    }

    getCurrentConnectionTestTarget(card = {}, preferredState = null) {
        const testState = this.getTestableAuthState(card, preferredState);
        if (testState) {
            return {
                kind: 'profile',
                providerId: String(card?.provider?.id || '').trim(),
                methodId: String(testState?.method_id || '').trim(),
                profileId: String(testState?.metadata?.profile_id || '').trim(),
            };
        }
        return getLegacyPresetTestTarget(card);
    }

    renderCurrentConnectionTestButton(card = {}, label = '测试连接', className = 'btn btn-secondary btn-sm', preferredState = null) {
        const target = this.getCurrentConnectionTestTarget(card, preferredState);
        if (!target) {
            return '';
        }
        return `
            <button
                type="button"
                class="${className}"
                data-model-auth-ui="test_current_connection"
                data-provider-id="${escapeHtml(target.providerId || '')}"
            >
                ${escapeHtml(label)}
            </button>
        `;
    }

    getMethodMap(provider = {}) {
        return new Map((provider?.auth_methods || []).map((item) => [String(item.id || ''), item]));
    }

    getVisibleCards(cards = this.getCards()) {
        const query = String(this._searchQuery || '').trim().toLowerCase();
        return sortCardsForDisplay(cards.filter((card) => {
            const provider = card?.provider || {};
            const matchesQuery = !query
                || String(provider.label || '').toLowerCase().includes(query)
                || String(provider.id || '').toLowerCase().includes(query)
                || String(card?.selected_label || '').toLowerCase().includes(query);
            if (!matchesQuery) {
                return false;
            }
            if (this._listFilter === 'ready') {
                return hasReady(card);
            }
            if (this._listFilter === 'attention') {
                return hasAttention(card);
            }
            if (this._listFilter === 'local') {
                return hasLocalReady(card);
            }
            return true;
        }));
    }

    isOnboardingSeen(type) {
        return !!this._onboardingSeen[String(type || '').trim()];
    }

    markOnboardingSeen(type) {
        const wanted = String(type || '').trim();
        if (!wanted || this._onboardingSeen[wanted]) {
            return;
        }
        this._onboardingSeen[wanted] = true;
        saveOnboardingState(this._onboardingSeen);
    }

    formatEmailVisibilityText(value) {
        return formatEmailVisibilityText(value, this._emailVisibilityMode);
    }

    getCurrentProfileDisplay(card = {}, state = {}, method = {}) {
        return this.formatEmailVisibilityText(getCurrentProfileLabel(card, state, method));
    }

    getAccountDisplayText(group = null, state = {}, method = {}) {
        return this.formatEmailVisibilityText(String(group?.account_display || getAccountDisplayValue(state, method)).trim());
    }

    async openWorkflow(workflow = {}) {
        const normalized = {
            providerId: String(workflow.providerId || this._selectedProviderId || '').trim(),
            methodId: String(workflow.methodId || '').trim(),
            kind: String(workflow.kind || '').trim(),
            skipOnboarding: workflow.skipOnboarding === true,
            manual: workflow.manual === true,
            nextWorkflow: workflow.nextWorkflow || null,
        };
        const onboardingType = getOnboardingTypeForWorkflow(normalized);
        if (onboardingType && !normalized.skipOnboarding && !normalized.manual && !this.isOnboardingSeen(onboardingType)) {
            this._activeWorkflow = {
                kind: 'onboarding',
                onboardingType,
                nextWorkflow: { ...normalized, skipOnboarding: true },
            };
        } else {
            this._activeWorkflow = normalized;
            if (normalized.kind === 'model') {
                await this._ensureProviderModels(normalized.providerId);
            }
        }
        this.renderWorkflowModal();
    }

    closeWorkflowModal(options = {}) {
        if (options.markSeen && this._activeWorkflow?.kind === 'onboarding' && this._activeWorkflow?.onboardingType) {
            this.markOnboardingSeen(this._activeWorkflow.onboardingType);
        }
        this._activeWorkflow = null;
        const nodes = this._getWorkflowModalNodes();
        if (nodes.modal) {
            nodes.modal.classList.remove('active');
        }
        if (options.restoreFocus && this.isActive()) {
            this.render();
        }
    }

    renderError(message) {
        const hero = this.$('#model-auth-hero');
        const list = this.$('#model-auth-provider-grid');
        const detail = this.$('#model-auth-detail-panel');
        const meta = this.$('#model-auth-sidebar-meta');
        const retryButton = `
            <div class="state-actions">
                <button type="button" class="btn btn-primary btn-sm" data-model-auth-ui="retry_overview">重新加载</button>
            </div>
        `;
        if (hero) {
            hero.innerHTML = `
                <div class="settings-card model-center-summary-bar">
                    <div class="model-center-summary-empty">${escapeHtml(message)}</div>
                    ${retryButton}
                </div>
            `;
        }
        if (list) {
            list.innerHTML = `<div class="empty-state"><span class="empty-state-text">${escapeHtml(message)}</span>${retryButton}</div>`;
        }
        if (detail) {
            detail.innerHTML = `
                <div class="empty-state">
                    <span class="empty-state-text">重新检查后会在当前页恢复服务方列表和详情。</span>
                    ${retryButton}
                </div>
            `;
        }
        if (meta) {
            meta.textContent = '无法加载';
        }
    }

    render() {
        const cards = this.getCards();
        const summary = summarizeCards(cards);
        const activeCard = cards.find((card) => card?.metadata?.is_active_provider) || pickDefaultProvider(cards);
        const hero = this.$('#model-auth-hero');
        const filterRow = this.$('#model-auth-filter-row');
        const list = this.$('#model-auth-provider-grid');
        const detail = this.$('#model-auth-detail-panel');
        const meta = this.$('#model-auth-sidebar-meta');
        if (!hero || !filterRow || !list || !detail || !meta) {
            return;
        }

        hero.innerHTML = this.renderSummaryBar(cards, summary, activeCard);
        filterRow.innerHTML = this.renderFilterRow();

        if (!cards.length) {
            meta.textContent = '暂无可管理的服务方';
            list.innerHTML = '<div class="empty-state"><span class="empty-state-text">暂无服务方</span></div>';
            detail.innerHTML = '<div class="empty-state"><span class="empty-state-text">等接入服务方后，这里会显示配置向导。</span></div>';
            this.renderWorkflowModal();
            return;
        }

        const visibleCards = this.getVisibleCards(cards);
        const selected = this.getSelectedCard(visibleCards) || visibleCards[0] || this.getSelectedCard(cards) || pickDefaultProvider(cards);
        if (selected) {
            this._selectedProviderId = String(selected?.provider?.id || '');
        }
        meta.textContent = visibleCards.length === cards.length
            ? `共 ${cards.length} 个服务方`
            : `显示 ${visibleCards.length} / ${cards.length} 个服务方`;
        list.innerHTML = visibleCards.length
            ? visibleCards.map((card) => this.renderProviderListItem(card)).join('')
            : '<div class="empty-state"><span class="empty-state-text">没有符合条件的服务方</span></div>';
        detail.innerHTML = selected
            ? this.renderProviderDetail(selected)
            : '<div class="empty-state"><span class="empty-state-text">请选择左侧服务方</span></div>';
        this.renderWorkflowModal();
    }

    renderSummaryBar(cards, summary, activeCard) {
        const providerId = String(activeCard?.provider?.id || '').trim();
        const provider = this.getProvider(providerId, activeCard?.provider || {});
        const selectedState = this.getTestableAuthState(activeCard, this.getSelectedAuthState(activeCard))
            || this.getSelectedAuthState(activeCard);
        const testState = this.getTestableAuthState(activeCard, selectedState) || getLegacyPresetTestTarget(activeCard);
        const selectedMethod = this.getMethodMap(provider).get(String(selectedState?.method_id || '')) || {};
        const currentProvider = String(activeCard?.provider?.label || '').trim() || '未配置';
        const currentModel = getCurrentModel(activeCard, activeCard?.provider || {}) || '未选择';
        const currentAuth = this.getCurrentProfileDisplay(activeCard, selectedState, selectedMethod) || '未配置';
        const healthSummary = this.getHealthSummary(activeCard);
        const healthDetail = this.getHealthDetail(activeCard);
        const readyText = summary.connected > 0
            ? `已有 ${Number(summary.connected || 0)} 个服务方可直接用于回复`
            : '还没有可直接用于回复的服务方';
        const isCurrentSelection = providerId && providerId === this._selectedProviderId;
        const summaryBadges = [
            renderBadge(getStateLabel(activeCard?.state), getStateTone(activeCard?.state)),
            activeCard?.metadata?.is_active_provider ? renderBadge('当前用于回复', 'ready') : '',
            hasAttention(activeCard) ? renderBadge('待处理', 'attention') : '',
        ].filter(Boolean).join('');
        const focusAction = providerId
            ? `<button type="button" class="btn btn-secondary btn-sm" data-model-auth-ui="select_provider" data-provider-id="${escapeHtml(providerId)}"${isCurrentSelection ? ' disabled' : ''}>${isCurrentSelection ? '当前服务方详情' : '查看当前服务方'}</button>`
            : '';
        const testAction = this.renderCurrentConnectionTestButton(activeCard, '测试当前连接', 'btn btn-primary btn-sm', selectedState);
        const authHint = currentAuth === '未配置'
            ? '先完成一组认证后，才能直接检查连接。'
            : (activeCard?.metadata?.is_active_provider
                ? '当前回复链路会优先使用这组认证。'
                : '认证就绪后可随时切换为当前回复模型。');
        return `
            <section class="settings-card model-center-summary-bar">
                <div class="model-center-summary-main">
                    <div class="model-center-summary-header">
                        <div class="model-center-summary-copy">
                            <div class="model-center-summary-kicker">当前回复服务方</div>
                            <div class="model-center-summary-badges">${summaryBadges}</div>
                        </div>
                        <div class="model-center-summary-actions">
                            ${focusAction}
                            ${testAction}
                        </div>
                    </div>
                    <div class="model-center-summary-title-row">
                        <div class="model-center-summary-title-block">
                            <div class="model-center-summary-title">${escapeHtml(currentProvider)}</div>
                            <div class="model-center-summary-note">回复模型：${escapeHtml(currentModel)}</div>
                        </div>
                        <div class="model-center-summary-meta">${escapeHtml(readyText)}</div>
                    </div>
                    <div class="model-center-summary-meta-row">
                        <article class="model-center-summary-meta-card">
                            <span class="model-center-summary-meta-label">默认认证</span>
                            <strong>${escapeHtml(currentAuth)}</strong>
                            <span class="model-center-summary-meta-text">${escapeHtml(authHint)}</span>
                        </article>
                        <article class="model-center-summary-meta-card">
                            <span class="model-center-summary-meta-label">连接健康</span>
                            <strong>${escapeHtml(healthSummary)}</strong>
                            <span class="model-center-summary-meta-text">${escapeHtml(healthDetail)}</span>
                        </article>
                    </div>
                </div>
                <div class="model-center-summary-stats">
                    <div class="model-center-stat">
                        <span class="model-center-stat-label">可直接使用</span>
                        <strong>${Number(summary.connected || 0)}</strong>
                    </div>
                    <div class="model-center-stat">
                        <span class="model-center-stat-label">可同步</span>
                        <strong>${Number(summary.localReady || 0)}</strong>
                    </div>
                    <div class="model-center-stat">
                        <span class="model-center-stat-label">待处理</span>
                        <strong>${Number(summary.attention || 0)}</strong>
                    </div>
                    <div class="model-center-stat">
                        <span class="model-center-stat-label">服务方总数</span>
                        <strong>${Number(cards.length || 0)}</strong>
                    </div>
                </div>
            </section>
        `;
    }

    renderFilterRow() {
        const chips = FILTER_OPTIONS.map((item) => `
            <button
                type="button"
                class="model-center-filter-chip${this._listFilter === item.value ? ' active' : ''}"
                data-model-auth-ui="set_filter"
                data-filter-value="${escapeHtml(item.value)}"
            >
                ${escapeHtml(item.label)}
            </button>
        `).join('');
        return `
            ${chips}
            <button
                type="button"
                class="model-center-filter-chip model-center-filter-chip-utility"
                data-model-auth-ui="toggle_email_visibility"
                aria-pressed="${this._emailVisibilityMode === 'masked' ? 'true' : 'false'}"
            >
                ${escapeHtml(getEmailVisibilityButtonLabel(this._emailVisibilityMode))}
            </button>
        `;
    }

    renderProviderListItem(card) {
        const provider = card?.provider || {};
        const providerId = String(provider.id || '');
        const selected = providerId === this._selectedProviderId;
        const badges = [
            card?.metadata?.is_active_provider ? renderBadge('用于回复', 'ready') : '',
            hasAttention(card) ? renderBadge('待处理', 'attention') : '',
            !hasAttention(card) && hasReady(card) ? renderBadge('可用', 'ready') : '',
            !hasAttention(card) && !hasReady(card) && hasLocalReady(card) ? renderBadge('可同步', 'local') : '',
        ].filter(Boolean).join('');
        return `
            <button
                type="button"
                class="model-center-provider-item${selected ? ' active' : ''}"
                data-model-auth-ui="select_provider"
                data-provider-id="${escapeHtml(providerId)}"
            >
                <div class="model-center-provider-top">
                    <span class="model-center-provider-name">${escapeHtml(provider.label || providerId)}</span>
                    <span class="model-center-provider-badges">${badges}</span>
                </div>
                <div class="model-center-provider-subtitle">${escapeHtml(this.formatEmailVisibilityText(getProviderListSubtitle(card)))}</div>
            </button>
        `;
    }

    renderProviderDetail(card) {
        const provider = this.getProvider(card?.provider?.id, card?.provider || {});
        const selectedState = this.getTestableAuthState(card, this.getSelectedAuthState(card))
            || this.getSelectedAuthState(card);
        const methodMap = this.getMethodMap(provider);
        const selectedMethod = methodMap.get(String(selectedState?.method_id || card?.selected_method_id || '')) || {};
        const viewMode = resolveCardViewMode(card);
        const currentModel = getCurrentModel(card, provider) || '未选择';
        const currentAuth = this.getCurrentProfileDisplay(card, selectedState, selectedMethod) || '未配置';
        const detailBadges = [
            renderBadge(getStateLabel(card?.state), getStateTone(card?.state)),
            card?.metadata?.is_active_provider ? renderBadge('正在用于回复', 'ready') : '',
            card?.metadata?.can_set_active_provider && !card?.metadata?.is_active_provider
                ? renderBadge('已就绪', 'local')
                : '',
        ].filter(Boolean).join('');
        const primaryAction = viewMode !== 'workbench' || card?.metadata?.is_active_provider
            ? ''
            : (
                card?.metadata?.can_set_active_provider
                    ? `<button type="button" class="btn btn-primary btn-sm" data-model-auth-action="set_active_provider" data-provider-id="${escapeHtml(provider.id || '')}">设为当前回复模型</button>`
                    : ''
            );
        const testButton = this.getTestableAuthState(card, selectedState) || getLegacyPresetTestTarget(card)
            ? `<button type="button" class="btn btn-secondary btn-sm" data-model-auth-action="test_profile" data-provider-id="${escapeHtml(provider.id || '')}" data-method-id="${escapeHtml(selectedState?.method_id || '')}" data-profile-id="${escapeHtml(selectedState?.metadata?.profile_id || '')}">测试连接</button>`
            : '';
        return `
            <div class="model-center-detail-shell">
                <header class="model-center-detail-header">
                    <div class="model-center-detail-copy">
                        <div class="model-center-detail-kicker">当前服务方</div>
                        <h2 class="model-center-detail-title">${escapeHtml(provider.label || provider.id || '')}</h2>
                        <div class="model-center-detail-badges">${detailBadges}</div>
                    </div>
                    <div class="model-center-detail-actions">
                        ${primaryAction}
                        ${testButton}
                    </div>
                </header>
                <div class="model-center-detail-facts">
                    ${this.renderDetailFact('当前模型', currentModel, getModelStepDescription(card))}
                    ${this.renderDetailFact('默认认证', currentAuth, card?.metadata?.is_active_provider ? '当前回复链路正在使用这组认证。' : '认证就绪后可随时切换为回复模型。')}
                    ${this.renderDetailFact('本机状态', this.getSyncSummary(card), this.getSyncDetail(card))}
                </div>
                <div class="model-center-stage model-center-stage-compact">
                    ${this.renderQuickActionsSection(card, provider, currentModel, currentAuth)}
                    ${this.renderAuthMethodsSection(card, provider)}
                    ${this.renderRuntimeSection(card)}
                    ${this.renderAdvancedPanel(card, provider)}
                </div>
            </div>
        `;
    }

    renderDetailFact(label, value, note = '') {
        return `
            <article class="model-center-detail-fact">
                <span class="model-center-detail-fact-label">${escapeHtml(label)}</span>
                <strong>${escapeHtml(value)}</strong>
                ${note ? `<span class="model-center-detail-fact-note">${escapeHtml(note)}</span>` : ''}
            </article>
        `;
    }

    renderQuickMetric(label, value, note = '') {
        return `
            <article class="model-center-quick-card">
                <div class="model-center-overview-label">${escapeHtml(label)}</div>
                <strong>${escapeHtml(value)}</strong>
                ${note ? `<span>${escapeHtml(note)}</span>` : ''}
            </article>
        `;
    }

    renderDetailSection({ title, meta = '', body = '', open = false, modifier = '', id = '' }) {
        const className = ['model-center-detail-section'];
        if (modifier) {
            className.push(modifier);
        }
        return `
            <details class="${className.join(' ')}"${open ? ' open' : ''}${id ? ` id="${escapeHtml(id)}"` : ''}>
                <summary class="model-center-detail-section-summary">
                    <div class="model-center-detail-section-copy">
                        <h3 class="model-center-section-title">${escapeHtml(title)}</h3>
                        ${meta ? `<p class="model-center-detail-section-meta">${escapeHtml(meta)}</p>` : ''}
                    </div>
                    <span class="model-center-detail-section-toggle" aria-hidden="true"></span>
                </summary>
                <div class="model-center-detail-section-body">
                    ${body}
                </div>
            </details>
        `;
    }

    renderQuickActionsSection(card, provider, currentModel, currentAuth) {
        const providerId = String(provider?.id || '');
        const options = this.getProviderModelOptions(providerId, currentModel);
        const isCustom = !!currentModel && !options.includes(currentModel);
        const applyLabel = getModelApplyLabel(card);
        const active = !!card?.metadata?.is_active_provider;
        const ready = !!card?.metadata?.can_set_active_provider;
        const activationAction = active
            ? '<div class="model-center-activate-state">当前正在用于回复</div>'
            : (
                ready
                    ? `<button type="button" class="btn btn-primary btn-sm" data-model-auth-action="set_active_provider" data-provider-id="${escapeHtml(providerId)}">设为当前回复模型</button>`
                    : '<div class="model-center-inline-feedback">认证完成后即可切换为当前回复模型。</div>'
            );
        const body = `
            <div class="model-center-quick-grid">
                ${this.renderQuickMetric('当前模型', currentModel, getModelStepDescription(card))}
                ${this.renderQuickMetric('默认认证', currentAuth, active ? '回复正在用这组认证' : '认证就绪后可切换')}
                ${this.renderQuickMetric('切换状态', active ? '已生效' : (ready ? '可切换' : '等认证'), active ? '修改会直接影响回复' : '先完成认证再切换')}
            </div>
            <div class="model-center-quick-stack">
                <form class="model-center-step-form" data-model-auth-form="provider_model" data-provider-id="${escapeHtml(providerId)}">
                    <div class="model-center-inline-row">
                        ${this.renderModelSelect(providerId, currentModel, options, isCustom)}
                        <button type="submit" class="btn btn-secondary btn-sm">保存模型</button>
                        ${applyLabel
                            ? `<button type="submit" class="btn btn-primary btn-sm" data-model-auth-submit-action="save_and_activate">${escapeHtml(applyLabel)}</button>`
                            : ''}
                    </div>
                </form>
                <div class="model-center-activate-row">
                    ${activationAction}
                </div>
            </div>
        `;
        return this.renderDetailSection({
            title: '快速操作',
            meta: ready ? '可先保存，再切换' : '先选模型，再完成认证',
            body,
            open: shouldOpenQuickActions(card),
            modifier: 'model-center-detail-section-primary',
        });
    }

    renderAuthMethodsSection(card, provider) {
        const viewMode = resolveCardViewMode(card);
        const authRows = groupAuthStates(card, provider)
            .map((group) => (
                viewMode === 'wizard'
                    ? this.renderWizardAuthCard(card, provider, group.primary_method || {}, group.primary_state || group, group)
                    : this.renderWorkbenchAuthRow(card, provider, group.primary_method || {}, group.primary_state || group, group)
            ))
            .filter(Boolean)
            .join('');
        const body = viewMode === 'wizard'
            ? `
                <div class="model-center-auth-choice-grid">
                    ${authRows || '<div class="empty-state"><span class="empty-state-text">当前没有可用的认证方式。</span></div>'}
                </div>
            `
            : `
                <div class="model-center-auth-row-list">
                    ${authRows || '<div class="empty-state"><span class="empty-state-text">当前没有可管理的认证配置。</span></div>'}
                </div>
            `;
        return this.renderDetailSection({
            title: '认证方式',
            meta: viewMode === 'wizard'
                ? '优先选最省事的方式'
                : '回复会用这里的默认认证',
            body,
            open: shouldOpenAuthSection(card),
            id: 'model-auth-auth-list',
        });
    }

    renderRuntimeSection(card) {
        const selectedState = this.getSelectedAuthState(card);
        const provider = this.getProvider(card?.provider?.id, card?.provider || {});
        const methodMap = this.getMethodMap(provider);
        const selectedMethod = methodMap.get(String(selectedState?.method_id || card?.selected_method_id || '')) || {};
        const currentAuth = this.getCurrentProfileDisplay(card, selectedState, selectedMethod) || '未配置';
        const body = `
            <div class="model-center-runtime-grid">
                <article class="model-center-runtime-card">
                    <div class="model-center-runtime-label">本机同步</div>
                    <strong>${escapeHtml(this.getSyncSummary(card))}</strong>
                    <span>${escapeHtml(this.getSyncDetail(card))}</span>
                </article>
                <article class="model-center-runtime-card">
                    <div class="model-center-runtime-label">连接健康</div>
                    <strong>${escapeHtml(this.getHealthSummary(card))}</strong>
                    <span>${escapeHtml(this.getHealthDetail(card))}</span>
                </article>
                <article class="model-center-runtime-card">
                    <div class="model-center-runtime-label">默认认证</div>
                    <strong>${escapeHtml(currentAuth)}</strong>
                    <span>${escapeHtml(card?.metadata?.is_active_provider ? '当前正在用于回复' : '可随时切换为回复模型')}</span>
                </article>
            </div>
        `;
        return this.renderDetailSection({
            title: '运行状态',
            meta: '有问题再看这里',
            body,
            open: shouldOpenRuntimeSection(card),
        });
    }

    renderWizardView(card, provider) {
        return `
            <div class="model-center-stage">
                ${this.renderModelStep(card, provider)}
                ${this.renderAuthStep(card, provider)}
                ${this.renderActivateStep(card, provider)}
                ${this.renderAdvancedPanel(card, provider)}
            </div>
        `;
    }

    renderModelStep(card, provider) {
        const providerId = String(provider?.id || '');
        const currentModel = getCurrentModel(card, provider) || '';
        const options = this.getProviderModelOptions(providerId, currentModel);
        const isCustom = !!currentModel && !options.includes(currentModel);
        const applyLabel = getModelApplyLabel(card);
        return `
            <section class="model-center-step-card">
                <div class="model-center-step-head">
                    <span class="model-center-step-index">1</span>
                    <div>
                        <h3 class="model-center-step-title">选择模型</h3>
                        <p class="model-center-step-meta">${escapeHtml(getModelStepDescription(card))}</p>
                    </div>
                </div>
                <form class="model-center-step-form" data-model-auth-form="provider_model" data-provider-id="${escapeHtml(providerId)}">
                    <div class="model-center-inline-row">
                        ${this.renderModelSelect(providerId, currentModel, options, isCustom)}
                        <button type="submit" class="btn btn-secondary btn-sm">保存模型</button>
                        ${applyLabel
                            ? `<button type="submit" class="btn btn-primary btn-sm" data-model-auth-submit-action="save_and_activate">${escapeHtml(applyLabel)}</button>`
                            : ''}
                    </div>
                </form>
            </section>
        `;
    }

    renderAuthStep(card, provider) {
        const authCards = groupAuthStates(card, provider)
            .map((group) => this.renderWizardAuthCard(card, provider, group.primary_method || {}, group.primary_state || group, group))
            .filter(Boolean)
            .join('');
        return `
            <section class="model-center-step-card" id="model-auth-auth-list">
                <div class="model-center-step-head">
                    <span class="model-center-step-index">2</span>
                    <div>
                        <h3 class="model-center-step-title">选择认证方式</h3>
                        <p class="model-center-step-meta">优先选最省事的方式。</p>
                    </div>
                </div>
                <div class="model-center-auth-choice-grid">
                    ${authCards || '<div class="empty-state"><span class="empty-state-text">当前没有可用的认证方式。</span></div>'}
                </div>
            </section>
        `;
    }

    renderActivateStep(card) {
        const ready = !!card?.metadata?.can_set_active_provider;
        const active = !!card?.metadata?.is_active_provider;
        return `
            <section class="model-center-step-card model-center-step-card-accent">
                <div class="model-center-step-head">
                    <span class="model-center-step-index">3</span>
                    <div>
                        <h3 class="model-center-step-title">设为当前回复模型</h3>
                        <p class="model-center-step-meta">${ready ? '现在可以切换。' : '先完成认证。'}</p>
                    </div>
                </div>
                <div class="model-center-activate-row">
                    ${active
                        ? '<div class="model-center-activate-state">当前正在用于回复</div>'
                        : (
                            ready
                                ? `<button type="button" class="btn btn-primary" data-model-auth-action="set_active_provider" data-provider-id="${escapeHtml(card?.provider?.id || '')}">设为当前回复模型</button>`
                                : '<button type="button" class="btn btn-primary" disabled>先完成认证</button>'
                        )}
                </div>
            </section>
        `;
    }

    renderWorkbenchView(card, provider) {
        const rows = groupAuthStates(card, provider)
            .map((group) => this.renderWorkbenchAuthRow(card, provider, group.primary_method || {}, group.primary_state || group, group))
            .join('');
        const selectedState = this.getSelectedAuthState(card);
        const methodMap = this.getMethodMap(provider);
        const selectedMethod = methodMap.get(String(selectedState?.method_id || card?.selected_method_id || '')) || {};
        const currentAuth = this.getCurrentProfileDisplay(card, selectedState, selectedMethod) || '未配置';
        return `
            <div class="model-center-stage">
                <section class="model-center-section-card" id="model-auth-auth-list">
                    <div class="model-center-section-head">
                        <h3 class="model-center-section-title">认证方式</h3>
                        <button type="button" class="model-center-inline-link" data-model-auth-ui="open_help">三步接入</button>
                    </div>
                    <div class="model-center-auth-row-list">
                        ${rows}
                    </div>
                </section>
                <section class="model-center-section-card">
                    <div class="model-center-section-head">
                        <h3 class="model-center-section-title">运行状态</h3>
                    </div>
                    <div class="model-center-runtime-grid">
                        <article class="model-center-runtime-card">
                            <div class="model-center-runtime-label">本机同步</div>
                            <strong>${escapeHtml(this.getSyncSummary(card))}</strong>
                            <span>${escapeHtml(this.getSyncDetail(card))}</span>
                        </article>
                        <article class="model-center-runtime-card">
                            <div class="model-center-runtime-label">连接健康</div>
                            <strong>${escapeHtml(this.getHealthSummary(card))}</strong>
                            <span>${escapeHtml(this.getHealthDetail(card))}</span>
                        </article>
                        <article class="model-center-runtime-card">
                            <div class="model-center-runtime-label">默认认证</div>
                            <strong>${escapeHtml(currentAuth)}</strong>
                            <span>${escapeHtml(card?.metadata?.is_active_provider ? '当前正在用于回复' : '可随时切换为回复模型')}</span>
                        </article>
                    </div>
                </section>
                ${this.renderAdvancedPanel(card, provider)}
            </div>
        `;
    }

    getWorkflowEntryActions(state = {}, method = {}) {
        return normalizeStateActions(state)
            .filter((item) => isWorkflowEntryAction(item?.id))
            .sort(compareWorkflowEntryActions);
    }

    renderWorkflowEntryButton(provider, method, state, action, options = {}) {
        const requiresWorkflowForm = action?.id === 'start_browser_auth'
            && this.getMethodRequiredFields(method).length > 0;
        const uiAction = action?.id === 'start_browser_auth' && !requiresWorkflowForm
            ? 'workflow_start_browser'
            : 'open_workflow';
        const tone = options.primary ? 'btn-primary' : 'btn-secondary';
        const workflowKind = getActionWorkflowKind(action?.id, method);
        const label = action?.label || getLocalizedActionLabel(action?.id) || '查看';
        const extraAttributes = uiAction === 'open_workflow'
            ? ` data-workflow-kind="${escapeHtml(workflowKind)}"`
            : '';
        return `
            <button
                type="button"
                class="btn ${tone} btn-sm"
                data-model-auth-ui="${escapeHtml(uiAction)}"
                data-provider-id="${escapeHtml(provider?.id || '')}"
                data-method-id="${escapeHtml(method?.id || state?.method_id || '')}"${extraAttributes}
            >
                ${escapeHtml(label)}
            </button>
        `;
    }

    renderWizardAuthCard(card, provider, method, state, group = null) {
        const actions = (group?.actions || this.getWorkflowEntryActions(state, method))
            .filter((item) => isWorkflowEntryAction(item?.id))
            .sort(compareWorkflowEntryActions);
        if (!actions.length) {
            return '';
        }
        const actionButtons = actions
            .map((action, index) => this.renderWorkflowEntryButton(
                provider,
                action?.source_method || method,
                action?.source_state || state,
                action,
                { primary: index === 0 },
            ))
            .join('');
        const title = String(group?.group_label || method?.label || state?.method_id || '').trim();
        const accountDisplay = this.getAccountDisplayText(group, state, method);
        const guideAction = actions[0] || {};
        return `
            <article class="model-center-auth-choice-card">
                <div class="model-center-auth-choice-top">
                    <div class="model-center-auth-choice-title">${escapeHtml(title)}</div>
                    ${renderBadge(getStateLabel(group?.status || state?.status), getStateTone(group?.status || state?.status))}
                </div>
                <div class="model-center-auth-choice-text">${escapeHtml(getMethodHint(method, state))}</div>
                ${accountDisplay ? `<div class="model-center-auth-choice-text">${escapeHtml(accountDisplay)}</div>` : ''}
                <div class="model-center-auth-choice-actions">
                    ${actionButtons}
                    <button
                        type="button"
                        class="model-center-inline-link"
                        data-model-auth-ui="open_workflow"
                        data-workflow-kind="${escapeHtml(getActionWorkflowKind(guideAction?.id, guideAction?.source_method || method))}"
                        data-provider-id="${escapeHtml(provider?.id || '')}"
                        data-method-id="${escapeHtml(guideAction?.source_method?.id || method?.id || state?.method_id || '')}"
                        data-manual-help="true"
                    >
                        怎么做
                    </button>
                </div>
            </article>
        `;
    }

    renderWorkbenchAuthRow(card, provider, method, state, group = null) {
        const actions = (group?.actions || normalizeStateActions(state)).filter((item) => item.id !== 'refresh_status');
        const actionButtons = actions
            .map((action) => this.renderWorkbenchActionButton(
                provider,
                action?.source_method || method,
                action?.source_state || state,
                action,
            ))
            .filter(Boolean)
            .join('');
        const title = String(group?.group_label || method?.label || state?.method_id || '').trim();
        const accountDisplay = this.getAccountDisplayText(group, state, method);
        const methodNames = group?.grouped_method_labels?.length > 1
            ? group.grouped_method_labels.join(' / ')
            : '';
        return `
            <article class="model-center-auth-row">
                <div class="model-center-auth-row-main">
                    <div class="model-center-auth-row-top">
                        <div class="model-center-auth-row-title">
                            <strong>${escapeHtml(title)}</strong>
                            ${(group?.default_selected || state?.default_selected) ? renderBadge('当前认证', 'ready') : ''}
                            ${(group?.experimental || state?.experimental) ? renderBadge('实验', 'attention') : ''}
                        </div>
                        ${renderBadge(getStateLabel(group?.status || state?.status), getStateTone(group?.status || state?.status))}
                    </div>
                    <div class="model-center-auth-row-meta">
                        ${escapeHtml(getMethodHint(method, state))}
                        ${accountDisplay ? ` · ${escapeHtml(accountDisplay)}` : ''}
                        ${methodNames ? ` · ${escapeHtml(methodNames)}` : ''}
                    </div>
                </div>
                <div class="model-center-auth-row-actions">
                    ${actionButtons}
                </div>
            </article>
        `;
    }

    renderWorkbenchActionButton(provider, method, state, action) {
        if (action?.id === 'set_default_profile' && state?.default_selected) {
            return '';
        }
        if (isWorkflowEntryAction(action?.id)) {
            return this.renderWorkflowEntryButton(provider, method, state, action);
        }
        const payload = {
            'data-model-auth-action': action?.id || '',
            'data-provider-id': provider?.id || '',
            'data-method-id': state?.method_id || '',
            'data-profile-id': state?.metadata?.profile_id || '',
            'data-flow-id': state?.metadata?.pending_flow?.flow_id || '',
        };
        return `
            <button
                type="button"
                class="btn ${action?.danger ? 'btn-danger' : 'btn-secondary'} btn-sm"
                ${buildDatasetAttributes(payload)}
            >
                ${escapeHtml(action?.label || getLocalizedActionLabel(action?.id))}
            </button>
        `;
    }

    getSyncSummary(card) {
        const sync = card?.metadata?.provider_sync || {};
        if (sync?.code === 'following_local_auth') {
            return '已跟随';
        }
        if (sync?.code === 'available_to_import') {
            return '可同步';
        }
        if (sync?.code === 'error') {
            return '需要处理';
        }
        if (sync?.code === 'unsupported') {
            return '不支持';
        }
        return '未检测到';
    }

    getSyncDetail(card) {
        const sync = card?.metadata?.provider_sync || {};
        const detail = localizeModelCenterMessage(
            sync?.source_message || sync?.source_error || sync?.account_email || sync?.account_label || '',
        );
        return this.formatEmailVisibilityText(detail) || '可同步本机登录，或去网页登录。';
    }

    getHealthSummary(card) {
        const health = card?.metadata?.provider_health || {};
        if (health?.code === 'healthy') {
            return '正常';
        }
        if (health?.code === 'not_checked') {
            return '待测试';
        }
        if (health?.code === 'warning' || health?.code === 'attention') {
            return '待处理';
        }
        if (health?.code === 'blocked') {
            return '未就绪';
        }
        if (health?.code === 'idle') {
            return '待绑定';
        }
        return '未检查';
    }

    getHealthDetail(card) {
        const health = card?.metadata?.provider_health || {};
        const checkedAt = formatTimestamp(health?.checked_at);
        const testTarget = this.getCurrentConnectionTestTarget(card);
        const localizedMessage = localizeModelCenterMessage(health?.message);
        if (checkedAt) {
            return `${localizedMessage || '最近一次检查已完成'} · ${checkedAt}`;
        }
        if (health?.code === 'not_checked') {
            return testTarget ? '当前连接尚未测试，可手动测试一次。' : '当前连接尚未测试。';
        }
        if (health?.code === 'idle') {
            return testTarget
                ? '当前回复服务方仍可先测试一次连接，建议尽快在模型中心完成认证绑定。'
                : '先完成认证后才能测试连接。';
        }
        return localizedMessage || (testTarget ? '需要时可手动测试连接。' : '先完成认证后才能测试连接。');
    }

    renderAdvancedPanel(card, provider) {
        const providerId = String(provider?.id || '');
        const metadata = provider?.metadata || {};
        const links = [
            provider?.homepage_url ? { label: '官网', url: provider.homepage_url } : null,
            provider?.docs_url ? { label: '文档', url: provider.docs_url } : null,
            provider?.api_key_url ? { label: '控制台', url: provider.api_key_url } : null,
        ].filter(Boolean);
        const sourceLinks = (metadata?.official_sources || [])
            .map((item) => ({
                label: item?.label || '参考',
                url: item?.url || '',
            }))
            .filter((item) => item.url);
        const providerNotes = Array.isArray(metadata?.notes) ? metadata.notes : [];
        const localAuthPaths = Array.isArray(metadata?.local_auth_paths) ? metadata.local_auth_paths : [];
        const extraFieldNames = new Set();
        (provider?.auth_methods || []).forEach((method) => {
            (method?.requires_fields || []).forEach((fieldName) => extraFieldNames.add(fieldName));
        });
        if (card?.metadata?.oauth_project_id) {
            extraFieldNames.add('oauth_project_id');
        }
        if (card?.metadata?.oauth_location) {
            extraFieldNames.add('oauth_location');
        }
        const body = `
            <form class="model-center-advanced-form" data-model-auth-form="advanced_settings" data-provider-id="${escapeHtml(providerId)}">
                <div class="model-center-advanced-grid">
                    <label class="form-group">
                        <span class="form-label">显示名称</span>
                        <input class="form-input" name="legacy_preset_name" type="text" value="${escapeHtml(card?.metadata?.legacy_preset_name || provider?.label || '')}">
                    </label>
                    <label class="form-group">
                        <span class="form-label">别名</span>
                        <input class="form-input" name="alias" type="text" value="${escapeHtml(card?.metadata?.alias || '')}" placeholder="例如：工作账号">
                    </label>
                    <label class="form-group">
                        <span class="form-label">接口地址（Base URL）</span>
                        <input class="form-input" name="default_base_url" type="text" value="${escapeHtml(getCurrentBaseUrl(card, provider))}" placeholder="留空时使用默认地址">
                    </label>
                    ${[...extraFieldNames].map((fieldName) => {
                        const meta = EXTRA_FIELD_META[fieldName] || { label: fieldName, placeholder: '' };
                        return `
                            <label class="form-group">
                                <span class="form-label">${escapeHtml(meta.label)}</span>
                                <input class="form-input" name="${escapeHtml(fieldName)}" type="text" value="${escapeHtml(card?.metadata?.[fieldName] || '')}" placeholder="${escapeHtml(meta.placeholder || '')}">
                            </label>
                        `;
                    }).join('')}
                </div>
                <div class="model-center-advanced-actions">
                    <button type="submit" class="btn btn-secondary btn-sm">保存高级配置</button>
                </div>
            </form>
            ${renderLinkChips(links)}
            ${sourceLinks.length ? renderLinkChips(sourceLinks) : ''}
            ${provider?.description ? renderAdvancedInfoBlock('服务说明', provider.description) : ''}
            ${metadata?.research_summary ? `<div class="model-center-advanced-note">${escapeHtml(metadata.research_summary)}</div>` : ''}
            ${localAuthPaths.length ? renderAdvancedInfoBlock('本地配置路径', localAuthPaths) : ''}
            ${providerNotes.length ? renderAdvancedInfoBlock('补充说明', providerNotes) : ''}
        `;
        return this.renderDetailSection({
            title: '更多设置',
            meta: '低频配置和参考信息',
            body,
            open: false,
            modifier: 'model-center-detail-section-advanced',
        });
    }

    getMethodRequiredFields(method = {}) {
        return Array.isArray(method?.requires_fields)
            ? method.requires_fields.map((item) => String(item || '').trim()).filter(Boolean)
            : [];
    }

    renderMethodRequiredFieldInputs(card = {}, method = {}) {
        const fieldNames = this.getMethodRequiredFields(method);
        if (!fieldNames.length) {
            return '';
        }
        return fieldNames.map((fieldName) => {
            const meta = EXTRA_FIELD_META[fieldName] || { label: fieldName, placeholder: '' };
            return `
                <label class="form-group full-width">
                    <span class="form-label">${escapeHtml(meta.label)}</span>
                    <input
                        class="form-input"
                        name="${escapeHtml(fieldName)}"
                        type="text"
                        value="${escapeHtml(card?.metadata?.[fieldName] || '')}"
                        placeholder="${escapeHtml(meta.placeholder || '')}"
                    >
                </label>
            `;
        }).join('');
    }

    buildMethodSetupDefaultsPayload(providerId, provider = {}, card = {}, method = {}, formData = null) {
        if (!providerId) {
            return null;
        }
        const payload = { provider_id: providerId };
        let hasChanges = false;
        const fieldNames = this.getMethodRequiredFields(method);
        fieldNames.forEach((fieldName) => {
            const value = String(formData?.get?.(fieldName) || '').trim();
            if (value) {
                payload[fieldName] = value;
                hasChanges = true;
            }
        });
        if (!this.hasConfiguredProfile(card)) {
            const recommendedModel = String(method?.metadata?.recommended_model || '').trim();
            const recommendedBaseUrl = normalizeRuntimeBaseUrl(method?.metadata?.recommended_base_url);
            const providerDefaultModel = String(provider?.default_model || '').trim();
            const providerDefaultBaseUrl = normalizeRuntimeBaseUrl(provider?.default_base_url);
            const currentDefaultModel = String(card?.metadata?.default_model || providerDefaultModel || '').trim();
            const currentDefaultBaseUrl = normalizeRuntimeBaseUrl(card?.metadata?.default_base_url || providerDefaultBaseUrl || '');
            if (recommendedModel && recommendedModel !== currentDefaultModel && (!currentDefaultModel || currentDefaultModel === providerDefaultModel)) {
                payload.default_model = recommendedModel;
                hasChanges = true;
            }
            if (
                recommendedBaseUrl
                && recommendedBaseUrl !== currentDefaultBaseUrl
                && (!currentDefaultBaseUrl || currentDefaultBaseUrl === providerDefaultBaseUrl)
            ) {
                payload.default_base_url = recommendedBaseUrl;
                hasChanges = true;
            }
        }
        if (!hasChanges) {
            return null;
        }
        return payload;
    }

    getMethodRuntimePreview(providerId, provider = {}, card = {}, method = {}) {
        const currentModel = String(getCurrentModel(card, provider) || '').trim();
        const currentBaseUrl = String(getCurrentBaseUrl(card, provider) || '').trim();
        const payload = this.buildMethodSetupDefaultsPayload(providerId, provider, card, method, null) || {};
        return {
            model: String(payload.default_model || currentModel || '').trim(),
            baseUrl: String(payload.default_base_url || currentBaseUrl || '').trim(),
            modelLabel: payload.default_model ? '完成后默认模型' : '当前模型',
            baseUrlLabel: payload.default_base_url ? '完成后默认端点' : '当前端点',
        };
    }

    renderMethodRuntimePreview(providerId, provider = {}, card = {}, method = {}, variant = 'meta') {
        const preview = this.getMethodRuntimePreview(providerId, provider, card, method);
        const rows = [];
        if (preview.model) {
            rows.push({ label: preview.modelLabel, value: preview.model });
        }
        if (preview.baseUrl) {
            rows.push({ label: preview.baseUrlLabel, value: preview.baseUrl });
        }
        if (!rows.length) {
            return '';
        }
        if (variant === 'callout') {
            return `
                <div class="modal-callout">
                    ${rows.map((item) => `<div>${escapeHtml(item.label)}：${escapeHtml(item.value)}</div>`).join('')}
                </div>
            `;
        }
        return rows
            .map((item) => `<div class="model-center-workflow-meta">${escapeHtml(item.label)}：${escapeHtml(item.value)}</div>`)
            .join('');
    }

    async persistMethodRequiredFields(providerId, provider, card, method, formData) {
        const payload = this.buildMethodSetupDefaultsPayload(providerId, provider, card, method, formData);
        if (!payload) {
            return null;
        }
        return this.runAction('update_provider_defaults', payload, { preserveSelection: true, providerId });
    }

    renderModelSelect(providerId, currentModel, options, isCustom) {
        const selectOptions = [
            ['', '选择模型'],
            ...options.map((item) => [item, item]),
            ['__custom__', '自定义模型'],
        ];
        const selectedValue = isCustom ? '__custom__' : (currentModel || '');
        return `
            <div class="model-center-model-picker">
                <select
                    class="form-input"
                    name="default_model_select"
                    data-model-auth-ui="model_select"
                    data-provider-id="${escapeHtml(providerId)}"
                >
                    ${selectOptions.map(([value, label]) => `
                        <option value="${escapeHtml(value)}"${value === selectedValue ? ' selected' : ''}>${escapeHtml(label)}</option>
                    `).join('')}
                </select>
                <input
                    class="form-input"
                    name="custom_model"
                    type="text"
                    value="${escapeHtml(isCustom ? currentModel : '')}"
                    placeholder="输入自定义模型名"
                    data-model-custom-input="true"
                    ${isCustom ? '' : 'hidden'}
                >
            </div>
        `;
    }

    renderWorkflowModal() {
        const nodes = this._getWorkflowModalNodes();
        if (!nodes.modal || !nodes.body || !nodes.footer || !nodes.title || !nodes.subtitle || !nodes.kicker) {
            return;
        }
        if (!this._activeWorkflow) {
            nodes.modal.classList.remove('active');
            return;
        }
        const content = this.getWorkflowContent();
        nodes.kicker.textContent = content.kicker;
        nodes.title.textContent = content.title;
        nodes.subtitle.textContent = content.subtitle;
        nodes.body.innerHTML = content.body;
        nodes.footer.innerHTML = content.footer;
        nodes.modal.classList.add('active');
    }

    getWorkflowContent() {
        const workflow = this._activeWorkflow || {};
        if (workflow.kind === 'help') {
            return {
                kicker: '三步接入',
                title: '先接通，再切换',
                subtitle: '选模型 -> 选认证 -> 用于回复',
                body: `
                    <div class="model-center-tip-grid">
                        ${renderWorkflowCard({ title: '1. 选模型', text: '先选一个能用的模型。' })}
                        ${renderWorkflowCard({ title: '2. 选认证', text: '优先用“本机同步”。' })}
                        ${renderWorkflowCard({ title: '3. 用于回复', text: '就绪后设为当前回复模型。' })}
                    </div>
                `,
                footer: '<button type="button" class="btn btn-primary btn-sm" data-model-auth-ui="workflow_close">知道了</button>',
            };
        }
        if (workflow.kind === 'onboarding') {
            const content = ONBOARDING_CONTENT[workflow.onboardingType] || ONBOARDING_CONTENT.api_key;
            return {
                kicker: content.kicker,
                title: content.title,
                subtitle: content.subtitle,
                body: `
                    <div class="model-center-tip-grid">
                        ${content.points.map((item) => renderWorkflowCard(item)).join('')}
                    </div>
                `,
                footer: `
                    <button type="button" class="btn btn-secondary btn-sm" data-model-auth-ui="workflow_close">稍后配置</button>
                    <button type="button" class="btn btn-primary btn-sm" data-model-auth-ui="workflow_continue">${escapeHtml(content.confirmLabel)}</button>
                `,
            };
        }
        const context = this.getWorkflowContext();
        if (workflow.kind === 'model') {
            const currentModel = getCurrentModel(context.card, context.provider) || '';
            const options = this.getProviderModelOptions(context.provider?.id, currentModel);
            const isCustom = !!currentModel && !options.includes(currentModel);
            const applyLabel = getModelApplyLabel(context.card);
            return {
                kicker: '模型设置',
                title: context.provider?.label || '选择模型',
                subtitle: getModelStepDescription(context.card),
                body: `
                    <form id="${MODAL_FORM_ID}" data-model-auth-form="workflow_model" data-provider-id="${escapeHtml(context.provider?.id || '')}">
                        <div class="model-center-workflow-stack">
                            ${this.renderModelSelect(context.provider?.id || '', currentModel, options, isCustom)}
                        </div>
                    </form>
                `,
                footer: `
                    <button type="button" class="btn btn-secondary btn-sm" data-model-auth-ui="workflow_close">取消</button>
                    <button type="submit" class="btn ${applyLabel ? 'btn-secondary' : 'btn-primary'} btn-sm" form="${MODAL_FORM_ID}">保存模型</button>
                    ${applyLabel
                        ? `<button type="submit" class="btn btn-primary btn-sm" form="${MODAL_FORM_ID}" data-model-auth-submit-action="save_and_activate">${escapeHtml(applyLabel)}</button>`
                        : ''}
                `,
            };
        }
        if (workflow.kind === 'api_key') {
            const shouldSetDefault = this.shouldSetDefaultByDefault(context.card);
            return {
                kicker: '配置 API Key',
                title: context.method?.label || '配置 API Key',
                subtitle: '填好就能用。',
                body: `
                    <form id="${MODAL_FORM_ID}" data-model-auth-form="api_key" data-provider-id="${escapeHtml(context.provider?.id || '')}" data-method-id="${escapeHtml(context.method?.id || '')}">
                        <div class="model-center-workflow-stack">
                            ${this.renderMethodRuntimePreview(context.provider?.id || '', context.provider, context.card, context.method, 'callout')}
                            <label class="form-group full-width">
                                <span class="form-label">API Key</span>
                                <input class="form-input" name="api_key" type="password" placeholder="粘贴 API Key">
                            </label>
                            <details class="model-center-mini-details">
                                <summary>可选项</summary>
                                <label class="form-group full-width">
                                    <span class="form-label">备注名</span>
                                    <input class="form-input" name="label" type="text" value="${escapeHtml(context.method?.label || '')}" placeholder="可选">
                                </label>
                            </details>
                            <label class="form-checkbox model-center-inline-checkbox">
                                <input type="checkbox" name="set_default" ${shouldSetDefault ? 'checked' : ''}>
                                <span class="form-checkbox-label">保存后直接使用</span>
                            </label>
                        </div>
                    </form>
                `,
                footer: `
                    <button type="button" class="btn btn-secondary btn-sm" data-model-auth-ui="workflow_close">取消</button>
                    <button type="submit" class="btn btn-primary btn-sm" form="${MODAL_FORM_ID}">保存 API Key</button>
                `,
            };
        }
        if (workflow.kind === 'session') {
            const shouldSetDefault = this.shouldSetDefaultByDefault(context.card);
            return {
                kicker: '导入会话',
                title: context.method?.label || '导入会话',
                subtitle: '粘贴后就能用。',
                body: `
                    <form id="${MODAL_FORM_ID}" data-model-auth-form="session" data-provider-id="${escapeHtml(context.provider?.id || '')}" data-method-id="${escapeHtml(context.method?.id || '')}">
                        <div class="model-center-workflow-stack">
                            <label class="form-group full-width">
                                <span class="form-label">会话内容</span>
                                <textarea class="form-input" name="session_payload" rows="6" placeholder="粘贴 Cookie / Session / Header 内容"></textarea>
                            </label>
                            <details class="model-center-mini-details">
                                <summary>可选项</summary>
                                <label class="form-group full-width">
                                    <span class="form-label">备注名</span>
                                    <input class="form-input" name="label" type="text" value="${escapeHtml(context.method?.label || '')}" placeholder="可选">
                                </label>
                            </details>
                            <label class="form-checkbox model-center-inline-checkbox">
                                <input type="checkbox" name="set_default" ${shouldSetDefault ? 'checked' : ''}>
                                <span class="form-checkbox-label">导入后直接使用</span>
                            </label>
                        </div>
                    </form>
                `,
                footer: `
                    <button type="button" class="btn btn-secondary btn-sm" data-model-auth-ui="workflow_close">取消</button>
                    <button type="submit" class="btn btn-primary btn-sm" form="${MODAL_FORM_ID}">导入会话</button>
                `,
            };
        }
        if (workflow.kind === 'local') {
            const hasImportCopy = normalizeStateActions(context.state).some((item) => item.id === 'import_local_auth_copy');
            const shouldSetDefault = this.shouldSetDefaultByDefault(context.card);
            return {
                kicker: '本机同步',
                title: context.method?.label || '同步本机登录',
                subtitle: '这台电脑登过就优先用这个。',
                body: `
                    <form id="${MODAL_FORM_ID}" data-model-auth-form="local_auth" data-provider-id="${escapeHtml(context.provider?.id || '')}" data-method-id="${escapeHtml(context.method?.id || '')}">
                        <div class="model-center-workflow-stack">
                        <div class="modal-callout">${escapeHtml(this.formatEmailVisibilityText(context.state?.account_label || context.state?.account_email || '已检测到本机可同步的登录状态。'))}</div>
                        ${this.renderMethodRuntimePreview(context.provider?.id || '', context.provider, context.card, context.method)}
                        ${this.renderMethodRequiredFieldInputs(context.card, context.method)}
                        <div class="model-center-tip-grid">
                            ${renderWorkflowCard({ title: '直接同步', text: '后面更省心。' })}
                            ${renderWorkflowCard({ title: '导入副本', text: '需要独立凭据时再用。' })}
                        </div>
                        <label class="form-checkbox model-center-inline-checkbox">
                            <input type="checkbox" name="set_default" ${shouldSetDefault ? 'checked' : ''}>
                            <span class="form-checkbox-label">完成后直接使用</span>
                        </label>
                    </div>
                    </form>
                `,
                footer: `
                    <button type="button" class="btn btn-secondary btn-sm" data-model-auth-ui="workflow_close">取消</button>
                    ${hasImportCopy ? `<button type="submit" class="btn btn-secondary btn-sm" form="${MODAL_FORM_ID}" data-model-auth-submit-action="import_local_auth_copy">导入认证副本</button>` : ''}
                    <button type="submit" class="btn btn-primary btn-sm" form="${MODAL_FORM_ID}" data-model-auth-submit-action="bind_local_auth">立即同步</button>
                `,
            };
        }
        const browserHasPending = this.browserWorkflowHasPending(context.state);
        const browserKicker = getMethodType(context.method) === 'oauth' ? 'OAuth 登录' : '网页登录';
        const browserTitle = context.method?.label || '打开登录页';
        const browserSubtitle = browserHasPending
            ? '登录后点“我已登录，继续”。'
            : '先打开登录页，再回来。';
        return {
            kicker: browserKicker,
            title: browserTitle,
            subtitle: browserSubtitle,
            body: this.renderBrowserAuthForm(context.card, context.provider, context.method, context.state),
            footer: browserHasPending
                ? `
                    <button type="submit" class="btn btn-secondary btn-sm" form="${MODAL_FORM_ID}" data-model-auth-submit-action="reopen_browser_auth">重新打开登录页</button>
                    <button type="submit" class="btn btn-primary btn-sm" form="${MODAL_FORM_ID}">我已登录，继续</button>
                `
                : `
                    <button type="button" class="btn btn-secondary btn-sm" data-model-auth-ui="workflow_close">取消</button>
                    <button type="submit" class="btn btn-primary btn-sm" form="${MODAL_FORM_ID}" data-model-auth-submit-action="start_browser_auth">打开登录页</button>
                `,
        };
    }

    getWorkflowContext() {
        const workflow = this._activeWorkflow || {};
        const card = this.getCardByProviderId(workflow.providerId) || this.getSelectedCard() || {};
        const provider = this.getProvider(workflow.providerId || card?.provider?.id, card?.provider || {});
        const methodMap = this.getMethodMap(provider);
        const state = (card?.auth_states || []).find((item) => String(item?.method_id || '') === String(workflow.methodId || ''))
            || this.getSelectedAuthState(card)
            || {};
        const resolvedMethodId = String(workflow.methodId || state?.method_id || '').trim();
        const method = methodMap.get(resolvedMethodId) || { id: resolvedMethodId };
        return { card, provider, state, method, resolvedMethodId };
    }

    hasConfiguredProfile(card = {}) {
        return Array.isArray(card?.auth_states)
            && card.auth_states.some((item) => String(item?.metadata?.profile_id || '').trim());
    }

    shouldSetDefaultByDefault(card = {}) {
        return !this.hasConfiguredProfile(card);
    }

    browserWorkflowHasPending(state = {}) {
        const pendingFlow = state?.metadata?.pending_flow || {};
        return !!(pendingFlow?.started_at || pendingFlow?.flow_id || pendingFlow?.browser_entry_url || pendingFlow?.auth_provider_id);
    }

    resolveBrowserFlowId(state = {}) {
        const pendingFlow = state?.metadata?.pending_flow || {};
        if (pendingFlow?.flow_id) {
            return String(pendingFlow.flow_id);
        }
        if (pendingFlow?.started_at || pendingFlow?.browser_entry_url || pendingFlow?.auth_provider_id) {
            return '__local_rescan__';
        }
        return '';
    }

    renderBrowserAuthForm(card, provider, method, state) {
        const pending = state?.metadata?.pending_flow || {};
        const flowId = this.resolveBrowserFlowId(state);
        const hasPending = this.browserWorkflowHasPending(state);
        const shouldSetDefault = this.shouldSetDefaultByDefault(card);
        return `
            <form id="${MODAL_FORM_ID}" data-model-auth-form="browser_callback" data-provider-id="${escapeHtml(provider?.id || '')}" data-method-id="${escapeHtml(method?.id || '')}" data-flow-id="${escapeHtml(flowId)}">
                <div class="model-center-workflow-stack">
                    <div class="modal-callout">
                        ${hasPending
                            ? '先登录，再点“我已登录，继续”'
                            : '先打开登录页，再回来'}
                    </div>
                    ${pending?.started_at ? `<div class="model-center-workflow-meta">最近打开：${escapeHtml(formatTimestamp(pending.started_at))}</div>` : ''}
                    ${this.renderMethodRuntimePreview(provider?.id || '', provider, card, method)}
                    <input type="hidden" name="flow_id" value="${escapeHtml(flowId)}">
                    ${this.renderMethodRequiredFieldInputs(card, method)}
                    <details class="model-center-mini-details">
                        <summary>可选项</summary>
                        <label class="form-group full-width">
                            <span class="form-label">备注名</span>
                            <input class="form-input" name="label" type="text" value="${escapeHtml(method?.label || '')}" placeholder="可选">
                        </label>
                        <label class="form-group full-width">
                            <span class="form-label">回调参数</span>
                            <textarea class="form-input" name="callback_payload" rows="4" placeholder="有 code / state / token 等参数时再填写"></textarea>
                        </label>
                    </details>
                    <label class="form-checkbox model-center-inline-checkbox">
                        <input type="checkbox" name="set_default" ${shouldSetDefault ? 'checked' : ''}>
                        <span class="form-checkbox-label">完成后直接使用</span>
                    </label>
                </div>
            </form>
        `;
    }

    _getWorkflowModalNodes() {
        return {
            modal: document.getElementById('model-auth-workflow-modal'),
            kicker: document.getElementById('model-auth-workflow-kicker'),
            title: document.getElementById('model-auth-workflow-title'),
            subtitle: document.getElementById('model-auth-workflow-subtitle'),
            body: document.getElementById('model-auth-workflow-body'),
            footer: document.getElementById('model-auth-workflow-footer'),
            closeButton: document.getElementById('btn-close-model-auth-workflow'),
        };
    }

    _bindWorkflowModal() {
        const nodes = this._getWorkflowModalNodes();
        if (!nodes.modal || nodes.modal.dataset.bound === 'true') {
            return;
        }
        this.bindEvent(nodes.closeButton, 'click', () => this.closeWorkflowModal());
        this.bindEvent(nodes.modal, 'click', (event) => {
            if (event.target === nodes.modal) {
                this.closeWorkflowModal();
                return;
            }
            const button = event.target?.closest?.('[data-model-auth-action],[data-model-auth-ui]');
            if (!button) {
                return;
            }
            event.preventDefault();
            void this.handleButtonAction(button);
        });
        this.bindEvent(nodes.modal, 'submit', (event) => {
            const form = event.target?.closest?.('[data-model-auth-form]');
            if (!form) {
                return;
            }
            event.preventDefault();
            void this.handleFormSubmit(form, event.submitter || null);
        });
        this.bindEvent(nodes.modal, 'change', (event) => this.handleFieldChange(event));
        this.bindEvent(document, 'keydown', (event) => {
            if (event.key === 'Escape' && nodes.modal.classList.contains('active')) {
                event.preventDefault();
                this.closeWorkflowModal();
            }
        });
        nodes.modal.dataset.bound = 'true';
    }

    handleInputChange(event) {
        const target = event?.target;
        if (!target) {
            return;
        }
        if (target.id === 'model-auth-provider-search') {
            this._searchQuery = String(target.value || '');
            this.render();
        }
    }

    handleFieldChange(event) {
        const target = event?.target;
        if (!target) {
            return;
        }
        if (target.name === 'default_model_select') {
            const form = target.closest?.('form');
            const customInput = form?.querySelector?.('[data-model-custom-input="true"]');
            if (customInput) {
                customInput.hidden = target.value !== '__custom__';
                if (target.value !== '__custom__') {
                    customInput.value = '';
                }
            }
        }
    }

    async handleButtonAction(button) {
        const uiAction = String(button?.dataset?.modelAuthUi || '').trim();
        const action = String(button?.dataset?.modelAuthAction || '').trim();
        const providerId = String(button?.dataset?.providerId || '').trim();
        const methodId = String(button?.dataset?.methodId || '').trim();
        const profileId = String(button?.dataset?.profileId || '').trim();
        const flowId = String(button?.dataset?.flowId || '').trim();
        const card = this.getCardByProviderId(providerId) || this.getSelectedCard() || {};

        if (uiAction === 'select_provider') {
            this._selectedProviderId = providerId;
            this.render();
            void this._ensureProviderModels(providerId).then(() => {
                if (this._selectedProviderId === providerId) {
                    this.render();
                }
            });
            return;
        }
        if (uiAction === 'test_current_connection') {
            await this.runCurrentConnectionTest(card);
            return;
        }
        if (uiAction === 'set_filter') {
            this._listFilter = String(button?.dataset?.filterValue || 'all').trim() || 'all';
            this.render();
            return;
        }
        if (uiAction === 'toggle_email_visibility') {
            this._emailVisibilityMode = toggleEmailVisibilityMode(this._emailVisibilityMode);
            saveEmailVisibilityPreference(this._emailVisibilityMode);
            this.render();
            return;
        }
        if (uiAction === 'open_help') {
            await this.openWorkflow({ kind: 'help', manual: true });
            return;
        }
        if (uiAction === 'retry_overview') {
            await this.loadOverview({ preserveSelection: true });
            return;
        }
        if (uiAction === 'open_workflow') {
            const workflowKind = String(button?.dataset?.workflowKind || '').trim();
            const manualHelp = String(button?.dataset?.manualHelp || '').trim() === 'true';
            if (manualHelp) {
                this._activeWorkflow = {
                    kind: 'onboarding',
                    onboardingType: getOnboardingTypeForWorkflow({ kind: workflowKind }),
                    manual: true,
                    nextWorkflow: null,
                };
                this.renderWorkflowModal();
                return;
            }
            await this.openWorkflow({
                kind: workflowKind,
                providerId,
                methodId,
                manual: false,
                skipOnboarding: false,
            });
            return;
        }
        if (uiAction === 'workflow_close') {
            this.closeWorkflowModal({ markSeen: false });
            return;
        }
        if (uiAction === 'workflow_continue') {
            const nextWorkflow = this._activeWorkflow?.nextWorkflow || null;
            if (this._activeWorkflow?.onboardingType) {
                this.markOnboardingSeen(this._activeWorkflow.onboardingType);
            }
              if (nextWorkflow) {
                  await this.openWorkflow({ ...nextWorkflow, skipOnboarding: true });
                  return;
              }
              this.closeWorkflowModal({ markSeen: true });
              return;
          }
        if (uiAction === 'workflow_start_browser') {
            await this.runAction('start_browser_auth', {
                provider_id: providerId,
                method_id: methodId,
            }, {
                preserveSelection: true,
                providerId,
            });
            await this.openWorkflow({
                kind: 'browser',
                providerId,
                methodId,
                skipOnboarding: true,
            });
            return;
        }
        if (uiAction === 'focus_auth') {
            this.$('#model-auth-auth-list')?.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
            return;
        }
        if (!action) {
            return;
        }
        if (action === 'disconnect_profile') {
            const confirmed = await this.confirmAction({
                title: '移除当前认证',
                subtitle: '这会移除当前项目中保存的这份认证配置。',
                message: '确定要移除这份认证吗？移除后仍可重新配置或重新登录。',
                confirmLabel: '确认断开',
                danger: true,
            });
            if (!confirmed) {
                return;
            }
        }
        if (action === 'logout_source') {
            const confirmed = await this.confirmAction({
                title: '退出本机登录',
                subtitle: '这会尝试退出这台电脑上的登录源。',
                message: '退出后，这个服务方的同步状态可能失效。确定继续吗？',
                confirmLabel: '确认退出',
                danger: true,
            });
            if (!confirmed) {
                return;
            }
        }
        if (action === 'test_profile' && !profileId) {
            await this.runCurrentConnectionTest(card);
            return;
        }
        const payload = {
            provider_id: providerId,
            method_id: methodId,
            profile_id: profileId,
            flow_id: flowId,
        };
        if (action === 'bind_local_auth' || action === 'import_local_auth_copy') {
            payload.set_default = this.shouldSetDefaultByDefault(card);
        }
        await this.runAction(action, payload, { preserveSelection: true, providerId });
        if (this._activeWorkflow && ['disconnect_profile', 'logout_source', 'bind_local_auth', 'import_local_auth_copy'].includes(action)) {
            this.closeWorkflowModal();
        }
    }

    async runCurrentConnectionTest(card = {}) {
        const target = this.getCurrentConnectionTestTarget(card);
        if (!target) {
            return null;
        }
        if (target.kind === 'profile') {
            return this.runAction('test_profile', {
                provider_id: target.providerId,
                method_id: target.methodId,
                profile_id: target.profileId,
            }, {
                preserveSelection: true,
                providerId: target.providerId,
            });
        }
        try {
            const result = await apiService.testConnection(target.presetName || null);
            const success = result?.success !== false;
            const message = String(result?.message || '').trim() || (success ? '连接测试已完成' : '连接测试失败');
            this.renderFeedback(message, success ? 'success' : 'error');
            if (success) {
                toast.success(message);
            } else {
                toast.error(message);
            }
            return result;
        } catch (error) {
            console.error('[ModelsPage] current connection test failed:', error);
            const message = error?.message || '连接测试失败';
            this.renderFeedback(message, 'error');
            toast.error(message);
            throw error;
        }
    }

    async handleFormSubmit(form, submitter = null) {
        const formType = String(form?.dataset?.modelAuthForm || '').trim();
        const providerId = String(form?.dataset?.providerId || '').trim();
        const methodId = String(form?.dataset?.methodId || '').trim();
        const formData = new FormData(form);
        const submitAction = String(submitter?.dataset?.modelAuthSubmitAction || '').trim();
        const card = this.getCardByProviderId(providerId) || this.getSelectedCard() || {};
        const provider = this.getProvider(providerId, card?.provider || {});
        const method = this.getMethodMap(provider).get(methodId) || { id: methodId };
        const defaultSetDefault = this.shouldSetDefaultByDefault(card);

        if (formType === 'provider_model' || formType === 'workflow_model') {
            const model = getModelValueFromFormData(formData);
            if (!model) {
                toast.error('请先选择一个模型');
                return;
            }
            await this.runAction('update_provider_defaults', {
                provider_id: providerId,
                default_model: model,
            }, { preserveSelection: true, providerId });
            if (submitAction === 'save_and_activate') {
                await this.runAction('set_active_provider', {
                    provider_id: providerId,
                }, { preserveSelection: true, providerId });
            }
            if (formType === 'workflow_model') {
                this.closeWorkflowModal();
            }
            return;
        }

        if (formType === 'advanced_settings') {
            const advancedPayload = { provider_id: providerId };
            for (const [key, value] of formData.entries()) {
                advancedPayload[key] = typeof value === 'string' ? value.trim() : value;
            }
            await this.runAction('update_provider_defaults', advancedPayload, { preserveSelection: true, providerId });
            return;
        }

        if (formType === 'api_key') {
            const apiKey = String(formData.get('api_key') || '').trim();
            if (!apiKey) {
                toast.error('请输入 API Key');
                return;
            }
            await this.persistMethodRequiredFields(providerId, provider, card, method, formData);
            await this.runAction('save_api_key', {
                provider_id: providerId,
                method_id: methodId,
                label: formData.get('label'),
                api_key: apiKey,
                set_default: getFormBooleanWithDefault(formData, 'set_default', defaultSetDefault),
            }, { preserveSelection: true, providerId });
            this.closeWorkflowModal();
            return;
        }

        if (formType === 'session') {
            const rawPayload = String(formData.get('session_payload') || '').trim();
            if (!rawPayload) {
                toast.error('请先粘贴会话内容');
                return;
            }
            await this.runAction('import_session', {
                provider_id: providerId,
                method_id: methodId,
                label: formData.get('label'),
                session_payload: parseSessionPayload(rawPayload),
                set_default: getFormBooleanWithDefault(formData, 'set_default', defaultSetDefault),
            }, { preserveSelection: true, providerId });
            this.closeWorkflowModal();
            return;
        }

        if (formType === 'local_auth') {
            await this.persistMethodRequiredFields(providerId, provider, card, method, formData);
            await this.runAction(
                submitAction === 'import_local_auth_copy' ? 'import_local_auth_copy' : 'bind_local_auth',
                {
                    provider_id: providerId,
                    method_id: methodId,
                    set_default: getFormBooleanWithDefault(formData, 'set_default', defaultSetDefault),
                },
                { preserveSelection: true, providerId },
            );
            this.closeWorkflowModal();
            return;
        }

        if (formType === 'browser_callback') {
            if (submitAction === 'start_browser_auth' || submitAction === 'reopen_browser_auth') {
                await this.persistMethodRequiredFields(providerId, provider, card, method, formData);
                await this.runAction('start_browser_auth', {
                    provider_id: providerId,
                    method_id: methodId,
                }, {
                    preserveSelection: true,
                    providerId,
                });
                await this.openWorkflow({
                    kind: 'browser',
                    providerId,
                    methodId,
                    skipOnboarding: true,
                });
                return;
            }
            const flowValue = String(formData.get('flow_id') || form?.dataset?.flowId || '').trim();
            if (!flowValue) {
                toast.error('登录流程信息缺失，请重新打开登录页');
                return;
            }
            await this.persistMethodRequiredFields(providerId, provider, card, method, formData);
            const result = await this.runAction('complete_browser_auth', {
                provider_id: providerId,
                method_id: methodId,
                flow_id: flowValue,
                label: formData.get('label'),
                callback_payload: parseCallbackPayload(formData.get('callback_payload')),
                set_default: getFormBooleanWithDefault(formData, 'set_default', defaultSetDefault),
            }, { preserveSelection: true, providerId });
            if (shouldKeepWorkflowOpen(result)) {
                await this.openWorkflow({
                    kind: 'browser',
                    providerId,
                    methodId,
                    skipOnboarding: true,
                });
            } else {
                this.closeWorkflowModal();
            }
        }
    }

    async runAction(action, payload = {}, options = {}) {
        try {
            const result = await apiService.runModelAuthAction(action, payload);
            this.applyOverview(result?.overview || null, { preserveSelection: options.preserveSelection !== false });
            if (this.isActive()) {
                this.render();
                this.renderFeedback(result?.message || '操作已完成');
            }
            toast.success(result?.message || '操作已完成');
            return result;
        } catch (error) {
            console.error('[ModelsPage] action failed:', action, error);
            this.renderFeedback(error?.message || '操作失败', 'error');
            toast.error(error?.message || '操作失败');
            throw error;
        }
    }

    renderFeedback(message, type = 'success') {
        const root = this.$('#model-auth-feedback');
        const summary = this.$('#model-auth-feedback-summary');
        const meta = this.$('#model-auth-feedback-meta');
        if (!root || !summary || !meta) {
            return;
        }
        root.hidden = false;
        root.dataset.state = type;
        summary.textContent = String(message || '').trim() || '操作已完成';
        meta.textContent = `更新时间 ${new Date().toLocaleString()}`;
    }

    _getConfirmModalNodes() {
        return {
            modal: document.getElementById('confirm-modal'),
            title: document.getElementById('confirm-modal-title'),
            subtitle: document.getElementById('confirm-modal-subtitle'),
            kicker: document.getElementById('confirm-modal-kicker'),
            message: document.getElementById('confirm-modal-message'),
            cancelButton: document.getElementById('btn-confirm-modal-cancel'),
            confirmButton: document.getElementById('btn-confirm-modal-confirm'),
            closeButton: document.getElementById('btn-close-confirm-modal'),
        };
    }

    _bindConfirmModal() {
        const nodes = this._getConfirmModalNodes();
        if (!nodes.modal || nodes.modal.dataset.bound === 'true') {
            return;
        }
        this.bindEvent(nodes.cancelButton, 'click', () => this._closeConfirmModal(false));
        this.bindEvent(nodes.closeButton, 'click', () => this._closeConfirmModal(false));
        this.bindEvent(nodes.confirmButton, 'click', () => this._closeConfirmModal(true));
        this.bindEvent(nodes.modal, 'click', (event) => {
            if (event.target === nodes.modal) {
                this._closeConfirmModal(false);
            }
        });
        this.bindEvent(document, 'keydown', (event) => {
            if (event.key === 'Escape' && nodes.modal.classList.contains('active')) {
                event.preventDefault();
                this._closeConfirmModal(false);
            }
        });
        nodes.modal.dataset.bound = 'true';
    }

    _closeConfirmModal(result) {
        const nodes = this._getConfirmModalNodes();
        if (nodes.modal) {
            nodes.modal.classList.remove('active');
        }
        if (nodes.confirmButton) {
            nodes.confirmButton.classList.remove('btn-danger');
            if (!nodes.confirmButton.classList.contains('btn-primary')) {
                nodes.confirmButton.classList.add('btn-primary');
            }
        }
        const resolver = this._confirmState.resolver;
        this._confirmState.resolver = null;
        if (resolver) {
            resolver(Boolean(result));
        }
    }

    async confirmAction(options = {}) {
        const nodes = this._getConfirmModalNodes();
        const message = String(options.message || '确认是否继续执行当前操作？').trim();
        if (!nodes.modal || !nodes.confirmButton) {
            return window.confirm(message);
        }
        if (this._confirmState.resolver) {
            this._closeConfirmModal(false);
        }
        if (nodes.kicker) {
            nodes.kicker.textContent = String(options.kicker || '操作确认').trim() || '操作确认';
        }
        if (nodes.title) {
            nodes.title.textContent = String(options.title || '确认操作').trim() || '确认操作';
        }
        if (nodes.subtitle) {
            nodes.subtitle.textContent = String(options.subtitle || '请确认是否继续执行当前操作。').trim() || '请确认是否继续执行当前操作。';
        }
        if (nodes.message) {
            nodes.message.textContent = message;
        }
        nodes.confirmButton.textContent = String(options.confirmLabel || '确认').trim() || '确认';
        nodes.confirmButton.classList.toggle('btn-primary', !options.danger);
        nodes.confirmButton.classList.toggle('btn-danger', !!options.danger);
        nodes.modal.classList.add('active');
        return new Promise((resolve) => {
            this._confirmState.resolver = resolve;
        });
    }
}

export default ModelsPage;
