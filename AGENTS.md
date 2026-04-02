# AGENTS.md

本文件定义 `wechat-ai-assistant` 仓库的人机协作规则。目标不是“写很多说明”，而是让协作者能在最小上下文下，稳定做出小步、可验证、可回滚的改动。

## 1. 协作目标

- 默认目标是推进交付，不是停留在分析。
- 所有完成都必须可验证；没有命令结果、测试结果或可复现观察，就不算完成。
- 优先级固定为：安全 > 正确性 > 可回滚 > 迭代速度。
- 单次只解决一个主题；不要把功能、重构、格式化、顺手优化混成一次大改。

## 2. Harness Engineering 原则

本仓库采用 Harness Engineering 思路组织协作，重点体现在四件事上：

### 2.1 上下文工程

- `AGENTS.md` 只保留决策入口、边界和工作流，不承载细枝末节说明。
- 详细知识放回仓库系统事实源，按需读取，避免一次性把无关上下文塞进工作记忆。
- 信息优先级：运行中的代码与测试 > 当前文档 > `AGENTS.md` > 对话记忆。
- 发现“文档与代码冲突”时，不允许沿用旧认知；要么在本次改动中修正，要么明确标注为待修正风险。

### 2.2 架构约束

- 先定义哪些边界不能穿透，再在边界内做改动。
- 优先复用现有模块、配置结构、API 形状、测试入口和发布流程，不另起一套旁路。
- 对运行时、配置、安全、跨进程通信、发布链路的改动，先确认约束，再动代码。

### 2.3 反馈循环

- 每完成一小步，立刻做最小验证。
- 能写成自动化检查的，就不要只靠人工判断。
- 先构造复现或观察点，再修复；不要“猜已经好了”。
- 发现回归后，优先补测试、补诊断、补文档，避免同类问题反复出现。

### 2.4 垃圾回收

- 仓库允许持续小规模“去腐化”：删除过时说明、重复约束、无效分支、死配置、重复脚手架。
- 垃圾回收必须与当前任务强相关、低风险、可解释；不要借机做大扫除式重构。
- 新规则进入仓库后，要替代旧规则，避免多份相互冲突的说明同时存在。

## 3. 系统事实源

遇到信息缺失时，优先阅读下面这些文件，而不是猜：

- `docs/SYSTEM_CHAINS.md`
  - 启动链路、消息链路、配置链路、热重载、状态与诊断链路。
- `docs/USER_GUIDE.md`
  - 环境要求、运行方式、配置来源、API、运维与验证步骤。
- `docs/HIGHLIGHTS.md`
  - 当前对外能力、架构亮点、近期稳定性能力。
- `README.md`
  - 仓库首页级信息、快速启动、功能总览。
- `.github/workflows/ci.yml`
  - 当前 CI 真正执行的质量门禁。
- `.github/workflows/release.yml`
  - 发布约束、版本校验、构建和 Release 行为。

如果以上文件仍无法确认，再读实现代码；不要把聊天记录当成系统事实源。

## 4. 仓库画像

- 项目名：`wechat-ai-assistant`
- 平台：Windows 10 / 11
- 本地运行要求：Python `3.9+`、Node.js `16+`
- CI 基线：Python `3.10`、Node.js `20`
- 关键运行依赖：`Quart`、`httpx`、`aiosqlite`、`LangChain`、`LangGraph`、`ChromaDB`、`Electron`、`electron-builder`
- 当前官方支持的微信版本：`3.9.12.51`
- 默认传输后端：`wcferry`

## 5. 目录职责与边界

- `backend/`
  - Python 后端；包含 bot 主循环、Quart API、LangGraph runtime、记忆、RAG、回复策略、备份恢复、模型认证中心。
- `backend/transports/`
  - 传输层抽象与实现；新传输能力必须遵守 `BaseTransport` 契约，不要把 bot 直接耦合到具体实现。
- `src/main/`
  - Electron 主进程；负责后端进程、IPC、桌面生命周期、共享配置入口。
- `src/renderer/`
  - 前端渲染层；通过既有 API/IPC 服务访问状态和动作，不直接绕过边界操作后端内部。
- `tests/`
  - Python `pytest` 与 Node 原生测试；行为变更优先补这里。
- `docs/`
  - 面向用户与维护者的系统文档；配置、API、运行模式、发布说明的系统事实源。
- `data/`
  - 运行时状态、共享配置、日志、备份、评测报告等输出目录。

## 6. 必须遵守的架构约束

### 6.1 配置约束

- 运行时共享配置文件以 `data/app_config.json` 为唯一真实配置源。
- `backend/config.py`、`data/config_override.json`、`data/api_keys.py`、`prompt_overrides.py` 仍可能参与兼容迁移或备份，但不再是运行时主配置入口。
- 改配置链路时，必须同时检查 `backend/shared_config.py`、设置页 IPC、相关 API 与迁移兼容性。

### 6.2 运行时与安全约束

- 默认 `wcferry` 方案依赖 Windows 管理员权限与指定微信版本；不要在文档或代码里暗示跨平台或微信 `4.x` 兼容。
- `python run.py web` 绑定非回环地址时，必须显式设置 `WECHAT_BOT_API_TOKEN`；不要降低这个安全门槛。
- 不要泄露真实 `API Key`、OAuth 凭据、聊天导出、诊断快照中的敏感内容。
- 涉及数据清理、备份恢复、权限或凭据存储时，先写出 1 到 3 条威胁或失败模式，再实施改动。

