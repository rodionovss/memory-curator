"""Тесты CLI cmd_save: статус hypothesis для майнинга + телеметрия кандидатов."""

import json

import pytest

import curator.control as control
from curator.backend.local import LocalBackend
from curator.models import FactQuery


CANDIDATES = [{
    "type": "Reference",
    "title": "Cursor-based пагинация для стримов",
    "content_summary": "Стабильный порядок — offset, меняющиеся данные — cursor.",
    "tags": ["pagination", "api"],
    "evidence": "сессия про выбор пагинации",
}]


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("CURATOR_DB_PATH", str(tmp_path / "knowledge.db"))
    monkeypatch.setenv("CURATOR_BASE_DIR", str(tmp_path / "learnings"))
    monkeypatch.setenv("CURATOR_USAGE_PATH", str(tmp_path / "usage.json"))
    return tmp_path


class TestSaveHypothesis:
    def test_hypothesis_flag_stores_as_hypothesis(self, env, capsys):
        control.cmd_save(auto_yes=True, hypothesis=True, session_id="ses_1",
                         raw=json.dumps(CANDIDATES))
        out = capsys.readouterr().out
        assert "статус: hypothesis" in out

        backend = LocalBackend(str(env / "knowledge.db"))
        facts = backend.query_facts(FactQuery(search="Cursor-based"))
        assert len(facts) == 1
        assert facts[0].status == "hypothesis"

    def test_default_save_is_verified(self, env, capsys):
        control.cmd_save(auto_yes=True, raw=json.dumps(CANDIDATES))
        backend = LocalBackend(str(env / "knowledge.db"))
        facts = backend.query_facts(FactQuery(search="Cursor-based"))
        assert facts[0].status == "verified"

    def test_writeback_md_contains_hypothesis_status(self, env, capsys):
        control.cmd_save(auto_yes=True, hypothesis=True, session_id="ses_1",
                         raw=json.dumps(CANDIDATES))
        md_files = list((env / "learnings").rglob("*.md"))
        assert md_files, "write-back должен создать .md"
        content = "\n".join(p.read_text(encoding="utf-8") for p in md_files)
        assert "Cursor-based" in content
        assert "Гипотеза" in content  # лейбл статуса hypothesis в .md

    def test_candidates_log_written_on_save(self, env, capsys):
        control.cmd_save(auto_yes=True, hypothesis=True, session_id="ses_1",
                         raw=json.dumps(CANDIDATES))
        from curator import candidates_log
        entries = candidates_log.read_entries()
        assert len(entries) == 1
        e = entries[0]
        assert e["source"] == "mining"  # --session → источник mining
        assert e["session"] == "ses_1"
        assert e["saved"] == 1
        assert e["final_status"] == "hypothesis"

    def test_human_decline_logs_zero_saved(self, env, capsys, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda: "n")
        control.cmd_save(auto_yes=False, raw=json.dumps(CANDIDATES))
        from curator import candidates_log
        entries = candidates_log.read_entries()
        assert entries[-1]["declined_by_human"] is True
        assert entries[-1]["saved"] == 0

    def test_exact_resave_is_upsert_not_duplicate(self, env, capsys):
        # Контракт: точное совпадение title — UPSERT (идемпотентный реингест),
        # дубликата в базе не появляется
        control.cmd_save(auto_yes=True, raw=json.dumps(CANDIDATES))
        control.cmd_save(auto_yes=True, raw=json.dumps(CANDIDATES))
        backend = LocalBackend(str(env / "knowledge.db"))
        facts = backend.query_facts(FactQuery(search="Cursor-based"))
        assert len(facts) == 1

    def test_near_duplicate_rejected_and_logged(self, env, capsys):
        control.cmd_save(auto_yes=True, raw=json.dumps(CANDIDATES))
        # Другой title, слово-пересечение > 0.6 — gatekeeper ловит как дубль
        near = dict(CANDIDATES[0])
        near["title"] = "Cursor-based пагинация для стримов и лент"
        control.cmd_save(auto_yes=True, raw=json.dumps([near]))
        from curator import candidates_log
        entries = candidates_log.read_entries()
        last = entries[-1]
        assert last["saved"] == 0
        rejected = [c for c in last["candidates"] if c["decision"] == "rejected"]
        assert rejected
        assert "дубликат" in rejected[0]["reason"].lower()


