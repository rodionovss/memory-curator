"""Диспетчер CLI: живые команды достижимы, машинерия фоновых процессов удалена.

Регрессия поломки 0.5.x: main() не диспетчеризовал install/demo — install.sh
фактически не работал. Плюс решение 2026-10-03: start/stop (worker-демон)
удаляются из CLI.
"""

import pytest

import curator.control as control


class TestDispatch:
    def test_install_reachable(self, monkeypatch):
        monkeypatch.setattr(control, "cmd_install", lambda: None)
        monkeypatch.setattr("sys.argv", ["curator", "install"])
        control.main()

    def test_demo_reachable(self, monkeypatch):
        monkeypatch.setattr(control, "cmd_demo", lambda: None)
        monkeypatch.setattr("sys.argv", ["curator", "demo"])
        control.main()

    def test_get_reachable(self, monkeypatch, capsys):
        monkeypatch.setattr(control, "cmd_get", lambda query="": None)
        monkeypatch.setattr("sys.argv", ["curator", "get", "kotlin"])
        control.main()

    def test_report_reachable(self, monkeypatch):
        monkeypatch.setattr(control, "cmd_report", lambda days=0: None)
        monkeypatch.setattr("sys.argv", ["curator", "report"])
        control.main()

    def test_start_removed(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["curator", "start"])
        control.main()
        assert "Неизвестная команда" in capsys.readouterr().out

    def test_stop_removed(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["curator", "stop"])
        control.main()
        assert "Неизвестная команда" in capsys.readouterr().out

    def test_usage_lists_no_worker(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["curator"])
        control.main()
        out = capsys.readouterr().out
        assert "worker" not in out.lower()
        assert "install" in out

    def test_session_flag_passes_id(self, monkeypatch):
        """`curator save --session <id>` передаёт id, а не литерал флага.

        Регрессия ревью 2026-11-14: sys.argv[idx+2] возвращал сам
        '--session' — мусорный session_id в журнале аналитики.
        """
        captured = {}
        monkeypatch.setattr(control, "cmd_save", lambda **kw: captured.update(kw))
        monkeypatch.setattr("sys.argv", ["curator", "save", "--yes", "--session", "ses_123"])

        control.main()

        assert captured["session_id"] == "ses_123"
        assert captured["auto_yes"] is True

    def test_install_base_dir_without_value_rejected(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["curator", "install", "--base-dir"])

        control.main()

        assert "требует путь" in capsys.readouterr().err
