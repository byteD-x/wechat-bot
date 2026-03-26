export function renderAboutPageShell() {
    return `
                <div class="page-header about-page-header">
                    <div>
                        <div class="about-page-kicker">认真做一个小工具</div>
                        <h1 class="page-title about-page-title">关于这个小助手</h1>
                        <p class="page-subtitle about-page-subtitle">希望它能让你的日常使用，稍微顺手一点。</p>
                    </div>
                </div>

                <div class="about-stage">
                    <div class="card about-hero">
                        <div class="card-body about-hero-body">
                            <div class="about-hero-main">
                                <div class="about-hero-brand">
                                    <div class="about-hero-logo-shell">
                                        <img class="about-hero-logo" src="../assets/icon.png" alt="微信AI助手图标">
                                    </div>
                                    <div class="about-hero-copy">
                                        <div class="about-hero-kicker">WeChat AI Assistant</div>
                                        <h2 class="about-hero-title">微信AI助手</h2>
                                        <p class="about-hero-description">把常用功能放在一起，少一点折腾，多一点顺手。</p>
                                    </div>
                                </div>

                                <div class="about-hero-tags">
                                    <span class="about-tag">桌面控制台</span>
                                    <span class="about-tag">开源协作</span>
                                    <span class="about-tag">长期打磨</span>
                                </div>
                            </div>

                            <aside class="about-hero-side">
                                <div class="about-hero-update">
                                    <div class="about-hero-update-kicker">版本与更新</div>
                                    <div class="update-panel">
                                        <div class="update-panel-content">
                                            <div class="update-status-text" id="update-status-text">未检查更新</div>
                                            <div class="update-status-meta" id="update-status-meta">当前版本：--</div>
                                        </div>
                                        <div class="update-panel-actions">
                                            <button class="btn btn-secondary btn-sm" id="btn-check-updates">检查更新</button>
                                            <button class="btn btn-primary btn-sm is-hidden" id="btn-open-update-download">下载更新</button>
                                        </div>
                                    </div>
                                </div>

                                <div class="about-hero-note">
                                    <div class="about-hero-note-label">谢谢你</div>
                                    <div class="about-hero-note-title">愿意用，也愿意提意见</div>
                                    <p class="about-hero-note-text">每一条反馈和支持，我都会认真看。</p>
                                    <div class="about-hero-sign">ByteD-x</div>
                                </div>
                            </aside>
                        </div>
                    </div>

                    <div class="card-grid about-link-grid">
                    <button class="about-link-card" type="button" data-kind="author" data-label="作者主页" data-url="https://github.com/ByteD-x">
                        <div class="about-link-card-top">
                            <div class="about-link-icon">
                                <svg class="icon">
                                    <use href="#icon-user" />
                                </svg>
                            </div>
                            <svg class="icon about-link-arrow">
                                <use href="#icon-external" />
                            </svg>
                        </div>
                        <div class="about-link-meta">作者</div>
                        <strong class="about-link-title">ByteD-x</strong>
                        <p class="about-link-description">项目维护者的主页。</p>
                        <div class="about-link-footer">
                            <span class="about-link-hint">github.com/ByteD-x</span>
                            <span class="about-link-cta">去主页看看</span>
                        </div>
                    </button>

                    <button class="about-link-card" type="button" data-kind="repository" data-label="开源仓库" data-url="https://github.com/byteD-x/wechat-bot">
                        <div class="about-link-card-top">
                            <div class="about-link-icon">
                                <svg class="icon">
                                    <use href="#icon-file-text" />
                                </svg>
                            </div>
                            <svg class="icon about-link-arrow">
                                <use href="#icon-external" />
                            </svg>
                        </div>
                        <div class="about-link-meta">开源仓库</div>
                        <strong class="about-link-title">源码、版本与更新</strong>
                        <p class="about-link-description">源码和更新都在这里。</p>
                        <div class="about-link-footer">
                            <span class="about-link-hint">byteD-x/wechat-bot</span>
                            <span class="about-link-cta">打开仓库</span>
                        </div>
                    </button>

                    <button class="about-link-card" type="button" data-kind="feedback" data-label="意见反馈" data-url="https://github.com/byteD-x/wechat-bot/issues">
                        <div class="about-link-card-top">
                            <div class="about-link-icon">
                                <svg class="icon">
                                    <use href="#icon-message" />
                                </svg>
                            </div>
                            <svg class="icon about-link-arrow">
                                <use href="#icon-external" />
                            </svg>
                        </div>
                        <div class="about-link-meta">意见反馈</div>
                        <strong class="about-link-title">来提一个想法</strong>
                        <p class="about-link-description">Bug、建议或想法，都欢迎留下。</p>
                        <div class="about-link-footer">
                            <span class="about-link-hint">GitHub Issues</span>
                            <span class="about-link-cta">提交 Issue</span>
                        </div>
                    </button>

                    <button class="about-link-card about-link-card-sponsor" type="button" data-kind="sponsor" data-label="赞助支持" data-url="https://github.com/byteD-x/wechat-bot/blob/main/docs/SPONSOR.md">
                        <div class="about-link-card-top">
                            <div class="about-link-icon">
                                <svg class="icon">
                                    <use href="#icon-coins" />
                                </svg>
                            </div>
                            <svg class="icon about-link-arrow">
                                <use href="#icon-external" />
                            </svg>
                        </div>
                        <div class="about-link-meta">赞助支持</div>
                        <strong class="about-link-title">给这个项目续一杯咖啡</strong>
                        <p class="about-link-description">如果它对你有帮助，欢迎支持一下。</p>
                        <div class="about-link-footer">
                            <span class="about-link-hint">docs/SPONSOR.md</span>
                            <span class="about-link-cta">查看支持方式</span>
                        </div>
                    </button>
                    </div>
                </div>
`;
}

export default renderAboutPageShell;

