from __future__ import annotations

from typing import Dict, Iterable, Optional

from backend.model_catalog import get_model_catalog

from ..domain.enums import AuthMethodType
from ..domain.models import AuthMethodDefinition, ProviderCapability, ProviderDefinition


def _build_capability(methods: Iterable[AuthMethodDefinition]) -> ProviderCapability:
    method_list = list(methods)
    return ProviderCapability(
        supports_api_key=any(item.type is AuthMethodType.API_KEY for item in method_list),
        supports_oauth=any(item.type is AuthMethodType.OAUTH for item in method_list),
        supports_local_auth_import=any(item.type is AuthMethodType.LOCAL_IMPORT for item in method_list),
        supports_web_session=any(item.type is AuthMethodType.WEB_SESSION for item in method_list),
        supports_multi_account=any(item.supports_multi_account for item in method_list),
        supports_health_check=any(item.runtime_supported for item in method_list),
        supports_auto_refresh=any(item.supports_refresh for item in method_list),
        supports_local_file_watch=any(item.supports_follow_mode for item in method_list),
        supports_default_auth_selection=True,
        supports_credential_follow_mode=any(item.supports_follow_mode for item in method_list),
    )


def get_method_auth_provider_id(method: AuthMethodDefinition | None) -> str:
    if method is None:
        return ""
    return str(method.auth_provider_id or method.legacy_provider_id or "").strip()


def _provider(
    *,
    id: str,
    label: str,
    description: str,
    homepage_url: str,
    docs_url: str,
    api_key_url: str,
    default_base_url: str,
    default_model: str,
    auth_methods: tuple[AuthMethodDefinition, ...],
    default_auth_order: tuple[str, ...],
    supported_models: tuple[str, ...],
    tags: tuple[str, ...] = (),
    metadata: Optional[Dict[str, object]] = None,
) -> ProviderDefinition:
    return ProviderDefinition(
        id=id,
        label=label,
        description=description,
        homepage_url=homepage_url,
        docs_url=docs_url,
        api_key_url=api_key_url,
        default_base_url=default_base_url,
        default_model=default_model,
        capability=_build_capability(auth_methods),
        auth_methods=auth_methods,
        default_auth_order=default_auth_order,
        supported_models=supported_models,
        tags=tags,
        metadata=dict(metadata or {}),
    )


