import pytest

from scripts.generate_release_notes import (
    build_compare_url,
    classify_commit,
    load_release_notes,
)
from scripts.validate_release_metadata import validate_release_notes


def _write_release_notes(project_root, tag: str, text: str):
    notes_path = project_root / "docs" / "release_notes" / f"{tag}.md"
    notes_path.parent.mkdir(parents=True)
    notes_path.write_text(text.strip() + "\n", encoding="utf-8")
    return notes_path


def test_classify_commit_supports_conventional_commits():
    commit_type, subject, breaking = classify_commit("feat(build): add release workflow")
    assert commit_type == "feat"
    assert subject == "add release workflow"
    assert breaking is False


def test_classify_commit_marks_non_conventional_as_other():
    commit_type, subject, breaking = classify_commit("Update release process")
    assert commit_type == "other"
    assert subject == "Update release process"
    assert breaking is False


def test_build_compare_url_uses_previous_and_current_tag():
    assert (
        build_compare_url("https://github.com/byteD-x/wechat-bot", "v1.1.0", "v1.2.0")
        == "https://github.com/byteD-x/wechat-bot/compare/v1.1.0...v1.2.0"
    )


def test_manual_release_notes_are_loaded_and_match_metadata_rules(tmp_path):
    notes = """# v1.2.0 更新内容

## Features

- 新增 Windows 安装包发布入口，用户可以从 GitHub Release 下载 setup 和 portable 产物。

## Fixes

- 修复发布说明读取手工 notes 时的路径校验，避免生成旧的提交历史正文。
"""
    _write_release_notes(tmp_path, "v1.2.0", notes)

    assert load_release_notes(tmp_path, "v1.2.0") == notes.strip()
    validate_release_notes(tmp_path, "v1.2.0")


def test_release_metadata_rejects_legacy_rendered_notes(tmp_path):
    legacy_notes = """# v1.2.0 更新说明

Compare 链接: [`v1.1.0...v1.2.0`](https://github.com/byteD-x/wechat-bot/compare/v1.1.0...v1.2.0)

### 功能新增
- switch release to GitHub Actions (`aaaaaaa`)

## 原始提交列表
- `aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa` feat(build): switch release to GitHub Actions
"""
    _write_release_notes(tmp_path, "v1.2.0", legacy_notes)

    with pytest.raises(SystemExit, match="Release notes title"):
        validate_release_notes(tmp_path, "v1.2.0")


def test_release_metadata_rejects_commit_hashes(tmp_path):
    notes = """# v1.2.0 更新内容

## Fixes

- 修复发布说明中泄露提交记录的问题，相关提交为 aaaaaaa。
"""
    _write_release_notes(tmp_path, "v1.2.0", notes)

    with pytest.raises(SystemExit, match="commit hashes"):
        validate_release_notes(tmp_path, "v1.2.0")
