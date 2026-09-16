"""Установщик без вопросов: автодетект харнесов, молчаливый дефолт базы,
идемпотентность. Всё в песочнице (HOME → tmp)."""

import json
from pathlib import Path

import pytest

from curator import installer


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("CURATOR_BASE_DIR", raising=False)
    return tmp_path


@pytest.fixture(autouse=True)
def no_worker(monkeypatch):
    from curator import daemon
    monkeypatch.setattr(daemon, "ensure_worker", lambda: "Worker уже запущен (pid 1)")


def _opencode_dir(home):
    d = home / ".config" / "opencode"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _claude_dir(home):
    d = home / ".claude"
    d.mkdir(parents=True, exist_ok=True)
    return d


class TestAutoDetect:
    def test_opencode_only(self, tmp_path):
        _opencode_dir(tmp_path)
        steps = installer.install_all()
        assert any("opencode: MCP" in s for s in steps)
        assert not any("Claude Code: MCP" in s for s in steps)
        config = json.loads((tmp_path / ".config" / "opencode" / "opencode.json").read_text(encoding="utf-8"))
        assert config["mcp"]["memory-curator"]["environment"]["ROUTER_CLASS"] == "curator.routing.map_router.MapRouter"

    def test_claude_only(self, tmp_path, monkeypatch):
        _claude_dir(tmp_path)
        project = tmp_path / "proj"
        project.mkdir()
        monkeypatch.chdir(project)

        steps = installer.install_all()

        assert any("Claude Code: MCP" in s for s in steps)
        assert not (tmp_path / ".config" / "opencode" / "opencode.json").exists(), \
            "opencode не найден — его конфиг не создаём"
        assert (project / ".mcp.json").exists()
        assert (tmp_path / ".claude" / "commands" / "curator-create-map.md").exists()

    def test_both_detected_installed_both(self, tmp_path, monkeypatch):
        _opencode_dir(tmp_path)
        _claude_dir(tmp_path)
        project = tmp_path / "proj"
        project.mkdir()
        monkeypatch.chdir(project)

        installer.install_all()

        assert (tmp_path / ".config" / "opencode" / "opencode.json").exists()
        assert (project / ".mcp.json").exists()

    def test_nothing_detected_opencode_layout_with_hint(self, tmp_path):
        steps = installer.install_all()
        assert any("не обнаружены" in s for s in steps), \
            "без находок — честная подсказка, а не молчаливая установка"
        assert (tmp_path / ".config" / "opencode" / "opencode.json").exists()

    def test_target_override_claude(self, tmp_path, monkeypatch):
        project = tmp_path / "proj"
        project.mkdir()
        monkeypatch.chdir(project)

        installer.install_all(target="claude")

        assert (project / ".mcp.json").exists()
        assert not (tmp_path / ".config" / "opencode").exists()


class TestZeroQuestions:
    def test_footer_tells_how_to_change_base(self, tmp_path):
        steps = installer.install_all()
        text = "\n".join(steps)
        assert "База" in text and "curator status" in text, \
            "где база и как сменить — обязаны быть в выводе, не вопросом"
        assert "попроси агента" in text

    def test_base_dir_flag_silent_override(self, tmp_path):
        _opencode_dir(tmp_path)
        installer.install_all(base_dir=str(tmp_path / "custom-kb"))
        config = json.loads((tmp_path / ".config" / "opencode" / "opencode.json").read_text(encoding="utf-8"))
        assert config["mcp"]["memory-curator"]["environment"]["CURATOR_BASE_DIR"] == str(tmp_path / "custom-kb")

    def test_default_base_neutral(self):
        assert installer.default_base_dir().endswith("memory-curator")
        assert "Documents/AI" not in installer.default_base_dir()


