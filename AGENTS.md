# 仓库协作指南

本文件面向自动化 Agent 与人工协作者，要求所有改动都遵循“小步、可验证、可回滚”。

## 1. 项目画像
- 项目名称：`wechat-ai-assistant`
- 运行平台：Windows 10 / 11
- 主要技术栈：
  - Python 3.9+：`Quart`、`httpx`、`aiosqlite`、`LangChain`、`LangGraph`、`ChromaDB`
  - Node.js 16+：`Electron`、`electron-builder`
- 关键入口：
  - `run.py`
  - `backend/`
  - `src/`
  - `tests/`
- 当前主要后端能力：
  - `BaseTransport` 传输层抽象，内置 `hook_wcferry` 与 `compat_ui`
  - LangGraph 运行时、SQLite 记忆、运行期 RAG、导出语料 RAG
  - `/api/status` 结构化状态与 `/api/metrics` 指标导出
  - 配置热重载优先使用 `watchdog`，缺失依赖时回退轮询

## 2. 目录与职责
- `backend/`
  - `bot.py`：机器人主循环与消息处理
  - `api.py`：Quart Web API
  - `core/`：AI 客户端、记忆、RAG、情感分析、LangGraph 运行时
  - `transports/`：传输层抽象与具体实现
  - `utils/`：日志、配置加载、配置监听、IPC
- `src/`
  - `main/`：Electron 主进程
  - `renderer/`：前端页面与状态管理
- `tests/`：`pytest` 为主的回归测试
- `docs/`：面向用户和维护者的说明文档

## 3. 协作原则
- 先读后改：先确认现有实现、配置来源和调用链，再动代码或文档。
- 单次只解决一个主题：不要把功能、重构、格式化混在一起。
- 不猜测成功：所有“已完成”都必须有命令输出或测试结果支撑。
- 优先复用：已有工具函数、配置结构、状态字段优先复用，不重复造轮子。
- 改动影响使用方式、配置项或接口时，必须同步更新文档。

## 4. 安全与操作边界
- 禁止输出或提交真实 `API Key`、聊天导出、日志中的敏感内容。
- 禁止执行来源不明的下载脚本或破坏性命令。
- 未经明确授权，不做下列操作：
  - 删除用户数据
  - 覆盖生产配置
  - 强推分支
  - 回滚不属于当前任务的改动
- 涉及用户数据、权限或支付链路时，先写 1 到 3 条威胁模型，再改代码。

## 5. 开发与验证命令
- 需要使用项目内的`.venv`环境
- 安装依赖：
  - `pip install -r requirements.txt`
  - `npm install`
- 本地运行：
  - `npm run dev`S
  - `python run.py start`
  - `python run.py web`
  - `python run.py check`
- 推荐验证命令，按改动范围选择，不要求每次全跑：
  - Python 语法检查：
    - `python -m py_compile backend\core\agent_runtime.py backend\bot.py backend\bot_manager.py backend\api.py`
  - 重点测试：
    - `python -m pytest tests\test_agent_runtime.py -q`
    - `python -m pytest tests\test_optimization_tasks.py -q`
    - `python -m pytest tests\test_runtime_observability.py -q`
  - 桌面端构建：
    - `npm run build`

说明：
- 不要声称验证通过，除非命令已经实际执行。

## 6. 配置与运行时约束
- 主要配置来源：
  - `backend/config.py`
  - `data/config_override.json`
  - `data/api_keys.py`
  - `prompt_overrides.py`
- 热重载相关字段：
  - `bot.config_reload_mode`: `auto` / `polling` / `watchdog`
  - `bot.config_reload_debounce_ms`
- 运行期 RAG 精排相关字段：
  - `agent.retriever_rerank_mode`: `lightweight` / `auto` / `cross_encoder`
  - `agent.retriever_cross_encoder_model`
  - `agent.retriever_cross_encoder_device`
- 本地 `Cross-Encoder` 只支持显式配置本地模型目录；项目不会自动联网下载模型。

## 7. 文档同步要求
- 改动以下内容时，至少同步 `README.md`、`docs/USER_GUIDE.md`、`docs/HIGHLIGHTS.md` 中的对应位置：
  - 新增或修改配置项
  - 新增或修改 API 接口
  - 新增运行模式、监控指标或诊断字段
  - 重要架构变化，如传输层抽象、RAG 精排策略
- 若版本发布行为或安装产物变化，还要同步 `RELEASE_UPDATES.md`。
- 若项目亮点或案例表述变化明显，还要同步 `STAR_REPO_STAR.md`。

## 8. 提交与评审
- 提交信息使用 Conventional Commits：
  - `feat`
  - `fix`
  - `docs`
  - `refactor`
  - `test`
  - `chore`
  - `build`
  - `ci`
- 提交说明至少包含：
  - What：改了什么
  - Why：为什么改
  - How to verify：怎么验证，附命令和期望结果
- 评审优先级：
  - 行为回归
  - 配置兼容性
  - 错误处理与日志安全
  - 测试覆盖是否足够

## 9. 执行清单
- 开始前：
  - 明确目标文件、影响范围和回滚点
  - 检查工作区是否已有用户未提交改动
- 修改中：
  - 每完成一块就做最小验证
  - 发现和任务冲突的陌生改动时先停下确认
- 结束前：
  - 汇总改动文件
  - 列出已执行验证命令与结果
  - 说明剩余风险或环境限制
