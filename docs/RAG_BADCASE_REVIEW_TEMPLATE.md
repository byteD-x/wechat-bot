# RAG badcase 复盘模板

> 适用场景：RAG 评测回归、成本管理页低质量回复复盘、项目复盘和技术面试讲解。
>
> 复盘原则：只记录脱敏摘要、指标、hash 引用和可复现命令；不要粘贴真实聊天正文、完整 Prompt、API Key、token、工具原始输出或完整本机路径。

## 1. 复盘目标

RAG badcase 复盘不是为了证明“模型不好”，而是把一次低质量回答拆成可验证的工程问题：

1. 判断问题归因：召回、引用、拒答、安全、上下文、模型生成、成本或时延。
2. 找到证据入口：RAG eval report、`/api/status.trace_logger`、成本复盘导出、Tool Workflow trace 或知识库治理摘要。
3. 给出最小修复动作：调配置、补数据、改 Prompt 约束、补评测用例或收紧工具边界。
4. 定义回归验证：本地复跑 RAG eval、查看状态摘要、检查 cost review 队列是否下降。
5. 沉淀面试讲法：能说明“怎么发现、怎么定位、怎么修、怎么防回归”。

推荐先跑一份离线 RAG report：

```powershell
python run.py eval --dataset tests\fixtures\evals\rag_cases.json --preset rag-smoke --report data\evals\rag-smoke-report.json
```

再把报告压缩成可复盘摘要：

```powershell
python scripts\summarize_rag_badcases.py --report data\evals\rag-smoke-report.json
```

当前 RAG 专项指标包括：

- `citation_accuracy`：引用是否指向期望证据。
- `context_recall`：期望证据是否被召回。
- `faithfulness`：回答是否有证据支撑，拒答场景是否符合预期。
- `answer_citation_binding`：答案里的引用标记是否绑定到返回 citation。
- `refusal_accuracy`：该拒答时是否拒答，不该拒答时是否放行。

可配合这些入口补证据：

- `/api/status.trace_logger`：查看最近模型调用的脱敏摘要，包括 `retrieval`、`safety`、`timings`、`model_tool`、`response_cache`。
- `/api/costs/review_queue_export`：导出低质量回复复盘 JSON，重点看 `review_reason`、`suggested_action`、`action_guidance`、`retrieval`、`context_summary`、`cost`。
- `POST /api/v1/agents/tool-workflow`：用白名单工具 `eval_latest`、`cost_summary` 读取评测和成本摘要；trace 不展开完整 cases、review queue 或本机路径。

## 2. 单条 badcase 记录

复制下面结构，每次只复盘一个主问题；如果一个样例同时有召回弱和引用错，先按最直接导致失败的原因归类。

```markdown
### Badcase ID

- 来源：RAG eval / cost review / 手工观察 / Tool Workflow trace
- 时间与环境：
- preset / provider / model：
- 输入摘要：
- 期望行为：
- 实际行为：
- 主分类：召回弱 / 引用错 / 拒答错 / 上下文污染 / 幻觉 / 成本高 / 时延高
- 影响范围：单 case / 单联系人 / 单 preset / 全局
- 复现方式：
- 证据：
  - RAG eval summary：
  - RAG eval case：
  - TraceLogger：
  - cost review：
  - Tool Workflow：
- 初步判断：
- 下一步修复：
- 回归验证：
- 面试讲法：
```

## 3. 常见 badcase 分类

### 3.1 召回弱

典型现象：

- 回答空泛、太短或没有命中用户真正问的事实。
- RAG eval 中 `context_recall` 下降，或单 case 的 `matched_evidence` 少于 `expected_evidence`。
- 成本复盘里 `review_reason` 可能是 `retrieval_not_used`、`retrieval_weak` 或 `context_thin`。

优先看字段和证据：

- RAG report：`summary.retrieval_hit_rate`、`summary.context_recall`、`cases[].flags.retrieval_hit`、`cases[].retrieval`、`cases[].rag_eval.expected_evidence`、`cases[].rag_eval.matched_evidence`。
- 检索摘要：`retrieval.augmented`、`runtime_hit_count`、`export_hit_count`、`knowledge_hit_count`、`knowledge_base_used`、`retrieval_mode`、`query_rewrite`。
- TraceLogger：`retrieval.augmented`、`retrieval.runtime_hit_count`、`retrieval.export_hit_count`、`retrieval.citation_count`。
- 成本复盘：`review_reason`、`suggested_action`、`action_guidance.config_paths`、`action_guidance.status_fields`。
- 配置方向：`agent.retriever_top_k`、`agent.retriever_score_threshold`、`agent.retriever_rerank_mode`、`agent.retriever_hybrid_enabled`。

