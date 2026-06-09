from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit

import httpx

MODEL_DISCOVERY_TIMEOUT_SEC = 8.0
MAX_DISCOVERED_MODELS = 200
MAX_MODEL_ID_CHARS = 200

_KNOWN_OPENAI_COMPAT_ENDPOINTS = (
    "/chat/completions",
    "/responses",
    "/embeddings",
    "/models",
)


@dataclass(frozen=True)
class ModelDiscoveryResult:
    success: bool
    models: list[str]
    base_url: str
    message: str
    code: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "models": list(self.models),
            "base_url": self.base_url,
            "message": self.message,
            "code": self.code,
        }


def _strip_known_endpoint(path: str) -> str:
    normalized = str(path or "").rstrip("/")
    lowered = normalized.lower()
    for suffix in _KNOWN_OPENAI_COMPAT_ENDPOINTS:
        if lowered.endswith(suffix):
            return normalized[: -len(suffix)].rstrip("/")
    return normalized


def normalize_openai_compatible_base_url(base_url: Any) -> tuple[str, str]:
    raw = str(base_url or "").strip()
    if not raw:
        raise ValueError("缺少 base_url，无法获取模型列表。")
    if len(raw) > 2048:
        raise ValueError("base_url 过长，无法获取模型列表。")

    parsed = urlsplit(raw)
    scheme = str(parsed.scheme or "").strip().lower()
    if scheme not in {"http", "https"}:
        raise ValueError("base_url must use http or https scheme")
    if not parsed.netloc:
        raise ValueError("base_url is invalid")

    base_path = _strip_known_endpoint(parsed.path)
    normalized_base = urlunsplit((scheme, parsed.netloc, base_path, "", "")).rstrip("/")
    if not normalized_base:
        raise ValueError("base_url is invalid")
    return normalized_base, f"{normalized_base}/models"


def _iter_model_candidates(payload: Any) -> Iterable[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    candidates = payload.get("data")
    if candidates is None:
        candidates = payload.get("models")
    if isinstance(candidates, dict):
        return candidates.values()
    if isinstance(candidates, list):
        return candidates
    return []


def _normalize_model_id(value: Any) -> str:
    if value is None:
        return ""
    rendered = str(value).strip()
    if not rendered or len(rendered) > MAX_MODEL_ID_CHARS:
        return ""
    if any(char in rendered for char in "\r\n\t"):
        return ""
    return rendered


def extract_openai_compatible_model_ids(payload: Any) -> list[str]:
    models: list[str] = []
    seen: set[str] = set()
    for item in _iter_model_candidates(payload):
        if isinstance(item, dict):
            raw_id = item.get("id") or item.get("model") or item.get("name")
        else:
            raw_id = item
        model_id = _normalize_model_id(raw_id)
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        models.append(model_id)
        if len(models) >= MAX_DISCOVERED_MODELS:
            break
    return models


def _status_failure(status_code: int, base_url: str) -> ModelDiscoveryResult:
    if status_code in {401, 403}:
        return ModelDiscoveryResult(
            success=False,
            models=[],
            base_url=base_url,
            message="模型列表获取失败：认证无效或权限不足。",
            code="model_discovery_auth_failed",
        )
    if status_code == 404:
        return ModelDiscoveryResult(
            success=False,
            models=[],
            base_url=base_url,
            message="模型列表获取失败：该端点没有提供 /models。",
            code="model_discovery_not_found",
        )
    if status_code == 429:
        return ModelDiscoveryResult(
            success=False,
            models=[],
            base_url=base_url,
            message="模型列表获取失败：请求过于频繁，请稍后重试。",
            code="model_discovery_rate_limited",
        )
    return ModelDiscoveryResult(
        success=False,
        models=[],
        base_url=base_url,
        message="模型列表获取失败：中转站返回异常状态。",
        code="model_discovery_upstream_failed",
    )


async def fetch_openai_compatible_models(
    base_url: Any,
    *,
    credential: Any = "",
    timeout_sec: float = MODEL_DISCOVERY_TIMEOUT_SEC,
) -> ModelDiscoveryResult:
    normalized_base_url, models_url = normalize_openai_compatible_base_url(base_url)
    headers = {"Accept": "application/json"}
    rendered_credential = str(credential or "").strip()
    if rendered_credential:
        headers["Authorization"] = f"Bearer {rendered_credential}"

    try:
        async with httpx.AsyncClient(
            timeout=float(timeout_sec or MODEL_DISCOVERY_TIMEOUT_SEC),
            follow_redirects=False,
        ) as client:
            response = await client.get(models_url, headers=headers)
    except Exception:
        return ModelDiscoveryResult(
            success=False,
            models=[],
            base_url=normalized_base_url,
            message="模型列表获取失败：无法连接中转站。",
            code="model_discovery_network_failed",
        )

    if response.status_code >= 400:
        return _status_failure(response.status_code, normalized_base_url)

    try:
        payload = response.json()
    except ValueError:
        return ModelDiscoveryResult(
            success=False,
            models=[],
            base_url=normalized_base_url,
            message="模型列表获取失败：中转站返回的不是有效 JSON。",
            code="model_discovery_invalid_json",
        )

    models = extract_openai_compatible_model_ids(payload)
    if not models:
        return ModelDiscoveryResult(
            success=False,
            models=[],
            base_url=normalized_base_url,
            message="模型列表为空，仍可手动输入模型名。",
            code="model_discovery_empty",
        )
    return ModelDiscoveryResult(
        success=True,
        models=models,
        base_url=normalized_base_url,
        message=f"已获取 {len(models)} 个模型。",
        code="",
    )
