"""Generate a Markdown index from Quart route decorators."""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


DEFAULT_SOURCE = Path("backend/api.py")
DEFAULT_OUTPUT = Path("docs/API_ROUTE_INDEX.md")


@dataclass(frozen=True)
class ApiRoute:
    path: str
    methods: tuple[str, ...]
    handler: str
    line: int


def parse_api_routes(source_path: str | Path) -> list[ApiRoute]:
    path = Path(source_path)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    routes: list[ApiRoute] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            route = _parse_route_decorator(decorator, handler=node.name)
            if route is not None:
                routes.append(route)
    return sorted(routes, key=lambda item: (item.path, item.methods, item.handler, item.line))


def build_markdown(routes: Sequence[ApiRoute], *, source_path: str | Path) -> str:
    source = _normalize_markdown_path(source_path)
    lines = [
        "# API Route Index",
        "",
        "本文件由 `scripts/generate_api_route_index.py` 从 `backend/api.py` 的 `@app.route` 装饰器静态生成。",
        "它只记录路由、方法、处理函数和源码行号，用于发现接口清单漂移；详细请求、响应和安全边界仍以 `docs/api.md` 为准。",
        "",
        "生成命令：",
        "",
        "```powershell",
        r".\.venv\Scripts\python.exe scripts\generate_api_route_index.py",
        "```",
        "",
        f"- Source: `{source}`",
        f"- Route count: `{len(routes)}`",
        "",
        "| Methods | Path | Handler | Source |",
        "| --- | --- | --- | --- |",
    ]
    for route in routes:
        methods = ", ".join(route.methods)
        lines.append(
            f"| `{_escape_table(methods)}` "
            f"| `{_escape_table(route.path)}` "
            f"| `{_escape_table(route.handler)}` "
            f"| `{source}:{route.line}` |"
        )
    return "\n".join(lines) + "\n"


def generate_route_index(
    *,
    source_path: str | Path = DEFAULT_SOURCE,
    output_path: str | Path = DEFAULT_OUTPUT,
) -> str:
    routes = parse_api_routes(source_path)
    markdown = build_markdown(routes, source_path=source_path)
    Path(output_path).write_text(markdown, encoding="utf-8")
    return markdown


def _parse_route_decorator(node: ast.AST, *, handler: str) -> ApiRoute | None:
    if not isinstance(node, ast.Call) or not _is_app_route(node.func):
        return None
    if not node.args:
        return None
    path = _literal_string(node.args[0])
    if not path:
        return None
    return ApiRoute(
        path=path,
        methods=tuple(_extract_methods(node.keywords)),
        handler=handler,
        line=int(getattr(node, "lineno", 0) or 0),
    )


def _is_app_route(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "route"
        and isinstance(node.value, ast.Name)
        and node.value.id == "app"
    )


def _extract_methods(keywords: Iterable[ast.keyword]) -> list[str]:
    for keyword in keywords:
        if keyword.arg == "methods":
            methods = _literal_string_sequence(keyword.value)
            if methods:
                return sorted({item.upper() for item in methods})
            return ["GET"]
    return ["GET"]


def _literal_string_sequence(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return [
            value
            for item in node.elts
            if (value := _literal_string(item))
        ]
    return []


def _literal_string(node: ast.AST) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return ""


def _normalize_markdown_path(path: str | Path) -> str:
    return Path(path).as_posix()


def _escape_table(value: str) -> str:
    return str(value).replace("|", r"\|")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate docs/API_ROUTE_INDEX.md from backend/api.py routes.",
    )
    parser.add_argument("--source", default=str(DEFAULT_SOURCE), help="Python source file to parse")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Markdown file to write")
    args = parser.parse_args(argv)
    generate_route_index(source_path=args.source, output_path=args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
