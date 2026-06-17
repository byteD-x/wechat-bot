# 面试讲解手册

这份文档用于把项目里的工程能力讲清楚。不要把它当营销稿；面试时只讲已经落地、能指出代码和验证方式的事实。

## 一句话定位

这是一个面向 Windows 微信桌面端的本地 AI 助手，不只是调用大模型，而是把微信接入、模型认证、配置热重载、记忆/RAG、回复治理、备份恢复、离线评测和桌面控制台做成一套可长期运行的个人 agent 基础设施。

## 可重点讲的 8 个方向

1. Windows 产品化体验
   - 目标不是做网页 demo，而是贴近成熟 Windows 工具：稳定侧边导航、清晰状态区、设置分组、自动脱敏诊断支持包、错误恢复、运行时只读摘要。
   - 代码证据：`src/main/`、`src/renderer/`、`docs/USER_GUIDE.md`。
   - 验证方式：`npm run test:main`、`npm run test:renderer`、`npm run build`。

2. 统一模型与认证中心
   - 把 `api_key / oauth / local_import / web_session` 收敛成统一认证状态，不让用户在多个散落表单里猜当前生效方式。
   - 代码证据：`backend/model_auth/`、`docs/MODEL_AUTH_CENTER.md`。

3. Prompt 版本治理与回滚
   - 系统 Prompt 不再只是一个可覆盖字段；回滚会追加新的 active revision，并保留 `rollback_from/reason/operator/created_at`。
   - 代码证据：`backend/core/prompt_governance.py`、`POST /api/v1/admin/prompts/{revision}/rollback`。
   - 讲法重点：这是审计账本，不是简单覆盖历史。

4. 受控 Agent Tool Workflow
   - Agent 工具流只执行白名单工具，限制步数和 payload，返回逐步 trace；未知工具不会执行。
   - 现在还包括模型侧 Tool Calling 和只读 MCP adapter：模型只能看到更窄的安全工具子集，MCP 也只允许 `tools/list` 与 `tools/call`。
   - 代码证据：`backend/core/tool_workflow.py`、`POST /api/v1/agents/tool-workflow`。
   - 讲法重点：把 Agent 能力从“模型想调什么就调什么”收敛为“产品允许什么才执行什么”。
   - 一键演示脚本：`python scripts/run_interview_demo.py`，会串联 Web API readiness、离线 RAG eval、badcase summary、`eval_latest`、`cost_summary` 和 `plan_reflect_repair` 的安全修复 trace。
   - 证据包输出：`python scripts/run_interview_demo.py --summary`，会额外生成可分享的 Markdown 结果，默认写到 `data/runtime/demo/interview-demo-summary.md`。
   - 单项演示脚本：`python scripts/run_tool_workflow_demo.py`，适合只讲受控工具流和 trace。
   - 讲法重点：先说明这是不启动微信、不启动 Web API 的离线治理切片；再证明工具流可审计、可回放，评测和坏例复盘能接上。

5. 回复策略与人工审批
   - 新联系人、群聊、静音时段、敏感词或手动模式可以进入待审批队列，避免自动回复直接造成社交风险。
   - 代码证据：`backend/core/reply_policy.py`、`tests/test_reply_policy.py`。

6. 记忆与 RAG 的保守降级
   - 运行期向量记忆、导出语料 RAG 和本地重排是增强能力；未配置或缺依赖时应能回退，不阻断主回复链路。
   - 代码证据：`backend/core/agent_runtime.py`、`backend/core/export_rag.py`、`docs/SYSTEM_CHAINS.md`。

7. 备份恢复与数据治理
   - 备份/恢复优先 dry-run、manifest、checksum 和运行中保护；数据清理要求显式 scope 与停止运行时。
   - 代码证据：`backend/core/workspace_backup.py`、`backend/core/data_controls.py`。

8. 离线评测与 CI 门禁
   - 用固定 smoke dataset 检查空回复、短回复、RAG 命中率和运行时异常；避免只靠人工主观判断。
   - 代码证据：`backend/core/eval_runner.py`、`tests/fixtures/evals/smoke_cases.json`、`.github/workflows/ci.yml`。

