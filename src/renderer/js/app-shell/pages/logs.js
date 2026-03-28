export function renderLogsPageShell() {
    return `
                <div class="page-header">
                    <div class="page-heading">
                        <span class="page-kicker">诊断时间线</span>
                        <h1 class="page-title">系统日志</h1>
                        <p class="page-subtitle">筛选异常、回看关键阶段，并在需要时复制或导出当前日志片段。</p>
                    </div>
                    <div class="page-actions log-actions">
                        <div class="search-wrapper log-search-field">
                            <svg class="icon">
                                <use href="#icon-search" />
                            </svg>
                            <input type="text" class="search-input" placeholder="搜索关键字..." id="log-search">
                        </div>
                        <select class="form-input log-compact-select" id="log-level">
                            <option value="">全部</option>
                            <option value="error">错误</option>
                            <option value="warning">警告</option>
                            <option value="info">信息</option>
                            <option value="send">发送</option>
                            <option value="receive">接收</option>
                        </select>
                        <select class="form-input log-compact-select" id="log-lines">
                            <option value="200">200行</option>
                            <option value="500" selected>500行</option>
                            <option value="1000">1000行</option>
                        </select>
                        <label class="form-checkbox">
                            <input type="checkbox" id="setting-auto-scroll" checked>
                            <span class="form-checkbox-label">自动滚动</span>
                        </label>
                        <label class="form-checkbox">
                            <input type="checkbox" id="setting-auto-refresh" checked>
                            <span class="form-checkbox-label">自动刷新</span>
                        </label>
                        <label class="form-checkbox">
                            <input type="checkbox" id="setting-wrap" checked>
                            <span class="form-checkbox-label">自动换行</span>
                        </label>
                        <button class="btn btn-secondary btn-sm" id="btn-clear-logs">
                            <svg class="icon icon-sm">
                                <use href="#icon-trash" />
                            </svg>
                            <span>清空</span>
                        </button>
                        <button class="btn btn-secondary btn-sm" id="btn-refresh-logs">
                            <svg class="icon icon-sm">
                                <use href="#icon-refresh" />
                            </svg>
                            <span>刷新</span>
                        </button>
                        <button class="btn btn-secondary btn-sm" id="btn-reset-log-filters">
                            <span>重置筛选</span>
                        </button>
                        <button class="btn btn-secondary btn-sm" id="btn-copy-logs">
                            <svg class="icon icon-sm">
                                <use href="#icon-file-text" />
                            </svg>
                            <span>复制</span>
                        </button>
                        <button class="btn btn-secondary btn-sm" id="btn-export-logs">
                            <svg class="icon icon-sm">
                                <use href="#icon-save" />
                            </svg>
                            <span>导出</span>
                        </button>
                        <button class="btn btn-ghost btn-sm" id="btn-restore-log-default-view">
                            <span>恢复默认视图</span>
                        </button>
                    </div>
                </div>

                <div class="log-meta">
                    <div class="log-meta-left">
                        <span class="log-meta-item" id="log-count">0 行</span>
                        <span class="log-meta-sep">·</span>
                        <span class="log-meta-item" id="log-visible-count">0 匹配</span>
                    </div>
                    <div class="log-meta-right">
                        <span class="log-meta-item">上次更新</span>
                        <span class="log-meta-value" id="log-updated">--</span>
                    </div>
                </div>

                <div class="log-container">
                    <pre class="log-content" id="log-content">等待日志加载...</pre>
                </div>
`;
}

export default renderLogsPageShell;

