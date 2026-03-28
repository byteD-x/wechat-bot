import { PageController } from '../core/PageController.js';
import { Events } from '../core/EventBus.js';
import { apiService } from '../services/ApiService.js';
import { toast } from '../services/NotificationService.js';
import { renderExportCenterPageShell } from '../app-shell/pages/index.js';

const CHAT_EXPORT_SUBDIR = '聊天记录';

function formatDateTime(value) {
    if (!value) {
        return '--';
    }
    const date = new Date(Number(value) * 1000);
    if (Number.isNaN(date.getTime())) {
        return '--';
    }
    return date.toLocaleString('zh-CN', { hour12: false });
}

function setElementText(element, text) {
    if (!element) {
        return;
    }
    element.textContent = String(text ?? '');
}

function joinPath(basePath, segment) {
    const base = String(basePath || '').trim().replace(/[\\/]+$/, '');
    if (!base) {
        return segment;
    }
    const separator = base.includes('\\') ? '\\' : '/';
    return `${base}${separator}${segment}`;
}

export function resolveRagDirFromExportResult(result, fallbackOutputDir = '') {
    const serverRagDir = String(result?.rag_dir || '').trim();
    if (serverRagDir) {
        return serverRagDir;
    }
    const outputDir = String(result?.output_dir || fallbackOutputDir || '').trim();
    if (!outputDir) {
        return '';
    }
    return joinPath(outputDir, CHAT_EXPORT_SUBDIR);
}

export class ExportCenterPage extends PageController {
    constructor() {
        super('ExportCenterPage', 'page-exports');
        this._probeAccounts = [];
        this._decryptJobId = '';
        this._contacts = [];
        this._selectedContacts = new Set();
        this._config = null;
        this._busy = false;
        this._decryptPolling = false;
    }

    async onInit() {
        await super.onInit();
        const container = this.container || (typeof document !== 'undefined' ? this.getContainer() : null);
        if (container) {
            container.innerHTML = renderExportCenterPageShell();
        }
        this._bindEvents();
        this.watchState('bot.status', () => {
            if (this.isActive()) {
                this._renderRuntimeStatus();
            }
        });
    }

    async onEnter() {
        await super.onEnter();
        await this._loadConfig();
        this._syncRagSwitchState();
        this._renderRuntimeStatus();
        if (!this._probeAccounts.length) {
            await this._probe();
        }
    }

    _bindEvents() {
        this.bindEvent('#btn-export-refresh-status', 'click', () => {
            this.emit(Events.BOT_STATUS_CHANGE, { force: true });
            this._renderRuntimeStatus();
        });
        this.bindEvent('#btn-export-probe', 'click', () => {
            void this._probe();
        });
        this.bindEvent('#export-rag-enabled', 'change', () => {
            this._syncRagSwitchState();
        });
        this.bindEvent('#export-account-select', 'change', () => {
            this._syncSelectedAccount();
        });
        this.bindEvent('#btn-export-start-decrypt', 'click', () => {
            void this._startDecrypt();
        });
        this.bindEvent('#btn-export-refresh-job', 'click', () => {
            void this._refreshDecryptJob();
        });
        this.bindEvent('#btn-export-load-contacts', 'click', () => {
            void this._loadContacts();
        });
        this.bindEvent('#btn-export-select-all', 'click', () => {
            this._selectAllContacts();
        });
        this.bindEvent('#btn-export-clear-select', 'click', () => {
            this._clearSelectedContacts();
        });
        this.bindEvent('#btn-export-run', 'click', () => {
            void this._runExport();
        });
        this.bindEvent('#btn-export-preview-apply', 'click', () => {
            void this._previewApply();
        });
        this.bindEvent('#btn-export-apply', 'click', () => {
            void this._apply();
        });
    }

    async _loadConfig() {
        try {
            const result = await apiService.getConfig();
            if (!result?.success) {
                return;
            }
            this._config = result;
            const bot = result.bot || {};
            const defaultDataDir = 'data/chat_exports/聊天记录';
            if (this.$('#export-rag-enabled')) {
                this.$('#export-rag-enabled').checked = !!bot.rag_enabled;
            }
            if (this.$('#export-rag-config-enabled')) {
                this.$('#export-rag-config-enabled').checked = bot.export_rag_enabled !== false;
            }
            if (this.$('#export-rag-auto-ingest')) {
                this.$('#export-rag-auto-ingest').checked = bot.export_rag_auto_ingest !== false;
            }
            if (this.$('#export-rag-dir')) {
                this.$('#export-rag-dir').value = String(bot.export_rag_dir || defaultDataDir);
            }
            if (this.$('#export-rag-top-k')) {
                this.$('#export-rag-top-k').value = Number(bot.export_rag_top_k || 3);
            }
            if (this.$('#export-rag-max-chunks')) {
                this.$('#export-rag-max-chunks').value = Number(bot.export_rag_max_chunks_per_chat || 500);
            }
            if (this.$('#export-rag-embedding-model')) {
                this.$('#export-rag-embedding-model').value = String(bot.vector_memory_embedding_model || '');
            }
            this._syncRagSwitchState();
        } catch (_) {
            // Keep local defaults when config read fails.
        }
    }

