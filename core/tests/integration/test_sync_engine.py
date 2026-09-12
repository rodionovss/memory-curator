"""Интеграционные тесты Sync Engine: .md ↔ backend."""

import pytest
from curator.sync_engine import SyncEngine
from curator.backend.local import LocalBackend
from curator.models import StructuredFact


class TestWrite:
    def test_new_fact_creates_md(self, tmpdir):
        be = LocalBackend(str(tmpdir / "test.db"))
        engine = SyncEngine(be, tmpdir)
        fact = StructuredFact(type="Reference", title="Test Rule", tags=["test"], status="verified", content_summary="Test content.", source_file="reference/test.md")
        path = engine.write_fact_to_md(fact)
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "Test Rule" in content
        assert "Test content" in content

    def test_upsert_updates_existing(self, tmpdir):
        be = LocalBackend(str(tmpdir / "test.db"))
        engine = SyncEngine(be, tmpdir)
        md_path = tmpdir / "reference/test.md"
        md_path.parent.mkdir(parents=True)
        md_path.write_text("### Old Rule\n\nOld text.\n\n*Тип:* Reference | *Статус:* Подтверждено | *Теги:* old\n*Файл:* reference/test.md\n", encoding="utf-8")

        fact = StructuredFact(type="Reference", title="Old Rule", tags=["updated"], status="verified", content_summary="Updated text.", source_file="reference/test.md")
        engine.write_fact_to_md(fact)
        content = md_path.read_text(encoding="utf-8")
        assert "Updated text" in content
        assert "Old text" not in content

    def test_append_to_existing_file(self, tmpdir):
        be = LocalBackend(str(tmpdir / "test.db"))
        engine = SyncEngine(be, tmpdir)
        md_path = tmpdir / "reference/test.md"
        md_path.parent.mkdir(parents=True)
        md_path.write_text("### Existing Rule\n\nContent.\n\n", encoding="utf-8")

        fact = StructuredFact(type="Reference", title="New Rule", tags=["new"], status="verified", content_summary="New content.", source_file="reference/test.md")
        engine.write_fact_to_md(fact)
        content = md_path.read_text(encoding="utf-8")
        assert "Existing Rule" in content
        assert "New Rule" in content


class TestRemove:
    def test_marks_deprecated(self, tmpdir):
        be = LocalBackend(str(tmpdir / "test.db"))
        engine = SyncEngine(be, tmpdir)
        md_path = tmpdir / "reference/test.md"
        md_path.parent.mkdir(parents=True)
        md_path.write_text("### Old Rule\n\nText.\n\n*Тип:* Reference\n", encoding="utf-8")

        fact = StructuredFact(type="Reference", title="Old Rule", tags=["t"], status="deprecated", content_summary="Text.", source_file="reference/test.md")
        path = engine.remove_fact_from_md(fact)
        assert path is not None
        content = path.read_text(encoding="utf-8")
        assert "[УСТАРЕЛО]" in content

    def test_nonexistent_fact_no_error(self, tmpdir):
        be = LocalBackend(str(tmpdir / "test.db"))
        engine = SyncEngine(be, tmpdir)
        md_path = tmpdir / "reference/test.md"
        md_path.parent.mkdir(parents=True)
        md_path.write_text("### Existing\n\nText.\n", encoding="utf-8")

        fact = StructuredFact(type="Reference", title="Missing Rule", tags=["t"], status="deprecated", content_summary=".", source_file="reference/test.md")
        assert engine.remove_fact_from_md(fact) is None

    def test_nonexistent_file_no_error(self, tmpdir):
        be = LocalBackend(str(tmpdir / "test.db"))
        engine = SyncEngine(be, tmpdir)
        fact = StructuredFact(type="Reference", title="Test", tags=["t"], status="deprecated", content_summary=".", source_file="reference/missing.md")
        assert engine.remove_fact_from_md(fact) is None


class TestErrors:
    def test_no_source_file_raises(self, tmpdir):
        be = LocalBackend(str(tmpdir / "test.db"))
        engine = SyncEngine(be, tmpdir)
        fact = StructuredFact(type="Reference", title="Test", tags=["t"], status="verified", content_summary="x" * 20)
        with pytest.raises(ValueError):
            engine.write_fact_to_md(fact)

    def test_update_no_source_file_raises(self, tmpdir):
        be = LocalBackend(str(tmpdir / "test.db"))
        engine = SyncEngine(be, tmpdir)
        fact = StructuredFact(type="Reference", title="Test", tags=["t"], status="verified", content_summary="x" * 20)
        with pytest.raises(ValueError):
            engine.update_fact_in_md(fact)