class TestIdempotencyAndSafety:
    def test_merge_preserves_existing(self, tmp_path):
        config_path = _opencode_dir(tmp_path) / "opencode.json"
        config_path.write_text(json.dumps({
            "model": "gpt-test",
            "mcp": {"other": {"command": "x"}},
            "command": {"my-command": {"description": "моя", "template": "т"}},
        }), encoding="utf-8")

        installer.install_all()

        data = json.loads(config_path.read_text(encoding="utf-8"))
        assert data["model"] == "gpt-test"
        assert data["mcp"]["other"] == {"command": "x"}
        assert data["command"]["my-command"]["description"] == "моя"
        assert "curator-save" in data["command"]
        assert "curator-create-map" in data["command"]
        assert "curator-project-save" not in data["command"]
        assert "curator-setup" in data["command"]

    def test_curator_save_command_points_to_skill(self):
        command = installer._commands_source()["curator-save"]
        assert "curator-save" in command["template"]
        assert "status=update_project_docs" in command["template"]
        assert "next_action=curator-update-docs" in command["template"]
        assert "CURATOR_MAP" not in command["template"]
        assert "curator_session_capture" in command["template"]
        assert "curator_capture_approve" in command["template"]
        assert "auto_approve" not in command["template"]
        assert "curator-project-save" not in installer._commands_source()

    def test_project_setup_command_documents_project_paths(self):
        setup = installer._commands_source()["curator-setup"]["template"]
        assert "CURATOR_STATE_DIR" in setup
        assert "CURATOR_BASE_DIR" in setup
        assert "CURATOR_MAP" in setup
        assert "/curator-create-map" in setup

    def test_idempotent_rerun(self, tmp_path):
        _opencode_dir(tmp_path)
        installer.install_all()
        first = (tmp_path / ".config" / "opencode" / "opencode.json").read_text(encoding="utf-8")
        installer.install_all()
        second = (tmp_path / ".config" / "opencode" / "opencode.json").read_text(encoding="utf-8")
        assert first == second

    def test_broken_existing_config_not_touched(self, tmp_path):
        config_path = _opencode_dir(tmp_path) / "opencode.json"
        config_path.write_text("{ это не json", encoding="utf-8")

        steps = installer.install_all()

        assert any("⛔" in s for s in steps)
        assert config_path.read_text(encoding="utf-8") == "{ это не json"

    def test_all_repo_skills_installed(self, tmp_path):
        _opencode_dir(tmp_path)
        installer.install_all()
        skills = {p.name for p in (tmp_path / ".config" / "opencode" / "skills").iterdir()}
        assert {"curator-save", "curator-update-docs",
                "mapping-documentation"} <= skills
        assert "curator-project-save" not in skills
        assert "curator-create-map" not in skills
        assert "curator-save-original" not in skills
        assert "curator-save-experiment" not in skills
        # A/B-обёртки curator-save удалены: канон — curator-save 0.2.0;
        # дубль-скилл curator-create-map удалён: живой оригинал —
        # mapping-documentation, команда /curator-create-map осталась

    @pytest.mark.parametrize("target", ["opencode", "claude"])
    def test_upgrade_removes_installed_project_save(self, tmp_path, monkeypatch, target):
        if target == "opencode":
            harness = _opencode_dir(tmp_path)
            (harness / "opencode.json").write_text(json.dumps({
                "command": {"curator-project-save": {"template": "old"}},
            }), encoding="utf-8")
            command = harness / "opencode.json"
        else:
            harness = _claude_dir(tmp_path)
            project = tmp_path / "proj"
            project.mkdir()
            monkeypatch.chdir(project)
            command = harness / "commands" / "curator-project-save.md"
            command.parent.mkdir()
            command.write_text("old", encoding="utf-8")
        retired_skill = harness / "skills" / "curator-project-save"
        retired_skill.mkdir(parents=True)
        (retired_skill / "SKILL.md").write_text("old", encoding="utf-8")

        installer.install_all(target=target)

        if target == "opencode":
            config = json.loads(command.read_text(encoding="utf-8"))
            assert "curator-project-save" not in config["command"]
        else:
            assert not command.exists()
        assert not retired_skill.exists()

    def test_unrelated_legacy_named_skill_is_preserved(self, tmp_path):
        _opencode_dir(tmp_path)
        legacy = tmp_path / ".config" / "opencode" / "skills" / "mapping-documentation"
        legacy.mkdir(parents=True)
        (legacy / "SKILL.md").write_text("пользовательский скилл", encoding="utf-8")

        installer.install_all()

        assert legacy.exists()


class TestConfiguredBaseDir:
    def test_cli_status_reads_installed_config(self, tmp_path, capsys):
        from curator import control
        _opencode_dir(tmp_path)
        installer.install_all(base_dir=str(tmp_path / "kb"))

        control.cmd_status()

        out = capsys.readouterr().out
        assert str(tmp_path / "kb") in out, "curator status показывает, где лежит база"

    def test_server_status_shows_base(self, tmp_path):
        import curator.server as server_mod
        from curator.backend.local import LocalBackend
        from curator.improve_loop import ImproveLoop
        server_mod.backend = LocalBackend(":memory:")
        server_mod.improve = ImproveLoop(server_mod.backend)
        out = server_mod._status()
        assert "База знаний:" in out
        assert "Состояние:" in out


class TestServerCommand:
    def test_returns_command_and_args(self):
        command, args = installer._server_command()
        assert Path(command).exists()
        assert isinstance(args, list)


