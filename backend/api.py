"""
微信AI助手 - Quart 异步 API 服务

为 Electron 客户端提供后端 API 接口。
使用 Quart（Flask 异步版本）实现统一的 asyncio 事件循环。
"""

from quart import Quart, jsonify, request, make_response
from quart_cors import cors
import logging
import os
import asyncio
from datetime import datetime
from types import SimpleNamespace
from urllib.parse import urlsplit, urlunsplit

import httpx

from .bot_manager import get_bot_manager
from backend.core.config_audit import (
    build_config_audit,
    build_reload_plan,
    diff_config_paths,
    get_effect_for_path,
)
from backend.core.config_probe import probe_config
from backend.core.config_service import get_config_service
from backend.core.cost_analytics import CostAnalyticsService
from backend.model_catalog import (
    get_model_catalog,
    infer_provider_id,
    merge_provider_defaults,
)
from backend.shared_config import get_app_config_path
from backend.utils.logging import (
    setup_logging,
    get_logging_settings,
    configure_http_access_log_filters,
)
from backend.utils.config import resolve_system_prompt

# 配置日志
config_service = get_config_service()
_initial_snapshot = config_service.get_snapshot()
level, log_file, max_bytes, backup_count, format_type = get_logging_settings(
    _initial_snapshot.config
)
setup_logging(level, log_file, max_bytes, backup_count, format_type)

logger = logging.getLogger(__name__)

API_TOKEN = str(os.environ.get("WECHAT_BOT_API_TOKEN") or "").strip()
configure_http_access_log_filters()

_REMOVED_PUBLIC_BOT_FIELDS = {
    "reply_timeout_fallback_text",
    "stream_buffer_chars",
    "stream_chunk_max_chars",
    "stream_reply",
}

_REMOVED_PUBLIC_AGENT_FIELDS = {
    "streaming_enabled",
}


def _is_local_request() -> bool:
    try:
        host = str(getattr(request, "host", "") or "")
    except Exception:
        host = ""
    host_lower = host.lower()
    return host_lower.startswith("127.0.0.1") or host_lower.startswith("localhost")


# 创建 Quart 应用
app = Quart(__name__)
app = cors(
    app,
    allow_origin="*",
    allow_headers=["Content-Type", "X-Api-Token"],
    allow_methods=["GET", "POST", "OPTIONS"],
)

# Security note: API is intended for local Electron clients only.
# - Run server defaults bind to 127.0.0.1.
# - When WECHAT_BOT_API_TOKEN is set, all /api/* endpoints require it.


@app.before_request
async def _refresh_and_enforce_local_api_token():
    # Keep token in sync for long-running debug reloader sessions.
    global API_TOKEN
    API_TOKEN = str(os.environ.get("WECHAT_BOT_API_TOKEN") or "").strip()

    if request.method == "OPTIONS":
        return None

    path = str(getattr(request, "path", "") or "")
    if not path.startswith("/api/"):
        return None

    if not _is_local_request():
        return jsonify({"success": False, "message": "forbidden"}), 403

    if not API_TOKEN:
        return None

    header_token = str(request.headers.get("X-Api-Token") or "").strip()
    query_token = str(request.args.get("token") or "").strip()
    if header_token == API_TOKEN or query_token == API_TOKEN:
        return None

    return jsonify({"success": False, "message": "unauthorized"}), 401


# 获取 BotManager 实例
manager = get_bot_manager()
cost_service = CostAnalyticsService()


def _mask_preset(preset: dict) -> dict:
    masked = merge_provider_defaults(preset)
    masked["provider_id"] = infer_provider_id(
        provider_id=masked.get("provider_id"),
        preset_name=masked.get("name"),
        base_url=masked.get("base_url"),
        model=masked.get("model"),
    )

    key = masked.get("api_key", "")
    allow_empty = bool(masked.get("allow_empty_key", False))
    if allow_empty:
        # 不需要 Key 的服务（如 Ollama）无需额外配置，但也不标记为“已配 Key”
        masked["api_key_configured"] = False
        masked["api_key_masked"] = ""
    elif key and not key.startswith("YOUR_"):
        masked["api_key_configured"] = True
        masked["api_key_masked"] = (
            key[:8] + "****" + key[-4:] if len(key) > 12 else "****"
        )
    else:
        masked["api_key_configured"] = False
        masked["api_key_masked"] = ""
    masked["api_key_required"] = not allow_empty

    masked.pop("api_key", None)
    return masked


