export function renderCostsPageShell() {
    return `
                <div class="page-header">
                    <div class="page-heading">
                        <span class="page-kicker">成本与复盘</span>
                        <h1 class="page-title">成本管理</h1>
                        <p class="page-subtitle">按时间、模型和处理建议收束成本数据，直接定位需要复盘的会话。</p>
                    </div>
                    <div class="page-actions">
                        <button class="btn btn-secondary btn-sm" id="btn-refresh-pricing">
                            <svg class="icon icon-sm">
                                <use href="#icon-refresh" />
                            </svg>
                            <span>刷新价格目录</span>
                        </button>
                        <button class="btn btn-primary btn-sm" id="btn-refresh-costs">
                            <svg class="icon icon-sm">
                                <use href="#icon-bar-chart" />
                            </svg>
                            <span>刷新数据</span>
                        </button>
                        <button class="btn btn-secondary btn-sm" id="btn-export-cost-review">
                            <svg class="icon icon-sm">
                                <use href="#icon-download" />
                            </svg>
                            <span>导出复盘</span>
                        </button>
                        <button class="btn btn-ghost btn-sm" id="btn-reset-cost-filters">
                            <span>恢复默认筛选</span>
                        </button>
                    </div>
                </div>

                <div class="toolbar-meta cost-toolbar-meta">
                    <span class="toolbar-meta-item" id="cost-filter-summary">当前筛选：近 30 天</span>
                    <span class="toolbar-meta-item toolbar-meta-value" id="cost-last-updated">尚未刷新</span>
                </div>

                <div class="cost-filter-bar">
                    <div class="cost-filter-group">
                        <label class="form-label" for="cost-period">时间范围</label>
                        <select class="form-input" id="cost-period">
                            <option value="today">今天</option>
                            <option value="7d">近 7 天</option>
                            <option value="30d" selected>近 30 天</option>
                            <option value="all">全部</option>
                        </select>
                    </div>
                    <div class="cost-filter-group">
                        <label class="form-label" for="cost-provider">服务方</label>
                        <select class="form-input" id="cost-provider">
                            <option value="">全部服务方</option>
                        </select>
                    </div>
                    <div class="cost-filter-group">
                        <label class="form-label" for="cost-model">模型</label>
                        <select class="form-input" id="cost-model">
                            <option value="">全部模型</option>
                        </select>
                    </div>
                    <div class="cost-filter-group">
                        <label class="form-label" for="cost-preset">预设</label>
                        <select class="form-input" id="cost-preset">
                            <option value="">全部预设</option>
                        </select>
                    </div>
                    <div class="cost-filter-group">
                        <label class="form-label" for="cost-review-reason">复盘原因</label>
                        <select class="form-input" id="cost-review-reason">
                            <option value="">全部原因</option>
                        </select>
                    </div>
                    <div class="cost-filter-group">
                        <label class="form-label" for="cost-suggested-action">处理建议</label>
                        <select class="form-input" id="cost-suggested-action">
                            <option value="">全部建议</option>
                        </select>
                    </div>
                    <label class="cost-toggle-row" for="cost-only-priced">
                        <input type="checkbox" id="cost-only-priced">
                        <span>仅已定价</span>
                    </label>
                    <label class="cost-toggle-row" for="cost-include-estimated">
                        <input type="checkbox" id="cost-include-estimated" checked>
                        <span>包含估算数据</span>
                    </label>
                </div>

                <div class="cost-kpi-grid" id="cost-overview">
                    <div class="loading-state">
                        <div class="spinner"></div>
                        <span>加载中...</span>
                    </div>
                </div>

                <div class="card">
                    <div class="card-header">
                        <h2 class="card-title">模型汇总</h2>
                    </div>
                    <div class="card-body">
                        <div id="cost-models">
                            <div class="loading-state">
                                <div class="spinner"></div>
                                <span>加载中...</span>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="card cost-session-card">
                    <div class="card-header">
                        <h2 class="card-title">低质量回复复盘</h2>
                    </div>
                    <div class="card-body">
                        <div id="cost-review-list">
                            <div class="loading-state">
                                <div class="spinner"></div>
                                <span>加载中...</span>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="card cost-session-card">
                    <div class="card-header">
                        <h2 class="card-title">会话明细</h2>
                    </div>
                    <div class="card-body">
                        <div id="cost-sessions">
                            <div class="loading-state">
                                <div class="spinner"></div>
                                <span>加载中...</span>
                            </div>
                        </div>
                    </div>
                </div>
`;
}

export default renderCostsPageShell;