9. 运行时观测与响应缓存
   - TraceLogger-lite 只保留内存级脱敏摘要，语义响应缓存默认关闭且不跨 chat/provider/model/safety/citation policy 命中。
   - 代码证据：`backend/core/trace_logger.py`、`backend/core/response_cache.py`、`tests/test_agent_runtime.py`。
   - 讲法重点：观测和缓存都是边界化能力，不保存原始 Prompt、聊天正文、token 或完整本机路径。

10. 受限容器化部署切片
   - Docker 只覆盖 Web API、`/api/readiness` 和离线 eval；不承诺 Linux 容器里运行微信桌面自动化或 wcferry 注入。
   - 代码证据：`Dockerfile`、`requirements-container.txt`、`backend/core/readiness.py`。
   - 讲法重点：这是把可验证的后端治理能力拆出来，而不是把微信机器人包装成跨平台服务。

## 一键演示流程

```powershell
npm run demo:interview
```

输出要按这个顺序讲：

1. `readiness`：`deployment_target=web-api` 表示脚本只验证 Web API / eval 治理切片，桌面微信传输检查会跳过。
2. `rag_*` 指标：重点解释 citation accuracy、context recall、faithfulness、answer-citation binding 和 refusal accuracy。
3. `badcases`：当前为 0 时，说明这组离线回归未发现失败样例；如果大于 0，就进入 [RAG badcase 复盘模板](RAG_BADCASE_REVIEW_TEMPLATE.md)。
4. `workflow_trace_steps` 与 `repair_attempted`：用来讲白名单工具、逐步 trace、schema 校验失败和受控 repair。
5. `rag_report`：默认落在 `data/runtime/demo/interview-rag-report.json`，属于本地运行时产物，不提交到仓库。
6. `--summary`：会额外生成一份 Markdown 证据包，适合投递前附带或面试时快速展开。

自动化流程如果需要 JSON，直接调用 Node 启动器并透传参数，避免 `npm run` 的命令前缀干扰标准输出：

```powershell
node scripts/run-interview-demo.mjs --skip-eval --json
```

这条演示链路的边界也要讲清楚：它不读取真实聊天、不访问真实微信、不执行任意 shell 或网络请求，也不替代 Windows + 微信 `3.9.12.51` 的人工收发验证。

## STAR 讲法示例

Situation：微信自动化项目容易停留在“能回消息”，但真实使用会遇到模型配置混乱、Prompt 被误改、Agent 工具不可控、用户不知道失败原因等问题。

Task：把项目从 demo 推向更成熟的 Windows 本地产品，要求关键能力可审计、可恢复、可验证。

Action：

- 收敛配置入口到共享配置快照，桌面端和后端读取同一事实源。
- 增加 Prompt 回滚账本，回滚追加新版本并保留原因和操作者。
- 增加受控工具流，限制白名单、步数、payload，并返回逐步 trace。
- 增加只读 MCP adapter、模型侧 Tool Calling 安全子集、TraceLogger-lite 和默认关闭的语义缓存，把模型可调用能力、观测能力和缓存能力都收在明确边界内。
- 扩充 API 测试、离线评测样例和文档契约。

Result：

- 当前新增 API 的目标测试已覆盖成功、404、白名单执行和未知工具拒绝。
- 全量 `tests/test_api.py` 已通过。
- 离线 smoke dataset 扩展到 27 条，覆盖 Prompt 回滚、工具流审计、Windows 首次运行、导出语料 RAG 风格召回、无命中回退和误命中防护场景。
- Docker/部署切片已提供 Web API/readiness/eval 镜像入口，`WECHAT_BOT_DEPLOYMENT_TARGET=web-api` 下 readiness 会明确跳过桌面微信传输检查。

## 不要夸大的点

- 不要说已经支持微信 `4.x` 或跨平台自动化；当前官方支持仍是 Windows + 微信 PC `3.9.12.51`。
- 不要说已经有线上真实用户指标；当前证据主要来自本地测试、离线评测和代码结构。
- 不要说 Agent 可以执行任意工具；当前设计故意只允许白名单工具。
- 不要说模型侧 Tool Calling、MCP adapter 或工具工作流能访问 shell、任意 HTTP、文件写入或动态插件；当前都只允许受控白名单能力。
- 不要说 Docker 支持微信收发；当前容器化只覆盖 Web API、readiness 和离线 eval。
- 不要说诊断支持包可以替代完整日志或聊天数据审查；它默认只导出脱敏摘要。
- 不要说真实 Windows/微信人工手测已完成，除非当场演示并记录结果。
