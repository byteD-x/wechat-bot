"""Check frontend/backend API contract drift."""

from __future__ import annotations

import argparse
import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence
from urllib.parse import urlsplit

try:
    from scripts.generate_api_route_index import parse_api_routes
except ModuleNotFoundError:  # pragma: no cover - supports direct script execution.
    from generate_api_route_index import parse_api_routes


DEFAULT_BACKEND_SOURCE = Path("backend/api.py")
DEFAULT_IPC_SOURCE = Path("src/main/ipc.js")
DEFAULT_API_SERVICE_SOURCE = Path("src/renderer/js/services/ApiService.js")


IPC_BACKEND_ROUTE_EXCEPTIONS: dict[str, str] = {}
API_SERVICE_IPC_EXCEPTIONS: dict[str, str] = {}
IDEMPOTENCY_STRATEGY_EXCEPTIONS: dict[tuple[str, str], str] = {}


@dataclass(frozen=True)
class ContractIssue:
    code: str
    message: str
    path: str = ""
    detail: str = ""


@dataclass(frozen=True)
class RegexPattern:
    source: str
    pattern: re.Pattern[str]


@dataclass(frozen=True)
class ApiServiceEndpoint:
    path: str
    line: int
    expression: str


@dataclass(frozen=True)
class HighSideEffectPostEndpoint:
    path: str
    reason: str
    sample_path: str | None = None

    @property
    def method(self) -> str:
        return "POST"

    @property
    def coverage_path(self) -> str:
        return self.sample_path or self.path


DEFAULT_HIGH_SIDE_EFFECT_POST_ENDPOINTS: tuple[HighSideEffectPostEndpoint, ...] = (
    HighSideEffectPostEndpoint("/api/send", "sends a WeChat message"),
    HighSideEffectPostEndpoint("/api/restart", "restarts the bot runtime"),
    HighSideEffectPostEndpoint("/api/backups", "creates a backup artifact"),
    HighSideEffectPostEndpoint("/api/backups/restore", "restores local runtime data"),
    HighSideEffectPostEndpoint("/api/data_controls/clear", "clears local runtime data"),
    HighSideEffectPostEndpoint(
        "/api/v1/admin/prompts/{revision}/rollback",
        "creates a replacement active prompt revision",
        sample_path="/api/v1/admin/prompts/1/rollback",
    ),
)


@dataclass(frozen=True)
class ContractCheckResult:
    issues: tuple[ContractIssue, ...]
    backend_routes: frozenset[str]
    ipc_fixed_paths: frozenset[str]
    api_service_fixed_paths: frozenset[str]
    backend_idempotent_posts: frozenset[str]
    api_service_idempotent_posts: frozenset[str]

    @property
    def ok(self) -> bool:
        return not self.issues


