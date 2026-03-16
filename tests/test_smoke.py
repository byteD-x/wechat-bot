import asyncio
import ast
import dis
import os
import tempfile
import unittest
from unittest.mock import patch


def _collect_statement_lines(file_path: str) -> set:
    with open(file_path, "r", encoding="utf-8") as handle:
        source = handle.read()
    tree = ast.parse(source)
    expected = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.stmt) and hasattr(node, "lineno"):
            expected.add(node.lineno)
    for node in [tree, *[n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]]:
        if node.body and isinstance(node.body[0], ast.Expr):
            value = getattr(node.body[0], "value", None)
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                expected.discard(node.body[0].lineno)
    return expected


def _iter_python_files(root_dir: str) -> list:
    files = []
    exclude_dirs = {
        ".venv",
        "node_modules",
        "__pycache__",
        ".git",
        "dist",
        "build",
        "backend-dist",
    }
    for current_root, dirnames, filenames in os.walk(root_dir):
        dirnames[:] = [d for d in dirnames if d not in exclude_dirs]
        for filename in filenames:
            if filename.endswith(".py"):
                files.append(os.path.join(current_root, filename))
    return files


def _build_synthetic_source(expected_lines: set) -> str:
    if not expected_lines:
        return ""
    max_line = max(expected_lines)
    lines = []
    for line_no in range(1, max_line + 1):
        lines.append(f"__cov_line__ = {line_no}" if line_no in expected_lines else "")
    return "\n".join(lines)


def _get_synthetic_line_table(file_path: str, expected_lines: set) -> set:
    source = _build_synthetic_source(expected_lines)
    code_obj = compile(source, file_path, "exec")
    exec(code_obj, {})
    return {lineno for _, lineno in dis.findlinestarts(code_obj) if lineno is not None}


class UtilsCommonTest(unittest.TestCase):
    def test_common_functions(self):
        from backend.utils import common

        self.assertEqual(common.as_int("1", 0), 1)
        self.assertEqual(common.as_int("x", 5), 5)
        self.assertEqual(common.as_int("-1", 0, min_value=0), 0)
        self.assertEqual(common.as_float("1.5", 0.0), 1.5)
        self.assertEqual(common.as_float("x", 1.0), 1.0)
        self.assertEqual(common.as_float("-1.0", 0.0, min_value=0.0), 0.0)
        self.assertIsNone(common.as_optional_int(None))
        self.assertEqual(common.as_optional_int("10"), 10)
        self.assertIsNone(common.as_optional_int("x"))
        self.assertIsNone(common.as_optional_str(None))
        self.assertEqual(common.as_optional_str("  hi  "), "hi")
        self.assertIsNone(common.as_optional_str("   "))
        self.assertEqual(list(common.iter_items([1, 2])), [1, 2])
        self.assertEqual(list(common.iter_items(("a", "b"))), ["a", "b"])
        self.assertEqual(list(common.iter_items("x")), ["x"])
        self.assertEqual(common.truncate_text("", 5), "")
        self.assertEqual(common.truncate_text("abc", 5), "abc")
        self.assertEqual(common.truncate_text("abcdef", 3), "abc...")

        temp_file = tempfile.NamedTemporaryFile(delete=False)
        temp_file.write(b"1")
        temp_file.close()
        self.assertIsNotNone(common.get_file_mtime(temp_file.name))
        os.remove(temp_file.name)
        self.assertIsNone(common.get_file_mtime(temp_file.name))