class TestPatchPreservesBase:
    """Патч (повторный install) не имеет права сбрасывать существующую
    базу: без --base-dir сохраняем CURATOR_BASE_DIR из установленной
    секции; флаг — осознанное переопределение; свежая установка — дефолт."""

    def _existing_config(self, tmp_path, base):
        config_path = _opencode_dir(tmp_path) / "opencode.json"
        config_path.write_text(json.dumps({
            "mcp": {"memory-curator": {
                "command": "old-server",
                "env": {
                    "MEMORY_BACKEND": "local",
                    "CURATOR_BASE_DIR": base,
                    "CURATOR_STATE_DIR": "/home/user/project/.curator",
                    "CURATOR_MAP": "/home/user/project/DOCUMENTATION-MAP.md",
                },
            }},
        }), encoding="utf-8")
        return config_path

    def test_existing_base_preserved_on_patch(self, tmp_path):
        self._existing_config(tmp_path, "/home/user/precious-kb")
        installer.install_all()
        data = json.loads((_opencode_dir(tmp_path) / "opencode.json").read_text(encoding="utf-8"))
        assert data["mcp"]["memory-curator"]["environment"]["CURATOR_BASE_DIR"] == "/home/user/precious-kb", \
            "патч обязан сохранять существующую базу — молчаливый сброс = потеря базы"
        assert "ROUTER_CLASS" in data["mcp"]["memory-curator"]["environment"], \
            "остальное при патче обновляется"
        assert data["mcp"]["memory-curator"]["environment"]["CURATOR_STATE_DIR"] == "/home/user/project/.curator"
        assert data["mcp"]["memory-curator"]["environment"]["CURATOR_MAP"] == "/home/user/project/DOCUMENTATION-MAP.md"

    def test_base_dir_flag_overrides_existing(self, tmp_path):
        self._existing_config(tmp_path, "/home/user/old-kb")
        installer.install_all(base_dir="/home/user/new-kb")
        data = json.loads((_opencode_dir(tmp_path) / "opencode.json").read_text(encoding="utf-8"))
        assert data["mcp"]["memory-curator"]["environment"]["CURATOR_BASE_DIR"] == "/home/user/new-kb"

    def test_fresh_install_gets_default(self, tmp_path):
        _opencode_dir(tmp_path)
        installer.install_all()
        data = json.loads((_opencode_dir(tmp_path) / "opencode.json").read_text(encoding="utf-8"))
        assert data["mcp"]["memory-curator"]["environment"]["CURATOR_BASE_DIR"].endswith("memory-curator")


class TestSkillSymlinkDest:
    """Локальный symlink не должен уничтожаться обычным install."""

    def test_symlink_preserved_by_default(self, tmp_path, monkeypatch):
        _opencode_dir(tmp_path)
        dest_root = tmp_path / ".config" / "opencode" / "skills"
        dest_root.mkdir(parents=True)
        link = dest_root / "curator-save"
        link.symlink_to(_repo_root_for_test() / ".agents" / "skills" / "curator-save")

        installer.install_all()

        assert link.is_dir() and link.is_symlink(), \
            "обычный install не должен уничтожать dev symlink"
        assert (link / "SKILL.md").exists()

    def test_link_mode_creates_symlink(self, tmp_path):
        _opencode_dir(tmp_path)
        installer.install_all(skills_mode="link")
        link = tmp_path / ".config" / "opencode" / "skills" / "curator-save"
        assert link.is_symlink()
        assert link.resolve() == _repo_root_for_test() / ".agents" / "skills" / "curator-save"

    def test_copy_mode_replaces_symlink(self, tmp_path):
        _opencode_dir(tmp_path)
        dest_root = tmp_path / ".config" / "opencode" / "skills"
        dest_root.mkdir(parents=True)
        link = dest_root / "curator-save"
        link.symlink_to(_repo_root_for_test() / ".agents" / "skills" / "curator-save")

        installer.install_all(skills_mode="copy")

        assert link.is_dir() and not link.is_symlink()


def _repo_root_for_test():
    from curator.installer import _repo_root
    return _repo_root()