def check_frontend_backend_contract(
    *,
    backend_source: str | Path = DEFAULT_BACKEND_SOURCE,
    ipc_source: str | Path = DEFAULT_IPC_SOURCE,
    api_service_source: str | Path = DEFAULT_API_SERVICE_SOURCE,
    high_side_effect_post_endpoints: Sequence[HighSideEffectPostEndpoint] = DEFAULT_HIGH_SIDE_EFFECT_POST_ENDPOINTS,
) -> ContractCheckResult:
    backend_routes = frozenset(route.path for route in parse_api_routes(backend_source))
    backend_idempotent_posts = frozenset(
        path
        for method, path in parse_backend_idempotent_endpoints(backend_source)
        if method == "POST"
    )
    ipc_fixed_paths, ipc_patterns = parse_ipc_allowlist(ipc_source)
    api_service_endpoints = parse_api_service_request_endpoints(api_service_source)
    api_service_fixed_paths = frozenset(endpoint.path for endpoint in api_service_endpoints)
    api_service_idempotent_posts, api_service_idempotent_patterns = parse_api_service_idempotent_posts(
        api_service_source
    )

    issues: list[ContractIssue] = []
    issues.extend(_validate_reasoned_exceptions("ipc route exception", IPC_BACKEND_ROUTE_EXCEPTIONS))
    issues.extend(_validate_reasoned_exceptions("api service ipc exception", API_SERVICE_IPC_EXCEPTIONS))
    issues.extend(_validate_reasoned_exceptions("idempotency exception", IDEMPOTENCY_STRATEGY_EXCEPTIONS))

    for path in sorted(ipc_fixed_paths):
        if path in backend_routes or path in IPC_BACKEND_ROUTE_EXCEPTIONS:
            continue
        issues.append(
            ContractIssue(
                code="ipc_path_missing_backend_route",
                path=path,
                message="IPC fixed allowlist path is not declared as a backend route.",
            )
        )

    for endpoint in sorted(api_service_endpoints, key=lambda item: (item.path, item.line, item.expression)):
        if _is_path_allowed_by_ipc(endpoint.path, ipc_fixed_paths, ipc_patterns):
            continue
        if endpoint.path in API_SERVICE_IPC_EXCEPTIONS:
            continue
        issues.append(
            ContractIssue(
                code="api_service_path_missing_ipc_allowlist",
                path=endpoint.path,
                detail=f"{api_service_source}:{endpoint.line}",
                message="ApiService fixed request path is not covered by the Electron IPC allowlist.",
            )
        )

    for endpoint in high_side_effect_post_endpoints:
        if not endpoint.reason.strip():
            issues.append(
                ContractIssue(
                    code="high_side_effect_endpoint_missing_reason",
                    path=endpoint.path,
                    message="High-side-effect POST endpoint declaration must include a reason.",
                )
            )
            continue
        if _has_idempotency_strategy(
            endpoint,
            backend_idempotent_posts=backend_idempotent_posts,
            api_service_idempotent_posts=api_service_idempotent_posts,
            api_service_idempotent_patterns=api_service_idempotent_patterns,
        ):
            continue
        issues.append(
            ContractIssue(
                code="high_side_effect_post_missing_idempotency",
                path=endpoint.path,
                message="High-side-effect POST endpoint has no backend, ApiService, or script idempotency strategy.",
            )
        )

    return ContractCheckResult(
        issues=tuple(issues),
        backend_routes=backend_routes,
        ipc_fixed_paths=frozenset(ipc_fixed_paths),
        api_service_fixed_paths=api_service_fixed_paths,
        backend_idempotent_posts=backend_idempotent_posts,
        api_service_idempotent_posts=frozenset(api_service_idempotent_posts),
    )


def parse_backend_idempotent_endpoints(source_path: str | Path) -> set[tuple[str, str]]:
    path = Path(source_path)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    endpoints: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        value = _assignment_value_for_name(node, "_IDEMPOTENT_ENDPOINTS")
        if value is None:
            continue
        for item in _literal_tuple_pairs(value):
            endpoints.add((item[0].upper(), item[1]))
    return endpoints


def parse_ipc_allowlist(source_path: str | Path) -> tuple[set[str], list[RegexPattern]]:
    source = Path(source_path).read_text(encoding="utf-8")
    fixed_block = _extract_js_array_block(source, "ALLOWED_BACKEND_PATHS")
    pattern_block = _extract_js_array_block(source, "ALLOWED_BACKEND_PATH_PATTERNS")
    fixed_paths = {
        value
        for value in _iter_js_string_literals(fixed_block)
        if value.startswith("/api/")
    }
    patterns = [
        RegexPattern(source=body, pattern=re.compile(body))
        for body, _flags in _iter_js_regex_literals(pattern_block)
    ]
    return fixed_paths, patterns


def parse_api_service_request_endpoints(source_path: str | Path) -> list[ApiServiceEndpoint]:
    source = Path(source_path).read_text(encoding="utf-8")
    endpoints: dict[tuple[str, int, str], ApiServiceEndpoint] = {}
    for expression, line in _iter_call_first_arguments(source, "this.request"):
        path = _fixed_api_path_from_js_expression(expression)
        if not path:
            continue
        endpoint = ApiServiceEndpoint(path=path, line=line, expression=expression.strip())
        endpoints[(endpoint.path, endpoint.line, endpoint.expression)] = endpoint
    return list(endpoints.values())