_REGISTRY: Dict[str, ProviderDefinition] = {
    "openai": _provider(
        id="openai",
        label="OpenAI / Codex / ChatGPT",
        description="支持 API Key，以及可同步的 Codex / ChatGPT 本机登录态。",
        homepage_url="https://openai.com/",
        docs_url="https://developers.openai.com/codex/cli/",
        api_key_url="https://platform.openai.com/api-keys",
        default_base_url="https://api.openai.com/v1",
        default_model="gpt-5.4-mini",
        auth_methods=(
            AuthMethodDefinition(
                id="api_key",
                type=AuthMethodType.API_KEY,
                label="API Key",
                description="直接使用 OpenAI Platform API Key。",
                api_key_url="https://platform.openai.com/api-keys",
                metadata={
                    "official_type": "api_key",
                    "recommended_base_url": "https://api.openai.com/v1",
                    "recommended_model": "gpt-5.4-mini",
                },
            ),
            AuthMethodDefinition(
                id="codex_local",
                type=AuthMethodType.LOCAL_IMPORT,
                label="Codex / ChatGPT 本机登录",
                description="同步本机的 Codex / ChatGPT 登录态，并持续跟随它。",
                supports_browser_flow=True,
                supports_local_discovery=True,
                supports_follow_mode=True,
                supports_import_copy=True,
                supports_multi_account=True,
                auth_provider_id="openai_codex",
                legacy_provider_id="openai_codex",
                browser_entry_url="https://chatgpt.com/",
                browser_flow_kind="cli_browser_login",
                connect_label="打开 ChatGPT / Codex 登录页",
                follow_label="跟随本机登录",
                import_label="导入本机登录副本",
                metadata={
                    "official_type": "local_import",
                    "browser_login": True,
                    "local_storage_paths": ["~/.codex/auth.json"],
                    "notes": [
                        "这里刻意建模为“本机同步 + 浏览器登录”，而不是公共标准 OAuth。",
                        "运行时会跟随最新的本机 Codex / ChatGPT 凭据，而不是长期保存一份静态副本。",
                    ],
                },
            ),
        ),
        default_auth_order=("codex_local", "api_key"),
        supported_models=(
            "gpt-5.4",
            "gpt-5.4-mini",
            "gpt-5.4-nano",
            "gpt-5.3-codex",
            "gpt-5",
            "gpt-5-mini",
            "gpt-5-nano",
            "gpt-4.1",
            "gpt-4.1-mini",
            "gpt-4.1-nano",
            "gpt-4o",
            "gpt-4o-mini",
        ),
        tags=("subscription", "api", "cli"),
        metadata={
            "research_summary": "OpenAI 同时支持直接使用 Platform API Key，以及通过 Codex 浏览器登录后在本机缓存并同步的 CLI 登录态。",
            "last_reviewed": "2026-03-26",
            "official_sources": [
                {"label": "Codex CLI 文档", "url": "https://developers.openai.com/codex/cli/"},
                {"label": "OpenAI 模型列表", "url": "https://developers.openai.com/api/docs/models/all"},
            ],
            "local_auth_paths": ["~/.codex/auth.json"],
            "notes": [
                "这里虽然存在浏览器登录，但不应在本项目里误标成通用 OAuth。",
                "订阅态 ChatGPT / Codex 登录和 API Key 可以并存。",
            ],
        },
    ),
    "google": _provider(
        id="google",
        label="Google / Gemini",
        description="支持 Gemini API Key，以及从本机 Gemini CLI 配置目录导入、粘贴 JWT 令牌或通过 OAuth 登录来管理 Gemini CLI 账号。",
        homepage_url="https://gemini.google.com/",
        docs_url="https://google-gemini.github.io/gemini-cli/",
        api_key_url="https://aistudio.google.com/apikey",
        default_base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        default_model="gemini-2.5-flash",
        auth_methods=(
            AuthMethodDefinition(
                id="google_oauth",
                type=AuthMethodType.OAUTH,
                label="Google OAuth",
                description="通过 Google OAuth 完成授权，并同步 Gemini CLI 本地配置目录中的可刷新凭据。",
                supports_browser_flow=True,
                supports_local_discovery=True,
                supports_follow_mode=True,
                supports_import_copy=True,
                supports_multi_account=True,
                supports_refresh=True,
                auth_provider_id="google_gemini_cli",
                legacy_provider_id="google_gemini_cli",
                browser_entry_url="https://gemini.google.com/",
                browser_flow_kind="standard_oauth",
                connect_label="通过 Google OAuth 登录",
                follow_label="同步本机 Gemini CLI 登录",
                import_label="导入 Gemini CLI 认证副本",
                metadata={
                    "official_type": "oauth",
                    "local_storage_paths": [
                        "~/.gemini/oauth_creds.json",
                        "~/.gemini/google_accounts.json",
                        "~/.gemini/settings.json",
                        "$GEMINI_CLI_HOME/.gemini/oauth_creds.json",
                        "$GEMINI_CLI_HOME/.gemini/google_accounts.json",
                        "$GEMINI_CLI_HOME/.gemini/settings.json",
                    ],
                    "requires_project_for_org_accounts": True,
                },
            ),
            AuthMethodDefinition(
                id="gemini_cli_local",
                type=AuthMethodType.LOCAL_IMPORT,
                label="Gemini CLI 本机登录",
                description="从本机 Gemini CLI 配置目录导入并跟随已登录账号，支持按需切换本地凭据。",
                supports_browser_flow=True,
                supports_local_discovery=True,
                supports_follow_mode=True,
                supports_import_copy=True,
                supports_multi_account=True,
                supports_refresh=True,
                auth_provider_id="google_gemini_cli",
                legacy_provider_id="google_gemini_cli",
                browser_entry_url="https://gemini.google.com/",
                browser_flow_kind="cli_browser_login",
                connect_label="打开 Gemini 登录页",
                follow_label="同步本机 Gemini CLI 登录",
                import_label="导入 Gemini CLI 认证副本",
                metadata={
                    "official_type": "local_import",
                    "local_storage_paths": [
                        "~/.gemini/oauth_creds.json",
                        "~/.gemini/google_accounts.json",
                        "~/.gemini/settings.json",
                        "$GEMINI_CLI_HOME/.gemini/oauth_creds.json",
                        "$GEMINI_CLI_HOME/.gemini/google_accounts.json",
                        "$GEMINI_CLI_HOME/.gemini/settings.json",
                    ],
                },
            ),
            AuthMethodDefinition(
                id="api_key",
                type=AuthMethodType.API_KEY,
                label="Gemini API Key",
                description="Google AI Studio 或 Google API Key。",
                api_key_url="https://aistudio.google.com/apikey",
                metadata={
                    "official_type": "api_key",
                    "recommended_base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
                    "recommended_model": "gemini-2.5-flash",
                },
            ),
        ),
        default_auth_order=("gemini_cli_local", "google_oauth", "api_key"),
        supported_models=("gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.5-flash-lite"),
        tags=("google_login", "api", "cli", "vertex"),
        metadata={
            "research_summary": "支持从本机 Gemini CLI 配置目录导入、粘贴 JWT 令牌，或通过 Google OAuth 登录来管理 Gemini CLI 账号。",
            "last_reviewed": "2026-03-26",
            "official_sources": [
                {"label": "Gemini CLI 认证文档", "url": "https://github.com/google-gemini/gemini-cli/blob/main/docs/get-started/authentication.md"},
                {"label": "Gemini API 弃用说明", "url": "https://ai.google.dev/gemini-api/docs/deprecations"},
            ],
            "local_auth_paths": [
                "~/.gemini/oauth_creds.json",
                "~/.gemini/google_accounts.json",
                "~/.gemini/settings.json",
                "$GEMINI_CLI_HOME/.gemini/oauth_creds.json",
                "$GEMINI_CLI_HOME/.gemini/google_accounts.json",
                "$GEMINI_CLI_HOME/.gemini/settings.json",
            ],
            "notes": [
                "权限范围：读取并写入默认 ~/.gemini 或实例目录（$GEMINI_CLI_HOME/.gemini）下的 oauth_creds.json、google_accounts.json、settings.json，用于账号导入与本地凭证注入（切换账号）。",
                "网络请求范围：OAuth 授权与令牌刷新只会访问 Google / Gemini 官方接口（例如 oauth2.googleapis.com、googleapis.com），仅发送认证与配额所需字段，不会向第三方服务器上传账号文件。",
                "Google OAuth 登录与本机 Gemini CLI 同步会分开建模。",
                "Vertex ADC / 服务账号等方式仍作为未来扩展点，暂不纳入当前认证类型集合。",
            ],
        },
    ),
    "qwen": _provider(
        id="qwen",
        label="Qwen / 通义千问 / 百炼",
        description="支持 DashScope API Key、Qwen OAuth，以及可同步的 Qwen 本机登录态。",
        homepage_url="https://chat.qwen.ai/",
        docs_url="https://qwenlm.github.io/qwen-code-docs/zh/cli/index",
        api_key_url="https://modelstudio.console.aliyun.com/",
        default_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        default_model="qwen3.5-plus",
        auth_methods=(
            AuthMethodDefinition(
                id="qwen_local",
                type=AuthMethodType.LOCAL_IMPORT,
                label="Qwen 本机登录",
                description="跟随本机缓存的 Qwen OAuth 凭据。",
                supports_local_discovery=True,
                supports_follow_mode=True,
                supports_import_copy=True,
                supports_refresh=True,
                auth_provider_id="qwen_oauth",
                legacy_provider_id="qwen_oauth",
                browser_entry_url="https://chat.qwen.ai/",
                browser_flow_kind="oauth_device_code",
                connect_label="打开 Qwen 登录页",
                follow_label="跟随本机 Qwen 登录",
                import_label="导入本机 Qwen 登录副本",
                metadata={
                    "official_type": "local_import",
                    "local_storage_paths": ["~/.qwen/oauth_creds.json"],
                },
            ),
            AuthMethodDefinition(
                id="qwen_oauth",
                type=AuthMethodType.OAUTH,
                label="Qwen OAuth",
                description="执行 Qwen OAuth 浏览器流程，并保存可刷新的 Token。",
                supports_browser_flow=True,
                supports_local_discovery=True,
                supports_follow_mode=True,
                supports_import_copy=True,
                supports_refresh=True,
                auth_provider_id="qwen_oauth",
                legacy_provider_id="qwen_oauth",
                browser_entry_url="https://chat.qwen.ai/",
                browser_flow_kind="oauth_device_code",
                connect_label="通过 Qwen OAuth 登录",
                follow_label="使用本机 Qwen OAuth",
                import_label="导入 Qwen OAuth 副本",
                metadata={
                    "official_type": "oauth",
                    "local_storage_paths": ["~/.qwen/oauth_creds.json"],
                },
            ),
            AuthMethodDefinition(
                id="api_key",
                type=AuthMethodType.API_KEY,
                label="DashScope API Key",
                description="阿里云 DashScope / 百炼兼容 OpenAI 的 API Key。",
                api_key_url="https://modelstudio.console.aliyun.com/",
                metadata={
                    "official_type": "api_key",
                    "recommended_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "recommended_model": "qwen3.5-plus",
                    "key_env_hint": "DASHSCOPE_API_KEY",
                },
            ),
            AuthMethodDefinition(
                id="coding_plan_api_key",
                type=AuthMethodType.API_KEY,
                label="Coding Plan API Key",
                description="阿里云 Coding Plan 专用编码端点与订阅额度使用的 API Key。",
                api_key_url="https://bailian.console.aliyun.com/",
                metadata={
                    "official_type": "api_key",
                    "recommended_base_url": "https://coding.dashscope.aliyuncs.com/v1",
                    "recommended_model": "qwen3-coder-next",
                    "key_env_hint": "BAILIAN_CODING_PLAN_API_KEY",
                    "key_prefix_hint": "sk-sp-",
                    "subscription": True,
                },
            ),
        ),
        default_auth_order=("qwen_local", "qwen_oauth", "coding_plan_api_key", "api_key"),
        supported_models=(
            "qwen3.5-plus",
            "qwen3.5-flash",
            "qwen3-max-2026-01-23",
            "qwen-plus-latest",
            "qwen-turbo-latest",
            "qwen3-coder-next",
            "qwen3-coder-plus",
            "qwen3-coder-flash",
        ),
        tags=("oauth", "api", "cli", "dashscope"),
        metadata={
            "research_summary": "Qwen Code 官方支持 Qwen OAuth、阿里云 Coding Plan，以及通用 API Key 模式的模型接入。",
            "last_reviewed": "2026-03-26",
            "official_sources": [
                {"label": "Qwen Code 认证文档", "url": "https://qwenlm.github.io/qwen-code-docs/en/users/configuration/auth/"},
                {"label": "DashScope 模型计费", "url": "https://help.aliyun.com/zh/model-studio/model-pricing"},
            ],
            "local_auth_paths": ["~/.qwen/oauth_creds.json", "~/.qwen/settings.json", "~/.qwen/.env"],
            "notes": [
                "Coding Plan 使用独立端点，不应和通用 DashScope API Key 路径混为一谈。",
                "Qwen OAuth 属于真实的浏览器 / 设备码 OAuth 流程，本机跟随模式会单独建模。",
            ],
        },
    ),
    "doubao": _provider(
        id="doubao",
        label="Doubao / 火山方舟 / TRAE",
        description="支持 Ark API 凭据，以及实验性的浏览器 / 会话绑定方式。",
        homepage_url="https://www.doubao.com/",
        docs_url="https://www.volcengine.com/docs/82379",
        api_key_url="https://console.volcengine.com/ark",
        default_base_url="https://ark.cn-beijing.volces.com/api/v3",
        default_model="doubao-seed-1.8",
        auth_methods=(
            AuthMethodDefinition(
                id="api_key",
                type=AuthMethodType.API_KEY,
                label="Ark API Key",
                description="火山引擎 Ark API Key 或兼容凭据。",
                api_key_url="https://console.volcengine.com/ark",
                metadata={
                    "official_type": "api_key",
                    "recommended_base_url": "https://ark.cn-beijing.volces.com/api/v3",
                    "recommended_model": "doubao-seed-1.8",
                },
            ),
            AuthMethodDefinition(
                id="doubao_web_session",
                type=AuthMethodType.WEB_SESSION,
                label="Doubao 网页会话",
                description="绑定 Doubao / TRAE 浏览器会话或导入会话。这里不会把它建模成标准 OAuth。",
                experimental=True,
                runtime_supported=False,
                supports_browser_flow=True,
                supports_local_discovery=True,
                supports_follow_mode=True,
                supports_import_copy=True,
                auth_provider_id="doubao_session",
                legacy_provider_id="doubao_session",
                browser_entry_url="https://www.doubao.com/",
                browser_flow_kind="browser_session",
                connect_label="打开 Doubao 登录页",
                follow_label="跟随本机浏览器会话",
                import_label="导入会话",
                metadata={
                    "official_type": "web_session",
                    "heuristic_local_detection": True,
                    "notes": [
                        "Doubao / TRAE 的消费端登录在本项目里不会建模成标准 OAuth。",
                        "在确认稳定的官方来源策略前，运行时调用会继续保持关闭。",
                        "本机探测优先使用浏览器 Cookie / Session，或显式导出的会话文件。",
                    ],
                },
            ),
        ),
        default_auth_order=("api_key", "doubao_web_session"),
        supported_models=(
            "doubao-seed-1.8",
            "doubao-seed-2.0-pro",
            "doubao-seed-2.0-lite",
            "doubao-seed-2.0-mini",
            "doubao-seed-code",
        ),
        tags=("api", "web_session", "consumer_app"),
        metadata={
            "research_summary": "火山引擎 Ark 提供 API Key 访问，而 Doubao / TRAE 的消费端登录更适合建模为网页会话式认证。",
            "last_reviewed": "2026-03-26",
            "official_sources": [
                {"label": "火山引擎 Ark 文档", "url": "https://www.volcengine.com/docs/82379"},
                {"label": "Doubao 1.8 latest", "url": "https://www.volcengine.com/docs/82379/2123228"},
                {"label": "Doubao", "url": "https://www.doubao.com/"},
                {"label": "TRAE 定价与登录入口", "url": "https://www.trae.ai/promo-code"},
            ],
            "local_auth_paths": [
                "%LOCALAPPDATA%/Google/Chrome/User Data/*/Network/Cookies",
                "%LOCALAPPDATA%/Microsoft/Edge/User Data/*/Network/Cookies",
                "$WECHAT_BOT_DOUBAO_SESSION_PATH",
                "$WECHAT_BOT_DOUBAO_PRIVATE_STORAGE_PATH",
                "$WECHAT_BOT_TRAE_PRIVATE_STORAGE_PATH",
                "$WECHAT_BOT_DOUBAO_KEYCHAIN_TARGETS",
                "$WECHAT_BOT_TRAE_KEYCHAIN_TARGETS",
            ],
            "notes": [
                "目前还没有证据表明 Doubao 消费端登录存在稳定的公开标准 OAuth 流程。",
                "浏览器 Cookie 探测属于启发式能力，会刻意保留在 web_session 范畴，而不是假装成标准 OAuth。",
                "桌面端私有存储也会保守探测，并继续留在同一个 web_session 分类里。",
            ],
        },
    ),
    "yuanbao": _provider(
        id="yuanbao",
        label="Yuanbao / 元宝",
        description="以浏览器 / 会话式认证为主，公开 API 认证会和元宝消费端登录分开建模。",
        homepage_url="https://yuanbao.tencent.com/",
        docs_url="https://yuanbao.tencent.com/",
        api_key_url="",
        default_base_url="",
        default_model="yuanbao-web",
        auth_methods=(
            AuthMethodDefinition(
                id="yuanbao_web_session",
                type=AuthMethodType.WEB_SESSION,
                label="元宝网页会话",
                description="绑定元宝浏览器会话。这里不会把它视为公开的标准 OAuth 集成。",
                experimental=True,
                runtime_supported=False,
                supports_browser_flow=True,
                supports_local_discovery=True,
                supports_follow_mode=True,
                supports_import_copy=True,
                auth_provider_id="tencent_yuanbao",
                legacy_provider_id="tencent_yuanbao",
                browser_entry_url="https://yuanbao.tencent.com/",
                browser_flow_kind="browser_session",
                connect_label="打开元宝登录页",
                follow_label="跟随本机浏览器会话",
                import_label="导入会话",
                metadata={
                    "official_type": "web_session",
                    "heuristic_local_detection": True,
                    "notes": [
                        "元宝消费端登录会刻意建模为会话式认证，而不是公开 OAuth。",
                    ],
                },
            ),
        ),
        default_auth_order=("yuanbao_web_session",),
        supported_models=("yuanbao-web",),
        tags=("web_session", "consumer_app"),
        metadata={
            "research_summary": "腾讯元宝当前更像消费端网页 / 应用登录入口，因此本项目会把它保留为网页会话式认证。",
            "last_reviewed": "2026-03-25",
            "official_sources": [
                {"label": "腾讯元宝", "url": "https://yuanbao.tencent.com/"},
            ],
            "local_auth_paths": [
                "%LOCALAPPDATA%/Google/Chrome/User Data/*/Network/Cookies",
                "%LOCALAPPDATA%/Microsoft/Edge/User Data/*/Network/Cookies",
                "$WECHAT_BOT_YUANBAO_SESSION_PATH",
                "$WECHAT_BOT_YUANBAO_PRIVATE_STORAGE_PATH",
                "$WECHAT_BOT_YUANBAO_KEYCHAIN_TARGETS",
            ],
            "notes": [
                "目前还没有证据表明这个消费端产品存在稳定的公开 API Key 或标准 OAuth 路径。",
                "本机浏览器会话探测会保持保守，并继续和未来可能出现的腾讯开放平台 API 分开。",
                "桌面端私有存储也会保守探测，并保持为 web_session 提示，而不是伪装成 OAuth 流程。",
            ],
        },
    ),
    "anthropic": _provider(
        id="anthropic",
        label="Claude / Claude Code",
        description="支持 Claude Console API Key，以及 Claude Code 本机凭据探测与同步。",
        homepage_url="https://claude.ai/",
        docs_url="https://code.claude.com/docs/en/authentication",
        api_key_url="https://platform.claude.com/settings/keys",
        default_base_url="https://api.anthropic.com/v1",
        default_model="claude-sonnet-4-0",
        auth_methods=(
            AuthMethodDefinition(
                id="api_key",
                type=AuthMethodType.API_KEY,
                label="Claude API Key",
                description="Claude Console API Key，或来自 API Helper 的输出。",
                api_key_url="https://platform.claude.com/settings/keys",
                metadata={
                    "official_type": "api_key",
                    "recommended_base_url": "https://api.anthropic.com/v1",
                    "recommended_model": "claude-sonnet-4-0",
                },
            ),
            AuthMethodDefinition(
                id="claude_code_local",
                type=AuthMethodType.LOCAL_IMPORT,
                label="Claude Code 本机登录",
                description="同步 Claude.ai 或 Claude Console 浏览器登录后留在本机的凭据。",
                experimental=True,
                runtime_supported=True,
                supports_browser_flow=True,
                supports_local_discovery=True,
                supports_follow_mode=True,
                supports_import_copy=True,
                supports_multi_account=True,
                supports_refresh=True,
                auth_provider_id="claude_code_local",
                legacy_provider_id="claude_code_local",
                browser_entry_url="https://claude.ai/",
                browser_flow_kind="cli_browser_login",
                connect_label="打开 Claude Code 登录页",
                follow_label="跟随本机 Claude 登录",
                import_label="导入本机 Claude 登录副本",
                metadata={
                    "official_type": "local_import",
                    "local_storage_paths": [
                        "~/.claude.json",
                        "~/.claude/settings.json",
                        "~/.claude/.credentials.json",
                        "C:/ProgramData/ClaudeCode/managed-settings.json",
                    ],
                    "recommended_base_url": "https://api.anthropic.com/v1",
                    "recommended_model": "claude-sonnet-4-0",
                    "supports_source_logout": False,
                },
            ),
        ),
        default_auth_order=("claude_code_local", "api_key"),
        supported_models=(
            "claude-sonnet-4-0",
            "claude-opus-4-1",
            "claude-opus-4-0",
            "claude-3-7-sonnet-latest",
            "claude-3-5-haiku-latest",
        ),
        tags=("extension", "api", "subscription", "cli"),
        metadata={
            "research_summary": "Claude Code 官方支持 Claude.ai / Console 凭据、API Key、云厂商认证，以及本机凭据存储。",
            "last_reviewed": "2026-03-26",
            "official_sources": [
                {"label": "Claude Code 快速开始", "url": "https://code.claude.com/docs/en/quickstart"},
                {"label": "Claude Code 设置文档", "url": "https://code.claude.com/docs/en/settings"},
                {"label": "Claude Code IAM", "url": "https://docs.anthropic.com/zh-CN/docs/claude-code/iam"},
                {"label": "Anthropic 模型列表", "url": "https://docs.anthropic.com/en/docs/about-claude/models/overview"},
            ],
            "local_auth_paths": [
                "~/.claude.json",
                "~/.claude/settings.json",
                "~/.claude/.credentials.json",
                "C:/ProgramData/ClaudeCode/managed-settings.json",
                "$WECHAT_BOT_CLAUDE_KEYCHAIN_TARGETS",
            ],
            "notes": [
                "官方文档已经明确说明 ~/.claude.json 会保存 OAuth 会话及其相关状态。",
                "官方文档说明 Linux / Windows 的凭据会放在 ~/.claude/.credentials.json（或 $CLAUDE_CONFIG_DIR）下。",
                "Windows 的托管设置文档路径是 ProgramData，而不是 Program Files。",
                "系统钥匙串探测在 Windows 上仍只作为保守发现提示；官方文档明确提到了 macOS Keychain 存储。",
                "当 Claude Code 暴露 apiKeyHelper 或可同步的本机 Claude API 凭据缓存时，本机跟随可以直接用于 Anthropic API 运行时。",
                "仅订阅态 Claude.ai OAuth 目前仍保守建模为跟随发现，不默认投射到 Anthropic API 运行时。",
            ],
        },
    ),
    "kimi": _provider(
        id="kimi",
        label="Kimi / Moonshot",
        description="支持 Moonshot API Key，以及 Kimi Code 本机 OAuth 凭据探测与同步。",
        homepage_url="https://kimi.com/",
        docs_url="https://www.kimi.com/code/docs/en/kimi-cli/guides/getting-started.html",
        api_key_url="https://platform.moonshot.cn/console/api-keys",
        default_base_url="https://api.moonshot.cn/v1",
        default_model="kimi-k2-turbo-preview",
        auth_methods=(
            AuthMethodDefinition(
                id="kimi_code_local",
                type=AuthMethodType.LOCAL_IMPORT,
                label="Kimi Code 本机登录",
                description="跟随 ~/.kimi/ 下的 Kimi Code 浏览器登录态和本机凭据缓存。",
                experimental=True,
                runtime_supported=True,
                supports_browser_flow=True,
                supports_local_discovery=True,
                supports_follow_mode=True,
                supports_import_copy=True,
                supports_multi_account=True,
                supports_refresh=True,
                auth_provider_id="kimi_code_local",
                legacy_provider_id="kimi_code_local",
                browser_entry_url="https://kimi.com/",
                browser_flow_kind="cli_browser_login",
                connect_label="打开 Kimi Code 登录页",
                follow_label="跟随本机 Kimi 登录",
                import_label="导入本机 Kimi 登录副本",
                metadata={
                    "official_type": "local_import",
                    "local_storage_paths": ["~/.kimi/config.toml", "~/.kimi/credentials/*.json"],
                    "recommended_base_url": "https://api.kimi.com/coding/v1",
                    "recommended_model": "kimi-k2-turbo-preview",
                    "supports_source_logout": False,
                },
            ),
            AuthMethodDefinition(
                id="kimi_code_oauth",
                type=AuthMethodType.OAUTH,
                label="Kimi Code OAuth",
                description="执行 Kimi Code CLI 使用的浏览器 OAuth 流程，并同步生成的本机凭据。",
                experimental=True,
                runtime_supported=True,
                supports_browser_flow=True,
                supports_local_discovery=True,
                supports_follow_mode=True,
                supports_import_copy=True,
                supports_multi_account=True,
                supports_refresh=True,
                auth_provider_id="kimi_code_local",
                legacy_provider_id="kimi_code_local",
                browser_entry_url="https://kimi.com/",
                browser_flow_kind="standard_oauth",
                connect_label="通过 Kimi OAuth 登录",
                follow_label="使用本机 Kimi OAuth",
                import_label="导入 Kimi OAuth 副本",
                metadata={
                    "official_type": "oauth",
                    "local_storage_paths": ["~/.kimi/credentials/*.json", "~/.kimi/config.toml"],
                    "recommended_base_url": "https://api.kimi.com/coding/v1",
                    "recommended_model": "kimi-k2-turbo-preview",
                    "supports_source_logout": False,
                },
            ),
            AuthMethodDefinition(
                id="api_key",
                type=AuthMethodType.API_KEY,
                label="Moonshot API Key",
                description="Moonshot / Kimi API Key。",
                api_key_url="https://platform.moonshot.cn/console/api-keys",
                metadata={
                    "official_type": "api_key",
                    "recommended_base_url": "https://api.moonshot.cn/v1",
                    "recommended_model": "kimi-k2-turbo-preview",
                },
            ),
        ),
        default_auth_order=("kimi_code_local", "kimi_code_oauth", "api_key"),
        supported_models=(
            "kimi-k2-turbo-preview",
            "kimi-k2-0905-preview",
            "kimi-k2-thinking-turbo",
            "kimi-thinking-preview",
            "kimi-latest",
        ),
        tags=("extension", "api", "oauth", "cli"),
        metadata={
            "research_summary": "Kimi Code CLI 官方会把运行时数据保存在 ~/.kimi/ 下，包括 config.toml 和 credentials/ 里的 OAuth 凭据。",
            "last_reviewed": "2026-03-26",
            "official_sources": [
                {"label": "Moonshot Console", "url": "https://platform.moonshot.cn/console/api-keys"},
                {"label": "Kimi Code 数据位置", "url": "https://moonshotai.github.io/kimi-cli/en/configuration/data-locations.html"},
                {"label": "Kimi Code Provider 与模型", "url": "https://moonshotai.github.io/kimi-cli/en/configuration/providers.html"},
                {"label": "Kimi K2 0905 更新说明", "url": "https://platform.moonshot.cn/blog/posts/kimi-k2-0905"},
            ],
            "local_auth_paths": ["~/.kimi/config.toml", "~/.kimi/credentials/*.json", "$KIMI_SHARE_DIR", "$WECHAT_BOT_KIMI_KEYCHAIN_TARGETS"],
            "notes": [
                "Kimi Code CLI 会在执行 /login 之后把 OAuth 凭据保存在 ~/.kimi/credentials/ 下。",
                "本机跟随会和直接使用 Moonshot API Key 分开实现。",
                "当前运行时跟随优先读取 ~/.kimi/config.toml 里的 provider 配置，必要时再退回 OAuth 凭据缓存。",
                "系统钥匙串探测属于框架层面的发现提示，暂时不视为正式的运行时契约。",
            ],
        },
    ),
    "zhipu": _provider(
        id="zhipu",
        label="GLM / 智谱",
        description="为 BigModel API Key 和未来的本机登录同步预留扩展位。",
        homepage_url="https://open.bigmodel.cn/",
        docs_url="https://open.bigmodel.cn/dev/howuse/introduction",
        api_key_url="https://open.bigmodel.cn/usercenter/apikeys",
        default_base_url="https://open.bigmodel.cn/api/paas/v4",
        default_model="glm-5",
        auth_methods=(
            AuthMethodDefinition(
                id="api_key",
                type=AuthMethodType.API_KEY,
                label="GLM API Key",
                description="BigModel API Key。",
                api_key_url="https://open.bigmodel.cn/usercenter/apikeys",
                metadata={
                    "official_type": "api_key",
                    "recommended_base_url": "https://open.bigmodel.cn/api/paas/v4",
                    "recommended_model": "glm-5",
                },
            ),
        ),
        default_auth_order=("api_key",),
        supported_models=("glm-5", "glm-4.7", "glm-4.6", "glm-4.5-air"),
        tags=("extension", "api"),
        metadata={
            "last_reviewed": "2026-03-26",
            "official_sources": [
                {"label": "BigModel tool streaming", "url": "https://docs.bigmodel.cn/cn/guide/capabilities/stream-tool"},
            ],
        },
    ),
    "minimax": _provider(
        id="minimax",
        label="MiniMax",
        description="为 MiniMax API Key 和未来的编码计划本机登录同步预留扩展位。",
        homepage_url="https://www.minimax.io/",
        docs_url="https://www.minimax.io/platform/document/ChatCompletion_v2",
        api_key_url="https://platform.minimax.io/",
        default_base_url="https://api.minimax.io/v1",
        default_model="MiniMax-M2.5",
        auth_methods=(
            AuthMethodDefinition(
                id="api_key",
                type=AuthMethodType.API_KEY,
                label="MiniMax API Key",
                description="MiniMax 平台 API Key。",
                api_key_url="https://platform.minimax.io/",
                metadata={
                    "official_type": "api_key",
                    "recommended_base_url": "https://api.minimax.io/v1",
                    "recommended_model": "MiniMax-M2.5",
                },
            ),
        ),
        default_auth_order=("api_key",),
        supported_models=("MiniMax-M2.5", "MiniMax-M2.1", "MiniMax-M2", "MiniMax-Text-01"),
        tags=("extension", "api"),
        metadata={
            "last_reviewed": "2026-03-26",
            "official_sources": [
                {"label": "MiniMax text models", "url": "https://www.minimax.io/models/text"},
                {"label": "MiniMax pricing", "url": "https://www.minimax.io/pricing"},
            ],
        },
    ),
    "deepseek": _provider(
        id="deepseek",
        label="DeepSeek",
        description="当前以 API Key 为主，并为后续生态集成预留扩展空间。",
        homepage_url="https://www.deepseek.com/",
        docs_url="https://api-docs.deepseek.com/",
        api_key_url="https://platform.deepseek.com/api_keys",
        default_base_url="https://api.deepseek.com/v1",
        default_model="deepseek-chat",
        auth_methods=(
            AuthMethodDefinition(
                id="api_key",
                type=AuthMethodType.API_KEY,
                label="DeepSeek API Key",
                description="DeepSeek 平台 API Key。",
                api_key_url="https://platform.deepseek.com/api_keys",
                metadata={
                    "official_type": "api_key",
                    "recommended_base_url": "https://api.deepseek.com/v1",
                    "recommended_model": "deepseek-chat",
                },
            ),
        ),
        default_auth_order=("api_key",),
        supported_models=("deepseek-chat", "deepseek-reasoner"),
        tags=("api",),
    ),
}


