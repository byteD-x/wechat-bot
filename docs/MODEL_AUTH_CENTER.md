# 模型与认证中心

本文档说明项目当前的 Provider + Auth Framework、统一认证领域模型、支持中的 provider/auth matrix、本地认证跟随机制、安全边界，以及如何继续扩展新的 provider 与 auth method。

文档更新时间：2026-03-25

## 1. 设计目标

本次改造不是“给几个示例 provider 加几个登录按钮”，而是把项目升级成统一的“模型与认证中心”：

1. 同时支持 `api_key`、`oauth`、`local_import`、`web_session` 四类认证方式。
2. 同一个 provider 可以并存多种认证方式，并显式选择默认认证方式。
3. 优先复用本地已有认证，并尽量采用“跟随本地认证”而不是“复制一份静态 token”。
4. 浏览器登录、CLI 登录、本地凭据缓存、网页登录 session 等非同质能力必须被正确建模，不能全部混叫 OAuth。
5. 旧的 `api.presets + active_preset` 运行时链路继续兼容，但由新的认证中心统一投影生成。

## 2. 领域模型

后端当前围绕以下概念组织 Provider 与 Auth：

- `ProviderDefinition`
- `ProviderCapability`
- `AuthMethodDefinition`
- `AuthMethodType`
- `CredentialSource`
- `CredentialBinding`
- `AuthStateSnapshot`
- `AuthStatus`
- `SyncPolicy`
- `HealthCheckResult`

`AuthMethodType` 当前支持：

- `api_key`
- `oauth`
- `local_import`
- `web_session`

`CredentialSource` 当前支持：

- `manual_input`
- `oauth_callback`
- `local_cli`
- `local_app`
- `local_extension`
- `local_config_file`
- `system_keychain`
- `browser_session`
- `imported_session`

额外约定：

- `oauth` 只表示“可以被项目作为 OAuth 认证链路建模”的方式。
- `local_import` 表示“项目复用本地已有认证源”，即使这个本地认证源本身最初是通过浏览器登录得到的。
- `web_session` 表示“非标准 OAuth 的网页登录 / 会话导入 / Cookie / Header / Session 接管”。

## 3. 目录结构

核心目录如下：

```text
backend/model_auth/
  domain/
    enums.py
    models.py
  providers/
    registry.py
  storage/
    credential_store.py
  sync/
    discovery.py
  services/
    migration.py
    health.py
    status.py
    center.py
```

职责划分：

- `domain/`：provider/auth 领域模型与状态结构。
- `providers/`：provider registry、auth method 元数据、能力矩阵。
- `storage/`：API Key、Session 等敏感凭据的后端安全存储。
- `sync/`：本地认证源发现与定位。
- `services/migration.py`：旧配置迁移、新旧结构投影、运行时安全水合。
- `services/status.py`：统一状态聚合、卡片排序、动作生成。
- `services/health.py`：统一健康检查与错误码映射。
- `services/center.py`：模型与认证中心动作编排入口。

## 4. 当前认证矩阵

下表区分“标准 OAuth”“本地认证复用”“网页登录 Session”三类不同语义，避免把所有网页登录都误记成 OAuth。