class TestMultipleFacts:
    def test_multiple_facts_one_file(self, tmpdir):
        be = LocalBackend(str(tmpdir / "test.db"))
        engine = SyncEngine(be, tmpdir)
        f1 = StructuredFact(type="Reference", title="Rule 1", tags=["a"], status="verified", content_summary="Content 1.", source_file="ref/all.md")
        f2 = StructuredFact(type="Reference", title="Rule 2", tags=["b"], status="verified", content_summary="Content 2.", source_file="ref/all.md")

        engine.write_fact_to_md(f1)
        engine.write_fact_to_md(f2)

        content = (tmpdir / "ref/all.md").read_text(encoding="utf-8")
        assert "Rule 1" in content
        assert "Rule 2" in content


class TestMarkerRobustness:
    """Регрессии код-ревью: асимметрия маркера секции.

    Поиск секции шёл подстрокой (marker in content), замена — по точному
    равенству строки: подстрочный «маркер» молча терял апдейт, а чужая секция,
    совпавшая с title, затиралась рендером факта.
    """

    def test_substring_match_appends_not_silent_loss(self, tmpdir):
        be = LocalBackend(str(tmpdir / "test.db"))
        engine = SyncEngine(be, tmpdir)
        md_path = tmpdir / "reference/test.md"
        md_path.parent.mkdir(parents=True)
        md_path.write_text("#### Docker build правила\n\nТекст.\n", encoding="utf-8")

        fact = StructuredFact(type="Reference", title="Docker build правила", tags=["t"],
                              status="verified", content_summary="Обновлённый рендер факта.",
                              source_file="reference/test.md")
        engine.write_fact_to_md(fact)

        content = md_path.read_text(encoding="utf-8")
        assert "### Docker build правила\n" in content, "секция факта обязана появиться"
        assert "Обновлённый рендер факта." in content

    def test_foreign_section_same_title_not_destroyed(self, tmpdir):
        be = LocalBackend(str(tmpdir / "test.db"))
        engine = SyncEngine(be, tmpdir)
        md_path = tmpdir / "reference/test.md"
        md_path.parent.mkdir(parents=True)
        user_content = "Личные заметки пользователя, не факт куратора."
        md_path.write_text(f"### Общее правило про пагинацию списков\n\n{user_content}\n", encoding="utf-8")

        fact = StructuredFact(type="Reference", title="Общее правило про пагинацию списков", tags=["t"],
                              status="verified", content_summary="Кураторский рендер факта.",
                              source_file="reference/test.md")
        engine.write_fact_to_md(fact)

        content = md_path.read_text(encoding="utf-8")
        assert user_content in content, "пользовательская секция обязана сохраниться"
        assert "Кураторский рендер факта." in content, "факт обязан быть дописан"

    def test_upsert_replaces_only_our_section(self, tmpdir):
        be = LocalBackend(str(tmpdir / "test.db"))
        engine = SyncEngine(be, tmpdir)
        md_path = tmpdir / "reference/test.md"
        md_path.parent.mkdir(parents=True)
        md_path.write_text(
            "### Общее правило про пагинацию списков\n\nЛичные заметки.\n\n"
            "### Общее правило про пагинацию списков\n\nСтарый рендер.\n\n*Тип:* Reference\n",
            encoding="utf-8")

        fact = StructuredFact(type="Reference", title="Общее правило про пагинацию списков", tags=["t"],
                              status="verified", content_summary="Новый рендер.", source_file="reference/test.md")
        engine.write_fact_to_md(fact)

        content = md_path.read_text(encoding="utf-8")
        assert "Личные заметки." in content
        assert "Новый рендер." in content
        assert "Старый рендер." not in content


