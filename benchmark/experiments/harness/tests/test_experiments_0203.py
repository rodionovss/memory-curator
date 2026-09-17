"""Юнит-тесты расширения harness под эксперименты 02/03 (без живых агентов).

Запуск из core: .venv/bin/python -m pytest ../benchmark/experiments/harness/tests/ -q
"""

import json
import sys
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HARNESS))

import curator_seed  # noqa: E402
import isolate  # noqa: E402
import runner  # noqa: E402
import transcript  # noqa: E402

curator_seed._ensure_core_on_path()  # sys.path: core/

from curator.models import FactQuery  # noqa: E402
from curator_seed import (  # noqa: E402
    fetch_context_for_task,
    parse_kb_fact,
    proactive_delivery,
    seed_curator_db,
)
from isolate import (  # noqa: E402
    build_isolated_home,
    curator_mcp_entry,
    isolated_env,
)
from transcript import curator_events, kb_events  # noqa: E402
from workspace import (  # noqa: E402
    CATALOG_FILE,
    build_workspace,
    curator_cards_block,
    knowledge_prompt,
    load_tasks,
    oracle_fact_content,
    task_prompt,
)

CORPUS = HARNESS.parent / "corpus"


def _task(task_id: str) -> dict:
    return {t["task_id"]: t for t in load_tasks()}[task_id]


class TestIsolate0203:
    def test_mcp_в_конфиге_когда_передан(self, tmp_path):
        mcp = {"memory-curator": {"type": "local", "enabled": True,
                                  "command": ["/bin/curator-mcp-server"],
                                  "environment": {"CURATOR_DB_PATH": "/tmp/x.db"}}}
        home = build_isolated_home(tmp_path, "bifrost_GA/glm-5.3", mcp=mcp)
        config = json.loads(
            (home / ".config" / "opencode" / "opencode.json").read_text()
        )
        assert config["mcp"] == mcp

    def test_mcp_не_в_конфиге_когда_не_передан(self, tmp_path):
        home = build_isolated_home(tmp_path, "bifrost_GA/glm-5.3")
        config = json.loads(
            (home / ".config" / "opencode" / "opencode.json").read_text()
        )
        assert "mcp" not in config

    def test_curator_mcp_entry_копия_плюс_db_path(self, tmp_path, monkeypatch):
        real_entry = {
            "type": "local",
            "enabled": True,
            "command": ["/venv/bin/curator-mcp-server"],
            "environment": {"MEMORY_BACKEND": "local"},
        }
        monkeypatch.setattr(isolate, "_real_config",
                            lambda: {"mcp": {"memory-curator": real_entry}})
        db = tmp_path / "curator.db"
        entry = curator_mcp_entry(db)["memory-curator"]
        assert entry["command"] == real_entry["command"]
        assert entry["environment"]["MEMORY_BACKEND"] == "local"
        assert entry["environment"]["CURATOR_DB_PATH"] == str(db)
        # источник не мутирован
        assert "CURATOR_DB_PATH" not in real_entry["environment"]

    def test_isolated_env_мержит_extra(self, tmp_path):
        home = build_isolated_home(tmp_path, "bifrost_GA/glm-5.3")
        env = isolated_env(home, extra={"CURATOR_DB_PATH": tmp_path / "curator.db"})
        assert env["HOME"] == str(home)
        assert env["CURATOR_DB_PATH"] == str(tmp_path / "curator.db")


class TestP2Catalog:
    def test_каталог_существует_и_без_путей_к_kb(self):
        text = (CORPUS / "variants" / CATALOG_FILE).read_text(encoding="utf-8")
        assert "| Тема | Когда | curator query |" in text
        # только curator-запросы, никаких ссылок на файлы базы
        assert "kb/" not in text
        assert ".md" not in text
        # каждая строка карты даёт curator query в backticks
        assert "withContext вокруг suspend DAO" in text

    def test_каталог_кладётся_в_workspace_руки_P2(self, tmp_path):
        ws = build_workspace(tmp_path, _task("T01"), "R2", catalog=True)
        assert (ws / CATALOG_FILE).exists()
        assert (ws / "AGENTS.md").exists()

    def test_чтение_каталога_даёт_событие_catalog_read(self, tmp_path):
        ws = build_workspace(tmp_path, _task("T01"), "R2", catalog=True)
        t = {
            "tool_calls": [
                {"tool": "read", "args": {"filePath": str(ws / CATALOG_FILE)}},
                {"tool": "read", "args": {"filePath": str(ws / "ProfileDao.kt")}},
            ]
        }
        events = kb_events(t, ws)
        assert [(e["event"], e["source"]) for e in events] == [
            ("catalog_read", "file_read")
        ]


