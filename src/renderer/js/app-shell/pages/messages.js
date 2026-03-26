export function renderMessagesPageShell() {
    return `
                <div class="page-header">
                    <div class="page-heading">
                        <span class="page-kicker">会话回看</span>
                        <h1 class="page-title">消息中心</h1>
                        <p class="page-subtitle">筛选消息、回看上下文，并在右侧抽屉里继续处理联系人 Prompt 与待审批回复。</p>
                    </div>
                    <div class="page-actions">
                        <div class="search-wrapper">
                            <svg class="icon">
                                <use href="#icon-search" />
                            </svg>
                            <input type="text" class="search-input" placeholder="搜消息内容、会话或发送者" id="message-search">
                        </div>
                        <select id="message-chat-filter" class="message-chat-filter">
                            <option value="">全部会话</option>
                        </select>
                        <button class="btn btn-secondary btn-sm" id="btn-refresh-messages">
                            <svg class="icon icon-sm">
                                <use href="#icon-refresh" />
                            </svg>
                            <span>刷新</span>
                        </button>
                        <button class="btn btn-secondary btn-sm" id="btn-clear-message-filters">
                            <span>清空筛选</span>
                        </button>
                    </div>
                </div>

                <div class="message-toolbar-meta">
                    <span id="message-filter-summary">全部消息</span>
                    <span id="message-total-count">0/0 条</span>
                    <span id="message-last-updated">尚未刷新</span>
                </div>

                <div class="message-list full-height" id="all-messages">
                    <div class="loading-state">
                        <div class="spinner"></div>
                        <span>加载中...</span>
                    </div>
                </div>
                <div class="message-footer-actions">
                    <button class="btn btn-secondary btn-sm" id="btn-load-more-messages" hidden>
                        <span>加载更多</span>
                    </button>
                </div>
`;
}

export default renderMessagesPageShell;

