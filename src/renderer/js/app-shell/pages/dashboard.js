export function renderDashboardPageShell() {
    return `
                <div class="page-header">
                    <div class="page-heading">
                        <span class="page-kicker">运行概览</span>
                        <h1 class="page-title">仪表盘</h1>
                        <p class="page-subtitle">把机器人状态、成本与运行质量收在一个视图里。</p>
                    </div>
                    <div class="page-actions">
                        <button class="btn btn-primary" id="btn-toggle-bot">
                            <svg class="icon icon-sm">
                                <use href="#icon-play" />
                            </svg>
                            <span>启动机器人</span>
                        </button>
                    </div>
                </div>

                <!-- 统计卡片 -->
                <div class="stats-row">
                    <div class="stat-card">
                        <div class="stat-icon">
                            <svg class="icon">
                                <use href="#icon-clock" />
                            </svg>
                        </div>
                        <div class="stat-content">
                            <div class="stat-value" id="stat-uptime">--</div>
                            <div class="stat-label">运行时长</div>
                        </div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-icon">
                            <svg class="icon">
                                <use href="#icon-message" />
                            </svg>
                        </div>
                        <div class="stat-content">
                            <div class="stat-value" id="stat-today-replies">0</div>
                            <div class="stat-label">今日回复</div>
                        </div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-icon">
                            <svg class="icon">
                                <use href="#icon-zap" />
                            </svg>
                        </div>
                        <div class="stat-content">
                            <div class="stat-value" id="stat-today-tokens">0</div>
                            <div class="stat-label">今日Token</div>
                        </div>
                    </div>
                    <div class="stat-card stat-card-accent">
                        <div class="stat-icon">
                            <svg class="icon">
                                <use href="#icon-coins" />
                            </svg>
                        </div>
                        <div class="stat-content">
                            <div class="stat-value" id="stat-today-cost">--</div>
                            <div class="stat-label">今日成本</div>
                        </div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-icon">
                            <svg class="icon">
                                <use href="#icon-bar-chart" />
                            </svg>
                        </div>
                        <div class="stat-content">
                            <div class="stat-value" id="stat-total-replies">0</div>
                            <div class="stat-label">累计回复</div>
                        </div>
                    </div>
                </div>

                <div class="dashboard-section-tabs" id="dashboard-section-tabs" role="tablist" aria-label="仪表盘分段">
                    <button class="dashboard-section-tab active" type="button" data-dashboard-section-button="overview" aria-pressed="true">运行总览</button>
                    <button class="dashboard-section-tab" type="button" data-dashboard-section-button="recovery" aria-pressed="false">风险与恢复</button>
                    <button class="dashboard-section-tab" type="button" data-dashboard-section-button="business" aria-pressed="false">经营与质量</button>
                    <button class="dashboard-section-tab" type="button" data-dashboard-section-button="messages" aria-pressed="false">最近消息</button>
                </div>

                <div class="dashboard-stage active" data-dashboard-section="overview">
                    <div class="dashboard-stage-grid">
                        <div class="dashboard-stage-column">
                            <div class="card">
                                <div class="card-header">
                                    <div>
                                        <h2 class="card-title">运行状态</h2>
                                        <p class="card-subtitle">先看机器人现在是否在线、是否可操作。</p>
                                    </div>
                                </div>
                                <div class="card-body">
                                    <div class="bot-control bot-control-compact">
                                        <div class="bot-avatar">
                                            <svg class="icon icon-xl">
                                                <use href="#icon-bot" />
                                            </svg>
                                        </div>
                                        <div class="bot-info">
                                            <div class="bot-name">微信AI助手</div>
                                            <div class="bot-state" id="bot-state">
                                                <span class="bot-state-dot starting"></span>
                                                <span class="bot-state-text">等待服务</span>
                                            </div>
                                            <div class="bot-meta" id="bot-transport-meta">
                                                <span id="bot-transport-backend">后端: --</span>
                                                <span id="bot-transport-version">微信: --</span>
                                            </div>
                                            <div class="bot-warning" id="bot-transport-warning" hidden></div>
                                            <div class="startup-panel" id="bot-startup-panel" hidden>
                                                <div class="startup-panel-header">
                                                    <span id="bot-startup-label">正在启动机器人...</span>
                                                    <span id="bot-startup-meta">0%</span>
                                                </div>
                                                <div class="startup-progress-bar">
                                                    <div class="startup-progress-fill" id="bot-startup-progress"></div>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                    <div class="bot-actions">
                                        <button class="btn btn-secondary btn-sm" id="btn-pause">
                                            <svg class="icon icon-sm">
                                                <use href="#icon-pause" />
                                            </svg>
                                            <span>暂停</span>
                                        </button>
                                        <button class="btn btn-secondary btn-sm" id="btn-restart">
                                            <svg class="icon icon-sm">
                                                <use href="#icon-refresh" />
                                            </svg>
                                            <span>重启</span>
                                        </button>
                                    </div>
                                </div>
                            </div>

                            <div class="card">
                                <div class="card-header">
                                    <div>
                                        <h2 class="card-title">后台任务</h2>
                                        <p class="card-subtitle">成长任务、待机和唤醒统一收在这里。</p>
                                    </div>
                                </div>
                                <div class="card-body">
                                    <div class="bot-growth-panel">
                                        <div class="bot-growth-meta">
                                            <div class="bot-growth-title">成长任务</div>
                                            <div class="bot-growth-text" id="growth-task-status">等待服务</div>
                                            <div class="bot-growth-subtext" id="growth-task-backlog">待处理任务 --</div>
                                            <div class="bot-growth-queue" id="growth-task-queue">
                                                <span class="growth-task-empty">等待服务</span>
                                            </div>
                                            <div class="bot-growth-batch" id="growth-task-batch">最近批次 --</div>
                                            <div class="bot-growth-next" id="growth-task-next">下次批处理 --</div>
                                            <div class="bot-growth-error" id="growth-task-error" hidden></div>
                                        </div>
                                        <button class="btn btn-secondary btn-sm" id="btn-toggle-growth">
                                            <span>启动成长任务</span>
                                        </button>
                                    </div>

                                    <div class="backend-idle-panel" id="backend-idle-panel" hidden>
                                        <div class="backend-idle-copy">
                                            <div class="backend-idle-title" id="backend-idle-title">后端待机中</div>
                                            <div class="backend-idle-detail" id="backend-idle-detail"></div>
                                            <div class="backend-idle-meta" id="backend-idle-meta"></div>
                                        </div>
                                        <div class="backend-idle-actions">
                                            <button class="btn btn-secondary btn-sm" id="btn-cancel-idle-shutdown" hidden>取消自动停机</button>
                                            <button class="btn btn-primary btn-sm" id="btn-wake-backend" hidden>立即唤醒</button>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <div class="dashboard-stage-column">
                            <div class="card">
                                <div class="card-header">
                                    <div>
                                        <h2 class="card-title">健康监控</h2>
                                        <p class="card-subtitle">确认机器、微信连接与记忆库是否健康。</p>
                                    </div>
                                </div>
                                <div class="card-body">
                                    <div class="health-grid">
                                        <div class="health-metric">
                                            <span class="health-metric-label">CPU 负载</span>
                                            <strong class="health-metric-value" id="health-cpu">--</strong>
                                        </div>
                                        <div class="health-metric">
                                            <span class="health-metric-label">内存占用</span>
                                            <strong class="health-metric-value" id="health-memory">--</strong>
                                        </div>
                                        <div class="health-metric">
                                            <span class="health-metric-label">队列积压</span>
                                            <strong class="health-metric-value" id="health-queue">--</strong>
                                        </div>
                                        <div class="health-metric">
                                            <span class="health-metric-label">AI 延迟</span>
                                            <strong class="health-metric-value" id="health-latency">--</strong>
                                        </div>
                                    </div>
                                    <div class="health-checks">
                                        <div class="health-check-item" id="health-ai">
                                            <span class="health-check-dot"></span>
                                            <span class="health-check-label">AI 服务</span>
                                            <span class="health-check-text">未检测</span>
                                        </div>
                                        <div class="health-check-item" id="health-wechat">
                                            <span class="health-check-dot"></span>
                                            <span class="health-check-label">微信连接</span>
                                            <span class="health-check-text">未检测</span>
                                        </div>
                                        <div class="health-check-item" id="health-db">
                                            <span class="health-check-dot"></span>
                                            <span class="health-check-label">记忆库</span>
                                            <span class="health-check-text">未检测</span>
                                        </div>
                                    </div>
                                    <div class="health-feedback" id="health-merge-feedback">消息合并状态：未激活</div>
                                    <div class="health-warning" id="health-warning" hidden></div>
                                </div>
                            </div>

                            <div class="card">
                                <div class="card-header">
                                    <div>
                                        <h2 class="card-title">快捷操作</h2>
                                        <p class="card-subtitle">常用操作集中入口，减少来回切页。</p>
                                    </div>
                                </div>
                                <div class="card-body">
                                    <div class="quick-grid">
                                        <button class="quick-btn" id="btn-open-wechat">
                                            <svg class="icon">
                                                <use href="#icon-external" />
                                            </svg>
                                            <span>打开微信</span>
                                        </button>
                                        <button class="quick-btn" id="btn-view-logs">
                                            <svg class="icon">
                                                <use href="#icon-file-text" />
                                            </svg>
                                            <span>查看日志</span>
                                        </button>
                                        <button class="quick-btn" id="btn-refresh-status">
                                            <svg class="icon">
                                                <use href="#icon-refresh" />
                                            </svg>
                                            <span>刷新状态</span>
                                        </button>
                                        <button class="quick-btn" id="btn-minimize-tray">
                                            <svg class="icon">
                                                <use href="#icon-minimize-2" />
                                            </svg>
                                            <span>最小化</span>
                                        </button>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="dashboard-stage" data-dashboard-section="recovery" hidden>
                    <div class="dashboard-stage-grid">
                        <div class="dashboard-stage-column">
                            <div class="card">
                                <div class="card-header">
                                    <div>
                                        <h2 class="card-title">启动准备</h2>
                                        <p class="card-subtitle">判断现在能不能安全启动，以及还缺什么。</p>
                                    </div>
                                </div>
                                <div class="card-body">
                                    <div class="bot-readiness" id="bot-readiness">
                                        <div class="bot-readiness-header">
                                            <div>
                                                <div class="bot-readiness-title" id="bot-readiness-title">运行准备度检查中</div>
                                                <div class="bot-readiness-detail" id="bot-readiness-detail">正在确认管理员权限、微信状态和可用预设。</div>
                                            </div>
                                            <span class="bot-readiness-badge" id="bot-readiness-badge">检查中</span>
                                        </div>
                                        <ul class="bot-readiness-list" id="bot-readiness-list"></ul>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <div class="dashboard-stage-column">
                            <div class="card">
                                <div class="card-header">
                                    <div>
                                        <h2 class="card-title">故障恢复</h2>
                                        <p class="card-subtitle">集中查看诊断信息和恢复动作。</p>
                                    </div>
                                </div>
                                <div class="card-body">
                                    <div class="bot-diagnostics" id="bot-diagnostics" hidden>
                                        <div class="bot-diagnostics-title" id="bot-diagnostics-title">运行诊断</div>
                                        <div class="bot-diagnostics-detail" id="bot-diagnostics-detail"></div>
                                        <ul class="bot-diagnostics-list" id="bot-diagnostics-list"></ul>
                                        <div class="bot-diagnostics-actions">
                                            <button class="btn btn-secondary btn-sm" id="btn-export-diagnostics-snapshot">导出诊断快照</button>
                                            <button class="btn btn-cta btn-sm" id="btn-recover-bot">一键恢复</button>
                                        </div>
                                    </div>
                                </div>
                            </div>

                            <div class="card">
                                <div class="card-header">
                                    <div>
                                        <h2 class="card-title">稳定性总览</h2>
                                        <p class="card-subtitle">恢复记录、待审批回复和最近质量检查。</p>
                                    </div>
                                </div>
                                <div class="card-body">
                                    <div class="dashboard-cost-summary" id="dashboard-stability-summary">
                                        <div class="dashboard-cost-stat">
                                            <span class="dashboard-cost-label">待审批回复</span>
                                            <strong class="dashboard-cost-value" id="dashboard-pending-replies">--</strong>
                                        </div>
                                        <div class="dashboard-cost-stat">
                                            <span class="dashboard-cost-label">最近备份</span>
                                            <strong class="dashboard-cost-value" id="dashboard-backup-summary">--</strong>
                                        </div>
                                        <div class="dashboard-cost-stat">
                                            <span class="dashboard-cost-label">最近评测</span>
                                            <strong class="dashboard-cost-value" id="dashboard-eval-status">--</strong>
                                        </div>
                                    </div>
                                    <div class="dashboard-subsection">
                                        <div class="dashboard-subsection-title">恢复与质量状态</div>
                                        <div class="dashboard-model-list" id="dashboard-restore-summary">
                                            <div class="empty-state compact-empty">
                                                <span class="empty-state-text">暂无恢复或评测记录</span>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="dashboard-stage" data-dashboard-section="business" hidden>
                    <div class="dashboard-stage-grid dashboard-stage-grid-business">
                        <div class="dashboard-stage-column">
                            <div class="card dashboard-cost-card">
                                <div class="card-header">
                                    <div>
                                        <h2 class="card-title">成本概览</h2>
                                        <p class="card-subtitle">近 30 天用量、已定价回复和主要模型消耗。</p>
                                    </div>
                                    <button class="btn btn-secondary btn-sm" id="btn-open-costs">
                                        <svg class="icon icon-sm">
                                            <use href="#icon-coins" />
                                        </svg>
                                        <span>查看明细</span>
                                    </button>
                                </div>
                                <div class="card-body">
                                    <div class="dashboard-cost-summary" id="dashboard-cost-summary">
                                        <div class="dashboard-cost-stat">
                                            <span class="dashboard-cost-label">近 30 天总金额</span>
                                            <strong class="dashboard-cost-value">--</strong>
                                        </div>
                                        <div class="dashboard-cost-stat">
                                            <span class="dashboard-cost-label">近 30 天总 Token</span>
                                            <strong class="dashboard-cost-value">--</strong>
                                        </div>
                                        <div class="dashboard-cost-stat">
                                            <span class="dashboard-cost-label">已定价回复</span>
                                            <strong class="dashboard-cost-value">--</strong>
                                        </div>
                                    </div>
                                    <div class="dashboard-subsection">
                                        <div class="dashboard-subsection-title">近 30 天主要模型消耗</div>
                                        <div class="dashboard-model-list" id="dashboard-cost-top-models">
                                            <div class="empty-state compact-empty">
                                                <span class="empty-state-text">暂无成本数据</span>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <div class="dashboard-stage-column">
                            <div class="card">
                                <div class="card-header">
                                    <div>
                                        <h2 class="card-title">质量表现</h2>
                                        <p class="card-subtitle">看检索配置、命中情况和最近一次调用耗时。</p>
                                    </div>
                                </div>
                                <div class="card-body">
                                    <div class="quality-overview-grid">
                                        <div class="dashboard-cost-stat">
                                            <span class="dashboard-cost-label">运行期向量记忆</span>
                                            <strong class="dashboard-cost-value" id="retrieval-vector">--</strong>
                                        </div>
                                        <div class="dashboard-cost-stat">
                                            <span class="dashboard-cost-label">导出聊天记录 RAG</span>
                                            <strong class="dashboard-cost-value" id="retrieval-export">--</strong>
                                        </div>
                                        <div class="dashboard-cost-stat">
                                            <span class="dashboard-cost-label">Top-K</span>
                                            <strong class="dashboard-cost-value" id="retrieval-topk">--</strong>
                                        </div>
                                        <div class="dashboard-cost-stat">
                                            <span class="dashboard-cost-label">检索阈值</span>
                                            <strong class="dashboard-cost-value" id="retrieval-threshold">--</strong>
                                        </div>
                                        <div class="dashboard-cost-stat">
                                            <span class="dashboard-cost-label">重排方式</span>
                                            <strong class="dashboard-cost-value" id="retrieval-rerank">--</strong>
                                        </div>
                                        <div class="dashboard-cost-stat">
                                            <span class="dashboard-cost-label">累计命中</span>
                                            <strong class="dashboard-cost-value" id="retrieval-hits">--</strong>
                                        </div>
                                    </div>
                                    <div class="dashboard-subsection">
                                        <div class="dashboard-subsection-title">最近一次调用耗时</div>
                                        <div class="quality-timings-grid" id="retrieval-timings"></div>
                                        <div class="empty-state compact-empty quality-timings-empty" id="retrieval-timings-empty">
                                            <span class="empty-state-text">暂无质量耗时数据</span>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="dashboard-stage" data-dashboard-section="messages" hidden>
                    <div class="card full-width dashboard-recent-card">
                        <div class="card-header">
                            <div>
                                <h2 class="card-title">最近消息</h2>
                                <p class="card-subtitle">保留最近 5 条消息，便于快速回看上下文。</p>
                            </div>
                            <button class="btn btn-ghost btn-sm" id="btn-view-all-messages">查看全部</button>
                        </div>
                        <div class="card-body">
                            <div class="message-list" id="recent-messages">
                                <div class="empty-state">
                                    <svg class="icon">
                                        <use href="#icon-inbox" />
                                    </svg>
                                    <span class="empty-state-text">暂无消息记录</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
`;
}

export default renderDashboardPageShell;

