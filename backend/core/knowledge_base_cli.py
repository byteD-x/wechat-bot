from __future__ import annotations

import argparse
import http.client
import ipaddress
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Union

from backend.core.knowledge_base import (
    KNOWLEDGE_AUTO_INDEX_INBOX_DIRNAME,
    MAX_KNOWLEDGE_CONTENT_CHARS,
    build_knowledge_auto_index_job_documents,
    build_knowledge_auto_index_preview_payload,
    build_knowledge_dry_run_payload,
    parse_knowledge_document_payload,
    redact_knowledge_local_path,
)
from backend.shared_config import ensure_data_root


_GLOB_CHARS = set("*?[]")
_TEXT_EXTENSIONS = {".txt", ".text", ".md", ".markdown", ".mdown", ".mkd"}


def _print_json(payload: Dict[str, Any]) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _is_loopback_host(value: str) -> bool:
    normalized = str(value or "").strip().lower().rstrip(".")
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _redacted_path(path: Union[Path, str]) -> str:
    return redact_knowledge_local_path(str(path))


def _collect_explicit_files(args: argparse.Namespace) -> List[Path]:
    raw_values: List[str] = []
    raw_values.extend(str(item or "").strip() for item in list(getattr(args, "files", []) or []))
    raw_values.extend(str(item or "").strip() for item in list(getattr(args, "file_paths", []) or []))
    raw_values = [item for item in raw_values if item]
    if not raw_values:
        raise ValueError("请至少显式传入一个文件路径")

    files: List[Path] = []
    for raw in raw_values:
        if any(char in raw for char in _GLOB_CHARS):
            raise ValueError(f"不支持通配符或 glob 路径: {redact_knowledge_local_path(raw)}")
        path = Path(raw).expanduser()
        if path.is_dir():
            raise ValueError(f"不支持目录导入，请显式传入文件: {_redacted_path(path)}")
        if not path.is_file():
            raise ValueError(f"文件不存在或不可读取: {_redacted_path(path)}")
        if path.suffix.lower() not in _TEXT_EXTENSIONS:
            raise ValueError(f"仅支持纯文本或 Markdown 文件: {_redacted_path(path)}")
        files.append(path)
    return files