def _build_config_payload(snapshot=None) -> dict:
    active_snapshot = snapshot or config_service.get_snapshot()
    config_dict = active_snapshot.config

    api_cfg = config_dict.get("api", {})
    bot_cfg = dict(config_dict.get("bot", {}))
    agent_cfg = dict(config_dict.get("agent", {}))
    presets = []
    for preset in api_cfg.get("presets", []):
        presets.append(_mask_preset(preset))

    api_cfg_safe = api_cfg.copy()
    api_cfg_safe["presets"] = presets
    for field in _REMOVED_PUBLIC_BOT_FIELDS:
        bot_cfg.pop(field, None)
    for field in _REMOVED_PUBLIC_AGENT_FIELDS:
        agent_cfg.pop(field, None)
    langsmith_key = str(agent_cfg.get("langsmith_api_key") or "").strip()
    agent_cfg["langsmith_api_key_configured"] = bool(langsmith_key)
    agent_cfg.pop("langsmith_api_key", None)
    return {
        "api": api_cfg_safe,
        "bot": bot_cfg,
        "logging": config_dict.get("logging", {}),
        "agent": agent_cfg,
        "services": config_dict.get("services", {}),
    }


def _normalize_ollama_tags_url(base_url: str) -> str:
    raw = str(base_url or "http://127.0.0.1:11434/v1").strip()
    if not raw:
        raw = "http://127.0.0.1:11434/v1"

    parsed = urlsplit(raw)
    scheme = parsed.scheme or "http"
    netloc = parsed.netloc or parsed.path
    path = parsed.path if parsed.netloc else ""
    path = path.rstrip("/")
    if path.endswith("/v1"):
        path = path[:-3]
    path = f"{path}/api/tags" if path else "/api/tags"
    return urlunsplit((scheme, netloc, path, "", ""))