def _build_dynamic_provider(definition: Dict[str, object]) -> Optional[ProviderDefinition]:
    provider_id = str(definition.get("id") or "").strip().lower()
    if not provider_id or provider_id in _REGISTRY:
        return None
    label = str(definition.get("label") or provider_id).strip() or provider_id
    base_url = str(definition.get("base_url") or "").strip()
    default_model = str(definition.get("default_model") or "").strip()
    api_key_url = str(definition.get("api_key_url") or "").strip()
    models = tuple(
        str(item).strip()
        for item in (definition.get("models") or [])
        if str(item).strip()
    )
    return _provider(
        id=provider_id,
        label=label,
        description=f"{label} 当前通过 API Key 提供运行时访问。",
        homepage_url=api_key_url,
        docs_url=api_key_url,
        api_key_url=api_key_url,
        default_base_url=base_url,
        default_model=default_model,
        auth_methods=(
            AuthMethodDefinition(
                id="api_key",
                type=AuthMethodType.API_KEY,
                label="API Key",
                description=f"为 {label} 配置一组 API Key。",
                api_key_url=api_key_url,
            ),
        ),
        default_auth_order=("api_key",),
        supported_models=models,
        tags=("dynamic", "api"),
        metadata={
            "research_summary": f"{label} 当前作为共享目录里的动态 API Key 服务方接入。",
            "last_reviewed": "2026-03-25",
        },
    )


def _with_dynamic_registry() -> Dict[str, ProviderDefinition]:
    merged = dict(_REGISTRY)
    try:
        catalog = get_model_catalog()
    except Exception:
        return merged
    for provider in catalog.get("providers") or []:
        if not isinstance(provider, dict):
            continue
        dynamic = _build_dynamic_provider(provider)
        if dynamic is not None:
            merged[dynamic.id] = dynamic
    return merged


def get_provider_registry() -> Dict[str, ProviderDefinition]:
    return _with_dynamic_registry()


def list_provider_definitions() -> list[ProviderDefinition]:
    return list(_with_dynamic_registry().values())


def get_provider_definition(provider_id: str | None) -> Optional[ProviderDefinition]:
    key = str(provider_id or "").strip().lower()
    if not key:
        return None
    return _with_dynamic_registry().get(key)


def get_provider_method(provider_id: str | None, method_id: str | None) -> Optional[AuthMethodDefinition]:
    provider = get_provider_definition(provider_id)
    if provider is None:
        return None
    wanted = str(method_id or "").strip().lower()
    if not wanted:
        return None
    for method in provider.auth_methods:
        if method.id == wanted:
            return method
    return None