def parse_api_service_idempotent_posts(source_path: str | Path) -> tuple[set[str], list[RegexPattern]]:
    source = Path(source_path).read_text(encoding="utf-8")
    fixed_block = _extract_js_array_block(source, "idempotentPostEndpoints")
    fixed_paths = {
        value
        for value in _iter_js_string_literals(fixed_block)
        if value.startswith("/api/")
    }
    patterns = [
        RegexPattern(source=body, pattern=re.compile(body))
        for body, _flags, _start, end in _iter_js_regex_literals_with_offsets(source)
        if source[end:].lstrip().startswith(".test(normalizedEndpoint)")
    ]
    return fixed_paths, patterns


def _assignment_value_for_name(node: ast.AST, name: str) -> ast.AST | None:
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == name:
                return node.value
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
        return node.value
    return None


def _literal_tuple_pairs(node: ast.AST) -> Iterable[tuple[str, str]]:
    if not isinstance(node, (ast.Set, ast.List, ast.Tuple)):
        return []
    pairs: list[tuple[str, str]] = []
    for item in node.elts:
        if not isinstance(item, (ast.Tuple, ast.List)) or len(item.elts) != 2:
            continue
        first = _literal_string(item.elts[0])
        second = _literal_string(item.elts[1])
        if first and second:
            pairs.append((first, second))
    return pairs


def _literal_string(node: ast.AST) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return ""


def _extract_js_array_block(source: str, name: str) -> str:
    name_index = source.find(name)
    if name_index < 0:
        return ""
    open_index = source.find("[", name_index)
    if open_index < 0:
        return ""
    close_index = _find_matching_bracket(source, open_index, "[", "]")
    if close_index < 0:
        return ""
    return source[open_index + 1 : close_index]


def _find_matching_bracket(source: str, open_index: int, opener: str, closer: str) -> int:
    depth = 0
    quote = ""
    escape = False
    for index in range(open_index, len(source)):
        char = source[index]
        if quote:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == quote:
                quote = ""
            continue
        if char in ("'", '"', "`"):
            quote = char
            continue
        if char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return index
    return -1


def _iter_js_string_literals(source: str) -> Iterable[str]:
    index = 0
    while index < len(source):
        char = source[index]
        if char not in ("'", '"'):
            index += 1
            continue
        start = index
        index += 1
        escape = False
        while index < len(source):
            current = source[index]
            if escape:
                escape = False
            elif current == "\\":
                escape = True
            elif current == char:
                yield _decode_js_string(source[start : index + 1])
                index += 1
                break
            index += 1
        else:
            break


def _decode_js_string(literal: str) -> str:
    body = literal[1:-1]
    return (
        body.replace(r"\/", "/")
        .replace(r"\'", "'")
        .replace(r"\"", '"')
        .replace(r"\n", "\n")
        .replace(r"\r", "\r")
        .replace(r"\t", "\t")
        .replace(r"\\", "\\")
    )


def _iter_js_regex_literals(source: str) -> Iterable[tuple[str, str]]:
    for body, flags, _start, _end in _iter_js_regex_literals_with_offsets(source):
        yield body, flags


def _iter_js_regex_literals_with_offsets(source: str) -> Iterable[tuple[str, str, int, int]]:
    index = 0
    while index < len(source):
        if source[index] != "/":
            index += 1
            continue
        start = index
        index += 1
        escape = False
        in_class = False
        body_chars: list[str] = []
        while index < len(source):
            char = source[index]
            if escape:
                body_chars.append(char)
                escape = False
            elif char == "\\":
                body_chars.append(char)
                escape = True
            elif char == "[":
                body_chars.append(char)
                in_class = True
            elif char == "]":
                body_chars.append(char)
                in_class = False
            elif char == "/" and not in_class:
                index += 1
                flags_start = index
                while index < len(source) and source[index].isalpha():
                    index += 1
                flags = source[flags_start:index]
                yield "".join(body_chars), flags, start, index
                break
            else:
                body_chars.append(char)
            index += 1
        else:
            break