def _fetch_ollama_models_sync(base_url: str) -> list[str]:
    tags_url = _normalize_ollama_tags_url(base_url)
    resp = httpx.get(tags_url, timeout=3.0)
    resp.raise_for_status()
    data = resp.json()
    models = data.get("models") or []
    names: list[str] = []
    for model in models:
        if not isinstance(model, dict):
            continue
        name = str(model.get("model") or model.get("name") or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def _get_cost_filters() -> dict:
    return {
        "period": request.args.get("period", "30d", type=str),
        "provider_id": request.args.get("provider_id", "", type=str),
        "model": request.args.get("model", "", type=str),
        "only_priced": str(request.args.get("only_priced", "false")).strip().lower() in {"1", "true", "yes", "on"},
        "include_estimated": str(request.args.get("include_estimated", "true")).strip().lower() in {"1", "true", "yes", "on"},
    }


# ═══════════════════════════════════════════════════════════════════════════════
#                               API 路由
# ═══════════════════════════════════════════════════════════════════════════════


@app.route("/api/status", methods=["GET"])
async def get_status():
    """获取机器人状态"""
    return jsonify(manager.get_status())


@app.route("/api/ping", methods=["GET"])
async def ping():
    """轻量探活接口，仅用于确认 Web API 已就绪。"""
    return jsonify({"success": True, "service_running": True})


@app.route("/api/metrics", methods=["GET"])
async def get_metrics():
    """Export Prometheus-style runtime metrics."""
    return app.response_class(
        manager.export_metrics(),
        mimetype="text/plain; version=0.0.4; charset=utf-8",
    )


@app.route("/api/events")
async def sse_events():
    """SSE 事件流"""
    response = await make_response(
        manager.event_generator(),
        {
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
    response.timeout = None
    return response


@app.route("/api/start", methods=["POST"])
async def start_bot():
    """启动机器人"""
    result = await manager.start()
    return jsonify(result)


@app.route("/api/stop", methods=["POST"])
async def stop_bot():
    """停止机器人"""
    result = await manager.stop()
    return jsonify(result)


@app.route("/api/growth/start", methods=["POST"])
async def start_growth():
    """启动独立成长任务。"""
    result = await manager.start_growth()
    return jsonify(result)


@app.route("/api/growth/stop", methods=["POST"])
async def stop_growth():
    """停止独立成长任务。"""
    result = await manager.stop_growth()
    return jsonify(result)


@app.route("/api/growth/tasks", methods=["GET"])
async def list_growth_tasks():
    """获取成长任务队列摘要。"""
    result = await manager.list_growth_tasks()
    return jsonify(result)


@app.route("/api/growth/tasks/<task_type>/clear", methods=["POST"])
async def clear_growth_task(task_type: str):
    """清空指定类型的成长任务队列。"""
    result = await manager.clear_growth_task(task_type)
    return jsonify(result), (200 if result.get("success") else 400)


@app.route("/api/growth/tasks/<task_type>/run", methods=["POST"])
async def run_growth_task(task_type: str):
    """立即执行指定类型的成长任务。"""
    result = await manager.run_growth_task_now(task_type)
    return jsonify(result), (200 if result.get("success") else 400)


@app.route("/api/growth/tasks/<task_type>/pause", methods=["POST"])
async def pause_growth_task(task_type: str):
    """暂停指定类型的成长任务。"""
    result = await manager.pause_growth_task(task_type)
    return jsonify(result), (200 if result.get("success") else 400)


@app.route("/api/growth/tasks/<task_type>/resume", methods=["POST"])
async def resume_growth_task(task_type: str):
    """恢复指定类型的成长任务。"""
    result = await manager.resume_growth_task(task_type)
    return jsonify(result), (200 if result.get("success") else 400)


@app.route("/api/pause", methods=["POST"])
async def pause_bot():
    """暂停机器人"""
    data = await request.get_json(silent=True) or {}
    reason = str(data.get("reason") or "用户暂停").strip() or "用户暂停"
    result = await manager.pause(reason)
    return jsonify(result)


@app.route("/api/resume", methods=["POST"])
async def resume_bot():
    """恢复机器人"""
    result = await manager.resume()
    return jsonify(result)


@app.route("/api/restart", methods=["POST"])
async def restart_bot():
    """重启机器人"""
    result = await manager.restart()
    return jsonify(result)


@app.route("/api/recover", methods=["POST"])
async def recover_bot():
    """一键恢复机器人"""
    result = await manager.recover()
    return jsonify(result)


@app.route("/api/messages", methods=["GET"])
async def get_messages():
    """获取消息历史"""
    try:
        limit = request.args.get("limit", 50, type=int)
        offset = request.args.get("offset", 0, type=int)
        chat_id = request.args.get("chat_id", "", type=str)
        keyword = request.args.get("keyword", "", type=str)

        # 使用共享的 MemoryManager 实例
        mem_mgr = manager.get_memory_manager()

        page = await mem_mgr.get_message_page(
            limit=limit,
            offset=offset,
            chat_id=chat_id,
            keyword=keyword,
        )
        chats = await mem_mgr.list_chat_summaries()

        return jsonify(
            {
                "success": True,
                "messages": page["messages"],
                "total": page["total"],
                "limit": page["limit"],
                "offset": page["offset"],
                "has_more": page["has_more"],
                "chats": chats,
            }
        )
    except Exception as e:
        logger.error(f"获取消息失败: {e}")
        return jsonify({"success": False, "message": f"获取消息失败: {str(e)}"})


@app.route("/api/contact_profile", methods=["GET"])
async def get_contact_profile():
    """获取指定联系人的成长画像与 Prompt 资产。"""
    try:
        chat_id = str(request.args.get("chat_id", "", type=str) or "").strip()
        if not chat_id:
            return jsonify({"success": False, "message": "缺少 chat_id"}), 400

        mem_mgr = manager.get_memory_manager()
        profile = await mem_mgr.get_contact_profile(chat_id)
        return jsonify({"success": True, "profile": profile})
    except Exception as e:
        logger.error(f"获取联系人画像失败: {e}")
        return jsonify({"success": False, "message": f"获取联系人画像失败: {str(e)}"})


@app.route("/api/contact_prompt", methods=["POST"])
async def save_contact_prompt():
    """保存联系人专属 Prompt。"""
    try:
        data = await request.get_json(silent=True) or {}
        chat_id = str(data.get("chat_id") or "").strip()
        contact_prompt = str(data.get("contact_prompt") or "").strip()
        if not chat_id:
            return jsonify({"success": False, "message": "缺少 chat_id"}), 400
        if not contact_prompt:
            return jsonify({"success": False, "message": "联系人 Prompt 不能为空"}), 400

        mem_mgr = manager.get_memory_manager()
        profile = await mem_mgr.save_contact_prompt(
            chat_id,
            contact_prompt,
            source="user_edit",
        )
        return jsonify({"success": True, "profile": profile})
    except Exception as e:
        logger.error(f"保存联系人 Prompt 失败: {e}")
        return jsonify({"success": False, "message": f"保存联系人 Prompt 失败: {str(e)}"})


@app.route("/api/send", methods=["POST"])
async def send_message():
    """发送消息"""
    try:
        data = await request.get_json()
        target = data.get("target")
        content = data.get("content")

        if not target or not content:
            return jsonify({"success": False, "message": "缺少目标或内容"})

        result = await manager.send_message(target, content)
        return jsonify(result)
    except Exception as e:
        logger.error(f"发送消息异常: {e}")
        return jsonify({"success": False, "message": f"发送异常: {str(e)}"})


@app.route("/api/usage", methods=["GET"])
async def get_usage():
    """获取使用统计"""
    try:
        stats = manager.get_usage()
        return jsonify({"success": True, "stats": stats})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@app.route("/api/pricing", methods=["GET"])
async def get_pricing():
    """返回当前价格目录快照。"""
    try:
        snapshot = await cost_service.get_pricing_snapshot()
        return jsonify({"success": True, **snapshot})
    except Exception as e:
        logger.error(f"鑾峰彇浠锋牸鐩綍澶辫触: {e}")
        return jsonify({"success": False, "message": f"鑾峰彇浠锋牸鐩綍澶辫触: {str(e)}"})


@app.route("/api/pricing/refresh", methods=["POST"])
async def refresh_pricing():
    """手动刷新价格目录。"""
    try:
        data = await request.get_json(silent=True) or {}
        providers = data.get("providers")
        payload = await cost_service.refresh_pricing(
            providers=providers if isinstance(providers, list) else None
        )
        return jsonify(payload)
    except Exception as e:
        logger.error(f"鍒锋柊浠锋牸鐩綍澶辫触: {e}")
        return jsonify({"success": False, "message": f"鍒锋柊浠锋牸鐩綍澶辫触: {str(e)}"})


@app.route("/api/costs/summary", methods=["GET"])
async def get_costs_summary():
    """返回成本总览和模型聚合。"""
    try:
        snapshot = config_service.get_snapshot()
        payload = await cost_service.get_summary(
            manager.get_memory_manager(),
            snapshot.config,
            **_get_cost_filters(),
        )
        return jsonify(payload)
    except Exception as e:
        logger.error(f"鑾峰彇鎴愭湰鎬昏澶辫触: {e}")
        return jsonify({"success": False, "message": f"鑾峰彇鎴愭湰鎬昏澶辫触: {str(e)}"})


@app.route("/api/costs/sessions", methods=["GET"])
async def get_cost_sessions():
    """返回按会话分组的成本摘要。"""
    try:
        snapshot = config_service.get_snapshot()
        payload = await cost_service.get_sessions(
            manager.get_memory_manager(),
            snapshot.config,
            **_get_cost_filters(),
        )
        return jsonify(payload)
    except Exception as e:
        logger.error(f"鑾峰彇浼氳瘽鎴愭湰澶辫触: {e}")
        return jsonify({"success": False, "message": f"鑾峰彇浼氳瘽鎴愭湰澶辫触: {str(e)}"})


@app.route("/api/costs/session_details", methods=["GET"])
async def get_cost_session_details():
    """返回单个会话的逐条回复成本。"""
    try:
        chat_id = str(request.args.get("chat_id", "", type=str) or "").strip()
        if not chat_id:
            return jsonify({"success": False, "message": "缂哄皯 chat_id"}), 400
        snapshot = config_service.get_snapshot()
        payload = await cost_service.get_session_details(
            manager.get_memory_manager(),
            snapshot.config,
            chat_id=chat_id,
            **_get_cost_filters(),
        )
        return jsonify(payload)
    except Exception as e:
        logger.error(f"鑾峰彇浼氳瘽鎴愭湰鏄庣粏澶辫触: {e}")
        return jsonify({"success": False, "message": f"鑾峰彇浼氳瘽鎴愭湰鏄庣粏澶辫触: {str(e)}"})


@app.route("/api/model_catalog", methods=["GET"])
async def get_model_catalog_api():
    """获取前端使用的模型目录"""
    try:
        return jsonify({"success": True, **get_model_catalog()})
    except Exception as e:
        logger.error(f"获取模型目录失败: {e}")
        return jsonify({"success": False, "message": f"获取模型目录失败: {str(e)}"})


@app.route("/api/ollama/models", methods=["GET"])
async def get_ollama_models():
    """获取本地 Ollama 已安装模型列表"""
    try:
        base_url = request.args.get("base_url", "http://127.0.0.1:11434/v1", type=str)
        models = await asyncio.to_thread(_fetch_ollama_models_sync, base_url)
        return jsonify({"success": True, "models": models, "base_url": base_url})
    except Exception as e:
        logger.warning(f"获取 Ollama 模型列表失败: {e}")
        return jsonify(
            {
                "success": False,
                "message": f"获取 Ollama 模型列表失败: {str(e)}",
                "models": [],
            }
        )


@app.route("/api/config", methods=["GET"])
async def get_config():
    """获取配置"""
    try:
        snapshot = config_service.get_snapshot()
        response = {"success": True, **_build_config_payload(snapshot)}
        return jsonify(response)
    except Exception as e:
        logger.error(f"获取配置失败: {e}")
        return jsonify({"success": False, "message": f"获取配置失败: {str(e)}"})


@app.route("/api/config/audit", methods=["GET"])
async def get_config_audit():
    """返回当前生效配置的审计信息。"""
    try:
        snapshot = config_service.get_snapshot()
        loaded_at_raw = getattr(snapshot, "loaded_at", None)
        if hasattr(loaded_at_raw, "isoformat"):
            loaded_at = loaded_at_raw.isoformat()
        elif loaded_at_raw:
            loaded_at = datetime.fromtimestamp(float(loaded_at_raw)).isoformat()
        else:
            loaded_at = None
        audit = build_config_audit(
            snapshot.config,
            override_path=get_app_config_path(),
        )
        return jsonify(
            {
                "success": True,
                "version": snapshot.version,
                "loaded_at": loaded_at,
                "audit": audit,
            }
        )
    except Exception as e:
        logger.error(f"配置审计失败: {e}")
        return jsonify({"success": False, "message": f"配置审计失败: {str(e)}"})


@app.route("/api/config", methods=["POST"])
async def save_config():
    """保存配置覆写"""
    try:
        data = await request.get_json()
        current_snapshot = config_service.get_snapshot()
        current_config = current_snapshot.to_dict()
        requested_active = None
        force_ai_reload = False
        strict_active_preset = False
        if isinstance(data, dict):
            api_updates = data.get("api")
            if isinstance(api_updates, dict):
                force_ai_reload = True
                requested_active = (
                    str(api_updates.get("active_preset") or "").strip() or None
                )
                strict_active_preset = True

        # 确保目录存在
        config_path = getattr(manager, "config_path", None)
        if not isinstance(config_path, str) or not config_path.strip():
            config_path = None

        snapshot = await asyncio.to_thread(
            config_service.save_effective_config,
            data or {},
            config_path=config_path,
            source="api_override",
        )
        effective_config = snapshot.to_dict()
        changed_paths = diff_config_paths(current_config, effective_config)
        reload_plan = build_reload_plan(changed_paths)
        if changed_paths:
            force_ai_reload = force_ai_reload or any(
                get_effect_for_path(path).get("component") == "ai_client"
                for path in changed_paths
            )

        # 🔍 检测模型切换并输出高亮日志
        new_api_cfg = snapshot.api
        new_active = new_api_cfg.get("active_preset")

        if new_active:
            preset_info = next(
                (p for p in new_api_cfg.get("presets", []) if p["name"] == new_active),
                {},
            )
            model_name = preset_info.get("model", "Unknown")
            alias = preset_info.get("alias", "")

            logger.info("\n" + "═" * 50)
            logger.info(f"✨ 模型配置已更新 | 当前预设: {new_active}")
            logger.info(f"📦 模型: {model_name} | 👤 别名: {alias}")
            logger.info("═" * 50 + "\n")

        runtime_apply = None
        if manager.is_running and manager.bot:
            runtime_apply = await manager.reload_runtime_config(
                new_config=effective_config,
                changed_paths=changed_paths,
                force_ai_reload=force_ai_reload,
                strict_active_preset=strict_active_preset,
            )
            if requested_active and runtime_apply.get("success"):
                runtime_apply["requested_preset"] = requested_active

        return jsonify(
            {
                "success": True,
                "config": _build_config_payload(snapshot),
                "changed_paths": changed_paths,
                "reload_plan": reload_plan,
                "runtime_apply": runtime_apply,
                "default_config_synced": True,
                "default_config_sync_message": "默认配置文件已同步更新（敏感字段仍保留在安全来源）",
            }
        )

    except Exception as e:
        logger.error(f"保存配置失败: {e}")
        return jsonify({"success": False, "message": f"保存失败: {str(e)}"})


@app.route("/api/test_connection", methods=["POST"])
async def test_connection():
    """测试 LLM 连接"""
    try:
        data = await request.get_json(silent=True) or {}
        preset_name = str(data.get("preset_name") or "").strip()
        patch = data.get("patch") if isinstance(data.get("patch"), dict) else {}
        snapshot = config_service.get_snapshot()
        candidate_config = snapshot.to_dict()
        if patch:
            candidate_config = config_service._merge_patch(candidate_config, patch)
        normalized = config_service._validate_config_dict(candidate_config)
        success, resolved_preset, message = await probe_config(normalized, preset_name)
        return jsonify(
            {
                "success": success,
                "preset_name": resolved_preset,
                "message": message,
            }
        )

    except Exception as e:
        logger.error(f"连接测试异常: {e}")
        return jsonify({"success": False, "message": f"测试异常: {str(e)}"})


@app.route("/api/preview_prompt", methods=["POST"])
async def preview_prompt():
    """预览当前配置生成的系统提示词。"""
    try:
        data = await request.get_json(silent=True) or {}
        snapshot = config_service.get_snapshot()
        bot_cfg = dict(snapshot.bot)
        bot_overrides = data.get("bot")
        if isinstance(bot_overrides, dict):
            bot_cfg.update(bot_overrides)

        sample = data.get("sample") if isinstance(data.get("sample"), dict) else {}
        chat_id = str(sample.get("chat_id") or "").strip()
        event = SimpleNamespace(
            chat_name=str(sample.get("chat_name") or "预览联系人"),
            sender=str(sample.get("sender") or "预览用户"),
            content=str(sample.get("message") or ""),
            is_group=bool(sample.get("is_group", False)),
        )

        user_profile = None
        wants_contact_context = bool(chat_id or str(sample.get("contact_prompt") or "").strip())
        if bot_cfg.get("profile_inject_in_prompt") or wants_contact_context:
            user_profile = {
                "nickname": str(sample.get("nickname") or event.sender),
                "relationship": str(sample.get("relationship") or "friend"),
                "message_count": int(sample.get("message_count") or 12),
                "profile_summary": str(sample.get("profile_summary") or "").strip(),
                "contact_prompt": str(sample.get("contact_prompt") or "").strip(),
            }
            if chat_id:
                try:
                    mem_mgr = manager.get_memory_manager()
                    stored_profile = await mem_mgr.get_profile_prompt_snapshot(chat_id)
                    if isinstance(stored_profile, dict):
                        user_profile.update(
                            {
                                key: value
                                for key, value in stored_profile.items()
                                if value not in (None, "")
                            }
                        )
                except Exception:
                    pass

        emotion = None
        if bot_cfg.get("emotion_inject_in_prompt"):
            emotion = SimpleNamespace(emotion=str(sample.get("emotion") or "neutral"))

        context = []
        preview = resolve_system_prompt(event, bot_cfg, user_profile, emotion, context)
        overrides = bot_cfg.get("system_prompt_overrides") or {}

        return jsonify(
            {
                "success": True,
                "prompt": preview,
                "summary": {
                    "chars": len(preview),
                    "lines": len(
                        [line for line in preview.splitlines() if line.strip()]
                    ),
                    "override_applied": bool(
                        getattr(event, "chat_name", "") in overrides
                    ),
                    "contact_prompt_applied": bool(
                        isinstance(user_profile, dict)
                        and str(user_profile.get("contact_prompt") or "").strip()
                    ),
                    "profile_injected": bool(
                        bot_cfg.get("profile_inject_in_prompt") and user_profile
                    ),
                    "emotion_injected": emotion is not None,
                },
            }
        )
    except Exception as e:
        logger.error(f"预览提示词失败: {e}")
        return jsonify({"success": False, "message": f"预览失败: {str(e)}"})


@app.route("/api/logs", methods=["GET"])
async def get_logs():
    """获取日志"""
    try:
        snapshot = config_service.get_snapshot()
        log_file = snapshot.logging.get("file", "data/logs/bot.log")

        if not os.path.exists(log_file):
            return jsonify({"success": True, "logs": []})

        lines_count = request.args.get("lines", 500, type=int)

        def _read_logs():
            if lines_count <= 0:
                return []
            with open(log_file, "rb") as f:
                f.seek(0, os.SEEK_END)
                end = f.tell()
                buffer = b""
                lines = []
                chunk_size = 8192
                while end > 0 and len(lines) <= lines_count:
                    read_size = min(chunk_size, end)
                    end -= read_size
                    f.seek(end)
                    buffer = f.read(read_size) + buffer
                    lines = buffer.splitlines()
                decoded = [
                    line.decode("utf-8", errors="replace").strip()
                    for line in lines
                    if line.strip()
                ]
                return decoded[-lines_count:]

        logs = await asyncio.to_thread(_read_logs)
        return jsonify({"success": True, "logs": logs})
    except Exception as e:
        logger.error(f"读取日志失败: {e}")
        return jsonify({"success": False, "message": f"读取日志失败: {str(e)}"})


@app.route("/api/logs/clear", methods=["POST"])
async def clear_logs():
    """清空日志"""
    try:
        import asyncio

        snapshot = config_service.get_snapshot()
        log_file = snapshot.logging.get("file", "data/logs/bot.log")

        def _clear_file():
            # 清空文件内容
            with open(log_file, "w", encoding="utf-8") as f:
                f.write("")

        await asyncio.to_thread(_clear_file)

        return jsonify({"success": True, "message": "日志已清空"})
    except Exception as e:
        return jsonify({"success": False, "message": f"清空日志失败: {str(e)}"})


# ═══════════════════════════════════════════════════════════════════════════════
#                               启动入口
# ═══════════════════════════════════════════════════════════════════════════════


async def run_server_async(host="127.0.0.1", port=5000):
    """异步启动 API 服务"""
    logger.info(f"API 服务启动于 http://{host}:{port}")
    await app.run_task(host=host, port=port)


def run_server(host="127.0.0.1", port=5000, debug=False):
    """启动 API 服务（同步入口）"""
    import asyncio

    logger.info(f"API 服务启动于 http://{host}:{port} (Debug={debug})")

    if debug:
        # Debug 模式下使用 app.run 启用 reloader
        # 注意：这会阻塞，直到服务停止
        app.run(host=host, port=port, debug=True, use_reloader=True)
    else:
        # 生产模式使用 asyncio.run
        asyncio.run(app.run_task(host=host, port=port))


if __name__ == "__main__":
    run_server(debug=True)