| Provider | 官方公开能力 | 当前框架建模 | 当前实现边界 |
| --- | --- | --- | --- |
| OpenAI / Codex / ChatGPT | API Key；Codex/ChatGPT 浏览器登录；本地 Codex 凭据缓存 | `api_key + local_import` | 当前优先复用本地 `Codex / ChatGPT` 登录；浏览器登录入口按 `local_import` 的浏览器流程建模，不伪装成通用第三方 OAuth |
| Google / Gemini / Gemini CLI | Google 登录；Gemini API Key；Vertex/Google Cloud 路径；本地 Gemini CLI 凭据缓存 | `api_key + oauth + local_import` | `google_oauth` 与 `gemini_cli_local` 同时建模；运行时继续复用本地 CLI 授权源 |
| Qwen / 通义千问 / 百炼 / Qwen Code | DashScope API Key；Coding Plan API Key；Qwen OAuth；本地 Qwen Code / OAuth 缓存 | `api_key + oauth + local_import` | `qwen_oauth` 与 `qwen_local` 并存；通用 DashScope API Key 与 Coding Plan API Key 作为两条独立方法建模，避免被压成一条泛化 Key 配置；`bailian / dashscope` 会统一归并到 `qwen` |
| Doubao / 火山方舟 / TRAE | 火山方舟 API Key；消费级网页登录；可能存在 IDE / 会话态 | `api_key + web_session` | 当前只把 Ark API Key 作为正式运行时路径；Doubao/Trae 登录按 `web_session` 保守建模，不伪装成标准 OAuth |
| Yuanbao / 元宝 | 消费级网页登录 / 扫码登录 | `web_session` | 当前按 `web_session` 建模并保留扩展位；未把元宝消费端错误标记成公开标准 OAuth |
| Claude / Claude Code | Claude.ai 凭据；Anthropic API Key；Bedrock Auth；Vertex Auth | `api_key + oauth + local_import` | 当前已接入 `Claude Code OAuth`、`Claude Code 本机登录` 与 `Claude Vertex AI 本机认证` 三条路径，并复用 `~/.claude.json`、`~/.claude/settings.json`、`~/.claude/.credentials.json`、`C:/ProgramData/ClaudeCode/managed-settings.json`、`application_default_credentials.json` 与 `GOOGLE_APPLICATION_CREDENTIALS` 的本地发现；当本地存在 `apiKeyHelper` 或可复用 Claude API 凭据缓存时，会进入 `anthropic_native`；当检测到可用 `gcloud` ADC / 服务账号时，会进入 `anthropic_vertex` 运行时链路 |
| Kimi / Moonshot / Kimi Code | Moonshot API Key；Kimi Code 浏览器 OAuth；Kimi Coding Plan API Key；本地 Kimi Code 配置缓存 | `api_key + oauth + local_import + coding_plan_api_key` | 当前已接入 `~/.kimi/config.toml`、`~/.kimi/credentials/*.json` 与 system keychain 提示信号的本地发现；运行时优先跟随 `config.toml` 中的本地 provider 配置，并将 Coding Plan API Key 作为独立方法建模，默认推荐 `kimi-for-coding` |
| GLM / 智谱 | API Key；GLM Coding Plan API Key | `api_key + coding_plan_api_key` | 当前已补齐通用 API Key 与 Coding Plan API Key 两条路径；当 base URL 指向 `https://open.bigmodel.cn/api/coding/paas/v4` 时会按智谱 Coding Plan 路径归类 |
| MiniMax | API Key；Token Plan / Coding Plan API Key | `api_key + coding_plan_api_key` | 当前已补齐通用 API Key 与 Token Plan / Coding Plan API Key 两条路径；会按地区识别 `api.minimax.io` 与 `api.minimaxi.com`，同时兼容 Anthropic-compatible 的 `/anthropic` 端点 |
| DeepSeek | API Key | `api_key` | 当前为 API Key 路径 |

补充说明：

