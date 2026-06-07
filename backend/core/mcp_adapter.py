"""Read-only MCP-style JSON-RPC adapter for controlled local tools."""

from __future__ import annotations

import json
from typing import Any

from backend.core.tool_workflow import ControlledToolWorkflowService


MCP_PROTOCOL_VERSION = "2025-06-18"
JSONRPC_VERSION = "2.0"
ERROR_INVALID_REQUEST = -32600
ERROR_METHOD_NOT_FOUND = -32601
ERROR_INVALID_PARAMS = -32602
ERROR_INTERNAL = -32603


class ReadOnlyMCPAdapter:
    """Expose the model-visible controlled tools through a small JSON-RPC surface."""

    def __init__(self, service: ControlledToolWorkflowService) -> None:
        self._service = service

    async def handle(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return self._error(None, ERROR_INVALID_REQUEST, "request must be a JSON object")

        request_id = payload.get("id")
        if payload.get("jsonrpc") != JSONRPC_VERSION:
            return self._error(request_id, ERROR_INVALID_REQUEST, "jsonrpc must be 2.0")

        method = str(payload.get("method") or "").strip()
        params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
        try:
            if method == "initialize":
                result = self._initialize()
            elif method == "tools/list":
                result = self._list_tools()
            elif method == "tools/call":
                result = await self._call_tool(params)
            else:
                return self._error(request_id, ERROR_METHOD_NOT_FOUND, f"unsupported MCP method: {method}")
        except ValueError as exc:
            return self._error(request_id, ERROR_INVALID_PARAMS, str(exc))
        except Exception as exc:
            return self._error(request_id, ERROR_INTERNAL, str(exc))

        return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": result}

    @staticmethod
    def _initialize() -> dict[str, Any]:
        return {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {
                "tools": {},
            },
            "serverInfo": {
                "name": "wechat-ai-assistant-readonly",
                "version": "1.0.0",
            },
        }

    def _list_tools(self) -> dict[str, Any]:
        tools: list[dict[str, Any]] = []
        for item in self._service.model_tool_schemas():
            function = item.get("function") if isinstance(item.get("function"), dict) else {}
            name = str(function.get("name") or "").strip()
            if not name:
                continue
            tools.append(
                {
                    "name": name,
                    "description": str(function.get("description") or ""),
                    "inputSchema": dict(function.get("parameters") or {}),
                }
            )
        return {"tools": tools}

    async def _call_tool(self, params: dict[str, Any]) -> dict[str, Any]:
        name = str(params.get("name") or "").strip()
        if not name:
            raise ValueError("params.name is required")
        arguments = params.get("arguments") if "arguments" in params else {}
        if not isinstance(arguments, dict):
            raise ValueError("params.arguments must be a JSON object")
        if name not in self._visible_tool_names():
            return self._tool_error_result(
                name,
                "unsupported_tool",
                f"unsupported MCP tool: {name}",
                trace=[],
            )

        result = await self._service.run([{"tool": name, "payload": arguments}])
        trace = result.get("trace") if isinstance(result.get("trace"), list) else []
        first_item = trace[0] if trace and isinstance(trace[0], dict) else {}
        structured = {
            "success": bool(result.get("success")),
            "tool": name,
            "trace": trace,
        }
        if isinstance(first_item.get("output"), dict):
            structured["output"] = first_item["output"]
        if first_item.get("error"):
            structured["error"] = {
                "type": first_item.get("error_type") or "tool_error",
                "message": str(first_item.get("error") or ""),
            }

        summary = self._build_summary(name, structured)
        response = {
            "content": [{"type": "text", "text": summary}],
            "structuredContent": structured,
        }
        if not result.get("success"):
            response["isError"] = True
        return response

    def _visible_tool_names(self) -> set[str]:
        names: set[str] = set()
        for item in self._service.model_tool_schemas():
            function = item.get("function") if isinstance(item.get("function"), dict) else {}
            name = str(function.get("name") or "").strip()
            if name:
                names.add(name)
        return names

    @staticmethod
    def _tool_error_result(
        name: str,
        error_type: str,
        message: str,
        *,
        trace: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "content": [{"type": "text", "text": f"{name} failed: {message}"}],
            "structuredContent": {
                "success": False,
                "tool": name,
                "trace": trace,
                "error": {
                    "type": error_type,
                    "message": message,
                },
            },
            "isError": True,
        }

    @staticmethod
    def _build_summary(name: str, structured: dict[str, Any]) -> str:
        if not structured.get("success"):
            error = structured.get("error") if isinstance(structured.get("error"), dict) else {}
            message = str(error.get("message") or "tool failed")
            return f"{name} failed: {message}"
        output = structured.get("output")
        try:
            rendered = json.dumps(output if isinstance(output, dict) else {}, ensure_ascii=False, sort_keys=True)
        except Exception:
            rendered = "{}"
        if len(rendered) > 600:
            rendered = f"{rendered[:600]}..."
        return f"{name} completed: {rendered}"

    @staticmethod
    def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id,
            "error": {
                "code": code,
                "message": message,
            },
        }
