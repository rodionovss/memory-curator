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
        assert any("opencode: команды" in s for s in steps)
        assert not any("Claude Code:" in s for s in steps), \
            "футер упоминает Claude Code — шагов его установки быть не должно"
        config = json.loads((tmp_path / ".config" / "opencode" / "opencode.json").read_text(encoding="utf-8"))
        assert "curator-save" in config["command"], \
            "MCP-машинерии нет: ставим команды, скиллы и правила"

    def test_claude_only(self, tmp_path, monkeypatch):
        _claude_dir(tmp_path)
        project = tmp_path / "proj"
        project.mkdir()
        monkeypatch.chdir(project)

        steps = installer.install_all()

        assert any("Claude Code" in s for s in steps)
        assert not (tmp_path / ".config" / "opencode" / "opencode.json").exists(), \
            "opencode не найден — его конфиг не создаём"
        assert not (project / ".mcp.json").exists(), "MCP-конфиг не пишется"
        assert (tmp_path / ".claude" / "commands" / "curator-create-map.md").exists()

    def test_both_detected_installed_both(self, tmp_path, monkeypatch):
        _opencode_dir(tmp_path)
        _claude_dir(tmp_path)
        project = tmp_path / "proj"
        project.mkdir()
        monkeypatch.chdir(project)

        installer.install_all()

        assert (tmp_path / ".config" / "opencode" / "opencode.json").exists()
        assert (tmp_path / ".claude" / "CLAUDE.md").exists()

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

        assert (tmp_path / ".claude" / "CLAUDE.md").exists()
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
        from curator.state import configured_base
        assert configured_base() == str(tmp_path / "custom-kb")

    def test_default_base_neutral(self):
        assert installer.default_base_dir().endswith("memory-curator")
        assert "Documents/AI" not in installer.default_base_dir()


class TestIdempotencyAndSafety:
    def test_merge_preserves_existing(self, tmp_path):
        config_path = _opencode_dir(tmp_path) / "opencode.json"
        config_path.write_text(json.dumps({
            "model": "gpt-test",
            "command": {"my-command": {"description": "моя", "template": "т"}},
        }), encoding="utf-8")

        installer.install_all()

        data = json.loads(config_path.read_text(encoding="utf-8"))
        assert data["model"] == "gpt-test"
        assert data["command"]["my-command"]["description"] == "моя"
        assert "curator-save" in data["command"]
        assert "curator-create-map" in data["command"]
        assert "curator-project-save" not in data["command"]
        assert "curator-setup" not in data["command"], \
            "project-local setup отложен до редизайна без MCP"
        assert "curator-start" not in data["command"], "ноль фоновых процессов"
        assert "curator-stop" not in data["command"]
        assert "curator-worker" not in data["command"]
        assert "curator-report" not in data["command"], "report снесён (2026-11-14)"
        assert "curator-full" not in data["command"]

    def test_curator_save_command_points_to_skill(self):
        command = installer._commands_source()["curator-save"]
        assert "curator-save" in command["template"]
        assert "curator save" in command["template"], \
            "команда ведёт к CLI-флоу скилла, не к MCP-тулам"
        assert "curator_session_capture" not in command["template"]
        assert "curator_capture_approve" not in command["template"]
        assert "curator-project-save" not in installer._commands_source()

    def test_commands_reference_cli_not_mcp(self):
        for name, spec in installer._commands_source().items():
            assert "memory-curator_" not in spec["template"], \
                f"команда {name} ссылается на MCP-тулы, которых больше нет"
            assert "mcp.memory-curator" not in spec["template"], \
                f"команда {name} ссылается на MCP-конфиг, которого больше нет"

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


