# 岗位驱动优化报告

本文记录基于 `E:\Project\resume-new` 岗位数据源，对当前项目进行的岗位匹配分析、最小增强、验证结果和后续路线。岗位数据源只读，目标项目修改仅发生在当前仓库。

## 1. 岗位数据源结论

- 全量岗位：332 条，来自 `normalized-jobs.json`。
- 主要来源：Boss直聘 172、智联 71、猎聘 66。
- 主要城市：上海 86、北京 48、深圳 37、杭州 30、广州 19。
- 主要薪资：15-25K 153、25-40K 65、40K+ 42。
- 经验要求：3-5 年 114、1-3 年 70、未明确 52、经验不限 39、实习 18。
- 学历要求：本科 306、大专 8、统招本科 8、学历不限 7。
- 投递优先级：强投 137、可投 77、冲刺 48；强投池文件 `application-priority-list.json` 共 140 条。
- 主要方向：AI应用/RAG 106、AI Agent/智能体 104、Python/FastAPI 后端 52、AI平台/模型服务化 26。
- 口径说明：部分 Markdown 仍写 333，属于历史描述；部分分布总和大于 332，疑似多标签或旧口径，不作为精确总数。
- 数据风险：332 条均为“需人工核验”；约 182 条链接更像列表页或搜索页，约 150 条更像详情页。重点核验 JD 完整度、岗位是否下线、外包属性、薪资月份、城市和技术深度。

## 2. 方向画像

| 方向 | 样本信号 | 常见标题 | 必备能力 | 当前项目承接点 | 不建议硬凑 |
| --- | ---: | --- | --- | --- | --- |
| AI应用/RAG | 主类 106，关键词约 158 | AI应用开发、RAG方向、知识库、Python后端 | 文档解析、切分、向量检索、rerank、引用、拒答、评测 | 知识库治理、Hybrid RAG、citation、RAG eval | 大规模知识图谱平台 |
| AI Agent/智能体 | 主类 104，关键词约 143 | Agent 工程师、智能体开发、AI Agent 全栈 | 工具调用、任务拆解、工作流、记忆、trace、人工接管 | Tool Workflow、只读 MCP、模型 Tool Calling | 任意工具执行、自动浏览器代理 |
| Python/FastAPI后端 | 主类 52，关键词约 159 | Python 后端、AI 后端、大模型后端 | API 设计、异步任务、鉴权、日志、数据库、测试 | Quart API、异步 runtime、CI、readiness | 为了匹配强行迁移 FastAPI |
| AI平台/模型服务化 | 主类 26，关键词约 78 | AI平台、模型服务、推理服务 | provider 抽象、路由、健康检查、限流、降级、成本统计 | 模型认证中心、路由决策记录、成本管理 | 大规模 GPU/K8s 平台 |
| Dify/Coze/MCP/工作流 | 主类 5，关键词约 37 | Dify 方向、工作流、MCP | 工作流编排、工具 schema、插件边界 | 只读 MCP、ToolRegistry、workflow trace | 宣称熟练 Dify/Coze 生产实施 |
| Java 后端 + AI | 主类 2，关键词约 45 | Java AI 后端、Spring AI 应用 | Java/Spring、AI 接口集成、业务系统嵌入 | 可迁移的 API/治理设计 | 重写 Java 版本 |
| 行业AI实施/解决方案 | 主类 2，关键词约 70 | 银行 AI、智能制造、行业方案 | 场景拆解、交付、客户沟通、系统集成 | 微信客服、企业知识库、诊断和演示 | 编造真实客户或业务量 |
| 算法/微调/RL/多模态 | 主类 4，关键词约 87 | 算法工程师、多模态、大模型训练 | 训练、微调、评测、模型部署 | 只可讲应用侧评测和 embedding/rerank | RLHF、复杂微调、视觉算法 |

## 3. 能力模型