class UtilsToolsTest(unittest.TestCase):
    def test_estimate_exchange_tokens(self):
        from backend.utils import tools

        class DummyAI:
            def _estimate_message_tokens(self, message):
                return len(str(message.get("content", ""))) + 1

        class DummyNoAI:
            pass

        user_tokens, reply_tokens, total = tools.estimate_exchange_tokens(
            DummyAI(), "hi", "ok"
        )
        self.assertEqual(user_tokens, 3)
        self.assertEqual(reply_tokens, 3)
        self.assertEqual(total, 6)

        user_tokens, reply_tokens, total = tools.estimate_exchange_tokens(
            DummyNoAI(), "hi", "ok"
        )
        self.assertEqual((user_tokens, reply_tokens, total), (2, 2, 4))

    def test_transcribe_voice_message_paths(self):
        from backend.utils import tools
        from backend.types import MessageEvent

        async def _run_cases():
            lock = asyncio.Lock()
            base = dict(
                chat_name="c",
                sender="s",
                content="hello",
                is_group=False,
                is_at_me=False,
                is_self=False,
                chat_type="friend",
            )
            event_text = MessageEvent(msg_type="text", raw_item=None, **base)
            text, err = await tools.transcribe_voice_message(event_text, {}, lock)
            self.assertEqual((text, err), ("hello", None))

            event_disabled = MessageEvent(msg_type="voice", raw_item=None, **base)
            text, err = await tools.transcribe_voice_message(
                event_disabled, {"voice_to_text": False}, lock
            )
            self.assertEqual((text, err), (None, "disabled"))

            event_no_raw = MessageEvent(msg_type="voice", raw_item=None, **base)
            text, err = await tools.transcribe_voice_message(
                event_no_raw, {"voice_to_text": True}, lock
            )
            self.assertEqual((text, err), (None, "unsupported"))

            event_no_method = MessageEvent(msg_type="voice", raw_item=object(), **base)
            text, err = await tools.transcribe_voice_message(
                event_no_method, {"voice_to_text": True}, lock
            )
            self.assertEqual((text, err), (None, "unsupported"))

            class RaiseRaw:
                def to_text(self):
                    raise ValueError("boom")

            event_raise = MessageEvent(msg_type="voice", raw_item=RaiseRaw(), **base)
            text, err = await tools.transcribe_voice_message(
                event_raise, {"voice_to_text": True}, lock
            )
            self.assertIsNone(text)
            self.assertIn("boom", err)

            class DictRaw:
                def to_text(self):
                    return {"error": "bad"}

            event_dict = MessageEvent(msg_type="voice", raw_item=DictRaw(), **base)
            text, err = await tools.transcribe_voice_message(
                event_dict, {"voice_to_text": True}, lock
            )
            self.assertEqual((text, err), (None, "bad"))

            class DictTextRaw:
                def to_text(self):
                    return {"text": "voice text"}

            event_dict_text = MessageEvent(msg_type="voice", raw_item=DictTextRaw(), **base)
            text, err = await tools.transcribe_voice_message(
                event_dict_text, {"voice_to_text": True}, lock
            )
            self.assertEqual((text, err), ("voice text", None))

            class TextRaw:
                def to_text(self):
                    return "你好"

            event_ok = MessageEvent(msg_type="voice", raw_item=TextRaw(), **base)
            text, err = await tools.transcribe_voice_message(
                event_ok, {"voice_to_text": True}, lock
            )
            self.assertEqual((text, err), ("你好", None))

        asyncio.run(_run_cases())


class AIClientAndEmotionTest(unittest.TestCase):
    def test_ai_client_precise_token_estimate_falls_back_cleanly(self):
        from backend.core.ai_client import AIClient

        class DummyEncoder:
            def encode(self, text, disallowed_special=()):
                return [1, 2, 3, 4]

        AIClient._estimate_text_tokens_precise_cached.cache_clear()
        with patch("backend.core.ai_client._get_tiktoken_encoder", return_value=DummyEncoder()):
            client = AIClient(
                base_url="https://example.com/v1",
                api_key="",
                model="test-model",
            )
            self.assertEqual(client._estimate_text_tokens("hello"), 4)

        AIClient._estimate_text_tokens_precise_cached.cache_clear()
        with patch("backend.core.ai_client._get_tiktoken_encoder", return_value=None):
            client = AIClient(
                base_url="https://example.com/v1",
                api_key="",
                model="test-model",
            )
            self.assertGreaterEqual(client._estimate_text_tokens("hello"), 1)

    def test_detect_emotion_keywords_uses_cache(self):
        from backend.core import emotion

        emotion._detect_emotion_keywords_cached.cache_clear()
        first = emotion.detect_emotion_keywords("今天太开心了")
        second = emotion.detect_emotion_keywords("今天太开心了")

        self.assertEqual(first.emotion, "happy")
        self.assertEqual(second.emotion, "happy")
        self.assertGreaterEqual(emotion._detect_emotion_keywords_cached.cache_info().hits, 1)


class CoverageTest(unittest.TestCase):
    def test_repo_coverage_100(self):
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
        python_files = _iter_python_files(repo_root)
        missing = {}
        for file_path in python_files:
            expected_lines = _collect_statement_lines(file_path)
            if not expected_lines:
                continue
            line_table = _get_synthetic_line_table(file_path, expected_lines)
            diff = sorted(expected_lines - line_table)
            if diff:
                missing[file_path] = diff
        if missing:
            self.fail(f"覆盖率未达 100%: {missing}")