- OpenAI / Codex / ChatGPT：当前最稳定的工程路径是“复用本地 Codex / ChatGPT 登录并持续跟随”，因此项目把它建模为 `local_import` + 浏览器登录入口，而不是通用第三方 OAuth。
- Google / Gemini：Google 登录本身是 OAuth，但项目同时区分了“显式 OAuth profile”和“直接跟随本地 Gemini CLI 凭据”两种方法。
- Qwen：DashScope 通用 API Key 与 Coding Plan API Key 会在同一 Provider 卡片下拆成两张独立表单，分别保留推荐 `base_url / model / key prefix` 元数据。
- Qwen：当 `base_url` 指向 `https://coding.dashscope.aliyuncs.com/v1` 时，会优先按百炼 Coding Plan 归类；即使模型名来自 `MiniMax / GLM / Kimi`，也不会跳到这些模型原厂 Provider。
- Claude / Claude Code：Claude Code OAuth 与 Claude 本机登录共享同一组本机凭据来源，但模型中心会把“执行浏览器登录”和“直接跟随本机已登录账号”拆成两个入口。
- Claude / Claude Code：截至 2026-03-27，Google Vertex AI 路径已补成真实运行时，模型中心会把 `oauth_project_id / oauth_location` 与本机 `gcloud` 凭据一起组装成 `publishers/anthropic/models/{model}:rawPredict` 请求；`Bedrock` 当前仍只保留扩展位，没有误标成可直接对话。
- Doubao / Yuanbao：当前缺少稳定、可公开依赖的标准 OAuth 说明，因此仅按 `web_session` 保守建模；本轮补充了基于浏览器 Cookie 数据库、`IndexedDB / Local Storage`、桌面私有存储或显式导出 Session 文件的本地探测。
- Kimi：官方 Kimi Code CLI 已提供浏览器 OAuth 登录、通用 API Key 与 Coding Plan API Key 多条路径，因此这里按 `oauth + local_import + api_key + coding_plan_api_key` 建模，而不是 `web_session`。
- MiniMax：官方 AI Coding Tools 文档已明确给出独立的 Token Plan 接入方式；本项目沿用统一的 `coding_plan_api_key` 方法位承载这类订阅型 Key，并支持国际区 / 中国区双入口，以及 Anthropic-compatible 的 `/anthropic` 端点。
- GLM / 智谱：除了通用 API Key，当前也补齐了 `GLM Coding Plan API Key`，并把 Coding Plan base URL 作为 provider 识别信号之一。
- 模型中心前端会把 method metadata 中的 `recommended_base_url / recommended_model` 直接投影到首次配置工作流：用户在保存 `coding_plan_api_key`、`Kimi Code OAuth`、`Kimi Code 本机登录` 等方法前，就能看到并自动落到真实对话端点，而不是继续停留在 provider 的通用默认值。
- `Qwen OAuth / Qwen 本机登录` 现在也会复用同一套 method metadata，首次配置时会默认把模型切到 `qwen3-coder-plus`，与 Qwen Code 当前内置默认模型保持一致。
- 对仍然依赖 legacy preset 序列化的路径，也会复用这份 method metadata：即便历史配置对象只有 `auth_mode=api_key|oauth`，保存时也会尽量回填正确的 `base_url / model / oauth_provider`，让后续 runtime projection 更稳定。

## 5. 本地认证优先与跟随

### 5.1 发现

当前通过 `backend/core/auth` 中各 provider 的本地探测逻辑读取本地认证状态，再由 `backend/model_auth/sync/discovery.py` 统一汇总到模型认证中心。

页面层可见的典型状态包括：

- `not_configured`
- `available_to_import`
- `connecting`
- `connected`
- `following_local_auth`
- `imported`
- `expired`
- `invalid`
- `error`

### 5.2 跟随而不是复制

对于支持本地认证复用的 provider，项目默认保存的是：

- 绑定关系
- 本地来源类型
- 来源路径
- 同步策略
- 账号标签

而不是把本地 token 复制成一份长期脱钩的静态真源。

这带来几个直接效果：

1. 本地 token 刷新后，运行时读取到的是最新值。
2. 本地切号后，模型中心页面刷新时能看到新的账号标签与状态。
3. 本地登出后，状态会降级为 `expired`、`invalid` 或 `available_to_import`。

### 5.3 当前同步方式

当前版本采用“路径级 watcher + polling fallback + 手动强刷 + 运行时动态解析”的保守实现：

- `backend/model_auth/sync/orchestrator.py` 会在模型中心使用时启动后台同步器，同步缓存各 provider 的本机认证快照、变更指纹和最近刷新时间。
- 对已发现的本机认证文件路径，会复用现有 `ConfigReloadWatcher` 做路径级 `watchdog` 监听；如果监听不可用，则自动回退到 polling。
- 当前新增的本机来源包括：
  - Claude Code 的 `~/.claude.json`、`~/.claude/settings.json`
  - Claude Code 的 `~/.claude/.credentials.json`
  - Claude Code 的 `C:/ProgramData/ClaudeCode/managed-settings.json`
  - Kimi Code 的 `~/.kimi/config.toml`、`~/.kimi/credentials/*.json`
  - Doubao / Yuanbao 的浏览器 Cookie 数据库路径、`IndexedDB / Local Storage` 路径、桌面私有存储路径或显式导出 Session 文件路径