    _syncRagSwitchState() {
        const globalToggle = this.$('#export-rag-enabled');
        const exportToggle = this.$('#export-rag-config-enabled');
        if (!globalToggle || !exportToggle) {
            return;
        }
        const ragEnabled = !!globalToggle.checked;
        exportToggle.disabled = !ragEnabled;
        if (!ragEnabled) {
            exportToggle.checked = false;
        }
    }

    async _probe() {
        if (this._busy) {
            return;
        }
        this._busy = true;
        try {
            const result = await apiService.probeWechatExport();
            if (!result?.success) {
                throw new Error(result?.message || '探测失败');
            }
            this._probeAccounts = Array.isArray(result.accounts) ? result.accounts : [];
            this._renderProbeSummary(result);
            this._renderAccountOptions();
            toast.success(`探测完成：发现 ${this._probeAccounts.length} 个账号`);
        } catch (error) {
            toast.error(toast.getErrorMessage(error, '探测失败，请检查微信是否登录'));
        } finally {
            this._busy = false;
        }
    }

    _renderProbeSummary(result) {
        const warningText = Array.isArray(result?.warnings) && result.warnings.length
            ? `\n警告：${result.warnings.join(' | ')}`
            : '';
        setElementText(
            this.$('#export-probe-summary'),
            `依赖就绪：${result?.dependency_ready ? '是' : '否'}，账号数量：${this._probeAccounts.length}${warningText}`,
        );
    }

    _renderAccountOptions() {
        const select = this.$('#export-account-select');
        if (!select) {
            return;
        }
        select.textContent = '';
        const placeholder = document.createElement('option');
        placeholder.value = '';
        placeholder.textContent = this._probeAccounts.length ? '请选择账号' : '未检测到可用账号';
        select.appendChild(placeholder);

        this._probeAccounts.forEach((item) => {
            const option = document.createElement('option');
            option.value = String(item.probe_ref || '');
            const label = item.name || item.account || item.wxid || '未命名账号';
            option.textContent = item.has_key ? `${label}（可解密）` : `${label}（缺少密钥）`;
            select.appendChild(option);
        });

        if (this._probeAccounts.length) {
            select.value = String(this._probeAccounts[0].probe_ref || '');
            this._syncSelectedAccount();
        }
    }

    _syncSelectedAccount() {
        const select = this.$('#export-account-select');
        if (!select) {
            return;
        }
        const probeRef = String(select.value || '').trim();
        const account = this._probeAccounts.find((item) => String(item.probe_ref || '') === probeRef);
        if (!account) {
            return;
        }
        if (this.$('#export-src-dir')) {
            this.$('#export-src-dir').value = String(account.db_dir_hint || '');
        }
        if (this.$('#export-dest-dir')) {
            const wxid = String(account.wxid || 'unknown').trim() || 'unknown';
            this.$('#export-dest-dir').value = `data/decrypted_wechat/${wxid}/Msg`;
        }
    }

    async _startDecrypt() {
        try {
            const accountRef = String(this.$('#export-account-select')?.value || '').trim();
            const payload = {
                probe_ref: accountRef,
                db_version: Number(this.$('#export-db-version')?.value || 4),
                src_dir: String(this.$('#export-src-dir')?.value || '').trim(),
                dest_dir: String(this.$('#export-dest-dir')?.value || '').trim(),
            };
            const result = await apiService.startWechatExportDecrypt(payload);
            if (!result?.success) {
                throw new Error(result?.message || '启动解密失败');
            }
            this._decryptJobId = String(result.job_id || '').trim();
            this._renderDecryptStatus(result);
            toast.success('解密任务已启动');
            void this._pollDecryptJobUntilDone();
        } catch (error) {
            toast.error(toast.getErrorMessage(error, '启动解密失败'));
        }
    }

    async _refreshDecryptJob() {
        if (!this._decryptJobId) {
            toast.warning('请先启动解密任务');
            return;
        }
        try {
            const result = await apiService.getWechatExportDecryptJob(this._decryptJobId);
            if (!result?.success) {
                throw new Error(result?.message || '读取解密进度失败');
            }
            this._renderDecryptStatus(result);
            if (String(result.status || '') === 'succeeded') {
                this._handleDecryptSucceeded(result);
            }
        } catch (error) {
            toast.error(toast.getErrorMessage(error, '查询解密进度失败'));
        }
    }

