export function renderExportCenterPageShell() {
    return `
                <div class="page-header">
                    <div class="page-heading">
                        <span class="page-kicker">聊天导出接入</span>
                        <h1 class="page-title">微信聊天导出中心</h1>
                        <p class="page-subtitle">按步骤完成自动解密、联系人导出和一键应用。全流程可视化，不需要手敲命令。</p>
                    </div>
                    <div class="page-actions">
                        <button class="btn btn-secondary btn-sm" id="btn-export-refresh-status" type="button">
                            <svg class="icon icon-sm">
                                <use href="#icon-refresh" />
                            </svg>
                            <span>刷新状态</span>
                        </button>
                    </div>
                </div>

                <div class="export-center-grid">
                    <section class="export-card">
                        <div class="export-card-head">
                            <h2 class="export-card-title">1. 探测微信与准备解密</h2>
                            <button class="btn btn-secondary btn-sm" id="btn-export-probe" type="button">重新探测</button>
                        </div>
                        <p class="export-card-text" id="export-probe-summary">尚未探测。</p>
                        <div class="export-form-grid">
                            <div class="form-group">
                                <label class="form-label">检测到的账号</label>
                                <select id="export-account-select" class="form-input">
                                    <option value="">请先探测</option>
                                </select>
                            </div>
                            <div class="form-group">
                                <label class="form-label">数据库版本</label>
                                <select id="export-db-version" class="form-input">
                                    <option value="4">4</option>
                                    <option value="3">3</option>
                                </select>
                            </div>
                            <div class="form-group full-width">
                                <label class="form-label">源目录（已加密 Msg）</label>
                                <input id="export-src-dir" class="form-input" type="text" placeholder="例如：C:\\Users\\你的用户名\\Documents\\WeChat Files\\wxid_xxx\\Msg">
                            </div>
                            <div class="form-group full-width">
                                <label class="form-label">解密输出目录</label>
                                <input id="export-dest-dir" class="form-input" type="text" placeholder="默认 data/decrypted_wechat/<wxid>/Msg">
                            </div>
                        </div>
                        <div class="export-actions">
                            <button class="btn btn-primary btn-sm" id="btn-export-start-decrypt" type="button">开始解密</button>
                            <button class="btn btn-secondary btn-sm" id="btn-export-refresh-job" type="button">查询解密进度</button>
                        </div>
                        <div class="export-help" id="export-decrypt-status">尚未启动解密。</div>
                    </section>

                    <section class="export-card">
                        <div class="export-card-head">
                            <h2 class="export-card-title">2. 选择联系人并导出 CSV</h2>
                            <button class="btn btn-secondary btn-sm" id="btn-export-load-contacts" type="button">读取联系人</button>
                        </div>
                        <div class="export-form-grid">
                            <div class="form-group">
                                <label class="form-label">筛选关键词</label>
                                <input id="export-contact-keyword" class="form-input" type="text" placeholder="昵称 / 备注 / wxid">
                            </div>
                            <div class="form-group">
                                <label class="form-checkbox form-checkbox-inline">
                                    <input id="export-include-chatrooms" type="checkbox">
                                    <span class="form-checkbox-label">包含群聊</span>
                                </label>
                            </div>
                            <div class="form-group full-width">
                                <label class="form-label">导出目录</label>
                                <input id="export-output-dir" class="form-input" type="text" placeholder="默认 data/chat_exports">
                            </div>
                            <div class="form-group">
                                <label class="form-label">起始时间（可选）</label>
                                <input id="export-start-time" class="form-input" type="text" placeholder="2024-01-01 00:00:00">
                            </div>
                            <div class="form-group">
                                <label class="form-label">结束时间（可选）</label>
                                <input id="export-end-time" class="form-input" type="text" placeholder="2025-12-31 23:59:59">
                            </div>
                        </div>
                        <div class="export-actions">
                            <button class="btn btn-secondary btn-sm" id="btn-export-select-all" type="button">全选</button>
                            <button class="btn btn-secondary btn-sm" id="btn-export-clear-select" type="button">清空</button>
                            <button class="btn btn-primary btn-sm" id="btn-export-run" type="button">导出选中联系人</button>
                        </div>
                        <div class="export-help" id="export-selected-count">已选 0 个联系人。</div>
                        <div class="export-contact-list" id="export-contact-list">
                            <div class="empty-state compact-empty">
                                <span class="empty-state-text">请先读取联系人</span>
                            </div>
                        </div>
                    </section>

                    <section class="export-card export-card-wide">
                        <div class="export-card-head">
                            <h2 class="export-card-title">3. 预览并应用到系统</h2>
                            <span class="export-chip">建议：先预览再应用</span>
                        </div>
                        <div class="export-form-grid">
                            <div class="form-group">
                                <label class="form-checkbox form-checkbox-inline">
                                    <input id="export-rag-enabled" type="checkbox" checked>
                                    <span class="form-checkbox-label">启用运行期 RAG 总开关</span>
                                </label>
                            </div>
                            <div class="form-group">
                                <label class="form-checkbox form-checkbox-inline">
                                    <input id="export-rag-config-enabled" type="checkbox" checked>
                                    <span class="form-checkbox-label">启用导出语料检索通道</span>
                                </label>
                            </div>
                            <div class="form-group">
                                <label class="form-checkbox form-checkbox-inline">
                                    <input id="export-rag-auto-ingest" type="checkbox" checked>
                                    <span class="form-checkbox-label">自动扫描并增量导入</span>
                                </label>
                            </div>
                            <div class="form-group full-width">
                                <label class="form-label">导出语料目录</label>
                                <input id="export-rag-dir" class="form-input" type="text" placeholder="data/chat_exports/聊天记录">
                            </div>
                            <div class="form-group">
                                <label class="form-label">每次注入片段数</label>
                                <input id="export-rag-top-k" class="form-input" type="number" min="1" step="1" value="3">
                            </div>
                            <div class="form-group">
                                <label class="form-label">每联系人最大片段数</label>
                                <input id="export-rag-max-chunks" class="form-input" type="number" min="1" step="1" value="500">
                            </div>
                            <div class="form-group full-width">
                                <label class="form-label">Embedding 模型（可选）</label>
                                <input id="export-rag-embedding-model" class="form-input" type="text" placeholder="留空则沿用当前配置">
                            </div>
                        </div>
                        <div class="export-actions">
                            <button class="btn btn-secondary btn-sm" id="btn-export-preview-apply" type="button">预览应用变更</button>
                            <button class="btn btn-primary btn-sm" id="btn-export-apply" type="button">一键应用到系统</button>
                        </div>
                        <pre class="export-preview" id="export-apply-preview">尚未生成预览。</pre>
                        <div class="export-help" id="export-runtime-status">运行状态未加载。</div>
                    </section>
                </div>
`;
}

export default renderExportCenterPageShell;