追问问题：

- 检索是否根本没启用，还是启用了但命中太少？
- 期望证据是否已经进入运行期向量记忆、导出语料 RAG 或知识库？
- query rewrite 是否把问题改偏了？
- 阈值是否过严，`top_k` 是否过小，rerank 是否把正确 chunk 排掉了？
- 这是单个文档缺失，还是某类中文问题都召回弱？

下一步修复动作：

- 如果 `retrieval.augmented=false`：先检查检索开关和当前 preset。
- 如果命中数低：小幅增加 `agent.retriever_top_k`，或降低 `agent.retriever_score_threshold`。
- 如果中文词面差异明显：评估开启 `agent.retriever_hybrid_enabled`，用本地关键词召回补向量召回。
- 如果知识缺失：通过知识库治理 `dry-run / ingest / rebuild` 补充或重建对应文档。
- 如果只在某类问题失败：把样例补进 `tests/fixtures/evals/rag_cases.json`，用 RAG eval 固化回归。

面试讲法：

> 我不会直接说“模型没理解”。我会先看 `context_recall` 和单 case 的 `matched_evidence`，判断证据有没有被召回；再结合 TraceLogger 的检索命中数和成本复盘的 `suggested_action`，决定是调阈值、补知识库，还是改 query rewrite。最后把失败样例进 RAG eval，避免同类问题再回归。

### 3.2 引用错

典型现象：

- 答案看似正确，但引用指向了错误文档、错误 chunk 或不存在的 citation。
- RAG eval 中 `citation_accuracy` 下降。
- `answer_citation_binding` 下降时，说明答案中的引用标记没有绑定到返回 citation。

优先看字段和证据：

- RAG report：`summary.citation_accuracy`、`summary.answer_citation_binding`、`cases[].rag_eval.returned_evidence`、`cases[].rag_eval.expected_evidence`、`cases[].rag_eval.answer_citation_bound`。
- citation 元数据：`citation_id`、`source`、`doc_id`、`chunk_id`、`chunk_index`、`source_file`。
- TraceLogger：`retrieval.citation_count`、`safety.citation_required`、`safety.answer_citation_bound`、`safety.citation_count`。
- Tool Workflow：`eval_latest.summary` 和 `eval_latest.regression_count`，用于快速确认是不是评测门禁问题。

追问问题：

- 引用 ID 是不存在，还是存在但指向错证据？
- 答案中的关键断言是否每一句都有对应 citation？
- 是否混用了运行期向量记忆、导出语料和知识库 citation？
- citation 元数据是否在 ingest / rebuild 后发生漂移？
- 是否因为重排把证据换了，但答案仍沿用旧引用？

下一步修复动作：

- 如果 citation 不存在：检查回答生成阶段是否只允许引用本轮返回 citation。
- 如果引用错文档：检查 chunk metadata，必要时重建对应 `doc_id`。
- 如果引用绑定失败：补 `answer_citation_binding` 相关 eval case。
- 如果引用过少：检查安全策略中是否启用 citation 要求，以及 Prompt 是否明确要求基于证据回答。
- 如果 source 混乱：按 `runtime_chat`、`export_chat`、`knowledge_base` 分开复盘，不把风格召回当事实来源。

面试讲法：

> 我把 RAG 引用拆成两层：第一层是 `citation_accuracy`，确认引用是否指向期望证据；第二层是 `answer_citation_binding`，确认答案里的引用标记是否真的绑定到返回 citation。这样能区分“检索到了但引用错”和“答案自己编了引用”。

### 3.3 拒答错

典型现象：

- 有证据时错误拒答，或缺证据、涉及敏感信息时仍然回答。
- RAG eval 中 `refusal_accuracy` 下降。
- `faithfulness` 在拒答场景失败。

优先看字段和证据：

- RAG report：`summary.refusal_accuracy`、`cases[].rag_eval.expected_action`、`cases[].rag_eval.actual_action`、`cases[].rag_eval.refusal_match`。
- case 标记：`unsupported_answer`、`expected_action`。
- safety 摘要：`safety.action`、`safety.reasons`、`missing_required_citation`、`pii_sensitive`。
- TraceLogger：`safety.action`、`safety.reason_count`、`safety.reason_refs`、`safety.prompt_injection_detected`、`safety.pii_detected`、`safety.pii_blocked`、`safety.grounded`。

追问问题：

