"""Health-чеки интеграции OpenCode для curator status (2026-09-18).

Каждый чек — конкретный режим отказа из дебага Desktop-контракта:
копии плагинов устарели / не зарегистрированы в plugin[] / env не
дошёл до GUI / бинарь вне PATH / shadow-лог не растёт.
"""

import json
from pathlib import Path

import pytest

from curator.harness import opencode
from curator.harness import integration_status


@pytest.fixture
def fake_env(tmp_path, monkeypatch):
    """Изолированный HOME с opencode-конфигом и репо-интеграциями."""
    home = tmp_path / "home"
    (home / ".config" / "opencode" / "plugins").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    repo = tmp_path / "repo" / "integrations"
    repo.mkdir(parents=True)
    (repo / "curator-context.js").write_text("// ctx v2", encoding="utf-8")
    (repo / "curator-reminder.js").write_text("// reminder v2", encoding="utf-8")
    monkeypatch.setattr(opencode, "_repo_root", lambda: tmp_path / "repo")
    return {
        "home": home,
        "repo": repo,
        "plugins_dir": home / ".config" / "opencode" / "plugins",
        "config": home / ".config" / "opencode" / "opencode.json",
    }


def _install_plugins(env):
    (env["plugins_dir"] / "curator-context.js").write_text("// ctx v2", encoding="utf-8")
    (env["plugins_dir"] / "curator-reminder.js").write_text("// reminder v2", encoding="utf-8")


def _register(env):
    env["config"].write_text(json.dumps({
        "plugin": [
            str(env["plugins_dir"] / "curator-context.js"),
            str(env["plugins_dir"] / "curator-reminder.js"),
        ],
    }), encoding="utf-8")


class TestPluginsSync:
    def test_ok_when_installed(self, fake_env):
        _install_plugins(fake_env)
        ok, message = opencode.check_plugins_sync()
        assert ok, message

    def test_fail_when_missing(self, fake_env):
        ok, message = opencode.check_plugins_sync()
        assert not ok
        assert "curator install" in message

    def test_fail_when_stale(self, fake_env):
        _install_plugins(fake_env)
        (fake_env["plugins_dir"] / "curator-context.js").write_text("// старая", encoding="utf-8")
        ok, message = opencode.check_plugins_sync()
        assert not ok
        assert "устарели" in message


class TestPluginsRegistered:
    def test_ok_when_in_plugin_array(self, fake_env):
        _register(fake_env)
        ok, message = opencode.check_plugins_registered()
        assert ok, message

    def test_fail_when_absent(self, fake_env):
        fake_env["config"].write_text(json.dumps({"plugin": []}), encoding="utf-8")
        ok, message = opencode.check_plugins_registered()
        assert not ok
        assert "plugin[]" in message

    def test_fail_when_relative_path(self, fake_env):
        """Относительный путь в plugin[] Desktop не грузит — нужен абсолютный."""
        fake_env["config"].write_text(json.dumps({
            "plugin": ["./plugins/curator-context.js"],
        }), encoding="utf-8")
        ok, message = opencode.check_plugins_registered()
        assert not ok

    def test_fail_when_no_config(self, fake_env):
        ok, message = opencode.check_plugins_registered()
        assert not ok


class TestCuratorBin:
    def test_ok_when_fallback_exists(self, fake_env):
        from shutil import which
        fake_bin = fake_env["home"] / ".local" / "bin"
        fake_bin.mkdir(parents=True)
        (fake_bin / "curator").write_text("#!/bin/sh\n", encoding="utf-8")
        ok, _ = opencode.check_curator_bin()
        assert ok

    def test_ok_when_in_path(self, fake_env, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/curator")
        ok, _ = opencode.check_curator_bin()
        assert ok

    def test_fail_when_nowhere(self, fake_env, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda name: None)
        ok, message = opencode.check_curator_bin()
        assert not ok


class TestDeliveryMode:
    def test_ok_shadow(self, fake_env, monkeypatch):
        monkeypatch.setenv("CURATOR_DELIVERY_MODE", "shadow")
        ok, message = opencode.check_delivery_mode()
        assert ok
        assert "shadow" in message

    def test_fail_when_unset(self, fake_env, monkeypatch):
        monkeypatch.delenv("CURATOR_DELIVERY_MODE", raising=False)
        ok, message = opencode.check_delivery_mode()
        assert not ok
        assert "launchctl" in message

    def test_fail_when_typo(self, fake_env, monkeypatch):
        monkeypatch.setenv("CURATOR_DELIVERY_MODE", "banana")
        ok, message = opencode.check_delivery_mode()
        assert not ok


class TestShadowLog:
    def _log(self, state_dir, events):
        path = state_dir / "delivery-shadow.jsonl"
        path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")

    def test_ok_when_recent(self, tmp_path):
        from datetime import datetime
        self._log(tmp_path, [{"session_id": "ses_1", "ts": datetime.now().isoformat()}])
        ok, message = opencode.check_shadow_log(tmp_path)
        assert ok, message
        assert "ses_1" in message

    def test_fail_when_stale(self, tmp_path):
        from datetime import datetime, timedelta
        old = datetime.now() - timedelta(days=3)
        self._log(tmp_path, [{"session_id": "ses_old", "ts": old.isoformat()}])
        ok, message = opencode.check_shadow_log(tmp_path)
        assert not ok
        assert "24ч" in message

    def test_fail_when_missing(self, tmp_path):
        ok, message = opencode.check_shadow_log(tmp_path)
        assert not ok


class TestIntegrationStatus:
    def test_all_checks_present(self, fake_env, monkeypatch, tmp_path):
        monkeypatch.delenv("CURATOR_DELIVERY_MODE", raising=False)
        from curator.state import state_dir
        monkeypatch.setattr("curator.state.state_dir", lambda: tmp_path)
        results = integration_status()
        assert len(results) == 5
        assert all(isinstance(ok, bool) for ok, _ in results)

    def test_full_green_path(self, fake_env, monkeypatch, tmp_path):
        from datetime import datetime
        from curator.state import state_dir
        _install_plugins(fake_env)
        _register(fake_env)
        monkeypatch.setenv("CURATOR_DELIVERY_MODE", "shadow")
        fake_bin = fake_env["home"] / ".local" / "bin"
        fake_bin.mkdir(parents=True)
        (fake_bin / "curator").write_text("#!/bin/sh\n", encoding="utf-8")
        monkeypatch.setattr("curator.state.state_dir", lambda: tmp_path)
        self_log = tmp_path / "delivery-shadow.jsonl"
        self_log.write_text(
            json.dumps({"session_id": "ses_live", "ts": datetime.now().isoformat()}) + "\n",
            encoding="utf-8")
        results = integration_status()
        failed = [m for ok, m in results if not ok]
        assert not failed, failed