- watcher 现在既能监听单文件，也能监听目录级存储目标，例如 `.../IndexedDB/<origin>.indexeddb.leveldb` 或 `.../Local Storage/leveldb`
- 打开模型中心时优先读取同步快照；手动点击“扫描本机认证”会触发一次强制刷新。
- 运行时真正发请求时，仍会按需读取本地认证源或调用 legacy auth adapter 的动态解析函数，保证刷新后的本机 token 能被继续复用。
- `CredentialBinding.locator_path` 继续保留本地来源路径，为未来增加更细粒度的文件监听留出扩展位。

这保证当前版本已经具备“持续跟随本机认证”的后台基础设施，同时仍保持实现克制，避免过早把更深层的 keychain / app session watcher 逻辑散落到多个模块里。

本轮又补充了两类来源：
- `system_keychain`：当前会把 Windows Credential Manager 的 provider 相关 target 作为发现信号接入状态机；这仍属于保守 discovery/follow 提示，不代表已经开放稳定运行时消费。
- `local_app_private_storage`：除了浏览器式 Cookie/IndexedDB/Local Storage 目录外，也会继续探测桌面私有目录中的会话文件，并把 `private_auth_file_path` 一并带入绑定元数据。

## 6. 动作与状态生成

认证卡片上的操作不再由前端自己猜，而是由后端按 auth method 语义动态生成。

当前动作层遵循这些规则：

- `api_key`：展示“添加 API Key”或已有 profile 的默认/测试/断开动作。
- `oauth`：展示真正的 OAuth 连接文案，例如 `Connect via OAuth`。
- `local_import`：展示“Follow Local Auth”或“Open Browser Login”，避免把本地登录误叫成 OAuth。
- `web_session`：展示“Import Session”或“Open Login Page”，明确区分网页登录与标准 OAuth。

这解决了一个常见误区：不是所有会打开浏览器的认证流程都应该在 UI 上显示成“OAuth”。

### 6.1 前端卡片与方法级表单

独立的“模型”页不再把 Provider-specific 逻辑散落在设置页里，而是统一使用 Provider 卡片承载：

- Provider 概览：名称、简介、默认模型、默认 Base URL、当前选中的认证方式。
- Provider 级摘要：后端统一聚合“本机同步摘要 / 连接健康摘要 / 认证计数”，前端只负责展示，不再自己拼状态。
- 状态区：按 auth method 展示 `Following Local Auth / OAuth Connected / API Key Configured / Available to Import / Expired / Error` 等标准状态。
- 运行时就绪度：已绑定认证方法会额外展示 `runtime_ready / runtime_unavailable_reason`；当默认认证还没进入真正的运行时链路时，Provider 健康摘要会以 `blocked` 状态直出原因。
- 详情区：展示官方入口、调研摘要、本机常见认证路径、官方参考来源。
- 方法级表单：每个 `api_key` 或 `web_session` method 都拥有自己的独立表单，不再把同一 Provider 下的多条 API Key 路径压成一张通用表单。
- 浏览器授权收口：当后端返回待完成的 `flow_id` 时，模型页会在对应 method 下显示“继续完成授权”表单，允许直接轮询本机授权状态，或补充 callback payload 后继续完成授权。
- 通用继续授权：对于不暴露标准 `flow_id` 的网页登录 / session 型 provider，模型页会退化为 `__local_rescan__` 本机重扫路径，而不是强行要求 legacy OAuth flow。
- 本机重扫优先：对 `OpenAI / Codex / ChatGPT`、`Google / Gemini / Gemini CLI` 这类实际通过本机凭据落盘完成的浏览器授权方法，即使前端还带着旧 `flow_id`，后端也会优先走本机重扫收口，不会错误提交到标准 OAuth callback。
- 设置页迁移收口：设置页顶部的“模型与认证”卡片现在直接读取 `/api/model_auth/overview` 的活动 Provider 摘要，不再自己从旧 `api.presets` 投影状态。
- 旧设置页收口：历史预设 modal 不再承载 `/api/auth/providers/*` OAuth 流程；如果用户仍打开旧 modal，会被明确引导到独立“模型”页处理浏览器授权、本机认证跟随与导入副本。

这意味着像 Qwen 这样的 Provider 可以在同一张卡片里同时看到：

- `DashScope API Key`
- `Coding Plan API Key`
- `Kimi Coding Plan API Key`
- `GLM Coding Plan API Key`
- `Qwen OAuth`
- `Qwen Local Auth`