| 层级 | 能力维度 | 目标项目现状 | 推荐动作 |
| --- | --- | --- | --- |
| 主投必备 | RAG 工程 | 已有知识库、Hybrid、rerank、citation、拒答评测 | 扩中文样例与 badcase |
| 主投必备 | Agent 工程 | 已有 Tool Workflow、MCP、模型工具白名单 | 增加演示脚本和 trace 讲法 |
| 主投必备 | Python 后端 | 已有 Quart API、异步任务、鉴权、测试 | 不迁移 FastAPI，强调可迁移 API 能力 |
| 主投必备 | 可观测性 | 已有 status、metrics、TraceLogger、诊断包 | 补演示截图或报告 |
| 主投必备 | 工程交付 | 已有 CI、Docker Web API、README | 固化一键 demo |
| 进阶强化 | 模型服务化 | 已有 provider/auth/cost，路由仅记录 | 做最小限流/降级/路由策略 |
| 进阶强化 | 评测体系 | 已有 smoke/RAG eval | 扩大 golden dataset，补 badcase 模板 |
| 进阶强化 | 稳定性 | 已有 timeout/retry/backup/readiness | 补真实 Windows 手测 |
| 冲刺加分 | 平台治理 | 有治理接口雏形 | 不做大规模平台化，先补小闭环 |
| 冲刺加分 | 算法能力 | 有 embedding/rerank 应用 | 不做微调/RLHF，最多补 rerank 原理 |

## 4. 目标项目定位

当前项目最适合包装为：

1. AI应用/RAG
2. AI Agent / 智能体工程化
3. Python 后端 + 模型治理

已具备的强证据：

- RAG 引用、Hybrid Search、Query Rewrite、可选 Cross-Encoder。
- 受控 Tool Workflow、只读 MCP、模型 Tool Calling 白名单。
- 模型与认证中心、多 Provider、成本统计、TraceLogger。
- 离线 eval、CI、Docker Web API 切片、Windows 文档和诊断体系。

主要缺口：

- 中文 RAG/拒答/引用对齐样例偏少。
- 一键演示基础闭环已补齐，仍缺真实 Windows/微信收发手测记录。
- 模型路由仍偏记录而非自动切换。
- 缺少真实 Windows/微信手测记录。

不适合硬补的方向：

- 纯算法训练、复杂微调、RLHF、多模态训练。
- 大规模 K8s/GPU 模型平台。
- 只为展示好看而做 UI 改版。
- 无法本地验证的伪生产级能力。

## 5. 本次增强

- 扩充 `tests/fixtures/evals/rag_cases.json`：
  - 新增中文知识库引用样例。
  - 新增导出语料 RAG 风格召回样例。
  - 新增中文敏感信息拒答样例。
- 同步 `tests/test_eval_runner.py`：
  - 断言总样本数为 5。
  - 断言 citation / context / refusal 相关评测 case 数量。
- 新增 `scripts/run_rag_eval_demo.py`：
  - 固化面试演示与本地回归用的 RAG 专项评测命令。
  - 运行后输出核心评测指标和报告路径。
- 新增 `scripts/run_interview_demo.py`：
  - 串联 Web API readiness、RAG eval、badcase summary 和受控 Tool Workflow trace。
  - 默认报告写入 `data/runtime/demo/interview-rag-report.json`，不启动真实微信或 Web API。
- 增强 `KnowledgeBaseJobQueue`：
  - 为知识库后台任务返回 `queued / started / completed / failed` 脱敏事件时间线。
  - 失败事件只记录短错误原因，不回显正文、chunk text、embedding、完整异常或完整本机路径。