class TestKnowledgeRoutesPointer:
    """Placement M2 (эксперимент 05): каталог маршрутов живёт в базе,
    в глобальном rules-файле — единая секция Memory Curator (правила
    памяти + pointer каталога + hint регенерации). Отдельной
    routes-секции нет; протухший блок старых установок удаляется.
    instructions конфига не трогаем, контент каталога в секцию не
    попадает."""

    def _agents_md(self, tmp_path):
        return tmp_path / ".config" / "opencode" / "AGENTS.md"

    def test_instructions_untouched_by_install(self, tmp_path):
        config_path = _opencode_dir(tmp_path) / "opencode.json"
        config_path.write_text(json.dumps({
            "instructions": ["/abs/AGENTS.md", "~/rules/*.md"],
        }), encoding="utf-8")

        installer.install_all()

        data = json.loads(config_path.read_text(encoding="utf-8"))
        assert data["instructions"] == ["/abs/AGENTS.md", "~/rules/*.md"], \
            "instructions — не наш механизм доставки, install их не меняет"

    def test_no_instructions_added_when_absent(self, tmp_path):
        config_path = _opencode_dir(tmp_path) / "opencode.json"
        config_path.write_text("{}", encoding="utf-8")

        installer.install_all()

        data = json.loads(config_path.read_text(encoding="utf-8"))
        assert "instructions" not in data, "M2: ничего не грузим в контекст через конфиг"

    def test_single_section_with_catalog_path_and_hint(self, tmp_path):
        base = tmp_path / "kb"
        base.mkdir()
        _opencode_dir(tmp_path)

        installer.install_all(base_dir=str(base))

        text = self._agents_md(tmp_path).read_text(encoding="utf-8")
        assert text.count("memory-curator:begin") == 1, "одна секция Curator"
        assert "memory-curator-routes:begin" not in text, "отдельной routes-секции больше нет"
        assert str(base / "knowledge-routes.md") in text, "абсолютный путь каталога"
        assert "curator knowledge-routes --write" in text, "hint регенерации"
        assert "/curator-save" in text, "правило сохранения знаний — в той же секции"

    def test_single_section_idempotent(self, tmp_path):
        base = tmp_path / "kb"
        base.mkdir()
        _opencode_dir(tmp_path)

        installer.install_all(base_dir=str(base))
        installer.install_all(base_dir=str(base))

        text = self._agents_md(tmp_path).read_text(encoding="utf-8")
        assert text.count("memory-curator:begin") == 1
        assert text.count(str(base / "knowledge-routes.md")) == 1

    def test_stale_routes_block_removed_on_reinstall(self, tmp_path):
        base = tmp_path / "kb"
        base.mkdir()
        _opencode_dir(tmp_path)
        agents = self._agents_md(tmp_path)
        agents.write_text(
            "# Мои правила\n\n"
            "<!-- memory-curator-routes:begin -->\n"
            "## Memory Curator — каталог маршрутов базы\n\nстарый дубль\n"
            "<!-- memory-curator-routes:end -->\n",
            encoding="utf-8")

        installer.install_all(base_dir=str(base))

        text = agents.read_text(encoding="utf-8")
        assert "memory-curator-routes:begin" not in text, "протухший блок удалён"
        assert "старый дубль" not in text
        assert "# Мои правила" in text, "чужой контент не трогаем"
        assert text.count("memory-curator:begin") == 1

    def test_section_keeps_foreign_content(self, tmp_path):
        _opencode_dir(tmp_path)
        agents = self._agents_md(tmp_path)
        agents.write_text("# Мои личные правила\n\nНе делать лишнего.\n", encoding="utf-8")

        installer.install_all()

        text = agents.read_text(encoding="utf-8")
        assert "Мои личные правила" in text, "чужой контент вне маркеров не трогаем"
        assert "memory-curator:begin" in text

    def test_no_catalog_content_in_section(self, tmp_path):
        base = tmp_path / "kb"
        base.mkdir()
        (base / "knowledge-routes.md").write_text(
            "## compose\n\n**When to use:**\n- секретный маршрут;\n",
            encoding="utf-8")
        _opencode_dir(tmp_path)

        installer.install_all(base_dir=str(base))

        text = self._agents_md(tmp_path).read_text(encoding="utf-8")
        assert "**When to use:**" not in text, "секция несёт путь, не контент каталога"
        assert "секретный маршрут" not in text
        assert str(base / "knowledge-routes.md") in text

    def test_missing_catalog_file_section_still_written(self, tmp_path):
        base = tmp_path / "kb"
        base.mkdir()  # без knowledge-routes.md
        _opencode_dir(tmp_path)

        installer.install_all(base_dir=str(base))

        text = self._agents_md(tmp_path).read_text(encoding="utf-8")
        assert "memory-curator:begin" in text, \
            "секция пишется и без файла — hint регенерации в самой секции"

    def test_claude_single_section_in_claude_md(self, tmp_path, monkeypatch):
        _claude_dir(tmp_path)
        project = tmp_path / "proj"
        project.mkdir()
        monkeypatch.chdir(project)

        installer.install_all(target="claude", base_dir=str(tmp_path / "kb"))

        text = (tmp_path / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
        assert text.count("memory-curator:begin") == 1
        assert "memory-curator-routes:begin" not in text
        assert str(tmp_path / "kb" / "knowledge-routes.md") in text
        assert "curator knowledge-routes --write" in text


class TestConfiguredBaseDir:
    def test_cli_status_reads_installed_config(self, tmp_path, capsys):
        from curator import control
        _opencode_dir(tmp_path)
        installer.install_all(base_dir=str(tmp_path / "kb"))

        control.cmd_status()

        out = capsys.readouterr().out
        assert str(tmp_path / "kb") in out, "curator status показывает, где лежит база"


class TestStateConfigBase:
    """База персистится в state-конфиге (~/.curator/config.json), не в
    MCP-секциях: env > state-конфиг > дефолт. Патч не сбрасывает базу."""

    def test_install_writes_state_config(self, tmp_path):
        _opencode_dir(tmp_path)

        installer.install_all(base_dir=str(tmp_path / "kb"))

        from curator.state import configured_base
        assert configured_base() == str(tmp_path / "kb")

    def test_existing_base_preserved_on_patch(self, tmp_path):
        from curator.state import write_configured_base
        _opencode_dir(tmp_path)
        write_configured_base("/home/user/precious-kb")

        installer.install_all()

        from curator.state import configured_base
        assert configured_base() == "/home/user/precious-kb", \
            "патч обязан сохранять существующую базу — молчаливый сброс = потеря базы"

    def test_base_dir_flag_overrides_existing(self, tmp_path):
        from curator.state import write_configured_base
        _opencode_dir(tmp_path)
        write_configured_base("/home/user/old-kb")

        installer.install_all(base_dir="/home/user/new-kb")

        from curator.state import configured_base
        assert configured_base() == "/home/user/new-kb"

    def test_fresh_install_gets_default(self, tmp_path):
        _opencode_dir(tmp_path)

        installer.install_all()

        from curator.state import configured_base
        assert (configured_base() or "").endswith("memory-curator")


class TestUpgradeCleansOldInstall:
    """Апгрейд установки старой версии (MCP-эпоха): свои мёртвые записи
    чистятся, база мигрирует из MCP-env в state-конфиг, чужие не тронуты."""

    def _old_opencode_config(self, tmp_path, base):
        config_path = _opencode_dir(tmp_path) / "opencode.json"
        config_path.write_text(json.dumps({
            "mcp": {
                "figma": {"type": "local", "command": ["node", "x"]},
                "memory-curator": {"type": "local", "command": ["curator-mcp-server"],
                                   "environment": {"CURATOR_BASE_DIR": base}},
            },
            "plugin": [
                "superpowers@git+https://github.com/obra/superpowers.git",
                str(tmp_path / ".config/opencode/plugins/curator-reminder.js"),
                str(tmp_path / ".config/opencode/plugins/curator-context.js"),
            ],
        }), encoding="utf-8")
        return config_path

    def test_mcp_entry_and_plugins_removed_base_migrated(self, tmp_path):
        self._old_opencode_config(tmp_path, "/home/user/old-kb")

        steps = installer.install_all()

        data = json.loads((_opencode_dir(tmp_path) / "opencode.json").read_text(encoding="utf-8"))
        assert "memory-curator" not in data["mcp"], "мёртвая MCP-запись удалена"
        assert data["mcp"]["figma"]["command"] == ["node", "x"], "чужой mcp цел"
        plugins = data["plugin"]
        assert all(not p.endswith((".js")) or "curator" not in p for p in plugins), \
            "свои plugin[]-записи удалены"
        assert any("superpowers" in p for p in plugins), "чужие plugin[] целы"
        from curator.state import configured_base
        assert configured_base() == "/home/user/old-kb", \
            "база из старой MCP-записи мигрирована в state-конфиг, не сброшена на дефолт"

    def test_claude_mcp_json_cleaned(self, tmp_path, monkeypatch):
        _claude_dir(tmp_path)
        project = tmp_path / "proj"
        project.mkdir()
        monkeypatch.chdir(project)
        (project / ".mcp.json").write_text(json.dumps({
            "mcpServers": {
                "other": {"command": "x"},
                "memory-curator": {"command": "curator-mcp-server",
                                   "env": {"CURATOR_BASE_DIR": "/home/user/claude-kb"}},
            },
        }), encoding="utf-8")

        installer.install_all(target="claude")

        data = json.loads((project / ".mcp.json").read_text(encoding="utf-8"))
        assert "memory-curator" not in data["mcpServers"], "мёртвая запись удалена"
        assert data["mcpServers"]["other"] == {"command": "x"}, "чужие целы"
        from curator.state import configured_base
        assert configured_base() == "/home/user/claude-kb", "база мигрирована"

    def test_state_config_wins_over_legacy(self, tmp_path):
        from curator.state import write_configured_base
        self._old_opencode_config(tmp_path, "/home/user/old-kb")
        write_configured_base("/home/user/precious-kb")

        installer.install_all()

        from curator.state import configured_base
        assert configured_base() == "/home/user/precious-kb", \
            "state-конфиг новее legacy — он и есть истина"


class TestNoBackgroundMachinery:
    """Решение 2026-10-03 «ноль фоновых процессов»: install не ставит
    MCP-сервер, worker-демон и delivery-плагины."""

    def test_no_mcp_section_written(self, tmp_path):
        config_path = _opencode_dir(tmp_path) / "opencode.json"
        config_path.write_text('{"mcp": {"other": {"command": "x"}}}', encoding="utf-8")

        installer.install_all()

        data = json.loads(config_path.read_text(encoding="utf-8"))
        assert "memory-curator" not in data.get("mcp", {}), \
            "MCP-сервер Curator не регистрируется"
        assert data["mcp"]["other"] == {"command": "x"}, "чужие mcp не трогаем"

    def test_no_plugins_installed(self, tmp_path):
        _opencode_dir(tmp_path)

        installer.install_all()

        assert not (tmp_path / ".config" / "opencode" / "plugins" / "curator-reminder.js").exists()
        assert not (tmp_path / ".config" / "opencode" / "plugins" / "curator-context.js").exists()

    def test_no_worker_step(self, tmp_path):
        _opencode_dir(tmp_path)

        steps = installer.install_all()

        assert not any("Worker:" in s or "worker не поднялся" in s for s in steps), \
            "worker-демон не поднимается установкой"
        assert not (tmp_path / ".curator" / "worker.pid").exists()


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
        assert "curator-save" in data["command"], "команды установлены в вылеченном конфиге"

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
        assert "memory-curator" not in data["mcp"], "своих MCP-записей не пишем"
        assert data["command"]["skill-creator"]["description"] == "d"
        assert "curator-save" in data["command"]
        from curator.state import configured_base
        assert configured_base() == "/home/user/kb"


class TestDefaultMap:
    """Новому пользователю нечего настраивать: install создаёт дефолтную
    knowledge-map.md, существующую карту не трогает."""

    def test_install_creates_default_map(self, tmp_path):
        _opencode_dir(tmp_path)

        installer.install_all(base_dir=str(tmp_path / "kb"))

        from curator.routing.map_router import MapRouter
        router = MapRouter(tmp_path / "kb" / "knowledge-map.md")
        assert router._topics, "дефолтная карта валидна и непуста"
        assert not router.validation_errors()

    def test_existing_map_not_overwritten(self, tmp_path):
        _opencode_dir(tmp_path)
        kb = tmp_path / "kb"
        kb.mkdir()
        (kb / "knowledge-map.md").write_text("Моя карта", encoding="utf-8")

        installer.install_all(base_dir=str(kb))

        assert (kb / "knowledge-map.md").read_text(encoding="utf-8") == "Моя карта", \
            "существующая карта — источник истины, дефолт её не заменяет"


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

    def test_claude_rules_in_claude_md(self, tmp_path, monkeypatch):
        _claude_dir(tmp_path)
        project = tmp_path / "proj"
        project.mkdir()
        monkeypatch.chdir(project)

        installer.install_all(target="claude")

        text = (tmp_path / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
        assert "memory-curator:begin" in text
        assert "/curator-save" in text, "правило сохранения знаний в секции"
        assert "knowledge-routes.md" in text, "pointer каталога с подставленным путём"


class TestRepoAssetsGuard:
    def test_missing_integrations_raises_with_fix_hint(self, tmp_path, monkeypatch):
        _opencode_dir(tmp_path)
        fake_root = tmp_path / "site-packages"
        fake_root.mkdir()
        monkeypatch.setattr(installer, "_repo_root", lambda: fake_root)

        with pytest.raises(installer.RepoAssetsMissingError) as exc:
            installer.install_all()

        message = str(exc.value)
        assert "integrations/commands.json" in message, "называем отсутствующий файл"
        assert "uv tool install" in message, "подсказка рабочего пути установки"
        assert "cd memory-curator" in message, "подсказка синхронна с README-флоу (clone → cd → -e ./core)"

    def test_cli_refusal_exits_nonzero(self, tmp_path, monkeypatch, capsys):
        import sys

        from curator import control
        _opencode_dir(tmp_path)
        fake_root = tmp_path / "site-packages"
        fake_root.mkdir()
        monkeypatch.setattr(installer, "_repo_root", lambda: fake_root)
        monkeypatch.setattr(sys, "argv", ["curator", "install"])

        with pytest.raises(SystemExit) as exc:
            control.cmd_install()

        assert exc.value.code == 1, "отказ установки ≠ успех для вызывающего скрипта"
