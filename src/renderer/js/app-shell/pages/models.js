export function renderModelsPageShell() {
    return `
                <div class="page-header">
                    <div class="page-heading">
                        <h1 class="page-title">模型中心</h1>
                    </div>
                    <div class="page-actions">
                        <button class="btn btn-secondary btn-sm" id="btn-model-auth-refresh" type="button">
                            <svg class="icon icon-sm">
                                <use href="#icon-refresh" />
                            </svg>
                            <span>重新检查</span>
                        </button>
                        <button class="btn btn-secondary btn-sm" id="btn-model-auth-scan" type="button">
                            <svg class="icon icon-sm">
                                <use href="#icon-search" />
                            </svg>
                            <span>扫描本机登录</span>
                        </button>
                    </div>
                </div>

                <div class="config-save-feedback" id="model-auth-feedback" hidden>
                    <div class="config-save-feedback-summary" id="model-auth-feedback-summary">最近一次模型操作结果会显示在这里</div>
                    <div class="config-save-feedback-meta" id="model-auth-feedback-meta"></div>
                    <div class="config-save-feedback-groups" id="model-auth-feedback-groups"></div>
                </div>

                <div class="settings-container models-settings-container">
                    <div class="model-center-layout">
                        <aside class="settings-card model-center-sidebar">
                            <div class="model-center-sidebar-header">
                                <div>
                                    <div class="models-card-kicker">服务方</div>
                                    <h2 class="settings-card-title">接入服务方</h2>
                                </div>
                                <div class="model-center-filter-row" id="model-auth-filter-row"></div>
                            </div>
                            <label class="search-wrapper model-center-search">
                                <svg class="icon icon-sm">
                                    <use href="#icon-search" />
                                </svg>
                                <input class="search-input" id="model-auth-provider-search" type="search" placeholder="搜索服务方">
                            </label>
                            <div class="model-center-sidebar-meta" id="model-auth-sidebar-meta">加载中...</div>
                            <div class="model-center-provider-list" id="model-auth-provider-grid">
                                <div class="loading-state">
                                    <div class="spinner"></div>
                                    <span>加载服务方中...</span>
                                </div>
                            </div>
                        </aside>

                        <div class="model-center-main">
                            <div id="model-auth-hero">
                                <div class="settings-card model-center-summary-bar shell-placeholder-state">
                                    <div class="model-center-summary-empty">加载模型中心中...</div>
                                </div>
                            </div>

                            <div class="settings-card model-center-detail" id="model-auth-detail-panel">
                                <div class="loading-state">
                                    <div class="spinner"></div>
                                    <span>加载详情中...</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <button class="btn btn-primary btn-sm settings-scroll-top" id="btn-model-auth-scroll-top" type="button">
                    回到顶部
                </button>

`;
}

export default renderModelsPageShell;

