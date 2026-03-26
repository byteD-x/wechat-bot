import { createElement } from './form-codec.js';
import {
    createModelKindBadge,
    getPresetModelMeta,
} from './preset-meta.js';

const GROUP_COPY = {
    featured: {
        kicker: 'Ready First',
        title: '当前生效 / 已可用',
        subtitle: '优先显示当前激活、已可直接使用，或已检测到本机授权的卡片。',
    },
    secondary: {
        kicker: 'Need Setup',
        title: '待授权 / 实验能力',
        subtitle: '仍需补齐认证、确认实验风险，或尚未完成绑定的卡片会显示在这里。',
    },
};

function getDraftList(page) {
    return Array.isArray(page?._apiPresetsSnapshot)
        ? page._apiPresetsSnapshot
        : (Array.isArray(page?._presetDrafts) ? page._presetDrafts : []);
}

function getActivePresetName(page) {
    return String(page?._activePresetName || page?._activePreset || '').trim();
}

function getCardStatusLabel(preset = {}) {
    const authMode = preset?.auth_mode === 'oauth' ? 'OAuth' : 'API Key';
    if (preset?.card_state === 'active' || preset?.name === preset?._active_marker) {
        return `当前生效 / ${authMode}`;
    }
    if (preset?.card_state === 'oauth_ready') {
        return 'OAuth 可用';
    }
    if (preset?.card_state === 'api_key_ready') {
        return 'API Key 可用';
    }
    if (preset?.card_state === 'detected_local') {
        return '检测到本机授权';
    }
    if (preset?.card_state === 'experimental') {
        return '实验能力';
    }
    return preset?.auth_mode === 'oauth' ? '等待 OAuth 授权' : '等待配置 API Key';
}

function sortPresets(page) {
    return [...getDraftList(page)]
        .sort((left, right) => {
            const leftRank = Number(left?.card_rank ?? 99);
            const rightRank = Number(right?.card_rank ?? 99);
            if (leftRank !== rightRank) {
                return leftRank - rightRank;
            }
            const activePresetName = getActivePresetName(page);
            const leftActive = String(left?.name || '').trim() === activePresetName;
            const rightActive = String(right?.name || '').trim() === activePresetName;
            if (leftActive !== rightActive) {
                return leftActive ? -1 : 1;
            }
            return String(left?.name || '').localeCompare(String(right?.name || ''), 'zh-CN');
        })
        .map((preset) => ({
            ...preset,
            _active_marker: getActivePresetName(page),
        }));
}

function createGroupHeader(groupKey, count) {
    const meta = GROUP_COPY[groupKey] || GROUP_COPY.secondary;
    const header = createElement('div', 'preset-group-header');
    const copy = createElement('div', 'preset-group-copy');
    copy.appendChild(createElement('div', 'preset-group-kicker', meta.kicker));
    copy.appendChild(createElement('div', 'preset-group-title', meta.title));
    copy.appendChild(createElement('div', 'preset-group-subtitle', meta.subtitle));
    header.appendChild(copy);
    header.appendChild(createElement('div', 'config-save-feedback-badge', `共 ${count} 张`));
    return header;
}

function createPresetCard(page, preset, index) {
    const provider = page?._providersById?.get?.(preset.provider_id) || null;
    const modelMeta = getPresetModelMeta(page, preset);
    const activePresetName = getActivePresetName(page);
    const stateClass = `state-${String(preset?.card_state || 'unconfigured').replace(/_/g, '-')}`;
    const card = createElement('div', `preset-card ${stateClass}${preset.name === activePresetName ? ' active' : ''}`);

    const header = createElement('div', 'preset-card-header');
    const info = createElement('div', 'preset-info');
    const name = createElement('div', 'preset-name', preset.name || '未命名预设');
    if (preset.name === activePresetName) {
        name.appendChild(createElement('span', 'config-save-feedback-badge live', '当前生效'));
    }
    if (preset.oauth_experimental) {
        name.appendChild(createElement('span', 'config-save-feedback-badge warning', '实验'));
    }
    info.appendChild(name);

    const meta = createElement('div', 'preset-meta');
    meta.appendChild(createElement('span', 'meta-item', provider?.label || preset.provider_id || '--'));
    meta.appendChild(createElement('span', 'meta-separator', '/'));
    meta.appendChild(createElement('span', 'meta-item model-name', preset.model || '--'));
    meta.appendChild(createElement('span', 'meta-separator', '/'));
    meta.appendChild(createElement('span', 'meta-item', preset.auth_mode === 'oauth' ? 'OAuth' : 'API Key'));
    if (modelMeta) {
        meta.appendChild(createModelKindBadge(modelMeta));
    }
    info.appendChild(meta);

    const status = createElement('div', `ping-result ${stateClass}`);
    status.textContent = preset.auth_status_summary || getCardStatusLabel(preset);
    info.appendChild(status);

    header.appendChild(info);
    card.appendChild(header);

    const actions = createElement('div', 'preset-card-actions');
    const useButton = createElement(
        'button',
        'btn btn-secondary btn-sm',
        preset.name === activePresetName ? '已启用' : '设为当前',
    );
    useButton.type = 'button';
    useButton.disabled = preset.name === activePresetName;
    useButton.addEventListener('click', () => {
        if ('_activePreset' in page) {
            page._activePreset = preset.name;
        }
        if ('_activePresetName' in page) {
            page._activePresetName = preset.name;
        }
        page._renderPresetList?.();
        page._renderHero?.();
        page._scheduleAutoSave?.({ immediate: true });
    });

    const testButton = createElement('button', 'btn btn-secondary btn-sm', '测试');
    testButton.type = 'button';
    testButton.addEventListener('click', () => void page._testPreset?.(index, status));

    const editButton = createElement('button', 'btn btn-primary btn-sm', '编辑');
    editButton.type = 'button';
    editButton.addEventListener('click', () => page._openPresetModal?.(index));

    actions.appendChild(useButton);
    actions.appendChild(testButton);
    actions.appendChild(editButton);

    if (getDraftList(page).length > 1) {
        const deleteButton = createElement('button', 'btn btn-secondary btn-sm', '删除');
        deleteButton.type = 'button';
        deleteButton.addEventListener('click', () => page._removePreset?.(index));
        actions.appendChild(deleteButton);
    }

    card.appendChild(actions);
    return card;
}

export function renderPresetList(page) {
    const list = page.$('#preset-list');
    if (!list) {
        return;
    }
    list.textContent = '';

    const drafts = getDraftList(page);
    if (!drafts.length) {
        list.appendChild(createElement('div', 'empty-state-text', '暂无预设，点击“新增模型”创建第一张卡片。'));
        return;
    }

    const presets = sortPresets(page);
    const featured = presets.filter((preset) => String(preset?.card_group || '') === 'featured');
    const secondary = presets.filter((preset) => String(preset?.card_group || '') !== 'featured');
    const groups = [
        ['featured', featured],
        ['secondary', secondary],
    ].filter(([, items]) => items.length > 0);

    const fragment = document.createDocumentFragment();
    groups.forEach(([groupKey, items]) => {
        const section = createElement('section', 'preset-group');
        section.appendChild(createGroupHeader(groupKey, items.length));

        const grid = createElement('div', 'preset-group-grid');
        items.forEach((preset) => {
            const index = drafts.findIndex((item) => String(item?.name || '') === String(preset?.name || ''));
            grid.appendChild(createPresetCard(page, preset, index));
        });
        section.appendChild(grid);
        fragment.appendChild(section);
    });

    list.appendChild(fragment);
}
