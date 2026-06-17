# 文档索引

本索引只放最常用的维护入口；完整事实仍以代码、测试和对应专题文档为准。

## 用户与配置

- [详细使用手册](USER_GUIDE.md)：环境要求、启动方式、配置项、排障和发布说明。
- [模型与认证中心](MODEL_AUTH_CENTER.md)：模型接入、Provider/Auth 状态、OpenAI-compatible 中转站和本机认证同步。
- [API 契约与治理接口](api.md)：模型中心、Prompt 治理、受控工具工作流、知识库治理等本机 API 契约。
- [系统链路说明](SYSTEM_CHAINS.md)：启动、消息、配置、状态、诊断、更新等链路。

## 模型接入快速入口

- 在桌面端打开“模型”页，选择 Provider 后配置 API Key、OAuth / 本机同步或 Session。
- newapi、sub2api 等中转站按 OpenAI-compatible Provider 接入：填写中转站的 `base_url` 和 API Key，再使用“获取模型”从 `<base_url>/models` 拉取模型列表。
- `POST /api/model_auth/action` 的 `discover_models` 动作用于模型发现；请求字段见 [api.md](api.md#post-apimodel_authaction-discover_models)，前端入口见 [MODEL_AUTH_CENTER.md](MODEL_AUTH_CENTER.md#模型发现与中转站接入)。
- `agent.model_routing` 当前只记录可解释路由决策，不会自动切换用户选择的 Provider 或认证方式；不要把未实现的环境变量式路由配置当成运行时能力。

## 工程与发布

- [Windows 发布准备清单](WINDOWS_RELEASE_READINESS.md)：Release 产物、版本、校验和安全基线。
- [Windows 安全模型](WINDOWS_SECURITY_MODEL.md)：管理员权限、IPC allowlist、外部链接和诊断脱敏边界。
- [桌面端自动升级与发布策略](DESKTOP_UPDATE_STRATEGY.md)：electron-updater、MSIX 和当前自研更新链路的对比与迁移路线。
- [发布与更新说明](RELEASE_UPDATES.md)：Release notes、构建产物和更新策略。

## 简历与面试包装

- [岗位驱动优化报告](JOB_DRIVEN_REMEDIATION_REPORT.md)：基于岗位数据源的方向画像、项目定位、增强记录、验证结果和简历表达。
- [RAG badcase 复盘模板](RAG_BADCASE_REVIEW_TEMPLATE.md)：面向 RAG eval、TraceLogger、成本复盘和 Tool Workflow 的失败样例分析模板。
