"""Scope git-коммита curator save: только база знаний, не всё дерево репо.

Регрессия ревью 2026-11-14: `git add -A` без pathspec коммитил любые
грязные файлы репо, когда база — подкаталог (~/Documents/AI).
"""

import json
import subprocess

import pytest

import curator.control as control


CANDIDATES = [{
    "type": "Reference",
    "title": "Cursor-based пагинация для стримов",
    "content_summary": "Стабильный порядок — offset, меняющиеся данные — cursor.",
    "tags": ["pagination"],
}]


@pytest.fixture
def repo_with_foreign_dirt(tmp_path, monkeypatch):
    """Git-репо: база в подкаталоге kb/, посторонний грязный файл в корне."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "--allow-empty", "-q", "-m", "init"],
                   cwd=tmp_path, check=True)
    kb = tmp_path / "kb"
    kb.mkdir()
    (tmp_path / "README.md").write_text("# репо\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "readme"], cwd=tmp_path, check=True)
    # посторонняя грязь после коммита
    (tmp_path / "skills").mkdir()
    (tmp_path / "skills" / "foreign.txt").write_text("чужое", encoding="utf-8")

    monkeypatch.setenv("CURATOR_DB_PATH", str(tmp_path / "knowledge.db"))
    monkeypatch.setenv("CURATOR_BASE_DIR", str(kb))
    monkeypatch.setenv("CURATOR_USAGE_PATH", str(tmp_path / "usage.json"))
    monkeypatch.delenv("CURATOR_MAP", raising=False)
    return tmp_path


class TestGitCommitScope:
    def test_commit_contains_only_base_changes(self, repo_with_foreign_dirt, capsys):
        tmp_path = repo_with_foreign_dirt

        control.cmd_save(auto_yes=True, raw=json.dumps(CANDIDATES))

        show = subprocess.run(
            ["git", "show", "--name-only", "--pretty=format:", "HEAD"],
            cwd=tmp_path, capture_output=True, text=True, check=True).stdout
        files = [f for f in show.splitlines() if f.strip()]
        assert files, "curator-коммит создан"
        assert all(f.startswith("kb/") for f in files), \
            f"коммит затронул посторонние пути: {files}"
        status = subprocess.run(["git", "status", "--porcelain", "--", "skills"],
                                cwd=tmp_path, capture_output=True, text=True).stdout
        assert "skills" in status, \
            "посторонний грязный файл не закоммичен и остался в рабочей копии"
