import { createElement } from './form-codec.js';
import {
    createModelKindBadge,
    getPresetModelMeta,
} from './preset-meta.js';

export function renderPresetList(page) {
    const list = page.$('#preset-list');
    if (!list) {
        return;
    }
    list.textContent = '';

    if (!page._presetDrafts.length) {
        list.appendChild(createElement('div', 'empty-state-text', '暂无预设，点击“新增”创建一个。'));
        return;
    }

    const fragment = document.createDocumentFragment();
    page._presetDrafts.forEach((preset, index) => {
        const provider = page._providersById.get(preset.provider_id) || null;
        const modelMeta = getPresetModelMeta(page, preset);
        const card = createElement('div', `preset-card${preset.name === page._activePreset ? ' active' : ''}`);
        const header = createElement('div', 'preset-card-header');
        const info = createElement('div', 'preset-info');
        const name = createElement('div', 'preset-name', preset.name || '未命名预设');
        if (preset.name === page._activePreset) {
            name.appendChild(createElement('span', 'config-save-feedback-badge live', '当前激活'));
        }
        info.appendChild(name);

        const meta = createElement('div', 'preset-meta');
        meta.appendChild(createElement('span', 'meta-item', provider?.label || preset.provider_id || '--'));
        meta.appendChild(createElement('span', 'meta-separator', '·'));
        meta.appendChild(createElement('span', 'meta-item model-name', preset.model || '--'));
        if (modelMeta) {
            meta.appendChild(createModelKindBadge(modelMeta));
        }
        info.appendChild(meta);

        const detail = createElement('div', 'ping-result', preset.api_key_required === false ? '无需 API Key' : (preset.api_key_configured ? '已配置 API Key' : '未配置 API Key'));
        info.appendChild(detail);
        header.appendChild(info);
        card.appendChild(header);

        const actions = createElement('div', 'preset-card-actions');
        const useButton = createElement('button', 'btn btn-secondary btn-sm', preset.name === page._activePreset ? '已启用' : '设为当前');
        useButton.type = 'button';
        useButton.disabled = preset.name === page._activePreset;
        useButton.addEventListener('click', () => {
            page._activePreset = preset.name;
            page._renderPresetList();
            page._renderHero();
            page._scheduleAutoSave({ immediate: true });
        });

        const testButton = createElement('button', 'btn btn-secondary btn-sm', '测试');
        testButton.type = 'button';
        testButton.addEventListener('click', () => void page._testPreset(index, detail));

        const editButton = createElement('button', 'btn btn-primary btn-sm', '编辑');
        editButton.type = 'button';
        editButton.addEventListener('click', () => page._openPresetModal(index));

        actions.appendChild(useButton);
        actions.appendChild(testButton);
        actions.appendChild(editButton);
        if (page._presetDrafts.length > 1) {
            const deleteButton = createElement('button', 'btn btn-secondary btn-sm', '删除');
            deleteButton.type = 'button';
            deleteButton.addEventListener('click', () => page._removePreset(index));
            actions.appendChild(deleteButton);
        }
        card.appendChild(actions);
        fragment.appendChild(card);
    });

    list.appendChild(fragment);
}
