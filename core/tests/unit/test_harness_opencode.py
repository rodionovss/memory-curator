"""Health-чеки интеграции OpenCode для curator status.

Пивот 2026-10-03 + дофиксация: плагины, доставка, MCP-сервер и worker
удалены — живой чек один (бинарь CLI), его и тестируем.
"""

from pathlib import Path

import pytest

from curator.harness import opencode
from curator.harness import integration_status


@pytest.fixture
def fake_env(tmp_path, monkeypatch):
    """Изолированный HOME без установленного бинаря."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    return home


class TestCuratorBin:
    def test_ok_when_fallback_exists(self, fake_env):
        local_bin = fake_env / ".local" / "bin"
        local_bin.mkdir(parents=True)
        (local_bin / "curator").write_text("#!/bin/sh\n", encoding="utf-8")
        ok, message = opencode.check_curator_bin()
        assert ok, message

    def test_ok_when_in_path(self, fake_env, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/curator")
        ok, message = opencode.check_curator_bin()
        assert ok, message

    def test_fail_when_nowhere(self, fake_env, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda name: None)
        ok, _ = opencode.check_curator_bin()
        assert not ok


class TestChecksAggregate:
    def test_checks_only_bin(self, fake_env):
        results = opencode.checks()
        assert len(results) == 1, "плагинов/доставки/MCP больше нет — чек один"

    def test_integration_status_aggregates(self, fake_env):
        results = integration_status()
        assert results, "агрегатор не пуст"
