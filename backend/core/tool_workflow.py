"""Controlled tool workflow execution for local admin APIs."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from backend.core.config_audit import build_config_audit
from backend.utils.config import resolve_system_prompt


MAX_WORKFLOW_STEPS = 8
MAX_STEP_PAYLOAD_CHARS = 12000
DEFAULT_TOOL_TIMEOUT_SEC = 5.0
DEFAULT_COST_SUMMARY_TIMEOUT_SEC = 10.0
DEFAULT_BACKUP_KEEP_QUICK = 5
DEFAULT_BACKUP_KEEP_FULL = 3
WORKFLOW_MODE_DIRECT = "direct"
WORKFLOW_MODE_PLAN_REFLECT_REPAIR = "plan_reflect_repair"
MAX_REPAIR_ATTEMPTS = 1
DATA_CONTROL_SCOPES = ("memory", "usage", "export_rag")
MODEL_VISIBLE_TOOL_NAMES = frozenset(
    {
        "readiness_check",
        "eval_latest",
        "cost_summary",
        "backup_cleanup_dry_run",
        "data_controls_dry_run",
    }
)
MODEL_TOOL_DESCRIPTIONS = {
    "readiness_check": "Return a read-only readiness summary for the local assistant runtime.",
    "eval_latest": "Return the latest offline evaluation report summary without raw cases.",
    "cost_summary": "Return aggregate model usage and cost statistics for a safe period.",
    "backup_cleanup_dry_run": "Preview backup cleanup impact without deleting files.",
    "data_controls_dry_run": "Preview local data cleanup impact for selected supported scopes.",
}

EvalReportLoader = Callable[[], Awaitable[dict[str, Any]]]
CostSummaryLoader = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
MaintenanceDryRunLoader = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


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


def build_model_tool_schemas(
    registry: ToolRegistry,
    *,
    allowed_names: Optional[set[str]] = None,
) -> list[dict[str, Any]]:
    """Build OpenAI-compatible function tool schemas for the model-visible subset."""
    visible_names = set(allowed_names or MODEL_VISIBLE_TOOL_NAMES)
    tools: list[dict[str, Any]] = []
    for name in registry.names():
        if name not in visible_names:
            continue
        definition = registry.get(name)
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": definition.name,
                    "description": MODEL_TOOL_DESCRIPTIONS.get(
                        definition.name,
                        f"Run read-only local tool: {definition.name}.",
                    ),
                    "parameters": dict(definition.payload_schema),
                },
            }
        )
    return tools


def model_tool_calls_to_steps(
    tool_calls: list[Any],
    *,
    allowed_names: Optional[set[str]] = None,
) -> list[dict[str, Any]]:
    """Convert normalized model tool calls into controlled workflow steps."""
    visible_names = set(allowed_names or MODEL_VISIBLE_TOOL_NAMES)
    steps: list[dict[str, Any]] = []
    for item in tool_calls or []:
        name = str(getattr(item, "name", "") or "").strip()
        if name not in visible_names:
            raise ToolWorkflowError(f"unsupported model tool: {name}")
        raw_arguments = str(getattr(item, "arguments", "") or "").strip()
        if len(raw_arguments) > MAX_STEP_PAYLOAD_CHARS:
            raise ToolWorkflowError("model tool arguments are too large")
        if raw_arguments:
            try:
                payload = json.loads(raw_arguments)
            except json.JSONDecodeError as exc:
                raise ToolWorkflowError(f"model tool arguments must be valid JSON: {name}") from exc
        else:
            payload = {}
        if not isinstance(payload, dict):
            raise ToolWorkflowError(f"model tool arguments must be a JSON object: {name}")
        steps.append(
            {
                "tool": name,
                "payload": payload,
                "tool_call_id": str(getattr(item, "id", "") or "").strip(),
            }
        )
    if not steps:
        raise ToolWorkflowError("model tool_calls are required")
    if len(steps) > MAX_WORKFLOW_STEPS:
        raise ToolWorkflowError(f"model tool_calls cannot exceed {MAX_WORKFLOW_STEPS}")
    return steps


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

    enum_values = schema.get("enum")
    if isinstance(enum_values, list) and value not in enum_values:
        allowed = ", ".join(str(item) for item in enum_values)
        errors.append(f"{path} must be one of: {allowed}")
        return errors

    if expected_type == "array" and isinstance(value, list):
        min_items = schema.get("minItems")
        if isinstance(min_items, int) and len(value) < min_items:
            errors.append(f"{path} must contain at least {min_items} item(s)")
            return errors
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                errors.extend(_validate_schema_value(item_schema, item, f"{path}[{index}]"))
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
        eval_report_loader: Optional[EvalReportLoader] = None,
        cost_summary_loader: Optional[CostSummaryLoader] = None,
        backup_cleanup_loader: Optional[MaintenanceDryRunLoader] = None,
        data_controls_loader: Optional[MaintenanceDryRunLoader] = None,
        registry: Optional[ToolRegistry] = None,
        allowed_permissions: Optional[set[str]] = None,
    ) -> None:
        self._config_loader = config_loader
        self._readiness_loader = readiness_loader
        self._eval_report_loader = eval_report_loader or self._default_eval_report_loader
        self._cost_summary_loader = cost_summary_loader or self._default_cost_summary_loader
        self._backup_cleanup_loader = backup_cleanup_loader or self._default_backup_cleanup_loader
        self._data_controls_loader = data_controls_loader or self._default_data_controls_loader
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
        registry.register(
            ToolDefinition(
                name="eval_latest",
                payload_schema={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
                permission="admin_read",
                timeout_sec=DEFAULT_TOOL_TIMEOUT_SEC,
                handler=self._tool_eval_latest,
            )
        )
        registry.register(
            ToolDefinition(
                name="cost_summary",
                payload_schema={
                    "type": "object",
                    "properties": {
                        "period": {"type": "string"},
                        "include_estimated": {"type": "boolean"},
                    },
                    "additionalProperties": False,
                },
                permission="admin_read",
                timeout_sec=DEFAULT_COST_SUMMARY_TIMEOUT_SEC,
                handler=self._tool_cost_summary,
            )
        )
        registry.register(
            ToolDefinition(
                name="backup_cleanup_dry_run",
                payload_schema={
                    "type": "object",
                    "properties": {
                        "keep_quick": {"type": "integer"},
                        "keep_full": {"type": "integer"},
                        "protect_restore_anchor": {"type": "boolean"},
                    },
                    "additionalProperties": False,
                },
                permission="admin_read",
                timeout_sec=DEFAULT_TOOL_TIMEOUT_SEC,
                handler=self._tool_backup_cleanup_dry_run,
            )
        )
        registry.register(
            ToolDefinition(
                name="data_controls_dry_run",
                payload_schema={
                    "type": "object",
                    "properties": {
                        "scopes": {
                            "type": "array",
                            "minItems": 1,
                            "items": {
                                "type": "string",
                                "enum": list(DATA_CONTROL_SCOPES),
                            },
                        },
                    },
                    "additionalProperties": False,
                },
                permission="admin_read",
                timeout_sec=DEFAULT_TOOL_TIMEOUT_SEC,
                handler=self._tool_data_controls_dry_run,
            )
        )
        return registry

    async def run(
        self,
        steps: list[dict[str, Any]],
        *,
        dry_run: bool = False,
        workflow_mode: str = WORKFLOW_MODE_DIRECT,
    ) -> dict[str, Any]:
        if not isinstance(steps, list) or not steps:
            raise ToolWorkflowError("steps is required")
        if len(steps) > MAX_WORKFLOW_STEPS:
            raise ToolWorkflowError(f"steps cannot exceed {MAX_WORKFLOW_STEPS}")

        mode = str(workflow_mode or WORKFLOW_MODE_DIRECT).strip() or WORKFLOW_MODE_DIRECT
        if mode not in {WORKFLOW_MODE_DIRECT, WORKFLOW_MODE_PLAN_REFLECT_REPAIR}:
            raise ToolWorkflowError(f"unsupported workflow_mode: {mode}")
        if mode == WORKFLOW_MODE_PLAN_REFLECT_REPAIR:
            return await self._run_plan_reflect_repair(steps, dry_run=dry_run, mode=mode)

        return await self._run_direct(steps, dry_run=dry_run)

    async def _run_direct(self, steps: list[dict[str, Any]], *, dry_run: bool) -> dict[str, Any]:
        trace: list[dict[str, Any]] = []
        success = True
        for index, raw_step in enumerate(steps, start=1):
            step = self._normalize_step(raw_step)
            item = await self._execute_step(index, step, dry_run=dry_run)
            if item["status"] == "error":
                success = False
            trace.append(item)
            if item["status"] == "error" and step.get("continue_on_error") is not True:
                break

        return {"success": success, "trace": trace}

    async def _run_plan_reflect_repair(
        self,
        steps: list[dict[str, Any]],
        *,
        dry_run: bool,
        mode: str,
    ) -> dict[str, Any]:
        trace: list[dict[str, Any]] = []
        reflection_items: list[dict[str, Any]] = []
        repair_items: list[dict[str, Any]] = []
        unresolved_error = False
        repair_attempts = 0

        for index, raw_step in enumerate(steps, start=1):
            step = self._normalize_step(raw_step)
            item = await self._execute_step(index, step, dry_run=dry_run)
            trace.append(item)
            if item["status"] != "error":
                continue

            repair_step, repair_meta = self._build_repair_step(step, item)
            can_repair = repair_step is not None and repair_attempts < MAX_REPAIR_ATTEMPTS
            reflection = self._build_reflection_item(item, repairable=can_repair)
            if can_repair and repair_meta is not None:
                repair_attempts += 1
                repair_meta["attempt"] = repair_attempts
                repair_items.append(repair_meta)
                reflection["repair_action"] = repair_meta["action"]
                reflection["status"] = "repairing"
                repair_item = await self._execute_step(index, repair_step, dry_run=dry_run)
                repair_item["repair_attempt"] = repair_attempts
                repair_item["repair_of_index"] = index
                trace.append(repair_item)
                if repair_item["status"] == "error":
                    reflection["status"] = "blocked"
                    unresolved_error = True
                    if step.get("continue_on_error") is not True:
                        reflection_items.append(reflection)
                        break
                else:
                    reflection["status"] = "resolved"
                reflection_items.append(reflection)
                continue

            reflection_items.append(reflection)
            unresolved_error = True
            if step.get("continue_on_error") is not True:
                break

        result: dict[str, Any] = {
            "success": not unresolved_error,
            "trace": trace,
            "planning": {
                "workflow_mode": mode,
                "step_count": len(steps),
                "tools": [
                    str(step.get("tool") or "").strip()
                    for step in (raw if isinstance(raw, dict) else {} for raw in steps)
                ],
                "max_repair_attempts": MAX_REPAIR_ATTEMPTS,
                "repair_policy": "schema_safe_defaults_only",
            },
            "repair": {
                "attempted": bool(repair_items),
                "count": len(repair_items),
                "max_attempts": MAX_REPAIR_ATTEMPTS,
                "items": repair_items,
            },
        }
        if reflection_items:
            result["reflection"] = {
                "status": "resolved" if result["success"] else "blocked",
                "items": reflection_items,
            }
        return result

    @staticmethod
    def _normalize_step(raw_step: Any) -> dict[str, Any]:
        step = raw_step if isinstance(raw_step, dict) else {}
        tool = str(step.get("tool") or "").strip()
        payload = step.get("payload") if isinstance(step.get("payload"), dict) else {}
        if not tool:
            raise ToolWorkflowError("step.tool is required")
        if len(str(payload)) > MAX_STEP_PAYLOAD_CHARS:
            raise ToolWorkflowError("step payload is too large")
        return step

    async def _execute_step(
        self,
        index: int,
        step: dict[str, Any],
        *,
        dry_run: bool,
    ) -> dict[str, Any]:
        tool = str(step.get("tool") or "").strip()
        payload = step.get("payload") if isinstance(step.get("payload"), dict) else {}
        started = time.perf_counter()
        item = {
            "index": index,
            "tool": tool,
            "status": "ok",
            "duration_ms": 0.0,
            "attempts": 0,
            "retry_count": 0,
        }
        tool_call_id = str(step.get("tool_call_id") or "").strip()
        if tool_call_id:
            item["tool_call_id"] = tool_call_id
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
            item["status"] = "error"
            item["error_type"] = "timeout"
            item["error"] = f"tool timed out after {item.get('timeout_ms', 0)} ms"
        except Exception as exc:
            item["status"] = "error"
            item["error_type"] = self._classify_error(exc)
            item["error"] = str(exc)
            if isinstance(exc, ToolSchemaValidationError):
                item["schema_valid"] = False
            else:
                item.setdefault("schema_valid", item.get("schema_valid", True))
        finally:
            item["duration_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
        return item

    @staticmethod
    def _build_repair_step(
        step: dict[str, Any],
        trace_item: dict[str, Any],
    ) -> tuple[Optional[dict[str, Any]], Optional[dict[str, Any]]]:
        payload = step.get("payload") if isinstance(step.get("payload"), dict) else {}
        if (
            trace_item.get("tool") != "data_controls_dry_run"
            or trace_item.get("error_type") != "schema_validation"
            or payload.get("scopes") != []
            or set(payload) != {"scopes"}
        ):
            return None, None
        repaired_step = dict(step)
        repaired_step["payload"] = {}
        return repaired_step, {
            "step_index": trace_item.get("index"),
            "tool": "data_controls_dry_run",
            "action": "use_default_scopes",
            "reason": "empty scopes fallback to default data control scopes",
        }

    @staticmethod
    def _build_reflection_item(
        trace_item: dict[str, Any],
        *,
        repairable: bool,
    ) -> dict[str, Any]:
        return {
            "step_index": trace_item.get("index"),
            "tool": trace_item.get("tool"),
            "status": "repairable" if repairable else "blocked",
            "error_type": trace_item.get("error_type"),
            "message": trace_item.get("error"),
            "repairable": repairable,
        }

    def model_tool_schemas(self) -> list[dict[str, Any]]:
        return build_model_tool_schemas(self._registry)

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

    async def _tool_eval_latest(self, payload: dict[str, Any]) -> dict[str, Any]:
        source = await self._eval_report_loader()
        report = source.get("report") if isinstance(source, dict) else None
        has_report = isinstance(report, dict)
        summary = report.get("summary") if has_report and isinstance(report.get("summary"), dict) else {}
        regressions = report.get("regressions") if has_report and isinstance(report.get("regressions"), list) else []
        return {
            "success": bool(source.get("success", True)) if isinstance(source, dict) else True,
            "has_report": has_report,
            "name": str(source.get("name") or "") if isinstance(source, dict) else "",
            "generated_at": report.get("generated_at") if has_report else None,
            "preset": report.get("preset") if has_report else None,
            "app_version": report.get("app_version") if has_report else None,
            "summary": dict(summary),
            "regression_count": len(regressions),
        }

    async def _tool_cost_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        period = str(payload.get("period") or "30d").strip().lower()
        if period not in {"today", "7d", "30d", "all"}:
            period = "30d"
        include_estimated = bool(payload.get("include_estimated", True))
        source = await self._cost_summary_loader({
            "period": period,
            "include_estimated": include_estimated,
        })
        overview = source.get("overview") if isinstance(source, dict) and isinstance(source.get("overview"), dict) else {}
        filters = source.get("filters") if isinstance(source, dict) and isinstance(source.get("filters"), dict) else {}
        models = source.get("models") if isinstance(source, dict) and isinstance(source.get("models"), list) else []
        review_queue = source.get("review_queue") if isinstance(source, dict) and isinstance(source.get("review_queue"), list) else []
        return {
            "success": bool(source.get("success", True)) if isinstance(source, dict) else True,
            "filters": dict(filters),
            "overview": dict(overview),
            "model_count": len(models),
            "review_queue_count": len(review_queue),
        }

    async def _tool_backup_cleanup_dry_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        keep_quick = self._safe_int(payload.get("keep_quick"), DEFAULT_BACKUP_KEEP_QUICK, min_value=0)
        keep_full = self._safe_int(payload.get("keep_full"), DEFAULT_BACKUP_KEEP_FULL, min_value=0)
        protect_restore_anchor = bool(payload.get("protect_restore_anchor", True))
        source = await self._backup_cleanup_loader(
            {
                "keep_quick": keep_quick,
                "keep_full": keep_full,
                "protect_restore_anchor": protect_restore_anchor,
            }
        )
        summary = source.get("summary") if isinstance(source, dict) and isinstance(source.get("summary"), dict) else {}
        source_keep_policy = source.get("keep_policy") if isinstance(source, dict) and isinstance(source.get("keep_policy"), dict) else {}
        protected_backup_ids = (
            source.get("protected_backup_ids")
            if isinstance(source, dict) and isinstance(source.get("protected_backup_ids"), list)
            else []
        )
        return {
            "success": bool(source.get("success", True)) if isinstance(source, dict) else True,
            "dry_run": True,
            "keep_policy": {
                "keep_quick": self._safe_int(source_keep_policy.get("keep_quick"), keep_quick, min_value=0),
                "keep_full": self._safe_int(source_keep_policy.get("keep_full"), keep_full, min_value=0),
                "protect_restore_anchor": bool(source_keep_policy.get("protect_restore_anchor", protect_restore_anchor)),
            },
            "candidate_count": self._safe_int(source.get("candidate_count"), 0, min_value=0) if isinstance(source, dict) else 0,
            "preserved_count": len(source.get("preserved_backups") or []) if isinstance(source, dict) else 0,
            "protected_count": len(protected_backup_ids),
            "reclaimable_bytes": self._safe_int(source.get("reclaimable_bytes"), 0, min_value=0) if isinstance(source, dict) else 0,
            "total_backups": self._safe_int(summary.get("total_backups"), 0, min_value=0),
            "quick_backup_count": self._safe_int(summary.get("quick_backup_count"), 0, min_value=0),
            "full_backup_count": self._safe_int(summary.get("full_backup_count"), 0, min_value=0),
            "deleted_count": 0,
        }

    async def _tool_data_controls_dry_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        scopes = payload.get("scopes")
        if scopes is None:
            scopes = list(DATA_CONTROL_SCOPES)
        source = await self._data_controls_loader({"scopes": list(scopes)})
        source_scopes = source.get("scopes") if isinstance(source, dict) and isinstance(source.get("scopes"), list) else scopes
        safe_scopes = [
            str(item)
            for item in source_scopes
            if str(item) in DATA_CONTROL_SCOPES
        ]
        return {
            "success": bool(source.get("success", True)) if isinstance(source, dict) else True,
            "dry_run": True,
            "scopes": safe_scopes,
            "target_count": self._safe_int(source.get("target_count"), 0, min_value=0) if isinstance(source, dict) else 0,
            "existing_target_count": self._safe_int(source.get("existing_target_count"), 0, min_value=0) if isinstance(source, dict) else 0,
            "unsupported_target_count": self._safe_int(source.get("unsupported_target_count"), 0, min_value=0) if isinstance(source, dict) else 0,
            "reclaimable_bytes": self._safe_int(source.get("reclaimable_bytes"), 0, min_value=0) if isinstance(source, dict) else 0,
            "deleted_count": 0,
        }

    @staticmethod
    def _safe_int(value: Any, default: int, *, min_value: int = 0) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = int(default)
        return max(int(min_value), parsed)

    @staticmethod
    async def _default_eval_report_loader() -> dict[str, Any]:
        return {"success": True, "report": None, "name": ""}

    @staticmethod
    async def _default_cost_summary_loader(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "success": True,
            "filters": {
                "period": payload.get("period") or "30d",
                "include_estimated": bool(payload.get("include_estimated", True)),
            },
            "overview": {},
            "models": [],
            "review_queue": [],
        }

    @staticmethod
    async def _default_backup_cleanup_loader(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "success": True,
            "dry_run": True,
            "keep_policy": {
                "keep_quick": payload.get("keep_quick"),
                "keep_full": payload.get("keep_full"),
                "protect_restore_anchor": bool(payload.get("protect_restore_anchor", True)),
            },
            "candidate_count": 0,
            "preserved_backups": [],
            "protected_backup_ids": [],
            "reclaimable_bytes": 0,
            "summary": {
                "total_backups": 0,
                "quick_backup_count": 0,
                "full_backup_count": 0,
            },
        }

    @staticmethod
    async def _default_data_controls_loader(payload: dict[str, Any]) -> dict[str, Any]:
        scopes = payload.get("scopes") if isinstance(payload.get("scopes"), list) else []
        return {
            "success": True,
            "dry_run": True,
            "scopes": scopes,
            "target_count": 0,
            "existing_target_count": 0,
            "unsupported_target_count": 0,
            "reclaimable_bytes": 0,
        }