- 预期是拒答、人工处理，还是允许回答？
- 拒答原因是缺 citation、PII、安全策略，还是上下文不足？
- safety action 与 eval 的 `actual_action` 是否一致？
- 是否因为 citation policy 太严导致有证据也拒答？
- 是否因为 Prompt 过度追求有帮助而越过拒答边界？

下一步修复动作：

- 如果该拒不拒：收紧无证据回答和敏感信息规则，补拒答 eval。
- 如果不该拒却拒：检查 citation 必需策略、PII 识别和证据匹配是否过严。
- 如果安全原因不清：用 TraceLogger 的 `reason_refs` 对照同一时间的脱敏状态摘要，不追查原始聊天正文。
- 如果是产品策略问题：明确该场景走自动回复、拒答还是待审批。

面试讲法：

> 我们把拒答做成可评测项，而不是只靠 Prompt。`refusal_accuracy` 负责看动作是否对，TraceLogger 负责保留脱敏的 safety 摘要，这样能说明系统为什么拒答，也能发现不该回答时模型越界的问题。

### 3.4 上下文污染

典型现象：

- 回答引用了别的联系人、别的会话、旧 Prompt 或不相关历史。
- 语义缓存命中后回答带入了不该复用的上下文。
- 导出语料 RAG 的风格内容被误当成事实证据。

优先看字段和证据：

- RAG report：`chat_id`、`user_text`、`retrieval.source`、`doc_id`、`source_file`、`context_recall`。
- TraceLogger：`chat_ref`、`model_ref`、`response_cache.hit`、`response_cache.stored`、`model_route.rag_augmented`、`retrieval`。
- 状态约束：语义缓存默认关闭；开启后也不应跨 chat、provider、model、system prompt、RAG citation ids 或安全策略边界命中。
- 成本复盘：`context_summary`、`review_reason=context_thin` 或 `suggested_action=enrich_context_sources`。

追问问题：

- 污染来自短期上下文、运行期向量记忆、导出语料 RAG、知识库，还是缓存？
- 错误事实是否来自“风格召回”而不是事实来源？
- 当前 case 的 `chat_id` 与证据来源是否一致？
- 是否存在 Prompt override 或联系人专属 Prompt 把系统固定注入块覆盖掉？
- 缓存是否在 citation 或安全策略变化后仍命中？

下一步修复动作：

- 先隔离来源：关闭或绕开可疑来源复测，确认污染层。
- 如果是导出语料误用：在 Prompt 和 eval 中强调导出语料 RAG 更偏表达风格，不当事实数据库。
- 如果是缓存：检查语义缓存边界和 `response_cache` 状态，必要时关闭语义缓存复测。
- 如果是上下文来源太薄：按成本复盘的 `action_guidance` 补充上下文来源。
- 如果是跨会话污染：补包含 `chat_id` 边界的 eval case。

面试讲法：

> 我会先问污染来自哪一层，而不是直接改 Prompt。项目里短期记忆、运行期向量、导出语料 RAG 和语义缓存都有边界；TraceLogger 只给 hash 引用和聚合字段，足够判断是否跨边界，同时不泄露聊天正文。

### 3.5 幻觉

典型现象：

- 回答给出了证据中没有的结论。
- 无 citation 或 citation 与答案断言不一致。
- RAG eval 中 `faithfulness` 下降。

优先看字段和证据：

- RAG report：`summary.faithfulness`、`cases[].assistant_reply`、`cases[].rag_eval.context_recall`、`cases[].rag_eval.citation_accuracy`、`cases[].rag_eval.answer_citation_bound`。
- safety 摘要：`safety.grounded`、`safety.citation_required`、`safety.citation_count`。
- TraceLogger：`finish_reason`、`flags.tool_call_only_response`、`flags.timeout_fallback_applied`、`retrieval.citation_count`。
- 成本复盘：`reply_preview`、`user_preview`、`review_reason`、`suggested_action`。

追问问题：

- 幻觉是因为没召回证据，还是召回了但模型没有遵守证据？
- 答案中哪一句是无证据断言？
- 是否有 citation 但 citation 不支持该断言？
- 是否 timeout fallback 或工具调用失败后仍生成了看似完整的答案？
- Prompt 是否允许模型在证据不足时“合理推断”？

下一步修复动作：

- 证据未召回：按召回弱处理。
- 证据已召回但不忠实：收紧 Prompt 的证据约束和无证据拒答策略。
- citation 不支撑断言：按引用错处理，补 `faithfulness` 与 `answer_citation_binding` case。
- 工具失败后幻觉：检查 Tool Workflow 或模型工具调用 trace，失败时走拒答或降级提示。

面试讲法：