### 6.3 边界约束

- 传输层改动经 `backend/transports/base.py` 抽象进入系统，不要在 `bot.py` 中堆特判。
- 前端与后端的交互优先复用现有 API、IPC、服务层与状态装配，不新增隐式通道。
- 备份/恢复链路保持保守策略：优先 `dry-run`、校验清单与 checksum、避免运行中热恢复。
- 发布链路保持 `git tag vX.Y.Z` 与 `package.json` 中 `X.Y.Z` 完全一致。

## 7. 标准工作流

1. 明确目标、影响范围、交付物和回滚点。
2. 读取最少但足够的上下文，只打开与当前任务直接相关的代码和文档。
3. 如果缺信息会影响方案或验收，一次性提出问题，并给出默认方案。
4. 先做最小改动，不预先扩展需求。
5. 每完成一块立即验证，再进入下一块。
6. 把新事实写回仓库：代码、测试、文档或注释，至少占一项。
7. 收尾时列出验证证据、结果、未覆盖项和残余风险。

## 8. 反馈循环与验证

### 8.1 最小验证原则

- 文档改动至少做语义自检，确认与仓库事实一致。
- Python 改动至少执行语法检查或目标测试。
- 前端或 Electron 改动至少执行相关 Node 测试；涉及打包再执行构建。
- 运行时行为改动优先通过 `run.py check`、`/api/status`、`/api/metrics`、日志或现有回归测试验证。

### 8.2 本仓库常用验证命令

使用项目内 `.venv` 环境执行。

```powershell
python -m py_compile backend\core\agent_runtime.py backend\bot.py backend\bot_manager.py backend\api.py
python -m pytest tests\test_agent_runtime.py -q
python -m pytest tests\test_optimization_tasks.py -q
python -m pytest tests\test_runtime_observability.py -q
python run.py check
npm test
npm run build
```

### 8.3 CI 当前门禁

`ci.yml` 当前会执行：

- Python 语法检查
- `ruff check` 指定文件集
- 重点 Python 回归测试
- `python run.py eval --dataset tests\fixtures\evals\smoke_cases.json --preset ci-smoke --report data\evals\ci-smoke-report.json`
- `npm test`

如果改动触发这些路径，就要优先确保本地验证策略与 CI 方向一致。

## 9. 垃圾回收规则

- 改到某块代码时，如果顺手发现同一作用域内的过时注释、失效规则、重复文档、明显死分支，可一并清理。
- 只清理能证明“现在已经无效”的内容；不确定就保留并标注。
- 清理后必须保证单次提交仍能清楚回答 `What / Why / How to verify`。
- 不要把“垃圾回收”当成无边界重构的理由。

## 10. 文档同步规则

改动以下内容时，必须同步对应文档：

- 配置项、配置来源、迁移路径
  - 更新 `README.md`、`docs/USER_GUIDE.md`
- API、状态字段、监控指标、诊断字段
  - 更新 `README.md`、`docs/USER_GUIDE.md`、必要时 `docs/HIGHLIGHTS.md`
- 架构主链路、传输层、RAG/重排策略、备份恢复流程
  - 更新 `docs/SYSTEM_CHAINS.md`、`docs/HIGHLIGHTS.md`
- 发布行为、版本策略、安装产物
  - 更新 `docs/RELEASE_UPDATES.md` 与 `docs/release_notes/<tag>.md`

文档不能只是“补一句”。要确保读者能据此完成配置、验证或排障。

## 11. 提交与发布约束

- 提交信息使用 Conventional Commits：`feat`、`fix`、`docs`、`refactor`、`test`、`chore`、`build`、`ci`
- 提交说明至少包含：
  - `What`
  - `Why`
  - `How to verify`
- 发布前必须满足：
  - Git tag 符合 `vX.Y.Z`
  - `package.json` 版本号符合 `X.Y.Z`
  - `docs/release_notes/<tag>.md` 存在
  - Release 文案只描述真实已发布且对外有影响的变更
  - `docs/release_notes/<tag>.md` 标题必须是 `# <tag> 更新内容`
  - 分组顺序固定为 `Features`、`Improvements`、`Fixes`、`Performance`、`Breaking Changes`
  - Release notes 只能包含标题与项目符号，不写代码块、不写 commit hash、不写 `misc changes`、`bug fixes and improvements`、`bump version` 之类空话

## 12. 禁止事项

- 禁止泄露密钥、凭据、聊天数据、未脱敏日志。
- 禁止未经授权删除用户数据、覆盖生产配置、强推分支、回滚他人未授权改动。
- 禁止在没有验证证据的情况下声称“已修复”“已完成”“已通过”。
- 禁止为了省事绕过现有安全门槛、配置边界、IPC/API 边界或发布校验。

## 13. 完成标准

一项任务只有同时满足以下条件，才算完成：

- 目标交付物已经落地。
- 已执行与改动范围匹配的验证。
- 验证结果已明确记录。
- 未覆盖项与剩余风险已说明。
- 改动可回滚，且没有顺手破坏不相关路径。
