from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

ANTHROPIC_VERSION = "2023-06-01"


@dataclass(slots=True)
class NormalizedToolCall:
    id: str
    name: str
    arguments: str
    type: str = "function"
    raw: Any = None


@dataclass(slots=True)
class NormalizedChatResult:
    text: str = ""
    reasoning: str = ""
    tool_calls: List[NormalizedToolCall] = field(default_factory=list)
    finish_reason: str = ""
    raw: Any = None


@dataclass(slots=True)
class NormalizedProviderError:
    message: str
    code: str = ""
    type: str = ""
    status_code: Optional[int] = None
    retryable: bool = False
    raw: Any = None


def _stringify_json(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value).strip()


def _extract_text_fragments(value: Any, *, allow_reasoning: bool = False) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, list):
        parts: List[str] = []
        for item in value:
            parts.extend(_extract_text_fragments(item, allow_reasoning=allow_reasoning))
        return parts
    if isinstance(value, dict):
        block_type = str(value.get("type") or "").strip().lower()
        if block_type in {"reasoning", "summary_text"} and not allow_reasoning:
            return []

        parts: List[str] = []
        text = str(value.get("text") or "").strip()
        if text and (
            allow_reasoning
            or block_type in {"text", "output_text", "input_text", ""}
        ):
            parts.append(text)

        for key in ("content", "message", "delta"):
            nested = value.get(key)
            if nested is not None:
                parts.extend(_extract_text_fragments(nested, allow_reasoning=allow_reasoning))
        return [item for item in parts if item]
    return []


def extract_visible_text(value: Any) -> str:
    content = getattr(value, "content", value)
    return "\n".join(_extract_text_fragments(content)).strip()


def _extract_reasoning_fragments(value: Any, *, inside_reasoning: bool = False) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text and inside_reasoning else []
    if isinstance(value, list):
        parts: List[str] = []
        for item in value:
            parts.extend(_extract_reasoning_fragments(item, inside_reasoning=inside_reasoning))
        return parts
    if isinstance(value, dict):
        parts: List[str] = []
        block_type = str(value.get("type") or "").strip().lower()
        if block_type == "summary_text":
            text = str(value.get("text") or "").strip()
            return [text] if text else []
        if block_type == "reasoning":
            parts.extend(_extract_reasoning_fragments(value.get("reasoning"), inside_reasoning=True))
            parts.extend(_extract_reasoning_fragments(value.get("summary"), inside_reasoning=True))
            parts.extend(_extract_reasoning_fragments(value.get("content"), inside_reasoning=True))
        else:
            parts.extend(_extract_reasoning_fragments(value.get("reasoning_content"), inside_reasoning=True))
            parts.extend(_extract_reasoning_fragments(value.get("reasoning"), inside_reasoning=True))
            parts.extend(_extract_reasoning_fragments(value.get("summary"), inside_reasoning=True))
            if inside_reasoning and block_type in {"text", "output_text", "input_text", ""}:
                text = str(value.get("text") or "").strip()
                if text:
                    parts.append(text)
            nested_content = value.get("content")
            if isinstance(nested_content, (list, dict)):
                parts.extend(
                    _extract_reasoning_fragments(
                        nested_content,
                        inside_reasoning=inside_reasoning,
                    )
                )
            message = value.get("message")
            if isinstance(message, (list, dict)):
                parts.extend(
                    _extract_reasoning_fragments(
                        message,
                        inside_reasoning=inside_reasoning,
                    )
                )
            delta = value.get("delta")
            if isinstance(delta, (list, dict)):
                parts.extend(
                    _extract_reasoning_fragments(
                        delta,
                        inside_reasoning=inside_reasoning,
                    )
                )
        return [item for item in parts if item]
    return []


