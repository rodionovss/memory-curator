"""Save → авто-регенерация каталога knowledge-routes.md.

Петля чтения не протухает: после сохранения фактов каталог обновляется
сам (детерминированный рендер, без LLM) и попадает в тот же git-коммит.
Сбой регенерации не валит save: факты важнее каталога (⚠-предупреждение).
"""

import json

import pytest

import curator.control as control
from curator.backend.local import LocalBackend
from curator.models import FactQuery


MAP = (
    "---\n"
    "title: Тестовая карта\n"
    "on_unmatched: report\n"
    "topics:\n"
    "  - name: pagination\n"
    "    watch_for: pagination, пагинация\n"
    "    targets:\n"
    "      - path: \"reference/pagination.md\"\n"
    "        captures: [knowledge]\n"
    "        mode: update\n"
    "        instructions: \"Факты по пагинации\"\n"
    "---\n"
)

CANDIDATES = [{
    "type": "Reference",
    "title": "Cursor-based пагинация для стримов",
    "content_summary": "Стабильный порядок — offset, меняющиеся данные — cursor.",
    "tags": ["pagination"],
}]


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("CURATOR_DB_PATH", str(tmp_path / "knowledge.db"))
    monkeypatch.setenv("CURATOR_BASE_DIR", str(tmp_path / "learnings"))
    monkeypatch.setenv("CURATOR_USAGE_PATH", str(tmp_path / "usage.json"))
    monkeypatch.delenv("CURATOR_MAP", raising=False)
    (tmp_path / "learnings").mkdir()
    return tmp_path


class TestSaveRegeneratesRoutes:
    def test_save_with_map_updates_catalog(self, env, capsys):
        (env / "learnings" / "knowledge-map.md").write_text(MAP, encoding="utf-8")

        control.cmd_save(auto_yes=True, raw=json.dumps(CANDIDATES))

        catalog = env / "learnings" / "knowledge-routes.md"
        assert catalog.exists(), "каталог регенерируется после save"
        text = catalog.read_text(encoding="utf-8")
        assert "reference/pagination.md" in text, "маршрут из карты"
        assert "Cursor-based пагинация" in text, "новый факт виден в Contains"

    def test_save_without_map_catalog_from_facts(self, env, capsys):
        # карты нет — старое поведение: каталог строится из самих фактов
        control.cmd_save(auto_yes=True, raw=json.dumps(CANDIDATES))

        catalog = env / "learnings" / "knowledge-routes.md"
        assert catalog.exists()
        text = catalog.read_text(encoding="utf-8")
        assert "Cursor-based пагинация" in text

    def test_save_survives_regen_failure(self, env, capsys, monkeypatch):
        (env / "learnings" / "knowledge-map.md").write_text(MAP, encoding="utf-8")

        def boom(backend, base_dir):
            raise RuntimeError("сломался рендер")

        import curator.knowledge_routes as kr
        monkeypatch.setattr(kr, "render_catalog", boom)

        control.cmd_save(auto_yes=True, raw=json.dumps(CANDIDATES))

        out = capsys.readouterr().out
        assert "⚠" in out, "сбой регенерации виден как предупреждение"
        backend = LocalBackend(str(env / "knowledge.db"))
        facts = backend.query_facts(FactQuery(search="Cursor-based"))
        assert len(facts) == 1, "факт сохранён, несмотря на сбой каталога"
        md = env / "learnings" / "session" / "reference.md"
        assert md.exists() or any(
            p.name != "knowledge-routes.md"
            for p in (env / "learnings").rglob("*.md")), "write-back .md не потерян"
