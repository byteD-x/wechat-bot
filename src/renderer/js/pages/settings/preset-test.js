import { apiService } from '../../services/ApiService.js';
import { toast } from '../../services/NotificationService.js';
import { deepClone } from './form-codec.js';
import {
    getPresetByName,
    setHeroTestFeedback,
} from './preset-meta.js';

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
        const result = globalThis.window?.electronAPI?.testConfigConnection
            ? await globalThis.window.electronAPI.testConfigConnection({
                presetName: preset.name,
                patch: {
                    api: {
                        active_preset: page._activePresetName || page._activePreset,
                        presets: deepClone(page._apiPresetsSnapshot || page._presetDrafts || []),
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
        toast.error(`${preset.name}: ${errorMessage}`);
    }
}

export async function testPreset(page, index, detailElement) {
    const preset = (page._apiPresetsSnapshot || page._presetDrafts || [])[index];
    if (!preset?.name) {
        return;
    }
    await runPresetConnectionTest(page, preset, detailElement);
}