def extract_reasoning_text(value: Any) -> str:
    parts: List[str] = []

    candidates: List[tuple[Any, bool]] = []
    if isinstance(value, dict):
        candidates.extend(
            [
                (value.get("reasoning_content"), True),
                (value.get("reasoning"), True),
                (value.get("summary"), True),
                (value.get("content"), False),
            ]
        )
        if isinstance(value.get("message"), dict):
            candidates.append((value.get("message"), False))
        if isinstance(value.get("delta"), dict):
            candidates.append((value.get("delta"), False))

    additional_kwargs = getattr(value, "additional_kwargs", None)
    if isinstance(additional_kwargs, dict):
        candidates.extend(
            [
                (additional_kwargs.get("reasoning_content"), True),
                (additional_kwargs.get("reasoning"), True),
                (additional_kwargs.get("summary"), True),
            ]
        )

    candidates.extend(
        [
            (getattr(value, "reasoning_content", None), True),
            (getattr(value, "reasoning", None), True),
            (getattr(value, "summary", None), True),
        ]
    )
    content = getattr(value, "content", None)
    if content is not None:
        candidates.append((content, False))

    for candidate, inside_reasoning in candidates:
        parts.extend(_extract_reasoning_fragments(candidate, inside_reasoning=inside_reasoning))

    deduped: List[str] = []
    for item in parts:
        normalized = str(item or "").strip()
        if normalized and normalized not in deduped:
            deduped.append(normalized)
    return "\n".join(deduped).strip()


def extract_tool_calls(value: Any) -> List[NormalizedToolCall]:
    raw_tool_calls: List[Any] = []

    def _collect(candidate: Any) -> None:
        if not candidate:
            return
        if isinstance(candidate, list):
            raw_tool_calls.extend(candidate)
            return
        raw_tool_calls.append(candidate)

    if isinstance(value, dict):
        _collect(value.get("tool_calls"))
        _collect(value.get("function_call"))
        message = value.get("message")
        if isinstance(message, dict):
            _collect(message.get("tool_calls"))
            _collect(message.get("function_call"))
        delta = value.get("delta")
        if isinstance(delta, dict):
            _collect(delta.get("tool_calls"))
            _collect(delta.get("function_call"))

    additional_kwargs = getattr(value, "additional_kwargs", None)
    if isinstance(additional_kwargs, dict):
        _collect(additional_kwargs.get("tool_calls"))
        _collect(additional_kwargs.get("function_call"))

    _collect(getattr(value, "tool_calls", None))
    _collect(getattr(value, "function_call", None))

    normalized: List[NormalizedToolCall] = []
    for index, item in enumerate(raw_tool_calls, start=1):
        if not item:
            continue
        if isinstance(item, dict):
            function = item.get("function") or {}
            name = str(function.get("name") or item.get("name") or "").strip()
            arguments = function.get("arguments")
            if arguments is None:
                arguments = item.get("arguments")
            call_id = str(item.get("id") or f"tool_call_{index}").strip()
            call_type = str(item.get("type") or "function").strip() or "function"
        else:
            function = getattr(item, "function", None) or {}
            if not isinstance(function, dict):
                function = {
                    "name": getattr(function, "name", None),
                    "arguments": getattr(function, "arguments", None),
                }
            name = str(function.get("name") or getattr(item, "name", "") or "").strip()
            arguments = function.get("arguments")
            if arguments is None:
                arguments = getattr(item, "arguments", None)
            call_id = str(getattr(item, "id", None) or f"tool_call_{index}").strip()
            call_type = str(getattr(item, "type", None) or "function").strip() or "function"

        if not name:
            continue
        normalized.append(
            NormalizedToolCall(
                id=call_id,
                name=name,
                arguments=_stringify_json(arguments),
                type=call_type,
                raw=item,
            )
        )
    return normalized