class TestSavePreviewShowsTarget:
    """Fast lane (пивот 2026-10-03): «что» и «куда» в одном preview —
    маршрут резолвится до подтверждения, а не после записи."""

    def test_approved_preview_contains_routed_target(self, env, capsys):
        control.cmd_save(auto_yes=True, raw=json.dumps(CANDIDATES))
        out = capsys.readouterr().out
        assert "→" in out
        assert ".md" in out

    def test_target_in_preview_matches_saved_source_file(self, env, capsys):
        import re
        control.cmd_save(auto_yes=True, raw=json.dumps(CANDIDATES))
        out = capsys.readouterr().out
        m = re.search(r"→ (\S+\.md)", out)
        assert m, "в preview должна быть строка «→ <файл>.md»"
        backend = LocalBackend(str(env / "knowledge.db"))
        facts = backend.query_facts(FactQuery(search="Cursor-based"))
        assert facts[0].source_file == m.group(1)


class TestGitCommit:
    @staticmethod
    def _init_repo(path):
        import subprocess
        subprocess.run(["git", "init", "-q", str(path)], check=True)
        subprocess.run(["git", "-C", str(path), "config", "user.email",
                        "test@local"], check=True)
        subprocess.run(["git", "-C", str(path), "config", "user.name",
                        "test"], check=True)

    def test_commits_pending_changes(self, tmp_path):
        import subprocess
        self._init_repo(tmp_path)
        (tmp_path / "base.md").write_text("знание", encoding="utf-8")

        assert control._git_commit(tmp_path, "curator: тест") == "committed"
        log = subprocess.run(
            ["git", "-C", str(tmp_path), "log", "-1", "--format=%s"],
            capture_output=True, text=True).stdout
        assert "curator: тест" in log

    def test_clean_repo_no_commit(self, tmp_path):
        import subprocess
        self._init_repo(tmp_path)
        (tmp_path / "base.md").write_text("знание", encoding="utf-8")
        subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "init"],
                       check=True)

        assert control._git_commit(tmp_path, "curator: тест") == "noop"

    def test_fresh_dir_becomes_repo_and_commits(self, tmp_path, monkeypatch):
        import subprocess
        monkeypatch.setenv("GIT_AUTHOR_NAME", "curator-test")
        monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@curator.local")
        monkeypatch.setenv("GIT_COMMITTER_NAME", "curator-test")
        monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@curator.local")
        (tmp_path / "base.md").write_text("знание", encoding="utf-8")

        assert control._git_commit(tmp_path, "curator: тест") == "committed"
        log = subprocess.run(
            ["git", "-C", str(tmp_path), "log", "-1", "--format=%s"],
            capture_output=True, text=True).stdout
        assert "curator: тест" in log, "свежая база получает историю сама"


class TestGitHistoryEndToEnd:
    @staticmethod
    def _identity(monkeypatch, name="curator-test", email="test@curator.local"):
        monkeypatch.setenv("GIT_AUTHOR_NAME", name)
        monkeypatch.setenv("GIT_AUTHOR_EMAIL", email)
        monkeypatch.setenv("GIT_COMMITTER_NAME", name)
        monkeypatch.setenv("GIT_COMMITTER_EMAIL", email)

    def test_fresh_base_gets_commit(self, env, capsys, monkeypatch):
        self._identity(monkeypatch)

        control.cmd_save(auto_yes=True, raw=json.dumps(CANDIDATES))

        out = capsys.readouterr().out
        assert "git: локальный коммит" in out, "save обязан закоммитить свежую базу"

    def test_commit_failure_is_visible_warning(self, env, capsys, monkeypatch):
        monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
        monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/dev/null")
        self._identity(monkeypatch, name="", email="")

        control.cmd_save(auto_yes=True, raw=json.dumps(CANDIDATES))

        out = capsys.readouterr().out
        assert "git-коммит не прошёл" in out, "провал коммита не должен молчать"
        assert "git: локальный коммит" not in out


