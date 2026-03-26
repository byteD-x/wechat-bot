export function renderGlobalOverlays() {
    return `
    <div class="modal-overlay" id="first-run-modal">
        <div class="modal">
            <div class="modal-header">
                <div class="modal-copy">
                    <span class="modal-kicker">首次运行</span>
                    <h3 class="modal-title" id="first-run-title">还差几项准备</h3>
                    <p class="modal-subtitle" id="first-run-subtitle">先把这些阻塞项补齐，应用就能更稳定地跑起来。</p>
                </div>
                <button class="modal-close" id="btn-close-first-run-modal" type="button" aria-label="关闭首次运行引导">
                    <svg class="icon icon-sm">
                        <use href="#icon-x" />
                    </svg>
                </button>
            </div>
            <div class="modal-body">
                <div class="modal-callout">
                    <div class="first-run-summary" id="first-run-summary">正在检查当前环境，请稍候。</div>
                </div>
                <ul class="first-run-check-list" id="first-run-check-list"></ul>
            </div>
            <div class="modal-footer">
                <button class="btn btn-secondary btn-sm" id="btn-first-run-later" type="button">稍后再说</button>
                <button class="btn btn-secondary btn-sm" id="btn-first-run-settings" type="button">前往设置</button>
                <button class="btn btn-primary btn-sm" id="btn-first-run-retry" type="button">重新检查</button>
            </div>
        </div>
    </div>

    <div class="modal-overlay" id="close-choice-modal">
        <div class="modal">
            <div class="modal-header">
                <div class="modal-copy">
                    <span class="modal-kicker">应用行为</span>
                    <h3 class="modal-title">关闭应用</h3>
                    <p class="modal-subtitle">选择本次关闭方式，也可以记住偏好，减少后续打断。</p>
                </div>
                <button class="modal-close" id="btn-close-choice-modal" type="button" aria-label="关闭关闭应用弹窗">
                    <svg class="icon icon-sm">
                        <use href="#icon-x" />
                    </svg>
                </button>
            </div>
            <div class="modal-body">
                <div class="form-group full-width modal-callout">
                    <div class="modal-choice-title">请选择关闭方式</div>
                    <div class="modal-choice-status">当前状态：<span id="close-choice-status">--</span></div>
                </div>
                <div class="form-group full-width modal-choice-remember">
                    <label class="form-checkbox form-checkbox-inline">
                        <input type="checkbox" id="close-choice-remember">
                        <span class="form-checkbox-label">记住我的选择，下次不再提示</span>
                    </label>
                </div>
            </div>
            <div class="modal-footer">
                <button class="btn btn-secondary btn-sm" id="btn-close-choice-minimize">最小化到托盘</button>
                <button class="btn btn-primary btn-sm" id="btn-close-choice-quit">彻底关闭</button>
            </div>
        </div>
    </div>

    <div class="modal-overlay" id="update-modal">
        <div class="modal">
            <div class="modal-header">
                <div class="modal-copy">
                    <span class="modal-kicker">版本更新</span>
                    <h3 class="modal-title">发现应用更新</h3>
                    <p class="modal-subtitle">保持当前安装版为最新状态，下载完成后可以直接安装并重启。</p>
                </div>
                <button class="modal-close" id="btn-close-update-modal" type="button" aria-label="关闭更新弹窗">
                    <svg class="icon icon-sm">
                        <use href="#icon-x" />
                    </svg>
                </button>
            </div>
            <div class="modal-body">
                <div class="detail-group">
                    <div class="detail-group-title">更新状态</div>
                    <div class="update-modal-status" id="update-modal-status">正在检查更新...</div>
                    <div class="update-modal-meta" id="update-modal-meta">当前版本：--</div>
                </div>
                <div class="detail-group update-modal-progress" id="update-modal-progress" hidden>
                    <div class="detail-group-title">下载进度</div>
                    <div class="update-modal-progress-bar">
                        <div class="update-modal-progress-fill" id="update-modal-progress-fill"></div>
                    </div>
                    <div class="update-modal-progress-text" id="update-modal-progress-text">下载进度 0%</div>
                </div>
                <div class="detail-group">
                    <div class="detail-group-title">更新说明</div>
                    <ul class="update-modal-notes" id="update-modal-notes"></ul>
                </div>
            </div>
            <div class="modal-footer">
                <button class="btn btn-secondary btn-sm" id="btn-update-modal-skip">跳过此版本</button>
                <button class="btn btn-primary btn-sm" id="btn-update-modal-action">下载更新</button>
            </div>
        </div>
    </div>

    <div class="modal-overlay" id="confirm-modal">
        <div class="modal modal-compact">
            <div class="modal-header">
                <div class="modal-copy">
                    <span class="modal-kicker" id="confirm-modal-kicker">操作确认</span>
                    <h3 class="modal-title" id="confirm-modal-title">确认操作</h3>
                    <p class="modal-subtitle" id="confirm-modal-subtitle">请确认是否继续执行当前操作。</p>
                </div>
                <button class="modal-close" id="btn-close-confirm-modal" type="button" aria-label="关闭确认弹窗">
                    <svg class="icon icon-sm">
                        <use href="#icon-x" />
                    </svg>
                </button>
            </div>
            <div class="modal-body">
                <div class="modal-callout">
                    <div class="confirm-modal-message" id="confirm-modal-message">确认是否继续？</div>
                </div>
            </div>
            <div class="modal-footer">
                <button class="btn btn-secondary btn-sm" id="btn-confirm-modal-cancel" type="button">取消</button>
                <button class="btn btn-primary btn-sm" id="btn-confirm-modal-confirm" type="button">确认</button>
            </div>
        </div>
    </div>

    <div class="modal-overlay drawer-overlay" id="model-auth-workflow-modal">
        <div class="modal modal-drawer modal-drawer-md">
            <div class="modal-header">
                <div class="modal-copy">
                    <span class="modal-kicker" id="model-auth-workflow-kicker">模型中心</span>
                    <h3 class="modal-title" id="model-auth-workflow-title">模型中心</h3>
                    <p class="modal-subtitle" id="model-auth-workflow-subtitle">在当前上下文里完成这一步，不必离开列表。</p>
                </div>
                <button class="modal-close" id="btn-close-model-auth-workflow" type="button" aria-label="关闭模型中心弹窗">
                    <svg class="icon icon-sm">
                        <use href="#icon-x" />
                    </svg>
                </button>
            </div>
            <div class="modal-body" id="model-auth-workflow-body"></div>
            <div class="modal-footer" id="model-auth-workflow-footer"></div>
        </div>
    </div>

    <div class="modal-overlay drawer-overlay" id="message-detail-modal">
        <div class="modal modal-drawer modal-drawer-lg">
            <div class="modal-header">
                <div class="modal-copy">
                    <span class="modal-kicker">消息洞察</span>
                    <h3 class="modal-title">消息详情</h3>
                    <p class="modal-subtitle">边看消息，边处理联系人 Prompt、审批策略和待审批回复。</p>
                </div>
                <button class="modal-close" id="btn-close-message-detail" type="button" aria-label="关闭消息详情弹窗">
                    <svg class="icon icon-sm">
                        <use href="#icon-x" />
                    </svg>
                </button>
            </div>
            <div class="modal-body">
                <div id="message-detail-body"></div>
            </div>
        </div>
    </div>

    <!-- Toast 容器 -->
    <div class="toast-container" id="toast-container"></div>
`;
}

export default renderGlobalOverlays;