def normalize_chat_result(value: Any) -> NormalizedChatResult:
    payload = value
    finish_reason = ""
    if isinstance(value, dict) and isinstance(value.get("choices"), list):
        choice = (value.get("choices") or [{}])[0] or {}
        payload = choice.get("message") or choice.get("delta") or choice
        finish_reason = str(choice.get("finish_reason") or "").strip()
    elif isinstance(value, dict):
        finish_reason = str(value.get("finish_reason") or value.get("stop_reason") or "").strip()
    else:
        finish_reason = str(getattr(value, "finish_reason", "") or "").strip()

    text = extract_visible_text(payload)
    if not text and payload is not value:
        text = extract_visible_text(value)

    reasoning = extract_reasoning_text(payload)
    if not reasoning and payload is not value:
        reasoning = extract_reasoning_text(value)

    tool_calls = extract_tool_calls(payload)
    if not tool_calls and payload is not value:
        tool_calls = extract_tool_calls(value)

    return NormalizedChatResult(
        text=text,
        reasoning=reasoning,
        tool_calls=tool_calls,
        finish_reason=finish_reason,
        raw=value,
    )


def build_openai_chat_payload(
    *,
    model: str,
    messages: Iterable[Dict[str, Any]],
    stream: bool = False,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    max_completion_tokens: Optional[int] = None,
    reasoning_effort: Optional[str] = None,
    tools: Optional[Iterable[Dict[str, Any]]] = None,
    tool_choice: Optional[Any] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "model": str(model or "").strip(),
        "messages": list(messages or []),
        "stream": bool(stream),
    }
    if temperature is not None:
        payload["temperature"] = temperature
    if max_completion_tokens is not None:
        payload["max_completion_tokens"] = max_completion_tokens
    elif max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if reasoning_effort:
        payload["reasoning_effort"] = str(reasoning_effort).strip()
    if tools:
        payload["tools"] = list(tools)
    if tool_choice is not None:
        payload["tool_choice"] = tool_choice
    return payload


