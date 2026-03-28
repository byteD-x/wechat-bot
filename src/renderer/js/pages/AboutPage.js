import { PageController } from '../core/PageController.js';
import { toast } from '../services/NotificationService.js';
import { checkUpdates, openUpdateDownload } from './settings/action-controller.js';
import { renderUpdatePanel } from './settings/renderers.js';
import { watchUpdatePanelState } from './settings/runtime-sync.js';
import { renderAboutPageShell } from '../app-shell/pages/index.js';

const FALLBACK_OPEN_OPTIONS = 'noopener,noreferrer';
const TEXT = {
    updateFailed: '检查更新失败',
};

export class AboutPage extends PageController {
    constructor() {
        super('AboutPage', 'page-about');
    }

    async onInit() {
        await super.onInit();
        const container = this.container || (typeof document !== 'undefined' ? this.getContainer() : null);
        if (container) {
            container.innerHTML = renderAboutPageShell();
        }
        this._bindEvents();
        this._watchUpdateState();
    }

    async onEnter() {
        await super.onEnter();
        this._renderUpdatePanel();
    }

    _bindEvents() {
        this.$$('.about-link-card').forEach(card => {
            this.bindEvent(card, 'click', () => {
                void this._openLinkCard(card);
            });
        });
        this.bindEvent('#btn-check-updates', 'click', () => void this._checkUpdates());
        this.bindEvent('#btn-open-update-download', 'click', () => void this._openUpdateDownload());
    }

    _watchUpdateState() {
        watchUpdatePanelState(this, () => this._renderUpdatePanel());
    }

    _renderUpdatePanel() {
        renderUpdatePanel(this);
    }

    async _checkUpdates() {
        await checkUpdates(this, TEXT, { updateSource: 'about-page' });
    }

    async _openUpdateDownload() {
        await openUpdateDownload(this);
    }

    async _openLinkCard(card) {
        const url = String(card?.dataset.url || '').trim();
        const label = String(card?.dataset.label || '外部链接').trim();

        if (!url) {
            toast.warning(`${label} 暂未配置链接`);
            return;
        }

        try {
            if (window.electronAPI?.openExternal) {
                const result = await window.electronAPI.openExternal(url);
                if (!result?.success) {
                    throw new Error(result?.error || 'open_external_failed');
                }
                return;
            }

            window.open(url, '_blank', FALLBACK_OPEN_OPTIONS);
        } catch (error) {
            console.error(`[AboutPage] 打开链接失败: ${label}`, error);
            toast.error(`打开${label}失败`);
        }
    }
}

export default AboutPage;