> 我把幻觉拆成“没有证据”和“有证据但没按证据答”。前者看 `context_recall`，后者看 `faithfulness`、`citation_accuracy` 和 `answer_citation_binding`。这样修复动作会落到检索、引用绑定或 Prompt 约束，而不是泛泛地换模型。

### 3.6 成本高

典型现象：

- 单次或某类会话 token / 金额异常高。
- 低质量回复很多，但成本没有换来质量收益。
- Tool Workflow 或模型侧工具调用增加了不必要步骤。

优先看字段和证据：

- 成本接口：`/api/costs/summary`、`/api/costs/sessions`、`/api/costs/session_details`、`/api/costs/review_queue_export`。
- 成本复盘：`cost`、`provider_id`、`model`、`preset`、`review_reason`、`suggested_action`、`review_playbook.top_action`、`playbook.actions`。
- Tool Workflow：`cost_summary.overview`、`cost_summary.model_count`、`cost_summary.review_queue_count`。
- TraceLogger：`model_tool.step_count`、`model_tool.trace`、`response_cache.hit`、`response_cache.stored`。

追问问题：

- 成本高集中在哪个 provider、model、preset 或联系人？
- 高成本样例是否同时是 `unhelpful`？
- 是否因为召回太宽、上下文太长、Prompt 太重或工具步骤过多？
- 是否重复调用同一工具，或 `continue_on_error` 导致失败后继续消耗？
- 是否有缓存命中空间，但语义缓存因安全边界不能复用？

下一步修复动作：

- 先按 `provider / model / preset / review_reason / suggested_action` 筛选成本复盘。
- 如果高成本且召回弱：先调检索，不先升级模型。
- 如果高成本且 Prompt 过长：收敛系统提示和上下文拼接。
- 如果工具步骤多：检查 Tool Workflow 白名单步骤，保留必要 dry-run。
- 如果低质量集中在某 preset：对该 preset 单独补 eval 和成本对比。

面试讲法：

> 成本复盘不是只看总金额。我会把 `/api/costs/*` 的模型、preset、低质量回复队列和 `suggested_action` 串起来，判断钱花在了哪里，以及有没有带来质量收益。对 Agent 工具流还会看 trace 步数，避免工具调用变成隐性成本黑洞。

### 3.7 时延高

典型现象：

- 回复慢、超时 fallback、工具调用链过长。
- 检索增强或重排显著增加等待时间。
- 模型路由进入高延迟模型，但问题本身不需要。

优先看字段和证据：

- TraceLogger：`timings`、`model_route.latency_priority`、`model_route.strategy`、`model_tool.step_count`、`flags.timeout_fallback_applied`、`flags.delayed_reply`。
- `/api/status.governance_metrics`：Tool Workflow 聚合耗时和失败原因短枚举。
- Tool Workflow trace：每步工具名、状态、耗时、失败原因和结果摘要。
- RAG 配置：`agent.retriever_rerank_mode`、`agent.retriever_cross_encoder_model`、`agent.retriever_top_k`。

追问问题：

- 慢在检索、重排、模型调用、工具流，还是后处理？
- 是否启用了本地 Cross-Encoder，且设备或模型路径导致慢启动？
- 是否工具流步骤过多，或某一步 timeout 后仍继续？
- 是否高延迟模型被用于简单问题？
- 时延高是否同时伴随更高质量，还是纯消耗？

下一步修复动作：

- 用 TraceLogger 的 `timings` 先定位慢阶段。
- 如果慢在 RAG：降低 `top_k`、检查 rerank mode，必要时回退轻量重排。
- 如果慢在工具流：减少步骤，或只保留 `eval_latest / cost_summary` 等必要摘要工具。
- 如果慢在模型：检查 `model_route` 与 preset，区分质量优先和延迟优先场景。
- 修复后用同一问题复测，并记录时延与质量是否一起改善。

面试讲法：

> 我不会只看“平均响应时间”。我会把 TraceLogger 的 `timings`、模型路由、检索命中和工具流 step trace 拆开看，先定位慢在哪一段，再决定是调 RAG、调模型，还是缩短工具流。

## 4. 复盘追问清单

面试或项目复盘时，可以按这组问题顺序展开：

1. 这个 badcase 的主失败指标是什么？`citation_accuracy`、`context_recall`、`faithfulness`、`answer_citation_binding` 还是 `refusal_accuracy`？
2. 证据是没召回，召回错了，还是召回对了但模型没按证据答？
3. 答案中的引用是否存在，是否绑定到本轮返回 citation？
4. 如果是拒答问题，`expected_action` 和 `actual_action` 分别是什么？
5. TraceLogger 的 `retrieval / safety / timings / model_tool` 是否支持这个判断？
6. 成本复盘里的 `review_reason` 和 `suggested_action` 是否与人工判断一致？
7. 修复动作是调配置、补数据、改 Prompt、补 eval，还是收紧 Tool Workflow？
8. 这次修复如何验证不会破坏已有路径？

