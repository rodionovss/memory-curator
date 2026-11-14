"""Fresh user: install → save без env-переменных.

Цепочка базы (env CURATOR_BASE_DIR > ~/.curator/config.json > дефолт)
обязана работать в главном пути записи, а не только в status: новичок
по README ставит `curator install` и сразу сохраняет — без ручных env.
Регрессия ревью 2026-11-14 (Critical): cmd_save хардкодил личный путь
автора и не видел state-конфиг.
"""

import json

import pytest

import curator.control as control
from curator import installer
from curator.backend.local import LocalBackend
from curator.models import FactQuery


CANDIDATES = [{
    "type": "Reference",
    "title": "Cursor-based пагинация для стримов",
    "content_summary": "Стабильный порядок — offset, меняющиеся данные — cursor.",
    "tags": ["pagination"],
}]


@pytest.fixture
def fresh_home(tmp_path, monkeypatch):
    """Новый пользователь: чистый HOME, никаких CURATOR_* env."""
    monkeypatch.setenv("HOME", str(tmp_path))
    for name in ("CURATOR_BASE_DIR", "CURATOR_MAP", "CURATOR_DB_PATH",
                 "CURATOR_USAGE_PATH", "CURATOR_STATE_DIR"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


class TestFreshUserFlow:
    def test_install_then_save_without_env(self, fresh_home, capsys):
        installer.install_all()  # дефолтная база + state-конфиг + карта

        control.cmd_save(auto_yes=True, raw=json.dumps(CANDIDATES))

        base = fresh_home / "memory-curator"
        md_files = [p for p in base.rglob("*.md") if p.name != "knowledge-map.md"]
        assert md_files, "write-back идёт в базу из state-конфига, не в хардкод"
        content = "\n".join(p.read_text(encoding="utf-8") for p in md_files)
        assert "Cursor-based" in content
        assert (base / "knowledge-routes.md").exists(), "каталог в той же базе"

    def test_save_uses_env_over_state_config(self, fresh_home, capsys, monkeypatch):
        installer.install_all()
        (fresh_home / "kb").mkdir()
        monkeypatch.setenv("CURATOR_BASE_DIR", str(fresh_home / "kb"))

        control.cmd_save(auto_yes=True, raw=json.dumps(CANDIDATES))

        assert any(p.read_text(encoding="utf-8").count("Cursor-based")
                   for p in (fresh_home / "kb").rglob("*.md")), "env выигрывает"

    def test_map_found_via_state_config(self, fresh_home):
        """find_map_path без env находит карту в базе из state-конфига."""
        from curator.routing.map_router import find_map_path
        installer.install_all()

        map_path = find_map_path()

        assert map_path is not None
        assert map_path.parent == fresh_home / "memory-curator"
        assert map_path.name == "knowledge-map.md"
