"""Юнит-тесты harness-а экспериментов (без живых прогонов агентов).

Запуск из core: .venv/bin/python -m pytest ../../benchmark/experiments/harness/tests/ -q
"""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HARNESS))

from checkrun import run_check  # noqa: E402
from isolate import build_isolated_home, cleanup_isolated_home  # noqa: E402
from report import summarize, wilson_ci  # noqa: E402
from transcript import kb_events, parse_session_db  # noqa: E402
from workspace import build_workspace, load_models, load_tasks, task_prompt  # noqa: E402


class TestCorpus:
    def test_8_задач_со_ссылками_на_существующие_файлы(self):
        tasks = load_tasks()
        assert len(tasks) == 8
        for t in tasks:
            if t["fixture_dir"] is not None:
                assert t["fixture_dir"].exists(), t["fixture_dir"]
            assert t["task_prompt_file"].exists()
            assert t["check"].exists()

    def test_все_expected_kb_файлы_существуют(self):
        for t in load_tasks():
            if t["expected_kb_file"]:
                kb_root = HARNESS.parent / "corpus"
                assert (kb_root / t["expected_kb_file"]).exists(), t["expected_kb_file"]

    def test_классы_задач_покрывают_протокол(self):
        classes = {t["class"] for t in load_tasks()}
        assert classes == {
            "hidden_trigger", "explicit_trigger", "looks_easy_with_rule",
            "consensus_task", "no_memory_control", "false_application_control",
        }

    def test_модели_определены(self):
        models = load_models()
        assert models["strong"] and models["weak"]


class TestWorkspace:
    def test_R0_без_agents_kb_в_workspace(self, tmp_path):
        tasks = {t["task_id"]: t for t in load_tasks()}
        ws = build_workspace(tmp_path, tasks["T01"], "R0")
        assert not (ws / "AGENTS.md").exists()
        assert (ws / "kb" / "index.md").exists()
        assert (ws / "ProfileDao.kt").exists()

    @pytest.mark.parametrize("variant", ["R1", "R2", "R3"])
    def test_R123_с_different_agents(self, tmp_path, variant):
        tasks = {t["task_id"]: t for t in load_tasks()}
        ws = build_workspace(tmp_path / variant, tasks["T01"], variant)
        agents = (ws / "AGENTS.md").read_text(encoding="utf-8")
        assert agents.strip()

    def test_варианты_различаются_по_содержимому(self):
        texts = {}
        for v in ("R1", "R2", "R3"):
            texts[v] = (HARNESS.parent / "corpus" / "variants" /
                        {"R1": "r1.md", "R2": "r2.md", "R3": "r3.md"}[v]
                        ).read_text(encoding="utf-8")
        assert len({texts["R1"], texts["R2"], texts["R3"]}) == 3
        assert "index.md" in texts["R1"]
        assert "F72" in texts["R2"] and "|" in texts["R2"]
        assert "when-to-use" in texts["R3"]

    def test_task_prompt_читается(self):
        tasks = {t["task_id"]: t for t in load_tasks()}
        assert "ProfileRepository" in task_prompt(tasks["T01"])


class TestIsolate:
    def test_минимальный_конфиг_без_mcp_и_инструкций(self, tmp_path):
        home = build_isolated_home(tmp_path, "bifrost_GA/glm-5.3")
        config = json.loads(
            (home / ".config" / "opencode" / "opencode.json").read_text()
        )
        assert config["model"] == "bifrost_GA/glm-5.3"
        assert "provider" in config
        assert "mcp" not in config
        assert "plugin" not in config
        assert "instructions" not in config
        assert not (home / ".config" / "opencode" / "AGENTS.md").exists()

    def test_file_ссылки_конфига_доступны_в_изолированном_home(self, tmp_path):
        home = build_isolated_home(tmp_path, "bifrost_GA/glm-5.3")
        config_text = (home / ".config" / "opencode" / "opencode.json").read_text()
        import re
        refs = re.findall(r"\{file:([^}]+)\}", config_text)
        for ref in refs:
            ref = ref.strip()
            if not ref.startswith("~/"):
                continue
            isolated = home / ref[2:]
            real = Path.home() / ref[2:]
            if real.exists():
                assert isolated.exists(), f"{ref} не перенесён в isolated home"

    def test_auth_symlink_не_удаляется_с_домом(self, tmp_path):
        home = build_isolated_home(tmp_path, "bifrost_GA/glm-5.3")
        assert (home / ".local" / "share" / "opencode" / "auth.json").exists()
        cleanup_isolated_home(tmp_path)
        assert not (tmp_path / "home").exists()
        # реальный auth не тронут
        assert (Path.home() / ".local" / "share" / "opencode" / "auth.json").exists()