## 4. 验证结果

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_eval_runner.py -q
.\.venv\Scripts\python.exe scripts\run_rag_eval_demo.py
.\.venv\Scripts\python.exe -m pytest tests\test_interview_demo.py tests\test_tool_workflow_demo.py tests\test_rag_badcase_summary.py -q
.\.venv\Scripts\python.exe scripts\run_interview_demo.py
.\.venv\Scripts\python.exe -m pytest tests\test_knowledge_base.py tests\test_api.py -q
```

结果：

- `tests/test_eval_runner.py`：4 passed。
- RAG demo：5 cases 全通过。
- 一键演示相关测试：9 passed。
- 一键演示脚本：readiness `target=web-api`、RAG 5 cases 全通过、`badcases=0`、Tool Workflow trace 5 步、`repair_attempted=True`。
- 关键指标：`citation_accuracy=1.0`、`context_recall=1.0`、`faithfulness=1.0`、`answer_citation_binding=1.0`、`refusal_accuracy=1.0`。
- 知识库后台任务：`tests/test_knowledge_base.py` 11 passed，`tests/test_api.py` 143 passed，覆盖成功与失败事件时间线。

说明：

- 系统 `python` 环境缺 `pytest/tenacity`，最终使用项目 `.venv` 完成验证。
- 工作区存在的 `src/renderer/js/app.module.js` 修改不是本次所做，未纳入本次提交。

## 7. 优先级增强方案

### P0：中文 RAG 评测与拒答闭环

- 优化目标：让 RAG 能用中文企业知识库场景证明引用溯源、拒答和忠实度。
- 对应岗位：AI应用/RAG、Python 后端。
- 修改范围：`tests/fixtures/evals/rag_cases.json`、`tests/test_eval_runner.py`、`scripts/run_rag_eval_demo.py`。
- 实现思路：扩充中文 cases，固定 eval 命令，输出核心指标。
- 值得做：投入小，岗位命中高，面试可直接演示。
- 不过度设计：只增强离线门禁，不引入新依赖。
- 验证方式：`python scripts/run_rag_eval_demo.py`。
- 简历价值：可写“RAG 引用与拒答通过离线门禁验证”。
- 面试价值：能讲清 citation accuracy、context recall、faithfulness。
- 预计耗时：0.5-1 天。
- 风险限制：离线样例不等于真实线上效果。

### P1：一键演示链路

- 优化目标：降低面试展示成本。
- 对应岗位：AI应用、Agent、后端工程。
- 修改范围：`scripts/`、`docs/USER_GUIDE.md`、`docs/interview-playbook.md`。
- 实现思路：串联 readiness、RAG eval、Tool Workflow dry-run。
- 值得做：展示“能跑、能验、能解释”。
- 不过度设计：不做全新 CLI 框架。
- 验证方式：执行演示脚本并检查输出。
- 简历价值：项目具备可复现 Demo。
- 面试价值：现场演示路径清晰。
- 预计耗时：1-2 天。
- 风险限制：Windows/微信真链路仍需单独手测。

### P1：badcase 复盘模板

- 优化目标：把评测失败从“分数下降”变成可排查动作。
- 对应岗位：RAG、模型应用评测、AI平台治理。
- 修改范围：`docs/` 或 `data/evals` 示例。
- 实现思路：按 retrieval、citation、refusal、runtime error 分类。
- 值得做：面试官常追问“效果不好怎么办”。
- 不过度设计：先文档模板，不做复杂看板。
- 验证方式：用一条失败 fixture 生成复盘样例。
- 简历价值：体现 badcase 分析能力。
- 面试价值：能讲评测闭环。
- 预计耗时：0.5-1 天。
- 风险限制：需要持续积累真实 badcase。

### P2：模型治理最小闭环

- 优化目标：从“路由记录”推进到最小限流/降级策略。
- 对应岗位：AI平台/模型服务化、Python 后端。
- 修改范围：`backend/core/model_router.py`、`agent_runtime.py`、相关测试。
- 实现思路：先做配置驱动的 fallback 解释和阻断策略，不自动切换凭据。
- 值得做：冲击 25-40K 岗位更有说服力。
- 不过度设计：不建设大模型网关。
- 验证方式：单元测试覆盖超时、不可用、成本优先。
- 简历价值：模型治理、降级、成本意识。
- 面试价值：讲清“为什么先记录再切换”。
- 预计耗时：3-5 天。
- 风险限制：自动切换 provider 会牵涉认证边界。

## 8. 推荐增强路线

### 轻量版（1 天）

- 任务：扩中文 RAG eval、跑 RAG demo、更新岗位驱动报告。
- 修改文件：`tests/fixtures/evals/rag_cases.json`、`tests/test_eval_runner.py`、`scripts/run_rag_eval_demo.py`、`docs/JOB_DRIVEN_REMEDIATION_REPORT.md`。
- 验收标准：RAG demo 5 cases 通过，关键指标均为 1.0。
- 验证命令：`.\.venv\Scripts\python.exe scripts\run_rag_eval_demo.py`。
- 简历成果：RAG 引用、拒答、忠实度通过离线评测门禁。
- 不做：不迁移 FastAPI，不做微调，不做 UI 改版。

### 标准版（2-5 天）

- 任务：补 readiness + RAG eval + Tool Workflow dry-run 演示脚本；补 badcase 模板；补中文知识库样例。
- 修改文件：`scripts/`、`docs/USER_GUIDE.md`、`docs/interview-playbook.md`、`tests/fixtures/evals/*`。
- 验收标准：一个脚本跑出演示摘要，文档能按步骤复现。
- 验证命令：演示脚本、`pytest tests\test_eval_runner.py -q`。
- 简历成果：完整 Demo、评测、复盘闭环。
- 不做：不承诺 Docker 微信收发，不做公网多租户。

### 增强版（1-2 周）

- 任务：补模型治理最小闭环、真实 Windows 手测、更多 RAG regression。
- 修改文件：`backend/core/model_router.py`、`backend/core/agent_runtime.py`、`tests/`、`.codex/verification-report.md` 或 `docs/`。
- 验收标准：新增策略有测试，Windows 手测有记录，eval 数据集更接近业务。
- 验证命令：目标 pytest、`run.py check`、`run.py eval`、人工手测记录。
- 简历成果：可冲刺 25-40K 的工程化、治理、稳定性证据。
- 不做：不搭 GPU 平台，不写 RLHF，不编造用户量。

## 9. 可执行任务拆解

| 任务 | 背景 | 输入 | 输出 | 修改点 | 依赖 | 验收 | 验证命令 | 并行 | 简历价值 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 扩中文 RAG eval | 岗位高频要求引用和拒答 | 现有 eval runner | 中文 cases | fixture/test | 无 | 5 cases 通过 | `python scripts/run_rag_eval_demo.py` | 是 | 高 |
| 固化演示脚本 | 面试展示命令过长 | `run.py eval` | demo 脚本 | `scripts/` | eval 数据 | 输出指标 | 同上 | 是 | 高 |
| 补 badcase 模板 | 面试追问效果差怎么办 | eval report | 复盘模板 | `docs/` | eval 数据 | 可按失败分类 | 人工检查 + 失败 fixture | 是 | 高 |
| 补 Tool Workflow demo | Agent 岗位需要工具闭环 | 现有 API | dry-run 示例 | `scripts/`/`docs/` | 运行 Web API | trace 可读 | API 测试或脚本 | 部分 | 高 |
| Windows 手测记录 | 项目依赖真实微信环境 | 本机环境 | 手测报告 | `.codex/` 或 `docs/` | 微信 3.9.12.51 | 有命令/截图/日志 | `run.py check` + 人工 | 否 | 中高 |
| 模型治理最小闭环 | 进阶岗位关注服务化 | model_router | 限流/降级策略 | `backend/core/`/`tests/` | 现有 auth | 测试覆盖 | 目标 pytest | 否 | 高 |

## 10. 简历可写表达

- 基于 `LangGraph + Quart + ChromaDB` 构建微信 AI 助手运行时，支持分层记忆、RAG 检索和受控工具调用。
- 建设 RAG 引用溯源与离线评测门禁，覆盖 citation accuracy、context recall、faithfulness 和 refusal accuracy。
- 为知识库后台队列补齐脱敏事件时间线，将异步写入/重建任务从单一状态变为可追踪、可排查的多阶段流程。
- 将高风险 Agent 操作收口为白名单 Tool Workflow 与只读 MCP adapter，补齐 trace、权限和失败可解释边界。
- 建设模型与认证中心，统一多 Provider、OAuth / API Key / 本机同步和成本统计。
- 通过 CI、pytest、Node tests、offline eval 和 Docker Web API 切片验证后端治理能力。

## 11. 项目介绍与 STAR

项目介绍：

> 这是一个面向 Windows 微信生态的本地 AI 助手运行时，核心不是单次调用大模型，而是把微信接入、模型认证、RAG、Agent 工具治理、评测和可观测性做成可长期运行、可验证、可排障的工程系统。

技术难点：

> 微信自动化边界不稳定，RAG 相关性和部署复杂度冲突，Agent 工具调用存在安全风险。项目通过传输层抽象、可降级 RAG、引用与拒答评测、白名单工具流和脱敏 trace 解决这些问题。

STAR：

- Situation：微信 AI 助手容易停留在“能回消息”的 Demo。
- Task：补齐 RAG、Agent、模型治理和可观测能力，让项目可面试、可演示、可验证。
- Action：建设分层记忆、Hybrid RAG、citation、拒答评测、Tool Workflow、只读 MCP、TraceLogger 和 CI eval gate。
- Result：RAG 专项评测 5 cases 通过，关键指标均为 1.0；`tests/test_eval_runner.py` 4 passed。

为什么匹配 AI 应用岗位：

> 岗位核心要求集中在 RAG、Agent、Python 后端、模型服务化、评测和可观测。当前项目在这些方向都有代码、测试和文档证据，尤其适合主投 AI应用/RAG 与 Agent 工程化岗位。

为什么不只是 Demo：

> 项目有配置与认证中心、离线评测、CI、诊断支持包、备份恢复、成本统计、Docker Web API 切片和测试门禁，不依赖“现场跑一次成功”来证明能力。

## 12. 高频面试追问

1. RAG chunk 怎么切？答：当前知识库按字符窗口和段落边界切，保留 chunk metadata；后续可按标题/表格结构增强。
2. rerank 为什么不用强依赖模型？答：默认轻量重排可运行，本地 Cross-Encoder 作为增强，失败可回退。
3. 怎么减少幻觉？答：citation policy、无证据拒答、RAG eval 的 faithfulness/refusal 指标共同约束。
4. 引用如何绑定？答：citation_id/doc_id/chunk_id/source_file 进入 metadata 和 eval，回答需引用返回证据。
5. Agent 工具怎么防越权？答：ToolRegistry 白名单、schema 校验、权限、超时、trace，不开放 shell/任意文件/任意 HTTP。
6. MCP 暴露了什么？答：只读安全工具子集，不暴露 prompt_preview/config_audit 等高风险工具。
7. 模型路由现在做到哪？答：当前记录可解释决策，不自动切换 provider；这是为了先守住认证和回退边界。
8. Docker 为什么不能跑微信？答：容器只覆盖 Web API/readiness/eval，微信自动化依赖 Windows、管理员权限和 WCFerry。
9. 效果差怎么排查？答：看 eval report、retrieval hit、citation match、refusal action、trace_logger 和成本复盘。
10. 下一步怎么增强？答：优先 badcase 模板、一键演示、真实 Windows 手测，再做模型限流/降级。

## 13. 最终判断

- 不是单轮调模型，而是做了可长期运行的本地 AI runtime。
- 不只是 RAG 召回，还补了引用、拒答、评测和 badcase 复盘。
- 不只是 Agent 调工具，而是把工具调用收进白名单和审计边界。
- 不只是能跑桌面端，而是把 Web API、readiness、评测和诊断做成可验证闭环。
- 最值得优先做：中文 RAG eval、演示脚本、真实 Windows 手测。
- 最不建议做：复杂微调/RLHF、大规模平台化重构、纯 UI 美化。
- 当前应优先补测试和 Demo，再补文档，最后做代码增强。
