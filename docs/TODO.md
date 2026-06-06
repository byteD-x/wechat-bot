# TODO 与成熟化路线

本文只记录当前仓库事实基础上的后续任务，避免把已完成、未完成和愿景混在一起。

## 已完成

- Windows 成熟化第一轮：桌面端壳、消息中心、设置中心、模型中心、诊断支持包和相关 Node 测试已有改动。
- Prompt 回滚 API：`POST /api/v1/admin/prompts/{revision}/rollback` 已落地，回滚追加新 active revision，并写入 `data/prompt_revisions.json` 审计账本。
- Prompt 版本列表与差异 API：`GET /api/v1/admin/prompts/revisions` 与 `GET /api/v1/admin/prompts/{revision}/diff` 已落地；列表只返回 revision 元数据，不泄露完整 Prompt，diff 供回滚确认前预览。
- Prompt 回滚 UI：设置页系统提示区已提供“Prompt 版本治理”折叠面板，可查看版本历史、先预览 diff、再确认回滚，并在成功后刷新只读注入块与运行时状态。
- 受控 Agent Tool Workflow API：`POST /api/v1/agents/tool-workflow` 已落地，当前白名单包含 `config_audit`、`readiness_check`、`prompt_preview`。
- API 测试：已覆盖 Prompt 版本列表、diff 预览、空/损坏账本诊断、active revision 唯一性、Prompt 回滚成功、revision 不存在、白名单工具执行和未知工具拒绝。
- Renderer 测试：已覆盖 Prompt 版本治理入口、ApiService 幂等回滚策略、必须先预览差异再执行回滚，以及成功回滚后的设置刷新与反馈。
- RAG/eval smoke 扩样：`tests/fixtures/evals/smoke_cases.json` 已从 20 条扩到 24 条，新增 Prompt 回滚、工具审计、Windows 首次运行和 RAG 风格参考场景。
- 文档入口：`README.md`、`docs/USER_GUIDE.md`、`docs/SYSTEM_CHAINS.md`、`docs/HIGHLIGHTS.md`、`docs/api.md` 和 `docs/interview-playbook.md` 已补充。

## 下一阶段 P0

- Tool Workflow UI
  - 在诊断或 Agent 管理区展示可选工具、dry-run、执行 trace 和失败恢复建议。
  - 交互要求：未知工具不可输入；长任务展示逐步状态；失败步骤突出但不吞掉 trace。
  - 验证：Node renderer 测试覆盖成功、dry-run、单步失败和 `continue_on_error`。

## 下一阶段 P1

- 扩展工具白名单
  - 候选：备份 dry-run、数据治理 dry-run、eval latest、成本摘要。
  - 原则：先只读或 dry-run，再考虑可写工具；每个工具必须有输入限制、审计字段和测试。

- RAG/eval 数据集治理
  - 修复或替换历史 fixture 中不可读的乱码样例，保留相同指标分布，避免评测语义不可审查。
  - 为导出语料 RAG 增加更明确的风格召回、无命中回退和误命中场景。
  - 验证：`python run.py eval --dataset tests/fixtures/evals/smoke_cases.json --preset smoke --report data/evals/smoke-report.json`。

- Windows 真实环境手测
  - 在 Windows 10/11、管理员权限、微信 PC `3.9.12.51` 下跑一次完整首启、连接、发消息、诊断导出和停止流程。
  - 记录：环境、命令、截图或日志位置、失败项、是否需要用户操作。

## 下一阶段 P2

- 统一 API 文档生成
  - 当前 `docs/api.md` 是人工维护；后续可从路由和测试生成接口清单，减少文档漂移。

- 运行时治理指标
  - 为 Prompt 回滚次数、Tool Workflow 成功率、失败原因和耗时增加可观测指标。
  - 注意不要记录完整 Prompt、聊天正文或 token。

- 安装包级体验打磨
  - 检查首次运行引导、权限提示、更新失败恢复和后台服务异常退出提示是否符合成熟 Windows 产品预期。

## 保留限制

- 当前不承诺微信 `4.x` 支持。
- 当前不承诺 Linux/macOS 微信自动化。
- 当前不开放任意 Agent 工具执行。
- 当前不把 Web API 设计为公网多租户服务。