    _handleDecryptSucceeded(result, withToast = false) {
        if (this.$('#export-src-dir')) {
            this.$('#export-src-dir').value = String(result.dest_dir || '');
        }
        if (withToast) {
            toast.success(`解密完成：共 ${Number(result.decrypted_db_files || 0)} 个数据库文件`);
        }
    }

    async _pollDecryptJobUntilDone() {
        if (this._decryptPolling || !this._decryptJobId) {
            return;
        }
        this._decryptPolling = true;
        let reachedTerminalStatus = false;
        try {
            for (let attempt = 0; attempt < 120; attempt += 1) {
                const result = await apiService.getWechatExportDecryptJob(this._decryptJobId);
                if (!result?.success) {
                    break;
                }
                this._renderDecryptStatus(result);
                const status = String(result.status || '');
                if (status === 'succeeded') {
                    reachedTerminalStatus = true;
                    this._handleDecryptSucceeded(result, true);
                    return;
                }
                if (status === 'failed') {
                    reachedTerminalStatus = true;
                    toast.error(String(result.error || '解密失败'));
                    return;
                }
                await new Promise((resolve) => {
                    setTimeout(resolve, 1500);
                });
            }
            if (!reachedTerminalStatus) {
                toast.info('解密仍在进行，请稍后点击“查询解密进度”继续查看。');
            }
        } catch (_) {
            // Keep manual refresh available when polling fails.
        } finally {
            this._decryptPolling = false;
        }
    }

    _renderDecryptStatus(job) {
        const status = String(job?.status || '--');
        const startedAt = job?.started_at ? formatDateTime(job.started_at) : '--';
        const finishedAt = job?.finished_at ? formatDateTime(job.finished_at) : '--';
        const detail = [
            `任务：${job?.job_id || '--'}`,
            `状态：${status}`,
            `阶段：${job?.stage || '--'}`,
            `解密数据库：${Number(job?.decrypted_db_files || 0)}`,
            `开始：${startedAt}`,
            `结束：${finishedAt}`,
            job?.error ? `错误：${job.error}` : '',
        ].filter(Boolean).join(' | ');
        setElementText(this.$('#export-decrypt-status'), detail);
    }

    async _loadContacts() {
        try {
            const payload = {
                db_dir: String(this.$('#export-src-dir')?.value || '').trim(),
                db_version: Number(this.$('#export-db-version')?.value || 4),
                include_chatrooms: !!this.$('#export-include-chatrooms')?.checked,
                keyword: String(this.$('#export-contact-keyword')?.value || '').trim(),
            };
            const result = await apiService.listWechatExportContacts(payload);
            if (!result?.success) {
                throw new Error(result?.message || '读取联系人失败');
            }
            this._contacts = Array.isArray(result.contacts) ? result.contacts : [];
            this._selectedContacts.clear();
            this._renderContacts();
            this._updateSelectedCount();
            toast.success(`读取联系人成功：${this._contacts.length} 个`);
        } catch (error) {
            toast.error(toast.getErrorMessage(error, '读取联系人失败'));
        }
    }

    _renderContacts() {
        const container = this.$('#export-contact-list');
        if (!container) {
            return;
        }
        container.textContent = '';
        if (!this._contacts.length) {
            container.innerHTML = `
                <div class="empty-state compact-empty">
                    <span class="empty-state-text">没有可导出的联系人</span>
                </div>
            `;
            return;
        }

        this._contacts.forEach((contact) => {
            const row = document.createElement('label');
            row.className = 'export-contact-row';
            const wxid = String(contact.wxid || '').trim();
            row.innerHTML = `
                <input type="checkbox" data-contact-wxid="${wxid}">
                <span class="export-contact-name">${contact.display_name || wxid}</span>
                <span class="export-contact-meta">${wxid}${contact.is_chatroom ? ' · 群聊' : ''}</span>
            `;
            const checkbox = row.querySelector('input[type="checkbox"]');
            if (checkbox) {
                checkbox.addEventListener('change', () => {
                    if (checkbox.checked) {
                        this._selectedContacts.add(wxid);
                    } else {
                        this._selectedContacts.delete(wxid);
                    }
                    this._updateSelectedCount();
                });
            }
            container.appendChild(row);
        });
    }

    _selectAllContacts() {
        this.$$('#export-contact-list input[type="checkbox"]').forEach((checkbox) => {
            checkbox.checked = true;
            const wxid = String(checkbox.dataset.contactWxid || '').trim();
            if (wxid) {
                this._selectedContacts.add(wxid);
            }
        });
        this._updateSelectedCount();
    }

