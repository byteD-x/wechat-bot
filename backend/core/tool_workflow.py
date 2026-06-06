"""Controlled tool workflow execution for local admin APIs."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from backend.core.config_audit import build_config_audit
from backend.utils.config import resolve_system_prompt


MAX_WORKFLOW_STEPS = 8
MAX_STEP_PAYLOAD_CHARS = 12000
DEFAULT_TOOL_TIMEOUT_SEC = 5.0


class ToolWorkflowError(ValueError):
    pass


class ToolRegistryError(ValueError):
    pass


class ToolSchemaValidationError(ToolWorkflowError):
    pass


class ToolPermissionError(ToolWorkflowError):
    pass


class ToolResultValidationError(ToolWorkflowError):
    pass


@dataclass(slots=True)
class ToolDefinition:
    name: str
    payload_schema: dict[str, Any]
    permission: str
    timeout_sec: float
    handler: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
    retry_count: int = 0


class ToolRegistry:
    """Small registry for explicitly allowed workflow tools."""

    def __init__(self) -> None:
        self._definitions: dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        name = str(definition.name or "").strip()
        if not name:
            raise ToolRegistryError("tool name is required")
        self._definitions[name] = definition

    def get(self, name: str) -> ToolDefinition:
        normalized = str(name or "").strip()
        definition = self._definitions.get(normalized)
        if definition is None:
            raise ToolWorkflowError(f"unsupported tool: {normalized}")
        return definition

    def names(self) -> list[str]:
        return sorted(self._definitions)


def _json_type_matches(value: Any, expected_type: str) -> bool:
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return (isinstance(value, int) or isinstance(value, float)) and not isinstance(value, bool)
    if expected_type == "null":
        return value is None
    return True


def _validate_schema_value(schema: dict[str, Any], value: Any, path: str) -> list[str]:
    errors: list[str] = []
    expected_type = schema.get("type")
    if isinstance(expected_type, str) and not _json_type_matches(value, expected_type):
        errors.append(f"{path} must be {expected_type}")
        return errors

    if expected_type != "object" or not isinstance(value, dict):
        return errors

    properties = schema.get("properties")
    if not isinstance(properties, dict):
        properties = {}

    required = schema.get("required")
    required_names = required if isinstance(required, list) else []
    for name in required_names:
        if str(name) not in value:
            errors.append(f"{path}.{name} is required")

    allow_extra = bool(schema.get("additionalProperties", True))
    if not allow_extra:
        for name in value:
            if name not in properties:
                errors.append(f"{path}.{name} is not allowed")

    for name, child_schema in properties.items():
        if name not in value or not isinstance(child_schema, dict):
            continue
        errors.extend(_validate_schema_value(child_schema, value[name], f"{path}.{name}"))
    return errors


def validate_payload(schema: dict[str, Any], payload: dict[str, Any]) -> list[str]:
    return _validate_schema_value(schema, payload, "payload")


class ControlledToolWorkflowService:
    """Execute an explicit sequence of registered internal tools."""

    def __init__(
        self,
        *,
        config_loader: Callable[[], Any],
        readiness_loader: Callable[[], Awaitable[dict[str, Any]]],
        registry: Optional[ToolRegistry] = None,
        allowed_permissions: Optional[set[str]] = None,
    ) -> None:
        self._config_loader = config_loader
        self._readiness_loader = readiness_loader
        self._registry = registry or self._build_default_registry()
        self._allowed_permissions = set(allowed_permissions or {"admin_read"})

    def _build_default_registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                name="config_audit",
                payload_schema={
                    "type": "object",
                    "properties": {
                        "override_path": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                permission="admin_read",
                timeout_sec=DEFAULT_TOOL_TIMEOUT_SEC,
                handler=self._tool_config_audit,
            )
        )
        registry.register(
            ToolDefinition(
                name="readiness_check",
                payload_schema={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
                permission="admin_read",
                timeout_sec=10.0,
                handler=self._tool_readiness_check,
                retry_count=1,
            )
        )
        registry.register(
            ToolDefinition(
                name="prompt_preview",
                payload_schema={
                    "type": "object",
                    "properties": {
                        "bot": {
                            "type": "object",
                            "additionalProperties": True,
                        },
                        "sample": {
                            "type": "object",
                            "properties": {
                                "chat_name": {"type": "string"},
                                "sender": {"type": "string"},
                                "message": {"type": "string"},
                                "is_group": {"type": "boolean"},
                                "nickname": {"type": "string"},
                                "relationship": {"type": "string"},
                                "message_count": {"type": "integer"},
                                "profile_summary": {"type": "string"},
                                "contact_prompt": {"type": "string"},
                            },
                            "additionalProperties": False,
                        },
                    },
                    "additionalProperties": False,
                },
                permission="admin_read",
                timeout_sec=DEFAULT_TOOL_TIMEOUT_SEC,
                handler=self._tool_prompt_preview,
            )
        )
        return registry

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
            item = {
                "index": index,
                "tool": tool,
                "status": "ok",
                "duration_ms": 0.0,
                "attempts": 0,
                "retry_count": 0,
            }
            try:
                definition = self._registry.get(tool)
                item["permission"] = definition.permission
                item["timeout_ms"] = round(definition.timeout_sec * 1000.0, 3)
                item["retry_count"] = self._normalize_retry_count(definition.retry_count)
                self._ensure_permission(definition)
                schema_errors = validate_payload(definition.payload_schema, payload)
                item["schema_valid"] = not schema_errors
                if schema_errors:
                    raise ToolSchemaValidationError("; ".join(schema_errors))
                if dry_run:
                    item["status"] = "skipped"
                    item["output"] = {"dry_run": True}
                else:
                    item["output"] = await self._execute_tool_with_retries(definition, payload, item)
                    self._validate_tool_result(item["output"])
            except asyncio.TimeoutError:
                success = False
                item["status"] = "error"
                item["error_type"] = "timeout"
                item["error"] = f"tool timed out after {item.get('timeout_ms', 0)} ms"
            except Exception as exc:
                success = False
                item["status"] = "error"
                item["error_type"] = self._classify_error(exc)
                item["error"] = str(exc)
                if isinstance(exc, ToolSchemaValidationError):
                    item["schema_valid"] = False
                else:
                    item.setdefault("schema_valid", item.get("schema_valid", True))
            finally:
                item["duration_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
                trace.append(item)
            if item["status"] == "error" and step.get("continue_on_error") is not True:
                break

        return {"success": success, "trace": trace}

    @staticmethod
    def _normalize_retry_count(value: Any) -> int:
        try:
            return max(0, min(3, int(value or 0)))
        except (TypeError, ValueError):
            return 0

    async def _execute_tool_with_retries(
        self,
        definition: ToolDefinition,
        payload: dict[str, Any],
        trace_item: dict[str, Any],
    ) -> dict[str, Any]:
        retry_count = self._normalize_retry_count(definition.retry_count)
        last_exc: BaseException | None = None
        for attempt in range(1, retry_count + 2):
            trace_item["attempts"] = attempt
            try:
                result = await asyncio.wait_for(
                    definition.handler(payload),
                    timeout=definition.timeout_sec,
                )
                return result
            except Exception as exc:
                last_exc = exc
                if attempt > retry_count:
                    raise
        if last_exc is not None:
            raise last_exc
        raise ToolWorkflowError(f"tool did not run: {definition.name}")

    @staticmethod
    def _classify_error(exc: Exception) -> str:
        if isinstance(exc, asyncio.TimeoutError):
            return "timeout"
        if isinstance(exc, ToolSchemaValidationError):
            return "schema_validation"
        if isinstance(exc, ToolPermissionError):
            return "permission_denied"
        if isinstance(exc, ToolResultValidationError):
            return "invalid_tool_result"
        if isinstance(exc, ToolWorkflowError) and str(exc).startswith("unsupported tool:"):
            return "unsupported_tool"
        return "tool_error"

    def _ensure_permission(self, definition: ToolDefinition) -> None:
        if definition.permission not in self._allowed_permissions:
            raise ToolPermissionError(f"permission denied for tool: {definition.name}")

    @staticmethod
    def _validate_tool_result(result: Any) -> None:
        if not isinstance(result, dict):
            raise ToolResultValidationError("tool result must be a JSON object")

    async def _tool_config_audit(self, payload: dict[str, Any]) -> dict[str, Any]:
        snapshot = self._config_loader()
        config = getattr(snapshot, "config", {}) or {}
        override_path = str(payload.get("override_path") or "")
        return build_config_audit(config, override_path=override_path)

    async def _tool_readiness_check(self, payload: dict[str, Any]) -> dict[str, Any]:
        report = await self._readiness_loader()
        return report if isinstance(report, dict) else {"success": False, "message": "invalid readiness result"}

    async def _tool_prompt_preview(self, payload: dict[str, Any]) -> dict[str, Any]:
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
