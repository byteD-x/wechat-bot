import { renderIconSprite } from './icons.js';
import { renderGlobalOverlays } from './modals.js';

const NAV_GROUPS = [
    {
        label: '运行',
        items: [
            { page: 'dashboard', icon: 'dashboard', label: '仪表盘', active: true },
            { page: 'costs', icon: 'coins', label: '成本' },
            { page: 'messages', icon: 'message', label: '消息' },
        ],
    },
    {
        label: '配置',
        items: [
            { page: 'exports', icon: 'download', label: '导出接入' },
            { page: 'models', icon: 'bot', label: '模型' },
            { page: 'settings', icon: 'settings', label: '设置' },
        ],
    },
    {
        label: '诊断',
        items: [
            { page: 'logs', icon: 'terminal', label: '日志' },
            { page: 'about', icon: 'info', label: '关于' },
        ],
    },
];

const PAGE_MOUNTS = [
    { id: 'dashboard', label: '仪表盘', active: true },
    { id: 'costs', label: '成本' },
    { id: 'messages', label: '消息' },
    { id: 'exports', label: '导出接入' },
    { id: 'models', label: '模型' },
    { id: 'settings', label: '设置' },
    { id: 'logs', label: '日志' },
    { id: 'about', label: '关于' },
];

function renderNavGroups() {
    return NAV_GROUPS.map((group) => `
        <div class="sidebar-group">
            <div class="sidebar-group-label">${group.label}</div>
            <div class="sidebar-nav">
                ${group.items.map((item) => `
                    <a href="#" class="nav-item${item.active ? ' active' : ''}" data-page="${item.page}">
                        <svg class="icon">
                            <use href="#icon-${item.icon}" />
                        </svg>
                        <span class="nav-label">${item.label}</span>
                    </a>
                `).join('')}
            </div>
        </div>
    `).join('');
}

function renderPageMounts() {
    return PAGE_MOUNTS.map((page) => `
        <section class="page page-${page.id}${page.active ? ' active' : ''}" id="page-${page.id}" data-page-label="${page.label}"></section>
    `).join('');
}

export function renderAppFrame() {
    return `
        ${renderIconSprite()}
        <header class="titlebar">
            <div class="titlebar-left">
                <svg class="icon titlebar-logo">
                    <use href="#icon-bot" />
                </svg>
                <div class="titlebar-copy">
                    <span class="titlebar-title">微信 AI 助手</span>
                    <span class="titlebar-subtitle">桌面控制台</span>
                </div>
            </div>
            <div class="titlebar-controls">
                <button class="titlebar-btn" id="btn-minimize" type="button" title="最小化" aria-label="最小化窗口">
                    <svg class="icon">
                        <use href="#icon-minus" />
                    </svg>
                </button>
                <button class="titlebar-btn" id="btn-maximize" type="button" title="最大化" aria-label="最大化窗口">
                    <svg class="icon">
                        <use href="#icon-maximize" />
                    </svg>
                </button>
                <button class="titlebar-btn btn-close" id="btn-close" type="button" title="关闭" aria-label="关闭窗口">
                    <svg class="icon">
                        <use href="#icon-x" />
                    </svg>
                </button>
            </div>
        </header>

        <div class="app-container app-shell-container">
            <nav class="sidebar">
                <div class="sidebar-brand">
                    <div class="sidebar-brand-mark">WA</div>
                    <div class="sidebar-brand-copy">
                        <strong>工作台</strong>
                        <span>运行、配置、诊断</span>
                    </div>
                </div>

                <div class="sidebar-content">
                    ${renderNavGroups()}
                </div>

                <div class="sidebar-footer">
                    <div class="sidebar-runtime-card">
                        <div class="sidebar-runtime-label">应用状态</div>
                        <div class="status-badge" id="status-badge" title="点击可尝试启动服务">
                            <span class="status-dot warning"></span>
                            <span class="status-label">准备服务中</span>
                        </div>
                        <button class="update-badge" id="update-badge" hidden>发现新版本</button>
                    </div>
                    <div class="sidebar-version-row">
                        <span class="sidebar-version-label">当前版本</span>
                        <span class="version-text" id="version-text">--</span>
                    </div>
                </div>
            </nav>

            <main class="main-content">
                ${renderPageMounts()}
            </main>
        </div>

        ${renderGlobalOverlays()}
    `;
}

export default renderAppFrame;
