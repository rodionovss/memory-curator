"""Тесты CLI curator knowledge-routes: render/json/write/check + exit-коды.

Контракт: design/knowledge-route-format.md + task-3 brief. Тестируют реальное
поведение CLI (парсинг → выполнение → exit code), stdout машинных режимов
остаётся чистым (ошибки — в stderr).
"""

import json
import os
import stat
import sys

import pytest

import curator.control as control
from curator import installer
from curator.backend.local import LocalBackend
from curator.knowledge_routes import build_routes, render_routes_markdown
from curator.models import FactQuery, StructuredFact


def make_fact(
    title: str,
    source_file: str | None = "compose.md",
    tags: tuple[str, ...] = ("compose",),
    status: str = "verified",
) -> StructuredFact:
    return StructuredFact(
        type="Reference",
        title=title,
        tags=list(tags),
        status=status,
        content_summary=f"Тело факта '{title}' — не должно попадать в каталог",
        source_file=source_file,
    )


def store(*facts: StructuredFact) -> None:
    backend = LocalBackend()
    for fact in facts:
        backend.store_fact(fact)


def db_facts() -> list[StructuredFact]:
    return LocalBackend().query_facts(FactQuery())


def expected_markdown(base_dir) -> str:
    return render_routes_markdown(list(build_routes(db_facts(), base_dir).routes))


@pytest.fixture
def env(monkeypatch, tmp_path):
    """Изолированные base dir + база фактов + HOME (publish указателей)."""
    base = tmp_path / "learnings"
    base.mkdir()
    monkeypatch.setenv("CURATOR_DB_PATH", str(tmp_path / "knowledge.db"))
    monkeypatch.setenv("CURATOR_BASE_DIR", str(base))
    monkeypatch.setenv("HOME", str(tmp_path))
    return base


class TestRenderMarkdown:
    def test_one_entry_per_source_file(self, env, capsys):
        store(make_fact("Alpha", source_file="a.md"), make_fact("Beta", source_file="b.md"))

        rc = control.cmd_knowledge_routes([])

        out = capsys.readouterr().out
        assert rc == 0
        assert out == expected_markdown(env)  # pristine stdout: только каталог
        assert "## a" in out and "## b" in out
        assert "`a.md`" in out and "`b.md`" in out
        assert "Тело факта" not in out

    def test_deprecated_facts_not_rendered(self, env, capsys):
        store(
            make_fact("Live", source_file="a.md"),
            make_fact("Dead", source_file="z.md", status="deprecated"),
        )

        rc = control.cmd_knowledge_routes([])

        out = capsys.readouterr().out
        assert rc == 0
        assert "Live" in out
        assert "Dead" not in out
        assert "z.md" not in out

    def test_validation_errors_exit1_printed_to_stderr(self, env, capsys):
        store(make_fact("NoFile", source_file=None), make_fact("Ok", source_file="a.md"))

        rc = control.cmd_knowledge_routes([])

        captured = capsys.readouterr()
        assert rc == 1
        assert "## a" in captured.out  # валидные маршруты рендерятся
        assert "NoFile" in captured.err  # ошибки видны человеку
        assert "source_file" in captured.err


class TestRenderJson:
    def test_json_records_have_contract_fields(self, env, capsys):
        store(make_fact("Alpha", source_file="a.md", tags=("compose",)))

        rc = control.cmd_knowledge_routes(["--json"])

        out = capsys.readouterr().out
        assert rc == 0
        data = json.loads(out)  # stdout — чистый JSON
        assert len(data) == 1
        route = data[0]
        assert set(route) == {"name", "source_file", "description", "when_to_use", "contains"}
        assert route["name"] == "a"
        assert route["source_file"] == "a.md"
        assert "Alpha" in route["when_to_use"]
        assert "compose" in route["when_to_use"]
        assert route["contains"] == ["Alpha"]
        assert "Тело факта" not in out