def _iter_call_first_arguments(source: str, callee: str) -> Iterable[tuple[str, int]]:
    pattern = re.compile(rf"\b{re.escape(callee)}\s*\(")
    for match in pattern.finditer(source):
        expression, end_index = _extract_first_argument(source, match.end())
        if end_index < 0:
            continue
        line = source.count("\n", 0, match.start()) + 1
        yield expression, line


def _extract_first_argument(source: str, start_index: int) -> tuple[str, int]:
    index = start_index
    depth = 0
    quote = ""
    escape = False
    while index < len(source):
        char = source[index]
        if quote:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == quote:
                quote = ""
            index += 1
            continue
        if char in ("'", '"', "`"):
            quote = char
            index += 1
            continue
        if char in "([{":
            depth += 1
        elif char in ")]}":
            if depth == 0:
                return source[start_index:index].strip(), index
            depth -= 1
        elif char == "," and depth == 0:
            return source[start_index:index].strip(), index
        index += 1
    return "", -1


def _fixed_api_path_from_js_expression(expression: str) -> str:
    stripped = expression.strip()
    if len(stripped) < 2:
        return ""
    if stripped[0] in ("'", '"') and stripped[-1] == stripped[0]:
        return _normalize_api_path(_decode_js_string(stripped))
    if stripped[0] == "`" and stripped[-1] == "`":
        body = stripped[1:-1]
        expression_index = body.find("${")
        prefix = body if expression_index < 0 else body[:expression_index]
        if prefix.endswith("/"):
            return ""
        return _normalize_api_path(prefix)
    return ""


def _normalize_api_path(value: str) -> str:
    if not value.startswith("/api/"):
        return ""
    return urlsplit(value).path


def _is_path_allowed_by_ipc(path: str, fixed_paths: set[str], patterns: Sequence[RegexPattern]) -> bool:
    return path in fixed_paths or any(pattern.pattern.fullmatch(path) for pattern in patterns)


def _has_idempotency_strategy(
    endpoint: HighSideEffectPostEndpoint,
    *,
    backend_idempotent_posts: set[str] | frozenset[str],
    api_service_idempotent_posts: set[str] | frozenset[str],
    api_service_idempotent_patterns: Sequence[RegexPattern],
) -> bool:
    key = (endpoint.method, endpoint.path)
    coverage_path = endpoint.coverage_path
    return (
        coverage_path in backend_idempotent_posts
        or coverage_path in api_service_idempotent_posts
        or any(pattern.pattern.fullmatch(coverage_path) for pattern in api_service_idempotent_patterns)
        or key in IDEMPOTENCY_STRATEGY_EXCEPTIONS
    )


def _validate_reasoned_exceptions(label: str, mapping: dict) -> list[ContractIssue]:
    issues: list[ContractIssue] = []
    for key, reason in mapping.items():
        if str(reason or "").strip():
            continue
        issues.append(
            ContractIssue(
                code="contract_exception_missing_reason",
                path=str(key),
                message=f"{label} must include a non-empty reason.",
            )
        )
    return issues


def _format_issue(issue: ContractIssue) -> str:
    parts = [f"[{issue.code}]", issue.path, issue.message]
    if issue.detail:
        parts.append(issue.detail)
    return " ".join(part for part in parts if part)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check frontend/backend API contract drift.")
    parser.add_argument("--backend-source", default=str(DEFAULT_BACKEND_SOURCE))
    parser.add_argument("--ipc-source", default=str(DEFAULT_IPC_SOURCE))
    parser.add_argument("--api-service-source", default=str(DEFAULT_API_SERVICE_SOURCE))
    args = parser.parse_args(argv)

    result = check_frontend_backend_contract(
        backend_source=args.backend_source,
        ipc_source=args.ipc_source,
        api_service_source=args.api_service_source,
    )
    if result.ok:
        print("Frontend/backend contract check passed.")
        return 0

    print("Frontend/backend contract check failed:")
    for issue in result.issues:
        print(f"- {_format_issue(issue)}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