class TestTranscript:
    def _make_db(self, path, parts):
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE session (id TEXT PRIMARY KEY, time_created TEXT, "
                     "tokens_input INTEGER, tokens_output INTEGER)")
        conn.execute("CREATE TABLE message (id TEXT PRIMARY KEY, session_id TEXT, time_created TEXT)")
        conn.execute("CREATE TABLE part (id TEXT PRIMARY KEY, message_id TEXT, time_created TEXT, data TEXT)")
        conn.execute("INSERT INTO session VALUES ('s1', '1', 120, 80)")
        conn.execute("INSERT INTO message VALUES ('m1', 's1', '1')")
        for i, p in enumerate(parts):
            conn.execute("INSERT INTO part VALUES (?, 'm1', ?, ?)", (f"p{i}", str(i), json.dumps(p)))
        conn.commit()
        conn.close()

    def test_parse_and_kb_events(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        parts = [
            {"type": "text", "text": "решаю задачу"},
            {"type": "tool-invocation", "toolInvocation": {
                "state": "call", "toolName": "read",
                "args": {"filePath": str(ws / "kb" / "index.md")}}},
            {"type": "tool-invocation", "toolInvocation": {
                "state": "call", "toolName": "read",
                "args": {"filePath": str(ws / "kb" / "F72-withcontext-suspend-dao.md")}}},
            {"type": "tool-invocation", "toolInvocation": {
                "state": "call", "toolName": "read",
                "args": {"filePath": str(ws / "ProfileDao.kt")}}},
        ]
        db = tmp_path / "opencode.db"
        self._make_db(db, parts)

        transcript = parse_session_db(db)
        assert transcript["tokens_input"] == 120
        assert len(transcript["tool_calls"]) == 3

        events = kb_events(transcript, ws)
        kinds = [e["event"] for e in events]
        assert kinds == ["index_read", "source_file_read"]
        assert events[1]["fact_id"] == "F72"

    def test_parse_new_tool_part_format(self, tmp_path):
        """Новая схема opencode: part type 'tool' с state.input."""
        ws = tmp_path / "ws"
        ws.mkdir()
        parts = [
            {"type": "tool", "tool": "read", "callID": "c1",
             "state": {"status": "completed",
                       "input": {"filePath": str(ws / "kb" / "F72-withcontext-suspend-dao.md")},
                       "output": "..."}},
        ]
        db = tmp_path / "opencode.db"
        self._make_db(db, parts)

        transcript = parse_session_db(db)
        assert len(transcript["tool_calls"]) == 1
        assert transcript["tool_calls"][0]["tool"] == "read"
        events = kb_events(transcript, ws)
        assert events and events[0]["fact_id"] == "F72"

    def test_macos_private_tmp_путь_матчится(self):
        """regression: opencode пишет /private/tmp, ws живёт в /tmp (symlink)."""
        ws = Path("/tmp/harness-rt-test-ws")
        kb = ws / "kb"
        kb.mkdir(parents=True, exist_ok=True)
        try:
            target = "/private/tmp/harness-rt-test-ws/kb/index.md"
            if not Path("/private/tmp").exists():
                pytest.skip("не macOS")
            parts = [
                {"type": "tool", "tool": "read", "callID": "c1",
                 "state": {"status": "completed",
                           "input": {"filePath": target},
                           "output": "..."}},
            ]
            db = Path("/tmp/harness-rt-test.db")
            self._make_db(db, parts)
            transcript = parse_session_db(db)
            events = kb_events(transcript, ws)
            assert events and events[0]["event"] == "index_read"
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)
            db.unlink(missing_ok=True)


class TestChecks:
    def test_frozen_check_проходит_на_эталонном_решении(self):
        solutions = (HARNESS.parents[1] / "application" / "results" /
                     "solutions" / "T01" / "arm_c")
        tasks = {t["task_id"]: t for t in load_tasks()}
        ok, msg = run_check(tasks["T01"]["check"], solutions)
        assert ok, msg

    def test_frozen_check_падает_на_исходном_fixture(self, tmp_path):
        import shutil
        tasks = {t["task_id"]: t for t in load_tasks()}
        ok, msg = run_check(tasks["T01"]["check"], tasks["T01"]["fixture_dir"])
        assert not ok


class TestReport:
    def test_wilson(self):
        lo, hi = wilson_ci(6, 6)
        assert 0.0 <= lo <= 1.0 and lo <= hi <= 1.0

    def test_summary_на_синтетических_прогонах(self, tmp_path, monkeypatch):
        monkeypatch.setattr(report_mod := sys.modules["report"], "RESULTS_DIR", tmp_path)
        runs_dir = tmp_path / "01-routing-format" / "runs"
        runs_dir.mkdir(parents=True)

        def make(variant, memory, kb_hits, passed, control=False, rc=0):
            return {
                "experiment": "01-routing-format",
                "run_id": f"{variant}_{memory}_{kb_hits}_{passed}_{rc}",
                "task_id": "T01" if not control else "K1",
                "task_class": "no_memory_control" if control else "hidden_trigger",
                "variant": variant,
                "model": "strong",
                "expected_fact_ids": ["F72"] if memory else [],
                "memory_required": memory,
                "looks_easy": True,
                "events": ([{"event": "source_file_read", "source": "file_read",
                             "fact_id": "F72", "path": "kb/x.md"}] if kb_hits else
                           ([{"event": "index_read", "source": "file_read",
                              "fact_id": None, "path": "kb/index.md"}] if kb_hits == 0 else [])),
                "checks": {"application_pass": passed, "false_application": False,
                           "review_status": "not_needed", "message": ""},
                "metrics": {"tool_calls": 1, "input_tokens": 10, "output_tokens": 5,
                            "latency_ms": 100, "kb_reads": 1 if kb_hits is not None else 0},
                "returncode": rc,
            }

        # R2: 2/2 нашли факт и прошли; R0: 0/2; K1-контроль: 1 шумный kb-рид
        rows = [
            make("R2", True, True, True), make("R2", True, True, True),
            make("R0", True, False, False), make("R0", True, False, False),
            make("R2", False, True, True, control=True),
        ]
        for i, r in enumerate(rows):
            r["run_id"] = f"{i}_{r['run_id']}"
            (runs_dir / f"{r['run_id']}.json").write_text(json.dumps(r))

        s = report_mod.summarize("01-routing-format")
        assert s["runs"] == 5
        assert s["rates"]["routing_recall"] == 0.5
        assert s["rates"]["routing_precision_noisy_kb_reads"] == 1.0
        assert s["rates"]["application_rate"] == 0.5
        assert s["per_variant"]["R2"]["routing_recall"] == 1.0
        assert s["per_variant"]["R0"]["application_rate"] == 0.0
