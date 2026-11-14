"""Диспетчер CLI: живые команды достижимы, мёртвый груз удалён.

Финальная минимизация 2026-11-14: остаются save / status / get /
knowledge-routes / install. Всё, что тянуло improve/demo/usage-хвосты,
недостижимо.
"""

import pytest

import curator.control as control


class TestDispatch:
    def test_save_reachable(self, monkeypatch):
        monkeypatch.setattr(control, "cmd_save", lambda **kw: None)
        monkeypatch.setattr("sys.argv", ["curator", "save"])
        control.main()

    def test_status_reachable(self, monkeypatch):
        monkeypatch.setattr(control, "cmd_status", lambda: None)
        monkeypatch.setattr("sys.argv", ["curator", "status"])
        control.main()

    def test_get_reachable(self, monkeypatch):
        monkeypatch.setattr(control, "cmd_get", lambda query="": None)
        monkeypatch.setattr("sys.argv", ["curator", "get", "kotlin"])
        control.main()

    def test_install_reachable(self, monkeypatch):
        monkeypatch.setattr(control, "cmd_install", lambda: None)
        monkeypatch.setattr("sys.argv", ["curator", "install"])
        control.main()

    def test_knowledge_routes_reachable(self, monkeypatch):
        monkeypatch.setattr(control, "cmd_knowledge_routes", lambda args=None: 0)
        monkeypatch.setattr("sys.argv", ["curator", "knowledge-routes"])
        with pytest.raises(SystemExit) as e:
            control.main()
        assert e.value.code == 0

    @pytest.mark.parametrize("cmd", ["demo", "improve", "report", "sessions", "candidates"])
    def test_dead_commands_removed(self, monkeypatch, capsys, cmd):
        monkeypatch.setattr("sys.argv", ["curator", cmd])
        control.main()
        assert "Неизвестная команда" in capsys.readouterr().out, cmd

    def test_usage_lists_only_live(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["curator"])
        control.main()
        out = capsys.readouterr().out
        assert "save" in out and "install" in out
        assert "demo" not in out and "improve" not in out and "report" not in out
