import { PageController } from '../core/PageController.js';
import { toast } from '../services/NotificationService.js';

const FALLBACK_OPEN_OPTIONS = 'noopener,noreferrer';

export class AboutPage extends PageController {
    constructor() {
        super('AboutPage', 'page-about');
    }

    async onInit() {
        await super.onInit();
        this._bindEvents();
    }

    _bindEvents() {
        this.$$('.about-link-card').forEach(card => {
            this.bindEvent(card, 'click', () => {
                void this._openLinkCard(card);
            });
        });
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
                await window.electronAPI.openExternal(url);
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
