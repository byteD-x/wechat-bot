# AI 能力亮点索引

本文件是面向项目介绍的轻量索引，详细证据以 `docs/PROJECT_HIGHLIGHTS_SUMMARY.md`、`docs/HIGHLIGHTS.md`、`docs/MODEL_AUTH_CENTER.md` 和测试为准。

## 模型接入闭环

- 模型中心统一管理 `api_key / oauth / local_import / web_session` 多种认证方式，并由后端返回 `overview.actions_schema` 约束前端动作。
- newapi、sub2api 等中转站按 OpenAI-compatible Provider 接入；`discover_models` 会规范化 `base_url` 并请求 `<base_url>/models`。
- 前端“模型”页只把发现到的模型加入候选列表，用户明确保存后才写入默认模型；发现模型不会保存临时 API Key。
- 诊断和 API 输出默认脱敏 API Key、OAuth/session、token 和完整本机路径；schema 字段元数据保留 `sensitive=true`，不当作真实密钥。
- `agent.model_routing` 当前只记录可解释路由决策和统计，不自动切换 Provider、认证方式或 fallback 路由。

## 证据文件

- `backend/core/model_discovery.py`
- `backend/model_auth/services/center.py`
- `backend/api.py`
- `src/renderer/js/pages/ModelsPage.js`
- `tests/test_model_auth_api.py`
- `tests/node/models_page_connection_button.test.mjs`