    _clearSelectedContacts() {
        this.$$('#export-contact-list input[type="checkbox"]').forEach((checkbox) => {
            checkbox.checked = false;
        });
        this._selectedContacts.clear();
        this._updateSelectedCount();
    }

    _updateSelectedCount() {
        setElementText(this.$('#export-selected-count'), `已选 ${this._selectedContacts.size} 个联系人。`);
    }

    async _runExport() {
        if (!this._selectedContacts.size) {
            toast.warning('请先选择至少一个联系人');
            return;
        }
        try {
            const outputDir = String(this.$('#export-output-dir')?.value || '').trim();
            const start = String(this.$('#export-start-time')?.value || '').trim();
            const end = String(this.$('#export-end-time')?.value || '').trim();
            const payload = {
                db_dir: String(this.$('#export-src-dir')?.value || '').trim(),
                db_version: Number(this.$('#export-db-version')?.value || 4),
                include_chatrooms: !!this.$('#export-include-chatrooms')?.checked,
                output_dir: outputDir,
                start,
                end,
                contacts: Array.from(this._selectedContacts),
            };
            const result = await apiService.runWechatExport(payload);
            if (!result?.success) {
                throw new Error(result?.message || '导出失败');
            }

            const normalizedOutputDir = String(result.output_dir || outputDir || '').trim();
            const ragDir = resolveRagDirFromExportResult(result, outputDir);
            if (normalizedOutputDir && this.$('#export-output-dir')) {
                this.$('#export-output-dir').value = normalizedOutputDir;
            }
            if (ragDir && this.$('#export-rag-dir')) {
                this.$('#export-rag-dir').value = ragDir;
            }
            toast.success(`导出完成：${Number(result.exported_contacts || 0)} 个联系人`);
        } catch (error) {
            toast.error(toast.getErrorMessage(error, '导出失败'));
        }
    }

    _collectApplySettings() {
        const globalRagEnabled = !!this.$('#export-rag-enabled')?.checked;
        const exportRagEnabled = this.$('#export-rag-config-enabled')
            ? !!this.$('#export-rag-config-enabled')?.checked
            : globalRagEnabled;
        return {
            rag_enabled: globalRagEnabled,
            export_rag_enabled: exportRagEnabled,
            export_rag_auto_ingest: !!this.$('#export-rag-auto-ingest')?.checked,
            export_rag_dir: String(this.$('#export-rag-dir')?.value || '').trim(),
            export_rag_top_k: Number(this.$('#export-rag-top-k')?.value || 3),
            export_rag_max_chunks_per_chat: Number(this.$('#export-rag-max-chunks')?.value || 500),
            vector_memory_embedding_model: String(this.$('#export-rag-embedding-model')?.value || '').trim(),
        };
    }

    async _previewApply() {
        try {
            const result = await apiService.previewWechatExportApply({
                settings: this._collectApplySettings(),
            });
            if (!result?.success) {
                throw new Error(result?.message || '预览失败');
            }
            if (this.$('#export-apply-preview')) {
                this.$('#export-apply-preview').textContent = JSON.stringify(result, null, 2);
            }
            toast.success(`预览完成：${Number(result.changed_count || 0)} 处变更`);
        } catch (error) {
            toast.error(toast.getErrorMessage(error, '预览失败'));
        }
    }

    async _apply() {
        try {
            const result = await apiService.applyWechatExport({
                settings: this._collectApplySettings(),
                run_sync: true,
            });
            if (!result?.success) {
                throw new Error(result?.message || '应用失败');
            }
            if (this.$('#export-apply-preview')) {
                this.$('#export-apply-preview').textContent = JSON.stringify(result, null, 2);
            }
            this.emit(Events.BOT_STATUS_CHANGE, { force: true });
            this._renderRuntimeStatus();
            toast.success('已应用到系统，并触发导出语料同步');
        } catch (error) {
            toast.error(toast.getErrorMessage(error, '应用失败'));
        }
    }

    _renderRuntimeStatus() {
        const status = this.getState('bot.status') || {};
        const exportRag = status.export_rag || {};
        const summary = exportRag.last_scan_summary || {};
        const text = [
            `导出RAG启用：${exportRag.enabled ? '是' : '否'}`,
            `索引联系人：${Number(exportRag.indexed_contacts || 0)}`,
            `索引片段：${Number(exportRag.indexed_chunks || 0)}`,
            summary.reason ? `最近扫描：${summary.reason}` : '',
        ].filter(Boolean).join(' | ');
        setElementText(this.$('#export-runtime-status'), text || '运行状态未加载。');
    }
}

export default ExportCenterPage;