class TestOraclePrompt:
    def test_факт_и_задача_задача_идёт_после(self):
        task = _task("T01")
        fact = oracle_fact_content(task)
        task_text = task_prompt(task)
        prompt = knowledge_prompt(fact, task_text)
        assert prompt.startswith("## Знание из базы")
        assert "Не оборачивай suspend-DAO в withContext" in prompt
        assert "ProfileRepository" in prompt
        assert prompt.index("ProfileRepository") > prompt.index("## Знание из базы")

    def test_P3_workspace_без_kb(self, tmp_path):
        ws = build_workspace(tmp_path, _task("T01"), "R2", include_kb=False)
        assert not (ws / "kb").exists()
        assert (ws / "AGENTS.md").exists()


class TestCuratorSeed:
    def test_засев_6_verified_плюс_deprecated_FD1(self, tmp_path):
        db = tmp_path / "curator.db"
        assert seed_curator_db(db) == 7
        backend = curator_seed.local_backend(db)
        verified = backend.query_facts(FactQuery(status="verified"))
        deprecated = backend.query_facts(FactQuery(status="deprecated"))
        assert len(verified) == 6
        assert len(deprecated) == 1
        assert deprecated[0].title == "MVP Moxy legacy presenter"
        titles = {f.title for f in verified}
        assert "Не оборачивай suspend-DAO в withContext" in titles

    def test_retriever_находит_F72_и_карточка_в_промпте(self, tmp_path):
        db = tmp_path / "curator.db"
        seed_curator_db(db)
        cards = fetch_context_for_task("withContext вокруг suspend DAO", db, limit=3)
        assert cards, "карточка F72 должна быть найдена"
        assert cards[0].title == "Не оборачивай suspend-DAO в withContext"
        block = curator_cards_block(cards)
        prompt = knowledge_prompt(block, "текст задачи")
        assert cards[0].title in prompt
        assert "текст задачи" in prompt

    def test_Q1_на_запросе_без_совпадений_молчит(self, tmp_path):
        db = tmp_path / "curator.db"
        seed_curator_db(db)
        prompt, delivery, silent = proactive_delivery("рецепт борща", db)
        assert prompt == "рецепт борща"
        assert delivery == "silent"
        assert silent is True

    def test_Q1_на_совпадающем_триггере_вставляет_карточку(self, tmp_path):
        db = tmp_path / "curator.db"
        seed_curator_db(db)
        trigger = "withContext вокруг suspend DAO"
        prompt, delivery, silent = proactive_delivery(trigger, db)
        assert delivery == "real_retriever"
        assert silent is False
        assert "Не оборачивай suspend-DAO в withContext" in prompt
        assert prompt.index(trigger) > prompt.index("## Знание из базы")

    def test_deprecated_факт_не_попадает_в_выдачу(self, tmp_path):
        db = tmp_path / "curator.db"
        seed_curator_db(db)
        cards = fetch_context_for_task("MVP Moxy legacy presenter", db, limit=3)
        assert all(c.status != "deprecated" for c in cards)
        assert all("Moxy" not in c.title for c in cards)

    def test_parse_kb_fact_frontmatter_и_заголовок(self):
        fact = parse_kb_fact(CORPUS / "kb" / "F72-withcontext-suspend-dao.md")
        assert fact.type == "Reference"
        assert fact.tags == ["coroutines", "dao", "withcontext"]
        assert fact.title == "Не оборачивай suspend-DAO в withContext"
        assert fact.status == "verified"
        assert fact.source_file == "kb/F72-withcontext-suspend-dao.md"
        assert "Room сам диспатчит" in fact.content_summary


class TestCuratorEvents:
    def test_детектор_по_имени_инструмента(self):
        t = {"tool_calls": [
            {"tool": "memory-curator_curator_query", "args": {"search": "x"}},
            {"tool": "memory-curator_curator_get", "args": {}},
            {"tool": "curator_status", "args": {}},
            {"tool": "read", "args": {"filePath": "/x"}},
        ]}
        events = curator_events(t)
        assert [(e["event"], e["source"]) for e in events] == [
            ("manual_curator_query", "manual_curator_query"),
            ("manual_curator_get", "manual_curator_query"),
            ("manual_curator_query", "manual_curator_query"),
        ]

    def test_без_curator_инструментов_пусто(self):
        t = {"tool_calls": [{"tool": "read", "args": {"filePath": "/x"}}]}
        assert curator_events(t) == []