class TestWrite:
    def test_write_creates_target_in_base_dir(self, env, capsys):
        store(make_fact("Alpha", source_file="a.md"))

        rc = control.cmd_knowledge_routes(["--write"])

        target = env / "knowledge-routes.md"
        assert rc == 0
        assert target.exists()
        assert target.read_text(encoding="utf-8") == expected_markdown(env)

    def test_repeated_writes_are_idempotent(self, env):
        store(make_fact("Alpha", source_file="a.md"))
        assert control.cmd_knowledge_routes(["--write"]) == 0
        first = (env / "knowledge-routes.md").read_bytes()

        assert control.cmd_knowledge_routes(["--write"]) == 0

        assert (env / "knowledge-routes.md").read_bytes() == first
        assert not list(env.glob("*.tmp.*"))  # временных файлов не осталось

    def test_write_preserves_existing_permissions(self, env):
        store(make_fact("Alpha", source_file="a.md"))
        control.cmd_knowledge_routes(["--write"])
        target = env / "knowledge-routes.md"
        target.chmod(0o640)

        rc = control.cmd_knowledge_routes(["--write"])

        assert rc == 0
        assert stat.S_IMODE(target.stat().st_mode) == 0o640

    def test_write_failure_cleans_tmp_and_keeps_target(self, env, capsys, monkeypatch):
        store(make_fact("Alpha", source_file="a.md"))
        control.cmd_knowledge_routes(["--write"])
        target = env / "knowledge-routes.md"
        original = target.read_bytes()

        def boom(src, dst):
            raise OSError("диск загорелся")

        monkeypatch.setattr(os, "replace", boom)
        rc = control.cmd_knowledge_routes(["--write"])

        err = capsys.readouterr().err
        assert rc != 0
        assert "Ошибка записи" in err  # человекочитаемая ошибка
        assert target.read_bytes() == original  # целевой файл не тронут
        assert not list(env.glob("*.tmp.*"))  # tmp удалён после неудачи

    def test_write_missing_base_dir_exit2_creates_nothing(self, monkeypatch, tmp_path, capsys):
        missing = tmp_path / "nope"
        monkeypatch.setenv("CURATOR_DB_PATH", str(tmp_path / "knowledge.db"))
        monkeypatch.setenv("CURATOR_BASE_DIR", str(missing))

        rc = control.cmd_knowledge_routes(["--write"])

        capsys.readouterr()
        assert rc == 2
        assert not missing.exists()  # директории не создаём

    def test_base_dir_not_configured_exit2(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setenv("CURATOR_DB_PATH", str(tmp_path / "knowledge.db"))
        monkeypatch.delenv("CURATOR_BASE_DIR", raising=False)
        monkeypatch.setattr(control, "_configured_base_dir", lambda: None)

        rc = control.cmd_knowledge_routes([])

        err = capsys.readouterr().err
        assert rc == 2
        assert "base dir" in err

    def test_base_dir_flag_overrides_env(self, env, tmp_path):
        other = tmp_path / "other"
        other.mkdir()
        store(make_fact("Alpha", source_file="a.md"))

        rc = control.cmd_knowledge_routes(["--write", "--base-dir", str(other)])

        assert rc == 0
        assert (other / "knowledge-routes.md").exists()
        assert not (env / "knowledge-routes.md").exists()

    def test_source_md_files_never_modified(self, env):
        source = env / "a.md"
        source.write_text("# A\n\nоригинал\n", encoding="utf-8")
        store(make_fact("Alpha", source_file="a.md"))

        control.cmd_knowledge_routes(["--write"])

        assert source.read_text(encoding="utf-8") == "# A\n\nоригинал\n"

    def test_write_with_validation_errors_writes_and_exits1(self, env, capsys):
        store(make_fact("NoFile", source_file=None), make_fact("Ok", source_file="a.md"))

        rc = control.cmd_knowledge_routes(["--write"])

        captured = capsys.readouterr()
        assert rc == 1
        assert (env / "knowledge-routes.md").exists()  # валидная часть записана
        assert "NoFile" in captured.err


class TestWritePublishesPointer:
    """--write публикует pointer-секцию каталога в глобальные rules-файлы
    обнаруженных харнесов (placement M2, эксперимент 05)."""

    def test_write_publishes_pointer_opencode(self, env, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        (home / ".config" / "opencode").mkdir(parents=True)
        monkeypatch.setenv("HOME", str(home))
        store(make_fact("Alpha", source_file="a.md"))

        rc = control.cmd_knowledge_routes(["--write"])

        assert rc == 0
        text = (home / ".config" / "opencode" / "AGENTS.md").read_text(encoding="utf-8")
        assert "memory-curator-routes:begin" in text
        assert str(env / "knowledge-routes.md") in text
        assert "curator knowledge-routes --write" in text
        assert "pointer" in capsys.readouterr().out.lower()

    def test_write_publishes_pointer_claude(self, env, tmp_path, monkeypatch):
        home = tmp_path / "home"
        (home / ".claude").mkdir(parents=True)
        monkeypatch.setenv("HOME", str(home))
        store(make_fact("Alpha", source_file="a.md"))

        rc = control.cmd_knowledge_routes(["--write"])

        assert rc == 0
        text = (home / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
        assert "memory-curator-routes:begin" in text
        assert str(env / "knowledge-routes.md") in text

    def test_write_twice_pointer_not_duplicated(self, env, tmp_path, monkeypatch):
        home = tmp_path / "home"
        (home / ".config" / "opencode").mkdir(parents=True)
        monkeypatch.setenv("HOME", str(home))
        store(make_fact("Alpha", source_file="a.md"))
        assert control.cmd_knowledge_routes(["--write"]) == 0

        rc = control.cmd_knowledge_routes(["--write"])

        assert rc == 0
        text = (home / ".config" / "opencode" / "AGENTS.md").read_text(encoding="utf-8")
        assert text.count("memory-curator-routes:begin") == 1

    def test_write_without_harnesses_publishes_nothing(self, env, tmp_path):
        store(make_fact("Alpha", source_file="a.md"))

        rc = control.cmd_knowledge_routes(["--write"])

        assert rc == 0
        assert not (tmp_path / ".config").exists(), "нет харнесов — rules-файлы не создаём"
        assert not (tmp_path / ".claude").exists()

    def test_write_unwritable_rules_one_harness_other_published(self, env, tmp_path, monkeypatch, capsys):
        """rules-файл одного харнеса незаписываем (OSError) — ⚠ вместо крэша:
        каталог уже записан, второй харнес опубликован, команда выходит 0."""
        home = tmp_path / "home"
        (home / ".config" / "opencode").mkdir(parents=True)
        (home / ".claude").mkdir(parents=True)
        monkeypatch.setenv("HOME", str(home))
        store(make_fact("Alpha", source_file="a.md"))

        real_install = installer._install_routes_pointer

        def opencode_boom(rules_path, base):
            if rules_path.name == "AGENTS.md":
                raise OSError("файл только для чтения")
            return real_install(rules_path, base)

        monkeypatch.setattr(installer, "_install_routes_pointer", opencode_boom)

        rc = control.cmd_knowledge_routes(["--write"])

        captured = capsys.readouterr()
        assert rc == 0, "каталог записан — сбой publish одного харнеса не валит команду"
        assert (env / "knowledge-routes.md").exists()
        assert "⚠" in captured.out  # сбой виден как предупреждение, не traceback
        text = (home / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
        assert "memory-curator-routes:begin" in text, "второй харнес всё же опубликован"
        assert not (home / ".config" / "opencode" / "AGENTS.md").exists()

    def test_check_does_not_touch_rules_files(self, env, tmp_path, monkeypatch):
        home = tmp_path / "home"
        (home / ".config" / "opencode").mkdir(parents=True)
        monkeypatch.setenv("HOME", str(home))
        store(make_fact("Alpha", source_file="a.md"))
        assert control.cmd_knowledge_routes(["--write"]) == 0
        agents = home / ".config" / "opencode" / "AGENTS.md"
        before = agents.read_text(encoding="utf-8")

        rc = control.cmd_knowledge_routes(["--check"])

        assert rc == 0
        assert agents.read_text(encoding="utf-8") == before, "--check ничего не меняет"


class TestCheck:
    def test_check_fresh_catalog_ok(self, env, capsys):
        store(make_fact("Alpha", source_file="a.md"))
        control.cmd_knowledge_routes(["--write"])

        rc = control.cmd_knowledge_routes(["--check"])

        capsys.readouterr()
        assert rc == 0

    def test_check_fails_when_facts_changed(self, env, capsys):
        store(make_fact("Alpha", source_file="a.md"))
        control.cmd_knowledge_routes(["--write"])
        store(make_fact("Beta", source_file="b.md"))  # факты ушли вперёд

        rc = control.cmd_knowledge_routes(["--check"])

        err = capsys.readouterr().err
        assert rc == 1
        assert "устарел" in err

    def test_check_fails_when_file_tampered(self, env, capsys):
        store(make_fact("Alpha", source_file="a.md"))
        control.cmd_knowledge_routes(["--write"])
        (env / "knowledge-routes.md").write_text("## подделка\n", encoding="utf-8")

        rc = control.cmd_knowledge_routes(["--check"])

        capsys.readouterr()
        assert rc == 1

    def test_check_missing_target_exit1(self, env, capsys):
        store(make_fact("Alpha", source_file="a.md"))

        rc = control.cmd_knowledge_routes(["--check"])

        err = capsys.readouterr().err
        assert rc == 1
        assert "knowledge-routes.md" in err

    def test_check_reports_facts_without_source_file(self, env, capsys):
        store(make_fact("NoFile", source_file=None), make_fact("Ok", source_file="a.md"))
        control.cmd_knowledge_routes(["--write"])

        rc = control.cmd_knowledge_routes(["--check"])

        captured = capsys.readouterr()
        assert rc == 1
        assert "NoFile" in captured.err
        assert "source_file" in captured.err


class TestFlagCombos:
    def test_json_write_invalid_exit2(self, env):
        assert control.cmd_knowledge_routes(["--json", "--write"]) == 2

    def test_check_write_invalid_exit2(self, env):
        assert control.cmd_knowledge_routes(["--check", "--write"]) == 2

    def test_check_json_invalid_exit2(self, env):
        assert control.cmd_knowledge_routes(["--check", "--json"]) == 2

    def test_unknown_flag_exit2(self, env):
        assert control.cmd_knowledge_routes(["--bogus"]) == 2

    def test_positional_argument_exit2(self, env):
        assert control.cmd_knowledge_routes(["stray"]) == 2


class TestMainDispatch:
    def test_main_exit_code_zero_on_success(self, env, capsys, monkeypatch):
        store(make_fact("Alpha", source_file="a.md"))
        monkeypatch.setattr(sys, "argv", ["curator", "knowledge-routes"])

        with pytest.raises(SystemExit) as exc:
            control.main()

        capsys.readouterr()
        assert exc.value.code == 0

    def test_main_exit_code_one_on_validation_errors(self, env, capsys, monkeypatch):
        store(make_fact("NoFile", source_file=None))
        monkeypatch.setattr(sys, "argv", ["curator", "knowledge-routes"])

        with pytest.raises(SystemExit) as exc:
            control.main()

        capsys.readouterr()
        assert exc.value.code == 1
