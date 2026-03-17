from scripts.generate_release_notes import (
    CommitEntry,
    build_compare_url,
    classify_commit,
    render_release_notes,
)


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


def test_render_release_notes_groups_commits_and_lists_raw_history():
    commits = [
        CommitEntry(full_sha="a" * 40, short_sha="aaaaaaa", subject="feat(build): switch release to GitHub Actions"),
        CommitEntry(full_sha="b" * 40, short_sha="bbbbbbb", subject="fix(build): exclude runtime data from package"),
        CommitEntry(full_sha="c" * 40, short_sha="ccccccc", subject="Update release docs"),
    ]

    notes = render_release_notes(
        current_tag="v1.2.0",
        previous_tag="v1.1.0",
        repository_url="https://github.com/byteD-x/wechat-bot",
        commits=commits,
    )

    assert "# v1.2.0 更新说明" in notes
    assert "`v1.1.0...v1.2.0`" in notes
    assert "### 功能新增" in notes
    assert "### 问题修复" in notes
    assert "### 其他变更" in notes
    assert "- switch release to GitHub Actions (`aaaaaaa`)" in notes
    assert "- exclude runtime data from package (`bbbbbbb`)" in notes
    assert "- Update release docs (`ccccccc`)" in notes
    assert "## 原始提交列表" in notes


def test_render_release_notes_handles_first_release():
    commits = [
        CommitEntry(full_sha="a" * 40, short_sha="aaaaaaa", subject="feat: initial release"),
    ]

    notes = render_release_notes(
        current_tag="v1.0.0",
        previous_tag="",
        repository_url="https://github.com/byteD-x/wechat-bot",
        commits=commits,
    )

    assert "这是首个正式版本" in notes
    assert "Compare 链接" not in notes
