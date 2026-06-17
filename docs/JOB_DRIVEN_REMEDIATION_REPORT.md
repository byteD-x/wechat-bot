# 岗位驱动优化报告

本文记录基于 `E:\Project\resume-new` 岗位数据源，对当前项目进行的岗位匹配分析、最小增强、验证结果和后续路线。岗位数据源只读，目标项目修改仅发生在当前仓库。

## 1. 岗位数据源结论

- 全量岗位：332 条，来自 `normalized-jobs.json`。
- 主要来源：Boss直聘 172、智联 71、猎聘 66。
- 主要城市：上海 86、北京 48、深圳 37、杭州 30、广州 19。
- 主要薪资：15-25K 153、25-40K 65、40K+ 42。
- 主要方向：AI应用/RAG 106、AI Agent/智能体 104、Python/FastAPI 后端 52、AI平台/模型服务化 26。
- 口径说明：部分 Markdown 仍写 333，属于历史描述；部分分布总和大于 332，疑似多标签或旧口径，不作为精确总数。

## 2. 目标项目定位

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
- 缺少更直接的一键演示闭环。
- 模型路由仍偏记录而非自动切换。
- 缺少真实 Windows/微信手测记录。

## 3. 本次增强

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

## 4. 验证结果

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_eval_runner.py -q
.\.venv\Scripts\python.exe scripts\run_rag_eval_demo.py
```

结果：

- `tests/test_eval_runner.py`：4 passed。
- RAG demo：5 cases 全通过。
- 关键指标：`citation_accuracy=1.0`、`context_recall=1.0`、`faithfulness=1.0`、`answer_citation_binding=1.0`、`refusal_accuracy=1.0`。

说明：

- 系统 `python` 环境缺 `pytest/tenacity`，最终使用项目 `.venv` 完成验证。
- 工作区存在的 `src/renderer/js/app.module.js` 修改不是本次所做，未纳入本次提交。

## 5. 推荐增强路线

### 轻量版（1 天）

- 继续扩展中文 RAG / 拒答 / citation 样例。
- 补 README / 面试讲法里的 eval 入口。
- 目标：让项目“能讲、能跑、能验”。

### 标准版（2-5 天）

- 做固定演示链路：readiness + RAG eval + Tool Workflow dry-run。
- 补 badcase 复盘模板。
- 补中文知识库样例。

### 增强版（1-2 周）

- 加模型路由 / 限流 / 降级的最小闭环。
- 补真实 Windows / 微信手测记录。
- 补长期运行和稳定性证据。

## 6. 简历可写表达

- 基于 `LangGraph + Quart + ChromaDB` 构建微信 AI 助手运行时，支持分层记忆、RAG 检索和受控工具调用。
- 建设 RAG 引用溯源与离线评测门禁，覆盖 citation accuracy、context recall、faithfulness 和 refusal accuracy。
- 将高风险 Agent 操作收口为白名单 Tool Workflow 与只读 MCP adapter，补齐 trace、权限和失败可解释边界。
- 建设模型与认证中心，统一多 Provider、OAuth / API Key / 本机同步和成本统计。

## 7. 面试回答主线

- 不是单轮调模型，而是做了可长期运行的本地 AI runtime。
- 不只是 RAG 召回，还补了引用、拒答、评测和 badcase 复盘。
- 不只是 Agent 调工具，而是把工具调用收进白名单和审计边界。
- 不只是能跑桌面端，而是把 Web API、readiness、评测和诊断做成可验证闭环。