def _normalize_responses_content_parts(value: Any) -> List[Dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [{"type": "input_text", "text": text}] if text else []
    if isinstance(value, list):
        parts: List[Dict[str, Any]] = []
        for item in value:
            if isinstance(item, dict):
                item_type = str(item.get("type") or "").strip().lower()
                if item_type == "text":
                    text = str(item.get("text") or "").strip()
                    if text:
                        parts.append({"type": "input_text", "text": text})
                    continue
                if item_type == "image_url":
                    image_payload = item.get("image_url")
                    if isinstance(image_payload, dict):
                        url = str(image_payload.get("url") or "").strip()
                        if url:
                            parts.append({"type": "input_image", "image_url": url})
                    continue
                text = str(item.get("text") or "").strip()
                if text:
                    parts.append({"type": "input_text", "text": text})
                continue
            text = str(item or "").strip()
            if text:
                parts.append({"type": "input_text", "text": text})
        return parts
    text = str(value).strip()
    return [{"type": "input_text", "text": text}] if text else []


def build_openai_responses_payload(
    *,
    model: str,
    messages: Iterable[Dict[str, Any]],
    stream: bool = True,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    max_completion_tokens: Optional[int] = None,
    reasoning_effort: Optional[str] = None,
) -> Dict[str, Any]:
    instructions: List[str] = []
    input_items: List[Dict[str, Any]] = []

    for item in messages or []:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        content_parts = _normalize_responses_content_parts(item.get("content"))
        if not content_parts:
            continue
        if role == "system":
            for part in content_parts:
                text = str(part.get("text") or "").strip()
                if text:
                    instructions.append(text)
            continue
        if role not in {"user", "assistant", "developer"}:
            role = "user"
        input_items.append(
            {
                "type": "message",
                "role": role,
                "content": content_parts,
            }
        )

    payload: Dict[str, Any] = {
        "model": str(model or "").strip(),
        "store": False,
        "stream": bool(stream),
        "input": input_items,
        "text": {"verbosity": "medium"},
    }
    payload["instructions"] = (
        "\n\n".join(item for item in instructions if item).strip()
        or "You are a helpful assistant. Reply directly to the latest user message."
    )
    if temperature is not None:
        payload["temperature"] = temperature
    if max_completion_tokens is not None:
        payload["max_output_tokens"] = max_completion_tokens
    elif max_tokens is not None:
        payload["max_output_tokens"] = max_tokens
    if reasoning_effort:
        payload["reasoning"] = {
            "effort": str(reasoning_effort).strip(),
            "summary": "auto",
        }
        payload["include"] = ["reasoning.encrypted_content"]
    return payload


def infer_auth_transport(base_url: str, explicit: Optional[str] = None) -> str:
    normalized = str(explicit or "").strip().lower()
    if normalized:
        return normalized
    base = str(base_url or "").strip().lower()
    if "api.anthropic.com" in base:
        return "anthropic_native"
    return "openai_compatible"


def build_anthropic_headers(
    *,
    api_key: str,
    extra_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    provided = dict(extra_headers or {})
    lowered = {str(key or "").strip().lower(): str(key or "").strip() for key in provided}
    if "anthropic-version" not in lowered:
        headers["anthropic-version"] = ANTHROPIC_VERSION
    headers.update(provided)
    if api_key and "x-api-key" not in lowered and "authorization" not in lowered:
        headers["x-api-key"] = api_key
    return headers


def _normalize_anthropic_content(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts: List[str] = []
        for item in value:
            if isinstance(item, dict):
                item_type = str(item.get("type") or "").strip().lower()
                if item_type == "text":
                    text = str(item.get("text") or "").strip()
                    if text:
                        parts.append(text)
                    continue
                if item_type in {"image_url", "input_audio"}:
                    continue
                nested_text = str(item.get("text") or "").strip()
                if nested_text:
                    parts.append(nested_text)
                    continue
            else:
                text = str(item or "").strip()
                if text:
                    parts.append(text)
        return "\n".join(part for part in parts if part).strip()
    if isinstance(value, dict):
        return str(value.get("text") or "").strip()
    return str(value or "").strip()


def build_anthropic_messages_payload(
    *,
    model: str,
    messages: Iterable[Dict[str, Any]],
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    max_completion_tokens: Optional[int] = None,
    stream: bool = False,
) -> Dict[str, Any]:
    system_parts: List[str] = []
    normalized_messages: List[Dict[str, Any]] = []
    for item in messages or []:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        content = _normalize_anthropic_content(item.get("content"))
        if not content:
            continue
        if role == "system":
            system_parts.append(content)
            continue
        if role not in {"user", "assistant"}:
            role = "user"
        normalized_messages.append(
            {
                "role": role,
                "content": [{"type": "text", "text": content}],
            }
        )
    payload: Dict[str, Any] = {
        "model": str(model or "").strip(),
        "messages": normalized_messages,
        "max_tokens": int(max_completion_tokens or max_tokens or 512),
        "stream": bool(stream),
    }
    if temperature is not None:
        payload["temperature"] = temperature
    if system_parts:
        payload["system"] = "\n\n".join(part for part in system_parts if part).strip()
    return payload


def normalize_provider_error(
    *,
    exc: Optional[BaseException] = None,
    response: Any = None,
    payload: Any = None,
) -> NormalizedProviderError:
    status_code = getattr(response, "status_code", None)
    error_payload = payload

    if error_payload is None and response is not None:
        try:
            error_payload = response.json()
        except Exception:
            error_payload = None

    error_obj: Any = error_payload
    if isinstance(error_payload, dict) and "error" in error_payload:
        error_obj = error_payload.get("error")

    message = str(exc or "").strip()
    code = ""
    error_type = ""

    if isinstance(error_obj, dict):
        message = str(error_obj.get("message") or message or "provider error").strip()
        code = str(error_obj.get("code") or "").strip()
        error_type = str(error_obj.get("type") or "").strip()
    elif error_obj not in (None, ""):
        message = str(error_obj).strip()

    if not message and response is not None:
        message = str(getattr(response, "text", "") or "").strip()[:200]
    if not message:
        message = "provider request failed"

    retryable = bool(
        status_code in {408, 409, 425, 429}
        or (status_code is not None and int(status_code) >= 500)
    )

    if exc is not None:
        exc_name = exc.__class__.__name__.lower()
        if any(token in exc_name for token in ("timeout", "connect", "network")):
            retryable = True

    return NormalizedProviderError(
        message=message,
        code=code,
        type=error_type,
        status_code=status_code,
        retryable=retryable,
        raw=error_payload if error_payload is not None else exc,
    )
