export function renderSettingsPageShell() {
    return `
                <div class="page-header">
                    <div class="page-heading">
                        <span class="page-kicker">配置工作台</span>
                        <h1 class="page-title">配置中心</h1>
                        <p class="page-subtitle">按模块切换、保存并回看当前运行摘要。</p>
                    </div>
                    <div class="page-actions">
                        <button class="btn btn-secondary btn-sm" id="btn-refresh-config" type="button">
                            <svg class="icon icon-sm">
                                <use href="#icon-refresh" />
                            </svg>
                            <span>重新加载</span>
                        </button>
                        <button class="btn btn-primary btn-sm" id="btn-save-settings" type="button">
                            <svg class="icon icon-sm">
                                <use href="#icon-save" />
                            </svg>
                            <span>保存设置</span>
                        </button>
                    </div>
                </div>

                <div class="settings-workbench-bar">
                    <div class="settings-workbench-nav" id="settings-section-nav" role="tablist" aria-label="配置分组">
                        <button type="button" class="settings-nav-pill" data-settings-section="common" aria-pressed="true">常用</button>
                        <button type="button" class="settings-nav-pill" data-settings-section="workspace" aria-pressed="false">工作台</button>
                        <button type="button" class="settings-nav-pill" data-settings-section="bot" aria-pressed="false">机器人</button>
                        <button type="button" class="settings-nav-pill" data-settings-section="prompt" aria-pressed="false">提示词</button>
                        <button type="button" class="settings-nav-pill" data-settings-section="memory" aria-pressed="false">记忆</button>
                        <button type="button" class="settings-nav-pill" data-settings-section="delivery" aria-pressed="false">发送策略</button>
                        <button type="button" class="settings-nav-pill" data-settings-section="guard" aria-pressed="false">限制与过滤</button>
                        <button type="button" class="settings-nav-pill" data-settings-section="quality" aria-pressed="false">质量与日志</button>
                        <button type="button" class="settings-nav-pill" data-settings-section="all" aria-pressed="false">全部</button>
                    </div>
                    <div class="settings-workbench-summary">
                        <div class="settings-workbench-status">
                            <span class="settings-workbench-label">保存状态</span>
                            <strong id="settings-dirty-status" data-state="ready">当前内容已同步</strong>
                        </div>
                        <div class="settings-workbench-status">
                            <span class="settings-workbench-label">运行能力</span>
                            <strong id="settings-capability-status" data-state="warning">未连接 Python 服务，预览与运行检查暂不可用</strong>
                        </div>
                    </div>
                </div>

                <div class="config-save-feedback" id="config-save-feedback" hidden>
                    <div class="config-save-feedback-summary" id="config-save-feedback-summary">本次保存结果将在这里显示</div>
                    <div class="config-save-feedback-meta" id="config-save-feedback-meta"></div>
                    <div class="config-save-feedback-groups" id="config-save-feedback-groups"></div>
                </div>

                <div class="settings-container">
                    <!-- 当前配置 Hero (由 JS 动态渲染) -->
                    <div id="current-config-hero">
                        <div class="config-hero-card shell-placeholder-state">
                            <div class="hero-content">
                                <div class="hero-title">
                                    <span class="hero-name">加载配置中...</span>
                                </div>
                            </div>
                        </div>
                    </div>

                    <div class="settings-card">
                        <div class="settings-card-header settings-card-header-inline">
                            <h2 class="settings-card-title settings-card-title-tight">备份与恢复</h2>
                        </div>
                        <div class="backup-workspace">
                            <div class="backup-action-grid">
                                <div class="backup-action-card">
                                    <span class="backup-action-kicker">先保存一份</span>
                                    <h3 class="backup-action-title">给当前状态留一个安心恢复点</h3>
                                    <p class="backup-action-text">快速备份适合日常留档；完整备份会额外带上聊天资料，适合迁移或大改前保存。</p>
                                    <div class="backup-button-row">
                                        <button class="btn btn-secondary btn-sm" id="btn-create-quick-backup" type="button">快速备份</button>
                                        <button class="btn btn-secondary btn-sm" id="btn-create-full-backup" type="button">完整备份聊天数据</button>
                                    </div>
                                    <div class="detail-help" id="settings-backup-summary">正在加载备份状态...</div>
                                </div>

                                <div class="backup-action-card">
                                    <span class="backup-action-kicker">恢复到某个时间点</span>
                                    <h3 class="backup-action-title">先确认，再恢复</h3>
                                    <p class="backup-action-text">选择一份之前保存的备份，先检查是否可恢复，再决定是否真正恢复。</p>
                                    <label class="detail-label" for="settings-backup-select">选择一个可恢复时间点</label>
                                    <select class="form-input" id="settings-backup-select">
                                        <option value="">暂无可恢复备份</option>
                                    </select>
                                    <div class="detail-help" id="settings-backup-restore-feedback">恢复前会自动留一份保险备份，避免恢复后找不回当前状态。</div>
                                    <div class="backup-button-row">
                                        <button class="btn btn-secondary btn-sm" id="btn-restore-backup-dry-run" type="button">先检查</button>
                                        <button class="btn btn-primary btn-sm" id="btn-restore-backup-apply" type="button">恢复到这个时间点</button>
                                    </div>
                                </div>
                            </div>

                            <div class="backup-action-card backup-action-card-wide">
                                <span class="backup-action-kicker">清理旧备份释放空间</span>
                                <h3 class="backup-action-title">不影响最近可用备份的前提下腾出空间</h3>
                                <p class="backup-action-text">系统默认会保留最近 5 份快速备份、3 份完整备份，并额外保护最近一次恢复前自动保留的保险备份。</p>
                                <div class="backup-detail-grid">
                                    <div class="detail-item">
                                        <span class="detail-label">最近质量检查</span>
                                        <div class="detail-help" id="settings-eval-summary">尚未发现评测报告</div>
                                    </div>
                                </div>
                                <div class="backup-button-row backup-button-row-end">
                                    <button class="btn btn-secondary btn-sm" id="btn-cleanup-backup-dry-run" type="button">先看看可清理什么</button>
                                    <button class="btn btn-secondary btn-sm" id="btn-cleanup-backup-apply" type="button">清理旧备份</button>
                                </div>
                            </div>

                            <div class="backup-action-card backup-action-card-wide">
                                <span class="backup-action-kicker">数据治理清理</span>
                                <h3 class="backup-action-title">按类别清理本地数据，并支持先预览后执行</h3>
                                <p class="backup-action-text">可按 memory / usage / export_rag 分类执行 dry-run 或 apply，避免误删。</p>
                                <div class="backup-detail-grid">
                                    <div class="detail-item">
                                        <label class="detail-label" for="settings-data-control-scope">清理范围</label>
                                        <select class="form-input" id="settings-data-control-scope">
                                            <option value="">请先选择清理范围</option>
                                        </select>
                                    </div>
                                    <div class="detail-item">
                                        <span class="detail-label">结果</span>
                                        <div class="detail-help" id="settings-data-control-feedback">尚未执行数据清理</div>
                                    </div>
                                </div>
                                <div class="backup-button-row backup-button-row-end">
                                    <button class="btn btn-secondary btn-sm" id="btn-data-control-dry-run" type="button">先检查</button>
                                    <button class="btn btn-secondary btn-sm" id="btn-data-control-apply" type="button">执行清理</button>
                                </div>
                            </div>

                            <div class="dashboard-subsection backup-list-section">
                                <div class="dashboard-subsection-title">最近保存的备份</div>
                                <div class="dashboard-model-list" id="settings-backup-list">
                                    <div class="empty-state compact-empty">
                                        <span class="empty-state-text">暂无备份</span>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- 机器人设置 -->
                    <div class="settings-card">
                        <h2 class="settings-card-title">机器人设置</h2>
                        <div class="settings-grid">
                            <div class="form-group">
                                <label class="form-label">微信昵称</label>
                                <input type="text" id="setting-self-name" placeholder="你的微信昵称">
                            </div>
                            <div class="form-group">
                                <label class="form-label">回复后缀</label>
                                <input type="text" id="setting-reply-suffix" placeholder="（AI回复）">
                            </div>
                            <div class="form-group">
                                <label class="form-label">回复完成时限（秒）</label>
                                <input type="number" id="setting-reply-deadline-sec" min="0.1" step="0.1">
                            </div>
                            <div class="form-group">
                                <label class="form-checkbox form-checkbox-inline">
                                    <input type="checkbox" id="setting-group-at-only">
                                    <span class="form-checkbox-label">群聊仅@时回复</span>
                                </label>
                            </div>
                        </div>
                    </div>

                    <div class="settings-card">
                        <h2 class="settings-card-title">系统提示</h2>
                        <div class="form-group full-width">
                            <label class="form-label">自定义系统提示词</label>
                            <textarea id="setting-system-prompt-editable" rows="6"></textarea>
                            <div class="detail-help">这里仅编辑你希望补充给系统的自定义规则；历史对话、用户画像、情绪/时间/风格等系统注入块会固定保留，不允许在这里改写。</div>
                        </div>
                        <div class="form-group full-width">
                            <label class="form-label">固定注入块（只读）</label>
                            <textarea id="setting-system-prompt-fixed" rows="8" readonly></textarea>
                            <div class="detail-help">这部分由系统在运行时自动填充，用来注入历史对话、联系人画像和当前情境。它会参与最终系统提示词，但不会暴露给普通设置编辑。</div>
                        </div>
                        <div class="form-group full-width">
                            <label class="form-label">会话提示覆盖（每行：会话名|提示词）</label>
                            <textarea id="setting-system-prompt-overrides" rows="4"></textarea>
                            <div class="detail-help">这里只填写每个会话额外的自定义规则；系统必需的历史对话、画像、情绪/时间/风格注入块仍会在运行时自动补齐。</div>
                        </div>
                    </div>

                    <div class="settings-card">
                        <div class="settings-card-header prompt-preview-header">
                        <h2 class="settings-card-title settings-card-title-tight">提示词预览</h2>
                            <button class="btn btn-secondary btn-sm" id="btn-preview-prompt">
                                <svg class="icon icon-sm">
                                    <use href="#icon-zap" />
                                </svg>
                                <span>生成预览</span>
                            </button>
                        </div>
                        <div class="settings-grid">
                            <div class="form-group">
                                <label class="form-label">预览会话名</label>
                                <input type="text" id="setting-preview-chat-name" placeholder="例如：张三">
                            </div>
                            <div class="form-group">
                                <label class="form-label">发送者昵称</label>
                                <input type="text" id="setting-preview-sender" placeholder="例如：张三">
                            </div>
                            <div class="form-group">
                                <label class="form-label">关系标签</label>
                                <input type="text" id="setting-preview-relationship" placeholder="例如：朋友">
                            </div>
                            <div class="form-group">
                                <label class="form-label">情绪标签</label>
                                <input type="text" id="setting-preview-emotion" placeholder="例如：开心">
                            </div>
                            <div class="form-group full-width">
                                <label class="form-label">示例消息</label>
                                <textarea id="setting-preview-message" rows="4" placeholder="输入一段示例对话，查看最终发送给模型的系统提示词"></textarea>
                            </div>
                            <div class="form-group">
                                <label class="form-checkbox form-checkbox-inline">
                                    <input type="checkbox" id="setting-preview-is-group">
                                    <span class="form-checkbox-label">按群聊场景预览</span>
                                </label>
                            </div>
                        </div>
                        <div class="prompt-preview-summary" id="settings-preview-summary">尚未生成预览</div>
                        <pre class="prompt-preview-output" id="settings-prompt-preview">点击“生成预览”后显示最终系统提示词。</pre>
                    </div>

                    <div class="settings-card">
                        <h2 class="settings-card-title">表情与语音</h2>
                        <div class="settings-grid">
                            <div class="form-group">
                                <label class="form-label">表情策略</label>
                                <select class="form-input" id="setting-emoji-policy">
                                    <option value="wechat">微信原样</option>
                                    <option value="strip">去掉表情</option>
                                    <option value="keep">尽量保留</option>
                                    <option value="mixed">智能混合</option>
                                </select>
                            </div>
                            <div class="form-group">
                                <label class="form-checkbox form-checkbox-inline">
                                    <input type="checkbox" id="setting-voice-to-text">
                                    <span class="form-checkbox-label">启用语音转文字</span>
                                </label>
                            </div>
                            <div class="form-group">
                                <label class="form-label">语音转写失败回复</label>
                                <input type="text" id="setting-voice-to-text-fail-reply">
                            </div>
                            <div class="form-group full-width">
                                <label class="form-label">表情替换（每行：原表情=替换表情）</label>
                                <textarea id="setting-emoji-replacements" rows="3"></textarea>
                            </div>
                        </div>
                    </div>

                    <div class="settings-card">
                        <h2 class="settings-card-title">记忆与上下文</h2>
                        <div class="settings-grid">
                            <div class="form-group">
                                <label class="form-label">记忆库路径</label>
                                <input type="text" id="setting-memory-db-path">
                            </div>
                            <div class="form-group">
                                <label class="form-label">上下文条数</label>
                                <input type="number" id="setting-memory-context-limit" min="0" step="1">
                            </div>
                            <div class="form-group">
                                <label class="form-label">记忆过期时间（秒，留空不过期）</label>
                                <input type="number" id="setting-memory-ttl-sec" min="0" step="1">
                            </div>
                            <div class="form-group">
                                <label class="form-label">记忆清理间隔（秒）</label>
                                <input type="number" id="setting-memory-cleanup-interval-sec" min="0" step="0.1">
                            </div>
                            <div class="form-group">
                                <label class="form-label">上下文轮数</label>
                                <input type="number" id="setting-context-rounds" min="0" step="1">
                            </div>
                            <div class="form-group">
                                <label class="form-label">上下文 token 上限</label>
                                <input type="number" id="setting-context-max-tokens" min="0" step="1">
                            </div>
                            <div class="form-group">
                                <label class="form-label">最大会话数</label>
                                <input type="number" id="setting-history-max-chats" min="0" step="1">
                            </div>
                            <div class="form-group">
                                <label class="form-label">会话过期时间（秒，留空不过期）</label>
                                <input type="number" id="setting-history-ttl-sec" min="0" step="1">
                            </div>
                        </div>
                    </div>

                    <div class="settings-card">
                        <h2 class="settings-card-title">轮询与延迟</h2>
                        <div class="settings-grid">
                            <div class="form-group">
                                <label class="form-label">轮询最短间隔（秒）</label>
                                <input type="number" id="setting-poll-interval-min-sec" min="0" step="0.01">
                            </div>
                            <div class="form-group">
                                <label class="form-label">轮询最长间隔（秒）</label>
                                <input type="number" id="setting-poll-interval-max-sec" min="0" step="0.01">
                            </div>
                            <div class="form-group">
                                <label class="form-label">退避倍数</label>
                                <input type="number" id="setting-poll-interval-backoff-factor" min="0" step="0.1">
                            </div>
                            <div class="form-group">
                                <label class="form-label">最小回复间隔（秒）</label>
                                <input type="number" id="setting-min-reply-interval-sec" min="0" step="0.01">
                            </div>
                            <div class="form-group">
                                <label class="form-label">随机延迟最小值（秒）</label>
                                <input type="number" id="setting-random-delay-min-sec" min="0" step="0.01">
                            </div>
                            <div class="form-group">
                                <label class="form-label">随机延迟最大值（秒）</label>
                                <input type="number" id="setting-random-delay-max-sec" min="0" step="0.01">
                            </div>
                        </div>
                    </div>

                    <div class="settings-card">
                        <h2 class="settings-card-title">合并与发送</h2>
                        <div class="settings-grid">
                            <div class="form-group">
                                <label class="form-label">合并等待窗口（秒）</label>
                                <input type="number" id="setting-merge-user-messages-sec" min="0" step="0.1">
                            </div>
                            <div class="form-group">
                                <label class="form-label">合并最长等待（秒）</label>
                                <input type="number" id="setting-merge-user-messages-max-wait-sec" min="0" step="0.1">
                            </div>
                            <div class="form-group">
                                <label class="form-label">单条消息最大长度</label>
                                <input type="number" id="setting-reply-chunk-size" min="1" step="1">
                            </div>
                            <div class="form-group">
                                <label class="form-label">分段发送间隔（秒）</label>
                                <input type="number" id="setting-reply-chunk-delay-sec" min="0" step="0.1">
                            </div>
                            <div class="form-group">
                                <label class="form-label">最大并发处理数</label>
                                <input type="number" id="setting-max-concurrency" min="1" step="1">
                            </div>
                        </div>
                    </div>

                    <div class="settings-card">
                        <h2 class="settings-card-title">智能分段</h2>
                        <div class="settings-grid">
                            <div class="form-group">
                                <label class="form-checkbox form-checkbox-inline">
                                    <input type="checkbox" id="setting-natural-split-enabled">
                                    <span class="form-checkbox-label">启用智能分段</span>
                                </label>
                            </div>
                            <div class="form-group">
                                <label class="form-label">每段最少字符数</label>
                                <input type="number" id="setting-natural-split-min-chars" min="0" step="1">
                            </div>
                            <div class="form-group">
                                <label class="form-label">每段最多字符数</label>
                                <input type="number" id="setting-natural-split-max-chars" min="0" step="1">
                            </div>
                            <div class="form-group">
                                <label class="form-label">最大分段数</label>
                                <input type="number" id="setting-natural-split-max-segments" min="1" step="1">
                            </div>
                            <div class="form-group">
                                <label class="form-label">段间延迟最小值（秒）</label>
                                <input type="number" id="setting-natural-split-delay-min-sec" min="0" step="0.1">
                            </div>
                            <div class="form-group">
                                <label class="form-label">段间延迟最大值（秒）</label>
                                <input type="number" id="setting-natural-split-delay-max-sec" min="0" step="0.1">
                            </div>
                        </div>
                    </div>

                    <div class="settings-card">
                        <h2 class="settings-card-title">微信连接与传输</h2>
                        <div class="settings-grid">
                            <div class="form-group">
                                <label class="form-label">目标微信版本</label>
                                <input type="text" id="setting-required-wechat-version" placeholder="例如：3.9.12.51">
                                <span class="form-hint">用于校验当前微信客户端版本，建议保持为官方支持版本。</span>
                            </div>
                            <div class="form-group">
                                <label class="form-checkbox form-checkbox-inline">
                                    <input type="checkbox" id="setting-silent-mode-required">
                                    <span class="form-checkbox-label">要求严格静默模式</span>
                                </label>
                                <span class="form-hint">开启后会更严格地校验静默运行条件，不满足时会提示连接风险。</span>
                            </div>
                        </div>
                    </div>

                    <div class="settings-card">
                        <h2 class="settings-card-title">热更新与重连</h2>
                        <div class="settings-grid">
                            <div class="form-group">
                                <label class="form-label">配置热重载间隔（秒）</label>
                                <input type="number" id="setting-config-reload-sec" min="0" step="0.1">
                            </div>
                            <div class="form-group">
                                <label class="form-checkbox form-checkbox-inline">
                                    <input type="checkbox" id="setting-reload-ai-client-on-change">
                                    <span class="form-checkbox-label">配置变更重载 AI 客户端</span>
                                </label>
                            </div>
                            <div class="form-group">
                                <label class="form-checkbox form-checkbox-inline">
                                    <input type="checkbox" id="setting-reload-ai-client-module">
                                    <span class="form-checkbox-label">重载 ai_client 模块</span>
                                </label>
                            </div>
                            <div class="form-group">
                                <label class="form-label">空闲超时重连阈值（秒）</label>
                                <input type="number" id="setting-keepalive-idle-sec" min="0" step="0.1">
                            </div>
                            <div class="form-group">
                                <label class="form-label">重连最大重试次数</label>
                                <input type="number" id="setting-reconnect-max-retries" min="0" step="1">
                            </div>
                            <div class="form-group">
                                <label class="form-label">重连退避基准（秒）</label>
                                <input type="number" id="setting-reconnect-backoff-sec" min="0" step="0.1">
                            </div>
                            <div class="form-group">
                                <label class="form-label">重连最大等待（秒）</label>
                                <input type="number" id="setting-reconnect-max-delay-sec" min="0" step="0.1">
                            </div>
                        </div>
                    </div>

                    <div class="settings-card">
                        <h2 class="settings-card-title">群聊与发送</h2>
                        <div class="settings-grid">
                            <div class="form-group">
                                <label class="form-checkbox form-checkbox-inline">
                                    <input type="checkbox" id="setting-group-include-sender">
                                    <span class="form-checkbox-label">群聊回复包含发送者</span>
                                </label>
                            </div>
                            <div class="form-group">
                                <label class="form-checkbox form-checkbox-inline">
                                    <input type="checkbox" id="setting-send-exact-match">
                                    <span class="form-checkbox-label">仅精确匹配会话名发送</span>
                                </label>
                            </div>
                            <div class="form-group">
                                <label class="form-checkbox form-checkbox-inline">
                                    <input type="checkbox" id="setting-send-fallback-current-chat">
                                    <span class="form-checkbox-label">发送失败回退当前会话</span>
                                </label>
                            </div>
                        </div>
                    </div>

                    <div class="settings-card">
                        <h2 class="settings-card-title">过滤规则</h2>
                        <div class="settings-grid">
                            <div class="form-group">
                                <label class="form-checkbox form-checkbox-inline">
                                    <input type="checkbox" id="setting-filter-mute">
                                    <span class="form-checkbox-label">过滤免打扰/静音会话</span>
                                </label>
                            </div>
                            <div class="form-group">
                                <label class="form-checkbox form-checkbox-inline">
                                    <input type="checkbox" id="setting-ignore-official">
                                    <span class="form-checkbox-label">忽略公众号</span>
                                </label>
                            </div>
                            <div class="form-group">
                                <label class="form-checkbox form-checkbox-inline">
                                    <input type="checkbox" id="setting-ignore-service">
                                    <span class="form-checkbox-label">忽略服务号</span>
                                </label>
                            </div>
                            <div class="form-group full-width">
                                <label class="form-checkbox form-checkbox-inline">
                                    <input type="checkbox" id="setting-allow-filehelper-self-message">
                                    <span class="form-checkbox-label">允许文件传输助手中的自发消息参与回复</span>
                                </label>
                                <span class="form-hint">关闭后，文件传输助手里自己发出的消息也会被当作自发消息直接忽略。</span>
                            </div>
                            <div class="form-group full-width">
                                <label class="form-label">忽略会话名（每行一个）</label>
                                <textarea id="setting-ignore-names" rows="3"></textarea>
                            </div>
                            <div class="form-group full-width">
                                <label class="form-label">忽略关键词（每行一个）</label>
                                <textarea id="setting-ignore-keywords" rows="3"></textarea>
                            </div>
                        </div>
                    </div>

                    <div class="settings-card">
                        <h2 class="settings-card-title">个性化</h2>
                        <div class="settings-grid">
                            <div class="form-group">
                                <label class="form-checkbox form-checkbox-inline">
                                    <input type="checkbox" id="setting-personalization-enabled">
                                    <span class="form-checkbox-label">启用个性化功能</span>
                                </label>
                            </div>
                            <div class="form-group">
                                <label class="form-label">画像更新频率（每 N 条）</label>
                                <input type="number" id="setting-profile-update-frequency" min="0" step="1">
                            </div>
                            <div class="form-group">
                                <label class="form-label">联系人 Prompt 更新频率（每 N 条）</label>
                                <input type="number" id="setting-contact-prompt-update-frequency" min="0" step="1">
                            </div>
                            <div class="form-group">
                                <label class="form-checkbox form-checkbox-inline">
                                    <input type="checkbox" id="setting-remember-facts-enabled">
                                    <span class="form-checkbox-label">启用事实记忆</span>
                                </label>
                            </div>
                            <div class="form-group">
                                <label class="form-label">最大事实数量</label>
                                <input type="number" id="setting-max-context-facts" min="0" step="1">
                            </div>
                            <div class="form-group">
                                <label class="form-checkbox form-checkbox-inline">
                                    <input type="checkbox" id="setting-profile-inject-in-prompt">
                                    <span class="form-checkbox-label">在提示词注入画像</span>
                                </label>
                            </div>
                            <div class="form-group">
                                <label class="form-checkbox form-checkbox-inline">
                                    <input type="checkbox" id="setting-vector-memory-enabled">
                                    <span class="form-checkbox-label">启用向量记忆 / RAG 总开关</span>
                                </label>
                            </div>
                            <div class="form-group full-width">
                                <label class="form-label">单独 embedding 模型</label>
                                <input type="text" id="setting-vector-memory-embedding-model" placeholder="留空则跟随当前预设；Ollama 可填 nomic-embed-text">
                                <div class="form-help-text" id="vector-memory-help">关闭总开关后，运行期 RAG 和导出聊天记录 RAG 都不会建立向量索引或执行召回。</div>
                            </div>
                            <div class="form-group">
                                <label class="form-checkbox form-checkbox-inline">
                                    <input type="checkbox" id="setting-export-rag-enabled">
                                    <span class="form-checkbox-label">启用导出聊天记录 RAG（默认关闭）</span>
                                </label>
                            </div>
                            <div class="form-group">
                                <label class="form-checkbox form-checkbox-inline">
                                    <input type="checkbox" id="setting-export-rag-auto-ingest">
                                    <span class="form-checkbox-label">自动扫描并增量导入</span>
                                </label>
                            </div>
                            <div class="form-group full-width">
                                <label class="form-label">导出目录</label>
                                <input type="text" id="setting-export-rag-dir" placeholder="chat_exports/聊天记录">
                            </div>
                            <div class="form-group">
                                <label class="form-label">每次注入片段数</label>
                                <input type="number" id="setting-export-rag-top-k" min="1" step="1">
                            </div>
                            <div class="form-group">
                                <label class="form-label">每联系人最大片段数</label>
                                <input type="number" id="setting-export-rag-max-chunks-per-chat" min="1" step="1">
                            </div>
                            <div class="form-group full-width">
                                <label class="form-label">索引状态</label>
                                <div id="export-rag-status" class="form-help-text">状态：未加载</div>
                            </div>
                        </div>
                    </div>

                    <div class="settings-card">
                        <h2 class="settings-card-title">控制命令</h2>
                        <div class="settings-grid">
                            <div class="form-group">
                                <label class="form-checkbox form-checkbox-inline">
                                    <input type="checkbox" id="setting-control-commands-enabled">
                                    <span class="form-checkbox-label">启用控制命令</span>
                                </label>
                            </div>
                            <div class="form-group">
                                <label class="form-label">命令前缀</label>
                                <input type="text" id="setting-control-command-prefix">
                            </div>
                            <div class="form-group">
                                <label class="form-checkbox form-checkbox-inline">
                                    <input type="checkbox" id="setting-control-reply-visible">
                                    <span class="form-checkbox-label">控制命令回复可见</span>
                                </label>
                            </div>
                            <div class="form-group full-width">
                                <label class="form-label">允许命令的用户（每行一个）</label>
                                <textarea id="setting-control-allowed-users" rows="3"></textarea>
                            </div>
                        </div>
                    </div>

                    <div class="settings-card">
                        <h2 class="settings-card-title">定时静默</h2>
                        <div class="settings-grid">
                            <div class="form-group">
                                <label class="form-checkbox form-checkbox-inline">
                                    <input type="checkbox" id="setting-quiet-hours-enabled">
                                    <span class="form-checkbox-label">启用静默时段</span>
                                </label>
                            </div>
                            <div class="form-group">
                                <label class="form-label">静默开始时间</label>
                                <input type="text" id="setting-quiet-hours-start" placeholder="23:00">
                            </div>
                            <div class="form-group">
                                <label class="form-label">静默结束时间</label>
                                <input type="text" id="setting-quiet-hours-end" placeholder="07:00">
                            </div>
                            <div class="form-group full-width">
                                <label class="form-label">静默自动回复</label>
                                <input type="text" id="setting-quiet-hours-reply">
                            </div>
                        </div>
                    </div>

                    <div class="settings-card">
                        <h2 class="settings-card-title">用量监控</h2>
                        <div class="settings-grid">
                            <div class="form-group">
                                <label class="form-checkbox form-checkbox-inline">
                                    <input type="checkbox" id="setting-usage-tracking-enabled">
                                    <span class="form-checkbox-label">启用用量追踪（默认关闭）</span>
                                </label>
                            </div>
                            <div class="form-group">
                                <label class="form-label">每日 token 上限</label>
                                <input type="number" id="setting-daily-token-limit" min="0" step="1">
                            </div>
                            <div class="form-group">
                                <label class="form-label">告警阈值（0-1）</label>
                                <input type="number" id="setting-token-warning-threshold" min="0" max="1" step="0.01">
                            </div>
                        </div>
                    </div>

                    <div class="settings-card">
                        <h2 class="settings-card-title">情感识别</h2>
                        <div class="settings-grid">
                            <div class="form-group">
                                <label class="form-checkbox form-checkbox-inline">
                                    <input type="checkbox" id="setting-emotion-detection-enabled">
                                    <span class="form-checkbox-label">启用情感识别</span>
                                </label>
                            </div>
                            <div class="form-group">
                                <label class="form-label">检测模式</label>
                                <select class="form-input" id="setting-emotion-detection-mode">
                                    <option value="keywords">keywords</option>
                                    <option value="ai">ai</option>
                                </select>
                            </div>
                            <div class="form-group">
                                <label class="form-checkbox form-checkbox-inline">
                                    <input type="checkbox" id="setting-emotion-inject-in-prompt">
                                    <span class="form-checkbox-label">注入情绪引导</span>
                                </label>
                            </div>
                            <div class="form-group">
                                <label class="form-checkbox form-checkbox-inline">
                                    <input type="checkbox" id="setting-emotion-log-enabled">
                                    <span class="form-checkbox-label">记录情绪日志</span>
                                </label>
                            </div>
                        </div>
                    </div>

                    <div class="settings-card">
                        <h2 class="settings-card-title">LangChain Runtime</h2>
                        <div class="settings-grid">
                            <div class="form-group">
                                <label class="form-checkbox form-checkbox-inline">
                                    <input type="checkbox" id="setting-agent-enabled">
                                    <span class="form-checkbox-label">启用 LangGraph 主链路</span>
                                </label>
                            </div>
                            <div class="form-group">
                                <label class="form-label">图模式</label>
                                <input type="text" id="setting-agent-graph-mode" placeholder="state_graph">
                            </div>
                            <div class="form-group">
                                <label class="form-label">Retriever Top-K</label>
                                <input type="number" id="setting-agent-retriever-top-k" min="1" step="1">
                            </div>
                            <div class="form-group">
                                <label class="form-label">检索阈值</label>
                                <input type="number" id="setting-agent-retriever-threshold" min="0" step="0.01">
                            </div>
                            <div class="form-group">
                                <label class="form-label">Embedding 缓存 TTL(秒)</label>
                                <input type="number" id="setting-agent-embedding-cache-ttl" min="0" step="1">
                            </div>
                            <div class="form-group">
                                <label class="form-label">最大并行检索器</label>
                                <input type="number" id="setting-agent-max-parallel-retrievers" min="1" step="1">
                            </div>
                            <div class="form-group">
                                <label class="form-checkbox form-checkbox-inline">
                                    <input type="checkbox" id="setting-agent-background-facts">
                                    <span class="form-checkbox-label">后台事实提取</span>
                                </label>
                            </div>
                            <div class="form-group">
                                <label class="form-checkbox form-checkbox-inline">
                                    <input type="checkbox" id="setting-agent-emotion-fast-path">
                                    <span class="form-checkbox-label">情绪快速路径</span>
                                </label>
                            </div>
                            <div class="form-group">
                                <label class="form-checkbox form-checkbox-inline">
                                    <input type="checkbox" id="setting-agent-langsmith-enabled">
                                    <span class="form-checkbox-label">启用 LangSmith tracing</span>
                                </label>
                            </div>
                            <div class="form-group">
                                <label class="form-label">LangSmith 项目名</label>
                                <input type="text" id="setting-agent-langsmith-project" placeholder="wechat-chat">
                            </div>
                            <div class="form-group">
                                <label class="form-label">LangSmith Endpoint</label>
                                <input type="text" id="setting-agent-langsmith-endpoint" placeholder="https://api.smith.langchain.com">
                            </div>
                            <div class="form-group">
                                <label class="form-label">LangSmith Key 状态</label>
                                <input type="text" id="agent-langsmith-key-status" disabled placeholder="未配置">
                            </div>
                        </div>
                    </div>

                    <div class="settings-card">
                        <h2 class="settings-card-title">日志设置</h2>
                        <div class="settings-grid">
                            <div class="form-group">
                                <label class="form-label">日志级别</label>
                                <select class="form-input" id="setting-log-level">
                                    <option value="DEBUG">DEBUG</option>
                                    <option value="INFO">INFO</option>
                                    <option value="WARNING">WARNING</option>
                                    <option value="ERROR">ERROR</option>
                                </select>
                            </div>
                            <div class="form-group">
                                <label class="form-label">日志格式</label>
                                <select class="form-input" id="setting-log-format">
                                    <option value="text">text</option>
                                    <option value="json">json</option>
                                </select>
                            </div>
                            <div class="form-group">
                                <label class="form-label">日志文件路径</label>
                                <input type="text" id="setting-log-file">
                            </div>
                            <div class="form-group">
                                <label class="form-label">单文件最大字节</label>
                                <input type="number" id="setting-log-max-bytes" min="1024" step="1024">
                            </div>
                            <div class="form-group">
                                <label class="form-label">保留文件数</label>
                                <input type="number" id="setting-log-backup-count" min="0" step="1">
                            </div>
                            <div class="form-group">
                                <label class="form-checkbox form-checkbox-inline">
                                    <input type="checkbox" id="setting-log-message-content">
                                    <span class="form-checkbox-label">记录用户消息内容</span>
                                </label>
                            </div>
                            <div class="form-group">
                                <label class="form-checkbox form-checkbox-inline">
                                    <input type="checkbox" id="setting-log-reply-content">
                                    <span class="form-checkbox-label">记录回复内容</span>
                                </label>
                            </div>
                        </div>
                    </div>

                    <div class="settings-card">
                        <h2 class="settings-card-title">关闭行为</h2>
                        <div class="form-group full-width">
                            <div class="detail-note">如需重新选择关闭方式，可在此重置</div>
                            <button class="btn btn-secondary btn-sm" id="btn-reset-close-behavior">重置关闭选择</button>
                        </div>
                    </div>

                    <!-- 白名单设置 -->
                    <div class="settings-card">
                        <h2 class="settings-card-title">白名单管理</h2>
                        <div class="form-group full-width">
                            <label class="form-checkbox form-checkbox-inline">
                                <input type="checkbox" id="setting-whitelist-enabled">
                                <span class="form-checkbox-label">启用白名单模式（仅回复白名单中的联系人/群）</span>
                            </label>
                        </div>
                        <div class="form-group full-width">
                            <label class="form-label">白名单（每行一个联系人或群名）</label>
                            <textarea id="setting-whitelist" rows="4" placeholder="联系人1&#10;群聊1&#10;..."></textarea>
                        </div>
                    </div>
                </div>

                <button class="btn btn-primary btn-sm settings-scroll-top" id="btn-settings-scroll-top" type="button">
                    回到顶部
                </button>

`;
}

export default renderSettingsPageShell;