class TestRunner0203:
    def test_матрицы_рук_и_имена_экспериментов(self):
        assert runner.EXPERIMENTS["02"]["name"] == "02-access-path"
        assert runner.EXPERIMENTS["03"]["name"] == "03-proactive-delivery"
        assert set(runner.EXP02_ARMS) == {"P0", "P1", "P2", "P3"}
        assert set(runner.EXP03_ARMS) == {"O0", "O1", "Q0", "Q1"}
        # P1/P2 дают агенту curator MCP, остальные руки 02 — нет
        assert runner.EXP02_ARMS["P1"]["curator_mcp"] is True
        assert runner.EXP02_ARMS["P2"]["curator_mcp"] is True
        assert runner.EXP02_ARMS["P3"]["include_kb"] is False
        assert runner.EXP03_ARMS["Q1"]["retriever"] is True

    def test_prepare_руки_P1_даёт_mcp_и_засеянную_базу(self, tmp_path, monkeypatch):
        monkeypatch.setattr(isolate, "_real_config", lambda: {
            "mcp": {"memory-curator": {"type": "local", "command": ["/bin/x"],
                                       "environment": {}}}})
        setup = runner._prepare(_task("T01"), runner.EXP02_ARMS["P1"],
                                tmp_path, "R2")
        assert setup["mcp"]["memory-curator"]["environment"]["CURATOR_DB_PATH"]
        assert setup["env_extra"]["CURATOR_DB_PATH"]
        assert (tmp_path / "curator.db").exists()
        assert setup["prompt"] == task_prompt(_task("T01"))

    def test_prepare_руки_P3_оракул_в_промпте_и_без_kb(self, tmp_path):
        setup = runner._prepare(_task("T01"), runner.EXP02_ARMS["P3"],
                                tmp_path, "R2")
        assert setup["mcp"] is None
        assert not (setup["ws"] / "kb").exists()
        assert setup["prompt"].startswith("## Знание из базы")
        assert "Не оборачивай suspend-DAO в withContext" in setup["prompt"]

    def test_prepare_руки_O1_оракул_и_delivery(self, tmp_path):
        setup = runner._prepare(_task("T01"), runner.EXP03_ARMS["O1"],
                                tmp_path, "R2")
        assert setup["delivery"] == "oracle_card"
        assert setup["prompt"].startswith("## Знание из базы")

    def test_prepare_руки_O1_на_контроле_без_факта_не_вставляет(self, tmp_path):
        setup = runner._prepare(_task("K1"), runner.EXP03_ARMS["O1"],
                                tmp_path, "R2")
        assert setup["delivery"] == "none"
        assert setup["prompt"] == task_prompt(_task("K1"))

    def test_prepare_руки_Q1_находит_карточку(self, tmp_path, monkeypatch):
        # скрытый триггер T01 не совпадает — подменяем текст задачи на явный
        monkeypatch.setattr(runner, "task_prompt", lambda t: "withContext вокруг suspend DAO")
        setup = runner._prepare(_task("T01"), runner.EXP03_ARMS["Q1"],
                                tmp_path, "R2")
        assert setup["delivery"] == "real_retriever"
        assert setup["silent_delivery"] is False
        assert "Не оборачивай suspend-DAO в withContext" in setup["prompt"]

    def test_prepare_руки_Q1_на_скрытом_триггере_молчит(self, tmp_path):
        """Фактическое поведение retriever-а: порог 0.4, скрытый триггер T01
        (весь смысл hidden_trigger) не даёт карточки → silent_delivery."""
        setup = runner._prepare(_task("T01"), runner.EXP03_ARMS["Q1"],
                                tmp_path, "R2")
        assert setup["delivery"] == "silent"
        assert setup["silent_delivery"] is True
        assert setup["prompt"] == task_prompt(_task("T01"))

    def test_emit_кладёт_в_папку_эксперимента(self, tmp_path, monkeypatch):
        monkeypatch.setattr(runner, "RESULTS_DIR", tmp_path)
        out = runner.emit({"experiment": "02-access-path", "run_id": "x1"})
        assert out == tmp_path / "02-access-path" / "runs" / "x1.json"
        out = runner.emit({"experiment": "03-proactive-delivery", "run_id": "x2"})
        assert out == tmp_path / "03-proactive-delivery" / "runs" / "x2.json"

    def test_cli_по_умолчанию_идентичен_01(self, capsys, monkeypatch):
        """--experiment 01 по умолчанию: те же варианты R0-R3, dry-режим."""
        monkeypatch.setattr(sys, "argv",
                            ["runner.py", "--dry", "--tasks", "T01"])
        assert runner.main() == 0
        out = capsys.readouterr().out
        assert "4 variants" in out
        assert "[dry] T01 R0 strong r1" in out
        assert "[dry] T01 R3 strong r1" in out

    def test_cli_эксперимент_02_с_руками_P(self, capsys, monkeypatch):
        monkeypatch.setattr(sys, "argv",
                            ["runner.py", "--experiment", "02", "--dry",
                             "--tasks", "T01"])
        assert runner.main() == 0
        out = capsys.readouterr().out
        assert "[dry] T01 P0 strong r1" in out
        assert "[dry] T01 P3 strong r1" in out

    def test_cli_эксперимент_03_и_routing(self, capsys, monkeypatch):
        monkeypatch.setattr(sys, "argv",
                            ["runner.py", "--experiment", "03", "--dry",
                             "--tasks", "T01", "--routing", "R1"])
        assert runner.main() == 0
        out = capsys.readouterr().out
        for arm in ("O0", "O1", "Q0", "Q1"):
            assert f"[dry] T01 {arm} strong r1" in out

    def test_cli_отвергает_чужие_варианты(self, monkeypatch):
        monkeypatch.setattr(sys, "argv",
                            ["runner.py", "--experiment", "02", "--dry",
                             "--variants", "R0"])
        with pytest.raises(SystemExit):
            runner.main()