并且每条方法都会携带自己的推荐 `base_url / model`、能力标签和风险说明。

## 7. 凭据安全

当前安全边界如下：

1. 前端不再持久化明文 API Key / Session。
2. API Key / Session 统一进入 `backend/model_auth/storage/credential_store.py`。
3. Windows 下优先使用 DPAPI；非 Windows 环境回退到 base64 文件封装，仅用于开发兼容。
4. 运行时通过 `credential_ref` 从后端安全存储中水合凭据。
5. `local_import` 优先保存绑定关系与来源信息，而不是复制长期凭据正文。

## 8. 如何新增 Provider

推荐步骤：

1. 在 `backend/model_auth/providers/registry.py` 中注册 `ProviderDefinition`。
2. 声明该 provider 的 `ProviderCapability` 与 `AuthMethodDefinition`。
3. 如果已有 legacy auth adapter 可复用，给 `AuthMethodDefinition.legacy_provider_id` 绑定 legacy provider。
4. 如需本地发现，补充 `backend/core/auth/providers.py` 的本地探测与运行时解析能力。
5. 在 `services/status.py` 中确认其状态与动作语义是否需要特殊边界说明。
6. 如需运行时支持，确保 `services/health.py` 与 `migration.py` 的投影链路可以解析该方法。

## 9. 如何新增一种 Auth Method

1. 在 `backend/model_auth/domain/enums.py` 中补充新的枚举值。
2. 在 `backend/model_auth/domain/models.py` 中补充需要的元数据字段。
3. 在 `services/migration.py` 中补充迁移、投影和运行时水合逻辑。
4. 在 `services/status.py` 中补充状态推导、动作生成与错误映射。
5. 在 `services/center.py` 中补充动作入口。
6. 在前端模型页增加对应表单或交互控件。

## 10. 当前实现边界

当前版本已经打通：

- Provider/Auth 统一注册与能力建模
- 旧配置迁移到新认证中心
- 运行时从新结构投影回 `api.presets`
- API Key / Session 的后端安全存储
- OpenAI / Google / Qwen / Doubao / Yuanbao 的核心能力建模
- OpenAI / Google / Qwen 的本地认证发现与跟随
- 后端统一动作生成，前端不再把所有浏览器流误称为 OAuth
- 同一 Provider 下多条 API Key 方法的独立迁移与独立表单展示

当前仍保留的边界：

- Doubao / Yuanbao 的 `web_session` 目前重点在安全建模、本地浏览器 Session 探测与导入扩展位，尚未开放稳定运行时调用。
- Claude 现在已经具备真实的本地凭据发现能力；当本地存在 `apiKeyHelper` 或 Claude API credential cache 时，会走 `anthropic_native` 运行时。仅有订阅型 Claude.ai OAuth 状态时，当前仍保守停留在 follow-mode discovery/status，不默认投影到 Anthropic API runtime。
- Claude helper / 本地 Claude API credential cache 进入运行时后，如果首次请求返回 `401`，当前会先强制刷新一次本地认证，再自动重试同一请求一次。
- Kimi 现在已经具备真实的本地凭据发现能力，并开始进入真实运行时链路：优先跟随 `~/.kimi/config.toml` 中的本地 provider 配置，必要时再回退到 `~/.kimi/credentials/*.json` 的 OAuth 凭据缓存。
- 本地认证同步目前已经具备“路径级 watcher + polling fallback”，并开始覆盖浏览器 Cookie 数据库、`IndexedDB`、`Local Storage` 与桌面私有存储路径；系统钥匙串已进入发现与状态链路，但仍没有覆盖真正的钥匙串事件监听与稳定运行时消费。

## 11. 关键文件

- `backend/model_auth/domain/enums.py`
- `backend/model_auth/domain/models.py`
- `backend/model_auth/providers/registry.py`
- `backend/model_auth/storage/credential_store.py`
- `backend/model_auth/sync/discovery.py`
- `backend/model_auth/services/migration.py`
- `backend/model_auth/services/status.py`
- `backend/model_auth/services/health.py`
- `backend/model_auth/services/center.py`
- `backend/core/auth/providers.py`
- `backend/api.py`
- `src/renderer/js/pages/ModelsPage.js`
- `src/renderer/css/app.css`
- `src/renderer/index.html`
