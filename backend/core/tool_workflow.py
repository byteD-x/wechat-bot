"""Controlled tool workflow execution for local admin APIs."""

from __future__ import annotations

import time
from typing import Any, Awaitable, Callable

from backend.core.config_audit import build_config_audit
from backend.utils.config import resolve_system_prompt


MAX_WORKFLOW_STEPS = 8
MAX_STEP_PAYLOAD_CHARS = 12000


class ToolWorkflowError(ValueError):
    pass


class ControlledToolWorkflowService:
    """Execute an explicit sequence of whitelisted internal tools."""

    def __init__(
        self,
        *,
        config_loader: Callable[[], Any],
        readiness_loader: Callable[[], Awaitable[dict[str, Any]]],
    ) -> None:
        self._config_loader = config_loader
        self._readiness_loader = readiness_loader

    async def run(self, steps: list[dict[str, Any]], *, dry_run: bool = False) -> dict[str, Any]:
        if not isinstance(steps, list) or not steps:
            raise ToolWorkflowError("steps is required")
        if len(steps) > MAX_WORKFLOW_STEPS:
            raise ToolWorkflowError(f"steps cannot exceed {MAX_WORKFLOW_STEPS}")

        trace: list[dict[str, Any]] = []
        success = True
        for index, raw_step in enumerate(steps, start=1):
            step = raw_step if isinstance(raw_step, dict) else {}
            tool = str(step.get("tool") or "").strip()
            payload = step.get("payload") if isinstance(step.get("payload"), dict) else {}
            if not tool:
                raise ToolWorkflowError("step.tool is required")
            if len(str(payload)) > MAX_STEP_PAYLOAD_CHARS:
                raise ToolWorkflowError("step payload is too large")

            started = time.perf_counter()
            item = {"index": index, "tool": tool, "status": "ok", "duration_ms": 0.0}
            try:
                if dry_run:
                    item["status"] = "skipped"
                    item["output"] = {"dry_run": True}
                else:
                    item["output"] = await self._run_tool(tool, payload)
            except Exception as exc:
                success = False
                item["status"] = "error"
                item["error"] = str(exc)
            finally:
                item["duration_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
                trace.append(item)
            if item["status"] == "error" and step.get("continue_on_error") is not True:
                break

        return {"success": success, "trace": trace}

    async def _run_tool(self, tool: str, payload: dict[str, Any]) -> dict[str, Any]:
        if tool == "config_audit":
            snapshot = self._config_loader()
            config = getattr(snapshot, "config", {}) or {}
            override_path = str(payload.get("override_path") or "")
            return build_config_audit(config, override_path=override_path)

        if tool == "readiness_check":
            report = await self._readiness_loader()
            return report if isinstance(report, dict) else {"success": False, "message": "invalid readiness result"}

        if tool == "prompt_preview":
            snapshot = self._config_loader()
            bot_cfg = dict(getattr(snapshot, "bot", {}) or {})
            bot_overrides = payload.get("bot")
            if isinstance(bot_overrides, dict):
                bot_cfg.update(bot_overrides)
            sample = payload.get("sample") if isinstance(payload.get("sample"), dict) else {}
            event = type(
                "PromptPreviewEvent",
                (),
                {
                    "chat_name": str(sample.get("chat_name") or "preview_contact"),
                    "sender": str(sample.get("sender") or "preview_user"),
                    "content": str(sample.get("message") or ""),
                    "is_group": bool(sample.get("is_group", False)),
                },
            )()
            user_profile = None
            if bot_cfg.get("profile_inject_in_prompt") or str(sample.get("contact_prompt") or "").strip():
                user_profile = {
                    "nickname": str(sample.get("nickname") or event.sender),
                    "relationship": str(sample.get("relationship") or "friend"),
                    "message_count": int(sample.get("message_count") or 12),
                    "profile_summary": str(sample.get("profile_summary") or "").strip(),
                    "contact_prompt": str(sample.get("contact_prompt") or "").strip(),
                }
            prompt = resolve_system_prompt(event, bot_cfg, user_profile, None, [])
            return {
                "prompt": prompt,
                "summary": {
                    "chars": len(prompt),
                    "lines": len([line for line in prompt.splitlines() if line.strip()]),
                },
            }

        raise ToolWorkflowError(f"unsupported tool: {tool}")