class TestAutoYesFlag:
    """0.4.0: `--auto-yes` из ранних док — алиас `-y`/`--yes`;
    интерактивный промпт появляться не должен (иначе агент без TTY падает)."""

    def test_auto_yes_alias_skips_prompt(self, env, capsys, monkeypatch):
        import io
        monkeypatch.setattr("sys.argv", ["curator", "save", "--auto-yes"])
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(CANDIDATES)))
        control.main()
        out = capsys.readouterr().out
        assert "[y/N]" not in out
        assert "Сохранено: 1" in out


MAP_YAML = """---
title: карта теста
topics:
  - name: test
    watch_for: test, тема
    targets:
      - path: "folder/test.md"
        captures: [knowledge]
        mode: update
        instructions: "Факты теста"
---
"""


class TestSaveDoc:
    """0.5.0: save --doc — фиксация файла-знания: путь по карте,
    git-коммит, событие в журнале аналитики; без записи в DB."""

    @staticmethod
    def _git_repo(path):
        import subprocess
        subprocess.run(["git", "init", "-q", str(path)], check=True)
        subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t"], check=True)
        subprocess.run(["git", "-C", str(path), "config", "user.name", "t"], check=True)

    def test_doc_outside_map_rejected(self, env, capsys, monkeypatch):
        (env / "learnings").mkdir(exist_ok=True)
        (env / "learnings" / "random.md").write_text("знание", encoding="utf-8")
        monkeypatch.setenv("CURATOR_MAP", str(env / "map.md"))
        (env / "map.md").write_text(MAP_YAML, encoding="utf-8")

        control.cmd_save_doc("random.md")
        out = capsys.readouterr().out
        assert "не совпадает ни с одним таргетом" in out
        assert "Зафиксирован" not in out
        from curator import candidates_log
        last = candidates_log.read_entries()[-1]
        assert last["source"] == "doc" and last["saved"] == 0

    def test_doc_missing_file_rejected(self, env, capsys):
        control.cmd_save_doc("no/such/file.md")
        out = capsys.readouterr().out
        assert "Файл не найден" in out

    def test_doc_map_target_committed(self, env, capsys, monkeypatch):
        import subprocess
        self._git_repo(env / "learnings")
        monkeypatch.setenv("CURATOR_MAP", str(env / "map.md"))
        (env / "map.md").write_text(MAP_YAML, encoding="utf-8")
        target = env / "learnings" / "folder" / "test.md"
        target.parent.mkdir(parents=True)
        target.write_text("## Теория\nграбли по теме", encoding="utf-8")

        control.cmd_save_doc("folder/test.md")
        out = capsys.readouterr().out
        assert "Документ зафиксирован: folder/test.md" in out
        log = subprocess.run(["git", "-C", str(env / "learnings"), "log", "-1", "--format=%s"],
                             capture_output=True, text=True).stdout
        assert "curator: doc folder/test.md" in log
        from curator import candidates_log
        last = candidates_log.read_entries()[-1]
        assert last["source"] == "doc" and last["saved"] == 1

    def test_doc_session_path_allowed_without_map(self, env, capsys):
        session_dir = env / "learnings" / "session"
        session_dir.mkdir(parents=True)
        (session_dir / "reference.md").write_text("неразобранное", encoding="utf-8")

        control.cmd_save_doc("session/reference.md")
        out = capsys.readouterr().out
        assert "Документ зафиксирован: session/reference.md" in out