class TestOpencodeMcpSchema:
    """Регрессия живых инцидентов. Официальная схема opencode
    (opencode.ai/docs/mcp-servers):
      1) без type=local+enabled — старт падает (ConfigInvalidError)
      2) command — МАССИВ, переменные — ключ environment (не env):
         отклонение = сервер молча не стартует, его нет в списке MCP
    """

    def test_opencode_entry_matches_official_schema(self, tmp_path):
        _opencode_dir(tmp_path)
        installer.install_all()
        entry = json.loads((_opencode_dir(tmp_path) / "opencode.json").read_text(encoding="utf-8"))["mcp"]["memory-curator"]
        assert entry["type"] == "local"
        assert entry["enabled"] is True
        assert isinstance(entry["command"], list) and entry["command"], \
            "command обязан быть массивом (команда и аргументы) — строка = сервер молча не стартует"
        assert "environment" in entry and "env" not in entry, \
            "переменные окружения в opencode живут под ключом environment"
        assert entry["environment"]["CURATOR_BASE_DIR"]

    def test_claude_entry_own_schema(self, tmp_path, monkeypatch):
        _claude_dir(tmp_path)
        project = tmp_path / "proj"
        project.mkdir()
        monkeypatch.chdir(project)
        installer.install_all()
        entry = json.loads((project / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["memory-curator"]
        assert "type" not in entry and "environment" not in entry, \
            "у Claude Code своя схема: command (строка) + env"
        assert isinstance(entry["command"], str) and entry["env"]["CURATOR_BASE_DIR"]


class TestJsoncTolerance:
    """Конфиги правят руками — jsonc-хвосты (запятая перед } или ]) не должны
    ломать установку; записываем обратно чистым JSON (лечим конфиг)."""

    def test_trailing_comma_read_and_healed(self, tmp_path):
        config_path = _opencode_dir(tmp_path) / "opencode.json"
        config_path.write_text('{"model": "x", "mcp": {},}', encoding="utf-8")

        steps = installer.install_all()

        assert not any("⛔" in s for s in steps)
        text = config_path.read_text(encoding="utf-8")
        data = json.loads(text)  # записанное обязано быть строгим JSON
        assert data["model"] == "x"
        assert "memory-curator" in data["mcp"]

    def test_real_user_scenario_after_manual_removal(self, tmp_path):
        """Инцидент: пользователь руками вырезал секцию и оставил запятую."""
        config_path = _opencode_dir(tmp_path) / "opencode.json"
        config_path.write_text(json.dumps({
            "model": "gpt-5",
            "mcp": {"gitlab": {"type": "remote", "enabled": True, "url": "https://x"}},
            "command": {"skill-creator": {"description": "d", "template": "t"}},
        })[:-1] + ",}", encoding="utf-8")

        installer.install_all(base_dir="/home/user/kb")

        data = json.loads(config_path.read_text(encoding="utf-8"))
        assert data["mcp"]["gitlab"]["url"] == "https://x", "чужой mcp цел"
        entry = data["mcp"]["memory-curator"]
        assert entry["type"] == "local" and entry["enabled"] is True
        assert entry["environment"]["CURATOR_BASE_DIR"] == "/home/user/kb"
        assert data["command"]["skill-creator"]["description"] == "d"


class TestGlobalRules:
    """Read-side без хуков: секция Memory Curator в глобальном файле правил
    (AGENTS.md / CLAUDE.md) — база попадает в контекст каждой сессии."""

    def test_opencode_rules_created(self, tmp_path):
        _opencode_dir(tmp_path)
        installer.install_all()
        agents = tmp_path / ".config" / "opencode" / "AGENTS.md"
        text = agents.read_text(encoding="utf-8")
        assert "memory-curator:begin" in text
        assert "/curator-save" in text

    def test_rules_keep_foreign_content(self, tmp_path):
        _opencode_dir(tmp_path)
        agents = tmp_path / ".config" / "opencode" / "AGENTS.md"
        agents.write_text("# Мои личные правила\n\nНе делать лишнего.\n", encoding="utf-8")

        installer.install_all()

        text = agents.read_text(encoding="utf-8")
        assert "Мои личные правила" in text, "чужой контент не трогаем"
        assert "memory-curator:begin" in text

    def test_rules_idempotent(self, tmp_path):
        _opencode_dir(tmp_path)
        installer.install_all()
        installer.install_all()
        text = (tmp_path / ".config" / "opencode" / "AGENTS.md").read_text(encoding="utf-8")
        assert text.count("memory-curator:begin") == 1, "повторный install не дублирует секцию"

    def test_plugin_installed(self, tmp_path):
        _opencode_dir(tmp_path)
        installer.install_all()
        plugin = tmp_path / ".config" / "opencode" / "plugins" / "curator-reminder.js"
        assert plugin.exists()
        assert "session.idle" in plugin.read_text(encoding="utf-8")

    def test_claude_rules_in_claude_md(self, tmp_path, monkeypatch):
        _claude_dir(tmp_path)
        project = tmp_path / "proj"
        project.mkdir()
        monkeypatch.chdir(project)

        installer.install_all(target="claude")

        text = (tmp_path / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
        assert "memory-curator:begin" in text
        assert "/curator-query" in text