class TestSectionBoundaries:
    """Регрессии ревью-2: границы заменяемой секции.

    Граница была только по `###` — апдейт последнего факта главы съедал
    следующую `##` главу целиком; `---`-разделители терялись; финальный
    перевод строки файла пропадал.
    """

    def _write_engine(self, tmpdir):
        be = LocalBackend(str(tmpdir / "test.db"))
        return SyncEngine(be, tmpdir)

    def test_update_does_not_eat_next_h2_chapter(self, tmpdir):
        engine = self._write_engine(tmpdir)
        md_path = tmpdir / "reference/test.md"
        md_path.parent.mkdir(parents=True)
        md_path.write_text(
            "## Глава Facts\n\n"
            "### Правило про устойчивость секций в markdown\n\nСтарый рендер.\n\n*Тип:* Reference\n\n"
            "## Chapter Tools\n\nИнструменты и заметки пользователя.\n",
            encoding="utf-8")

        fact = StructuredFact(type="Reference", title="Правило про устойчивость секций в markdown",
                              tags=["t"], status="verified", content_summary="Новый рендер.",
                              source_file="reference/test.md")
        engine.write_fact_to_md(fact)

        content = md_path.read_text(encoding="utf-8")
        assert "Новый рендер." in content
        assert "## Chapter Tools" in content, "чужая ## глава обязана сохраниться"
        assert "Инструменты и заметки пользователя." in content, "контент главы не должен быть съеден"

    def test_separator_between_sections_preserved(self, tmpdir):
        engine = self._write_engine(tmpdir)
        md_path = tmpdir / "reference/test.md"
        md_path.parent.mkdir(parents=True)
        md_path.write_text(
            "### Правило первое про сохранение разделителей\n\nРендер один.\n\n*Тип:* Reference\n\n"
            "---\n\n"
            "### Правило второе про сохранение разделителей\n\nРендер два.\n\n*Тип:* Reference\n",
            encoding="utf-8")

        fact = StructuredFact(type="Reference", title="Правило первое про сохранение разделителей",
                              tags=["t"], status="verified", content_summary="Обновлённый рендер.",
                              source_file="reference/test.md")
        engine.write_fact_to_md(fact)

        content = md_path.read_text(encoding="utf-8")
        assert "Обновлённый рендер." in content
        assert "\n---\n" in content, "разделитель между секциями обязан сохраниться"
        assert "Рендер два." in content

    def test_file_keeps_trailing_newline(self, tmpdir):
        engine = self._write_engine(tmpdir)
        md_path = tmpdir / "reference/test.md"
        md_path.parent.mkdir(parents=True)
        md_path.write_text("### Правило про финальный перенос строки файла\n\nРендер.\n\n*Тип:* Reference\n", encoding="utf-8")

        fact = StructuredFact(type="Reference", title="Правило про финальный перенос строки файла",
                              tags=["t"], status="verified", content_summary="Обновлённый рендер.",
                              source_file="reference/test.md")
        engine.write_fact_to_md(fact)

        content = md_path.read_text(encoding="utf-8")
        assert content.endswith("\n"), "POSIX-финал файла обязан сохраняться"


class TestPathTraversal:
    """Регрессия код-ревью: source_file без ограничения корнем base_dir."""

    def test_traversal_rejected(self, tmpdir):
        be = LocalBackend(str(tmpdir / "test.db"))
        engine = SyncEngine(be, tmpdir)
        fact = StructuredFact(type="Reference", title="Вредоносный факт с длинным заголовком", tags=["t"],
                              status="verified", content_summary="x" * 20,
                              source_file="../../outside.md")
        with pytest.raises(ValueError):
            engine.write_fact_to_md(fact)

    def test_absolute_source_file_rejected(self, tmpdir):
        be = LocalBackend(str(tmpdir / "test.db"))
        engine = SyncEngine(be, tmpdir)
        fact = StructuredFact(type="Reference", title="Вредоносный факт с длинным заголовком", tags=["t"],
                              status="verified", content_summary="x" * 20,
                              source_file="/etc/hosts")
        with pytest.raises(ValueError):
            engine.write_fact_to_md(fact)

