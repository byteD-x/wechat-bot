# Repo Inventory

Repo: `E:\Project\wechat-chat`
Generated: 2026-06-06

本清单按源码视角生成，排除了 `.git/`、`node_modules/`、`data/`、`release/`、`backend-dist/`、`dist/`、`build/` 以及本地未跟踪临时目录 `MagicMock/`。构建产物和运行数据不计入项目规模。

## 总览

- 源码文件数：375
- 源码体积：约 4.85 MB
- Python 文件：198
- JS / MJS / CJS 文件：104
- Markdown 文件：25
- 测试文件：58
- 当前应用版本：`package.json` 中为 `1.6.2`

## 顶层目录职责

| 路径 | 文件数 | 职责 |
| --- | ---: | --- |
| `src/` | 111 | Electron 主进程、preload、渲染层页面、服务层与样式 |
| `tools/` | 85 | 微信数据库解析、聊天导出、Prompt 生成等离线工具 |
| `backend/` | 80 | Quart API、Bot 生命周期、LangGraph runtime、记忆、RAG、备份、模型认证中心 |
| `tests/` | 58 | Python 回归测试与 Node 原生测试 |
| `docs/` | 24 | 使用、系统链路、模型认证、发布、项目亮点与仓库盘点文档 |
| `scripts/` | 5 | 本地检查、发布元数据校验与 Release notes 生成 |

根目录关键文件包括 `README.md`、`AGENTS.md`、`run.py`、`requirements.txt`、`package.json`、`electron-builder.yml`、`pytest.ini`、`.github/workflows/ci.yml` 和 `.github/workflows/release.yml`。

## 主要扩展名

| 扩展名 | 数量 |
| --- | ---: |
| `.py` | 198 |
| `.js` | 87 |
| `.md` | 25 |
| `.css` | 20 |
| `.mjs` | 14 |
| `.proto` | 9 |
| `.json` | 7 |
| `.cjs` | 3 |

## 入口点

- `run.py`：统一 CLI，支持 `start`、`setup`、`check`、`web`、`eval`、`backup`、`config`。
- `backend/main.py`：后端主入口。
- `backend/api.py`：Quart Web API，承载状态、生命周期、消息、微信导出、成本、模型认证、配置与日志接口。
- `backend/bot.py` / `backend/bot_manager.py`：机器人生命周期、消息主循环和运行态管理。
- `backend/core/agent_runtime.py`：LangChain / LangGraph 对话快路径与后台成长能力。
- `backend/core/wechat_export_service.py`：微信导出中心后端服务。
- `src/main/index.js`：Electron 主进程入口。
- `src/preload/index.js`：受控 preload API。
- `src/renderer/js/app.module.js`：渲染层应用装配。
- `src/renderer/js/pages/ModelsPage.js`：模型与认证中心页面。
- `src/renderer/js/pages/ExportCenterPage.js`：微信聊天记录导出中心页面。
- `tools/chat_exporter/cli.py`：已解密微信数据库的 CSV 导出 CLI。

## 主要文档

- `README.md`：仓库首页、快速启动、功能与开发命令。
- `docs/USER_GUIDE.md`：详细使用、配置、运行、排障与 API 摘要。
- `docs/SYSTEM_CHAINS.md`：启动、API、消息、配置、状态、更新等系统链路。
- `docs/HIGHLIGHTS.md`：当前能力与架构亮点。
- `docs/MODEL_AUTH_CENTER.md`：Provider/Auth 领域模型、认证矩阵、扩展方式与安全边界。
- `docs/wechat-export-guide.md`：微信聊天记录探测、解密、导出与导出语料 RAG 流程。
- `docs/RELEASE_UPDATES.md` 与 `docs/release_notes/`：发布策略与各版本 Release notes。

## 测试与质量门禁

当前 CI 在 Windows 上执行：

- Python 3.10 与 Node.js 20 环境安装。
- `python -m py_compile backend\core\agent_runtime.py backend\bot.py backend\bot_manager.py backend\api.py`
- `python -m ruff check` 指定后端、CLI 和测试文件集。
- 重点 Python 回归测试：`tests\test_smoke.py`、`tests\test_api.py`、`tests\test_runtime_observability.py`、`tests\test_agent_runtime.py`、`tests\test_optimization_tasks.py`、`tests\test_reply_policy.py`、`tests\test_backup_service.py`、`tests\test_eval_runner.py`
- 离线评测烟雾门禁：`python run.py eval --dataset tests\fixtures\evals\smoke_cases.json --preset ci-smoke --report data\evals\ci-smoke-report.json`
- Node 测试：`npm test`

`package.json` 当前还提供：

- `npm run test:main`
- `npm run test:renderer`
- `npm run build:release`
- `npm run build:msi`

## 盘点结论

- 代码主体已经从早期机器人脚本演进为“Python 后端 + Electron 前端 + 离线工具 + CI 门禁”的桌面产品结构。
- 当前系统事实源应优先读取 `backend/`、`src/`、`tests/`、`.github/workflows/` 和 `docs/`，不要从 `release/`、`backend-dist/` 或运行时 `data/` 推断源码规模。
- 与文档同步相关的高频事实包括：共享配置真源 `data/app_config.json`、默认传输后端 `wcferry`、官方支持微信 `3.9.12.51`、配置 CLI `python run.py config ...`、微信导出 API、成本复盘导出 API 与模型中心 API。