## 5. 下一步修复动作库

常用动作按优先级从低风险到高风险排列：

1. 补 eval case：把失败样例沉淀进 RAG eval，先防回归。
2. 补或重建知识：用知识库治理 dry-run 预览，再 ingest / rebuild。
3. 调检索参数：小步调整 `top_k`、score threshold、hybrid、rerank mode。
4. 收紧引用策略：要求答案只引用本轮返回 citation，证据不足时拒答。
5. 调 Prompt 约束：减少“自由发挥”，强调证据、拒答和引用绑定。
6. 调安全策略：明确 PII、Prompt injection、缺 citation 等拒答边界。
7. 调工具流：减少非必要步骤，只保留白名单工具和摘要输出。
8. 调模型或 preset：只有当证据和 Prompt 都合理但生成仍失败时，再评估换模型。

每个动作都要写回一个验证方式：

- RAG eval：复跑 `python run.py eval --dataset tests\fixtures\evals\rag_cases.json --preset rag-smoke --report data\evals\rag-smoke-report.json`。
- 状态摘要：查看 `/api/status.trace_logger`、`/api/status.governance_metrics`。
- 成本复盘：查看 `/api/costs/review_queue_export` 中同类 `review_reason` 是否下降。
- Tool Workflow：用 `eval_latest` 或 `cost_summary` 看摘要，不展开敏感明细。

## 6. 简历和面试讲法

可以使用下面三种粒度。

一句话：

> 建设 RAG badcase 复盘闭环，把 citation accuracy、context recall、faithfulness、answer-citation binding、refusal accuracy 与 TraceLogger、成本复盘和受控 Tool Workflow 串起来，定位召回、引用、拒答、幻觉、成本和时延问题。

STAR 版：

- Situation：微信 AI 助手的回复质量问题不能只靠人工感觉判断，RAG 还会出现召回弱、引用错、拒答错和幻觉。
- Task：把 badcase 复盘做成可验证闭环，要求能定位根因、给出修复动作，并进入离线评测门禁。
- Action：用 `rag_cases.json` 和 `run.py eval` 固化 RAG 指标；用 TraceLogger-lite 记录脱敏的 retrieval、safety、timings 和 model_tool 摘要；用成本复盘导出聚合低质量回复；用 Tool Workflow 的 `eval_latest / cost_summary` 快速读取摘要。
- Result：问题可以按指标和证据拆解为召回、引用、拒答、上下文、幻觉、成本、时延七类，每类都有对应字段、追问和回归验证方式。

追问展开：

> 如果面试官问“RAG 效果差怎么排查”，我会先用 eval report 看是 `context_recall` 低还是 `citation_accuracy` / `faithfulness` 低；再看 TraceLogger 的检索命中、安全动作和耗时；如果来自真实用户反馈，就从成本复盘的 `review_reason`、`suggested_action` 和 `action_guidance` 找优先动作。修完后不是口头说好了，而是补 case 并复跑 RAG eval。

## 7. 复盘样例骨架

```markdown
### rag-case-xxx

- 主分类：召回弱
- 失败指标：`context_recall=0.0`，`matched_evidence=[]`
- 现象：回答没有提到知识库中的容器化边界。
- 证据：
  - RAG eval：`expected_doc_ids=["docs-user-guide"]`，`returned_evidence=[]`
  - TraceLogger：`retrieval.augmented=true`，`runtime_hit_count=0`，`citation_count=0`
  - cost review：`review_reason=retrieval_weak`，`suggested_action=tune_retrieval_threshold`
- 追问：
  - 文档是否已经入库？
  - query rewrite 是否保留了“容器 / 微信 / WCFerry”关键词？
  - score threshold 是否过严？
- 修复：
  - 对目标文档执行 knowledge base dry-run，确认 chunk 摘要。
  - 小幅调低 `agent.retriever_score_threshold`，必要时开启 hybrid。
  - 把该问题加入 RAG eval。
- 验证：
  - 复跑 RAG eval，确认 `context_recall` 恢复。
  - 查看 TraceLogger，确认 citation_count 大于 0。
- 面试讲法：
  - 这是召回链路问题，不是生成问题；先让证据进入上下文，再谈模型回答。
```