class TestRewriteStatus:
    """rewrite_status: смена статуса факта ядром отражается в .md —
    deprecated → маркер [УСТАРЕЛО], hypothesis → перерендер секции."""

    def _fact(self, title="Факт для проверки статуса", status="verified"):
        return StructuredFact(
            type="Reference", title=title, tags=["test"], status=status,
            content_summary="Достаточно длинная сводка факта для секции.",
            source_file="session/reference.md",
        )

    def test_deprecated_gets_marker(self, tmp_path):
        be = LocalBackend(":memory:")
        engine = SyncEngine(be, tmp_path)
        fact = self._fact()
        engine.write_fact_to_md(fact)

        path = engine.rewrite_status(self._fact(title=fact.title, status="deprecated"))

        text = path.read_text(encoding="utf-8")
        assert f"### {fact.title} [УСТАРЕЛО]" in text
        assert "*Это знание помечено как устаревшее.*" in text

    def test_hypothesis_rerenders_status_line(self, tmp_path):
        be = LocalBackend(":memory:")
        engine = SyncEngine(be, tmp_path)
        fact = self._fact()
        engine.write_fact_to_md(fact)

        engine.rewrite_status(self._fact(title=fact.title, status="hypothesis"))

        text = (tmp_path / "session" / "reference.md").read_text(encoding="utf-8")
        assert "*Статус:* Гипотеза" in text
        assert text.count(f"### {fact.title}") == 1, "перерендер не плодит секции"

    def test_no_source_file_is_silent_noop(self):
        from pathlib import Path as _Path
        be = LocalBackend(":memory:")
        engine = SyncEngine(be, _Path("/nonexistent-base"))
        fact = self._fact()
        fact = StructuredFact(**{**fact.__dict__, "source_file": None})

        assert engine.rewrite_status(fact) is None

    def test_missing_file_deprecated_returns_none(self, tmp_path):
        be = LocalBackend(":memory:")
        engine = SyncEngine(be, tmp_path)

        assert engine.rewrite_status(self._fact(status="deprecated")) is None


class TestIndexRegeneration:
    """index.md пересобирается после записей: живые факты по файлам.
    Чужой index.md (без маркера) не трогается; index не инжестится как факты."""

    def _fact(self, title, source_file="session/reference.md", status="verified"):
        return StructuredFact(
            type="Reference", title=title, tags=["test"], status=status,
            content_summary="Достаточно длинная сводка факта для секции.",
            source_file=source_file,
        )

    def test_index_created_with_marker(self, tmp_path):
        be = LocalBackend(":memory:")
        engine = SyncEngine(be, tmp_path)
        engine.write_fact_to_md(self._fact("Первое правило про индекс"))

        index = tmp_path / "index.md"
        assert index.exists()
        text = index.read_text(encoding="utf-8")
        assert SyncEngine.INDEX_MARKER in text
        assert "## session/reference.md" in text
        assert "- [Первое правило про индекс](session/reference.md)" in text

    def test_index_updated_and_deprecated_removed(self, tmp_path):
        be = LocalBackend(":memory:")
        engine = SyncEngine(be, tmp_path)
        fact = self._fact("Второе правило про индекс")
        engine.write_fact_to_md(fact)

        engine.rewrite_status(self._fact("Второе правило про индекс", status="deprecated"))

        text = (tmp_path / "index.md").read_text(encoding="utf-8")
        assert "Второе правило про индекс" not in text, \
            "устаревший факт уходит из навигации"

    def test_foreign_index_untouched(self, tmp_path):
        be = LocalBackend(":memory:")
        engine = SyncEngine(be, tmp_path)
        (tmp_path / "index.md").write_text(
            "# Knowledge Base\n\n- [Reference](reference/index.md) — ручная навигация\n",
            encoding="utf-8",
        )

        engine.write_fact_to_md(self._fact("Третье правило про индекс"))

        text = (tmp_path / "index.md").read_text(encoding="utf-8")
        assert "ручная навигация" in text, "чужой index.md нельзя перезаписывать"
        assert "Третье правило" not in text

    def test_index_not_ingested_as_facts(self, tmp_path):
        from curator.analyzers.ingest import ingest_directory
        from curator.gatekeeper import Gatekeeper
        be = LocalBackend(":memory:")
        engine = SyncEngine(be, tmp_path)
        engine.write_fact_to_md(self._fact("Четвёртое правило про индекс"))

        be2 = LocalBackend(":memory:")
        saved = ingest_directory(tmp_path, be2, Gatekeeper(be2, check_duplicates=False))

        assert saved == 1, "index.md не должен превращаться в факты"