def _read_explicit_text_file(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(f"文件不是有效 UTF-8 文本: {_redacted_path(path)}") from exc
    except OSError as exc:
        raise ValueError(f"文件读取失败: {_redacted_path(path)}") from exc
    if len(text) > MAX_KNOWLEDGE_CONTENT_CHARS:
        raise ValueError(
            f"文件内容过长: {_redacted_path(path)}，最多 {MAX_KNOWLEDGE_CONTENT_CHARS} 字符"
        )
    return text


def _infer_content_type(path: Path, requested: str) -> str:
    normalized = str(requested or "auto").strip().lower()
    if normalized in {"text", "markdown"}:
        return normalized
    if path.suffix.lower() in {".md", ".markdown", ".mdown", ".mkd"}:
        return "markdown"
    return "text"


def _build_file_payload(path: Path, content: str, args: argparse.Namespace, *, total_files: int) -> Dict[str, Any]:
    if total_files > 1 and str(getattr(args, "doc_id", "") or "").strip():
        raise ValueError("--doc-id 只允许在单文件导入时使用")
    if total_files > 1 and str(getattr(args, "url", "") or "").strip():
        raise ValueError("--url 只允许在单文件导入时使用")

    source_file = _redacted_path(path)
    payload: Dict[str, Any] = {
        "content": content,
        "content_type": _infer_content_type(path, str(getattr(args, "content_type", "auto") or "auto")),
        "version": str(getattr(args, "version", "") or "v1").strip() or "v1",
        "source_file": source_file,
    }
    doc_id = str(getattr(args, "doc_id", "") or "").strip()
    if doc_id:
        payload["doc_id"] = redact_knowledge_local_path(doc_id)
    else:
        payload["doc_id"] = source_file
    url = str(getattr(args, "url", "") or "").strip()
    if url:
        payload["url"] = redact_knowledge_local_path(url)
    return payload


def _preview_file(path: Path, args: argparse.Namespace, *, total_files: int) -> Dict[str, Any]:
    content = _read_explicit_text_file(path)
    document = parse_knowledge_document_payload(_build_file_payload(path, content, args, total_files=total_files))
    preview = build_knowledge_dry_run_payload(document)
    return {
        "success": bool(preview.get("success", False)),
        "path": _redacted_path(path),
        "source_file": str(document.source_file or ""),
        "doc_id": str(preview.get("doc_id") or ""),
        "version": str(preview.get("version") or ""),
        "char_count": int(preview.get("char_count") or 0),
        "chunk_count": int(preview.get("chunk_count") or 0),
        "chunk_ids": list(preview.get("chunk_ids") or []),
        "chunks": list(preview.get("chunks") or []),
        "_payload": _build_file_payload(path, content, args, total_files=total_files),
    }


def _build_import_preview(files: Iterable[Path], args: argparse.Namespace) -> Dict[str, Any]:
    file_list = list(files)
    entries = []
    for path in file_list:
        entry = _preview_file(path, args, total_files=len(file_list))
        payload = entry.pop("_payload")
        entry["_payload"] = payload
        entries.append(entry)
    return {
        "success": True,
        "dry_run": True,
        "mode": "preview",
        "total_files": len(entries),
        "total_chunks": sum(int(item.get("chunk_count") or 0) for item in entries),
        "files": entries,
        "warning": "默认仅预览知识库分块；如需写入运行中的本机服务，请显式传入 --apply。",
    }


def _build_inbox_preview(args: argparse.Namespace) -> Dict[str, Any]:
    inbox_dir = ensure_data_root() / KNOWLEDGE_AUTO_INDEX_INBOX_DIRNAME
    preview = build_knowledge_auto_index_preview_payload(
        inbox_dir,
        version=str(getattr(args, "version", "v1") or "v1").strip() or "v1",
    )
    preview["mode"] = "auto-index-preview"
    preview["warning"] = "固定 inbox 仅做只读预览；如需写入请显式传入 --apply。"
    return preview


def _build_inbox_job_documents(preview: Dict[str, Any], args: argparse.Namespace) -> List[Dict[str, Any]]:
    inbox_dir = ensure_data_root() / KNOWLEDGE_AUTO_INDEX_INBOX_DIRNAME
    version = str(getattr(args, "version", "v1") or "v1").strip() or "v1"
    return [
        {
            "content": document.content,
            "content_type": str((document.metadata or {}).get("content_type") or "text"),
            "doc_id": str(document.doc_id or ""),
            "version": str(document.version or version),
            "source_file": str(document.source_file or ""),
            "url": str(document.url or ""),
            "metadata": dict(document.metadata or {}),
        }
        for document in build_knowledge_auto_index_job_documents(
            inbox_dir,
            preview,
            version=version,
        )
    ]


def _apply_inbox_import(preview: Dict[str, Any], args: argparse.Namespace) -> Dict[str, Any]:
    documents = _build_inbox_job_documents(preview, args)
    payload = {
        "mode": "rebuild",
        "documents": documents,
    }
    return _post_json_to_local_api(
        host=str(getattr(args, "host", "127.0.0.1") or "127.0.0.1"),
        port=int(getattr(args, "port", 5000) or 5000),
        endpoint="/api/knowledge_base/jobs",
        payload=payload,
    )


def cmd_import_inbox(args: argparse.Namespace) -> int:
    try:
        preview = _build_inbox_preview(args)
        if bool(getattr(args, "apply", False)):
            if int(preview.get("document_count") or 0) <= 0:
                raise ValueError("fixed inbox does not contain any importable documents")
            job = _apply_inbox_import(preview, args)
            payload = {
                "success": bool(job.get("success", False)),
                "dry_run": False,
                "mode": "rebuild",
                "total_files": int(preview.get("document_count") or 0),
                "total_chunks": int(preview.get("chunk_count") or 0),
                "job": job,
                "files": list(preview.get("documents") or []),
            }
        else:
            payload = preview
    except Exception as exc:
        payload = {
            "success": False,
            "dry_run": not bool(getattr(args, "apply", False)),
            "message": str(exc),
        }
        if bool(getattr(args, "json", False)):
            _print_json(payload)
        else:
            print(f"知识库固定 inbox 导入失败: {exc}")
        return 1

    if bool(getattr(args, "json", False)):
        _print_json(payload)
    else:
        print("Knowledge base inbox import")
        print("-" * 50)
        file_count = payload.get("document_count", payload.get("total_files", 0))
        print(f"Mode: {payload.get('mode')} / files={file_count}")
        if payload.get("dry_run"):
            print(f"Chunks: {payload.get('chunk_count', 0)}")
            print(str(payload.get("warning") or ""))
        for item in list(payload.get("documents") or []):
            print(
                f"- {item.get('name')} / doc={item.get('doc_id')} / "
                f"chunks={item.get('chunk_count', item.get('result', {}).get('indexed_chunks', '-'))}"
            )
    return 0 if payload.get("success") else 1


def _post_json_to_local_api(
    *,
    host: str,
    port: int,
    endpoint: str,
    payload: Dict[str, Any],
    timeout: float = 30.0,
) -> Dict[str, Any]:
    if not _is_loopback_host(host):
        raise ValueError("知识库 CLI 只允许调用 loopback 本机 API")
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    auth_value = str(os.environ.get("WECHAT_BOT_API_TOKEN") or "").strip()
    if auth_value:
        headers["X-Api-Token"] = auth_value

    conn: Optional[http.client.HTTPConnection] = None
    try:
        conn = http.client.HTTPConnection(host, int(port), timeout=timeout)
        conn.request("POST", endpoint, body=body, headers=headers)
        response = conn.getresponse()
        raw = response.read()
        try:
            data = json.loads(raw.decode("utf-8", errors="replace"))
        except Exception:
            data = {"success": False, "message": "invalid_json_response"}
        if response.status >= 400:
            data["success"] = False
            data.setdefault("status", response.status)
        return data
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _apply_import(files: List[Dict[str, Any]], args: argparse.Namespace) -> Dict[str, Any]:
    endpoint = "/api/knowledge_base/rebuild" if bool(getattr(args, "rebuild", False)) else "/api/knowledge_base/ingest"
    results = []
    for item in files:
        payload = dict(item.get("_payload") or {})
        result = _post_json_to_local_api(
            host=str(getattr(args, "host", "127.0.0.1") or "127.0.0.1"),
            port=int(getattr(args, "port", 5000) or 5000),
            endpoint=endpoint,
            payload=payload,
        )
        results.append(
            {
                "path": item.get("path"),
                "doc_id": item.get("doc_id"),
                "endpoint": endpoint,
                "success": bool(result.get("success", False)),
                "result": result,
            }
        )
    success = all(bool(item.get("success")) for item in results)
    return {
        "success": success,
        "dry_run": False,
        "mode": "rebuild" if bool(getattr(args, "rebuild", False)) else "ingest",
        "total_files": len(results),
        "files": results,
    }


def cmd_import_files(args: argparse.Namespace) -> int:
    try:
        files = _collect_explicit_files(args)
        preview = _build_import_preview(files, args)
        if bool(getattr(args, "apply", False)):
            payload = _apply_import(list(preview.get("files") or []), args)
        else:
            for item in list(preview.get("files") or []):
                item.pop("_payload", None)
            payload = preview
    except Exception as exc:
        payload = {
            "success": False,
            "dry_run": not bool(getattr(args, "apply", False)),
            "message": str(exc),
        }
        if bool(getattr(args, "json", False)):
            _print_json(payload)
        else:
            print(f"知识库导入失败: {exc}")
        return 1

    if bool(getattr(args, "json", False)):
        _print_json(payload)
    else:
        print("Knowledge base import")
        print("-" * 50)
        print(f"Mode: {payload.get('mode')} / files={payload.get('total_files', 0)}")
        if payload.get("dry_run"):
            print(f"Chunks: {payload.get('total_chunks', 0)}")
            print(str(payload.get("warning") or ""))
        for item in list(payload.get("files") or []):
            print(
                f"- {item.get('path')} / doc={item.get('doc_id')} / "
                f"chunks={item.get('chunk_count', item.get('result', {}).get('indexed_chunks', '-'))}"
            )
    return 0 if payload.get("success") else 1


def build_knowledge_base_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "knowledge-base",
        help="知识库治理 CLI",
        description="Preview or import explicit text/Markdown files into the local knowledge base.",
    )
    knowledge_subparsers = parser.add_subparsers(
        dest="knowledge_base_command",
        metavar="<knowledge-base-command>",
    )
    knowledge_subparsers.required = True

    parser_import = knowledge_subparsers.add_parser(
        "import-files",
        help="preview or import explicit text/Markdown files",
        description=(
            "Preview chunking for explicitly provided text/Markdown files by default, "
            "or import them into the running local Web API with --apply."
        ),
    )
    parser_import.add_argument("files", nargs="*", help="Explicit text/Markdown file paths.")
    parser_import.add_argument(
        "--file",
        dest="file_paths",
        action="append",
        default=[],
        help="Explicit text/Markdown file path. Can be repeated.",
    )
    parser_import.add_argument(
        "--apply",
        action="store_true",
        help="Call the running local Web API to ingest the previewed files.",
    )
    parser_import.add_argument(
        "--rebuild",
        action="store_true",
        help="With --apply, replace existing chunks for the same doc_id.",
    )
    parser_import.add_argument(
        "--content-type",
        choices=("auto", "text", "markdown"),
        default="auto",
        help="Content type for all files. Defaults to extension-based auto detection.",
    )
    parser_import.add_argument("--version", default="v1", help="Document version metadata.")
    parser_import.add_argument("--doc-id", default="", help="Optional doc_id for single-file import.")
    parser_import.add_argument("--url", default="", help="Optional source URL for single-file import.")
    parser_import.add_argument("--host", default="127.0.0.1", help="Local Web API host for --apply.")
    parser_import.add_argument("--port", type=int, default=5000, help="Local Web API port for --apply.")
    parser_import.add_argument("--json", action="store_true", help="Output JSON.")
    parser_import.set_defaults(func=cmd_import_files)

    parser_inbox = knowledge_subparsers.add_parser(
        "import-inbox",
        help="preview or import the fixed knowledge-base inbox",
        description=(
            "Preview the fixed data/knowledge_base/inbox directory by default, "
            "or submit its previewed documents to the running local Web API with --apply."
        ),
        )
    parser_inbox.add_argument(
        "--apply",
        action="store_true",
        help="Call the running local Web API to queue the previewed inbox documents.",
    )
    parser_inbox.add_argument("--version", default="v1", help="Document version metadata.")
    parser_inbox.add_argument("--host", default="127.0.0.1", help="Local Web API host for --apply.")
    parser_inbox.add_argument("--port", type=int, default=5000, help="Local Web API port for --apply.")
    parser_inbox.add_argument("--json", action="store_true", help="Output JSON.")
    parser_inbox.set_defaults(func=cmd_import_inbox)


__all__ = [
    "build_knowledge_base_parser",
    "cmd_import_inbox",
    "cmd_import_files",
]