class TestSymlinkEscape:
    """Security-trace по матрице скилла curator-create-map: symlink
    внутри base_dir, ведущий наружу, не может вывести запись за sandbox —
    resolve() разворачивает symlink до проверки принадлежности корню."""

    def test_symlink_escape_rejected(self, tmp_path):
        import os as _os
        outside_dir = tmp_path.parent / "outside-escape"
        outside_dir.mkdir(exist_ok=True)

        base = tmp_path / "learnings"
        base.mkdir()
        be = LocalBackend(":memory:")
        engine = SyncEngine(be, base)

        link = base / "escape.md"
        _os.symlink(outside_dir / "target.md", link)

        fact = StructuredFact(
            type="Reference", title="Факт пытающийся выйти через симлинк", tags=["t"],
            status="verified", content_summary="x" * 20,
            source_file="escape.md",
        )
        with pytest.raises(ValueError, match="вне base_dir"):
            engine.write_fact_to_md(fact)

        assert not (outside_dir / "target.md").exists(), \
            "ни одного байта за пределами sandbox"


class TestMapModeWriteBack:
    """mode таргетов карты управляет write-back: update — upsert,
    append — не перезаписывать существующее, readonly — честный отказ."""

    def _map(self, tmp_path, body):
        (tmp_path / "DOCUMENTATION-MAP.md").write_text(
            "---\n"
            "status: draft\n"
            "categories: [knowledge, rules, records]\n"
            "modes: [update, append, readonly]\n"
            f"topics:\n{body}"
            "---\n",
            encoding="utf-8",
        )

    def _fact(self, title, source_file, status="verified"):
        return StructuredFact(
            type="Reference", title=title, tags=["test"], status=status,
            content_summary="Достаточно длинная сводка факта для секции.",
            source_file=source_file,
        )

    def test_readonly_rejected(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CURATOR_MAP", raising=False)
        self._map(tmp_path, (
            "  - name: context\n"
            "    targets:\n"
            "      - path: docs/context.md\n"
            "        captures: [knowledge]\n"
            "        mode: readonly\n"
        ))
        be = LocalBackend(":memory:")
        engine = SyncEngine(be, tmp_path)
        with pytest.raises(ValueError, match="readonly"):
            engine.write_fact_to_md(self._fact("Факт в readonly контексте", "docs/context.md"))

    def test_append_never_overwrites(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CURATOR_MAP", raising=False)
        self._map(tmp_path, (
            "  - name: journal\n"
            "    targets:\n"
            "      - path: docs/journal.md\n"
            "        captures: [records]\n"
            "        mode: append\n"
        ))
        be = LocalBackend(":memory:")
        engine = SyncEngine(be, tmp_path)
        fact = self._fact("Запись в журнале первая", "docs/journal.md")
        engine.write_fact_to_md(fact)

        # перезапись существующей секции запрещена — «сохраняя историю»
        changed = self._fact("Запись в журнале первая", "docs/journal.md", status="deprecated")
        engine.write_fact_to_md(changed)

        text = (tmp_path / "docs" / "journal.md").read_text(encoding="utf-8")
        assert "*Статус:* Подтверждено" in text, "append не перезаписывает существующую секцию"

    def test_update_upserts_as_before(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CURATOR_MAP", raising=False)
        self._map(tmp_path, (
            "  - name: living\n"
            "    targets:\n"
            "      - path: docs/living.md\n"
            "        captures: [knowledge]\n"
            "        mode: update\n"
        ))
        be = LocalBackend(":memory:")
        engine = SyncEngine(be, tmp_path)
        fact = self._fact("Живое правило про обновление", "docs/living.md")
        engine.write_fact_to_md(fact)
        engine.write_fact_to_md(self._fact("Живое правило про обновление", "docs/living.md", status="hypothesis"))

        text = (tmp_path / "docs" / "living.md").read_text(encoding="utf-8")
        assert "*Статус:* Гипотеза" in text, "update — прежний upsert"

    def test_no_map_update_default(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CURATOR_MAP", raising=False)
        be = LocalBackend(":memory:")
        engine = SyncEngine(be, tmp_path)
        fact = self._fact("Обычный факт без карты", "session/reference.md")
        engine.write_fact_to_md(fact)
        assert (tmp_path / "session" / "reference.md").exists()
