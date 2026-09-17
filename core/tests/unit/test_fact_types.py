"""Реестр типов: словарь с описаниями, расширение, честный capture.

Три источника типов (база → env → реестр ~/.curator/fact_types.json),
регистрация только с описанием (контракт для агента), неизвестный тип
агента — отказ со словарём, молчаливый фолбэк на Reference запрещён."""

import pytest

from curator.models import (
    BASE_FACT_TYPES, get_fact_types,
    register_fact_type, resolve_fact_type,
)


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("CURATOR_FACT_TYPES", raising=False)
    return tmp_path


class TestGetFactTypes:
    def test_base_types_with_descriptions(self):
        types = get_fact_types()
        assert set(BASE_FACT_TYPES) <= set(types)
        assert all(desc for desc in types.values()), "тип без описения — угадайка"

    def test_env_extension(self, monkeypatch):
        monkeypatch.setenv("CURATOR_FACT_TYPES", "Note,Decision")
        types = get_fact_types()
        assert "Note" in types and "Decision" in types

    def test_registry_file_read(self, tmp_path):
        registry = tmp_path / ".curator" / "fact_types.json"
        registry.parent.mkdir(parents=True)
        registry.write_text('{"Note": {"description": "Заметки об инструментах и окружении"}}',
                            encoding="utf-8")
        assert get_fact_types()["Note"] == "Заметки об инструментах и окружении"


class TestRegisterFactType:
    def test_register_persists_with_description(self, tmp_path):
        ok, error = register_fact_type("Note", "Заметки об инструментах: статус, наблюдения")
        assert ok, error
        registry = tmp_path / ".curator" / "fact_types.json"
        assert registry.exists()
        assert "Note" in get_fact_types()

    def test_register_rejects_bad_name(self):
        for bad in ("", "1note", "не латиница", "note/type", "x" * 31):
            ok, error = register_fact_type(bad, "Описание достаточной длины")
            assert not ok, bad

    def test_register_requires_meaningful_description(self):
        ok, error = register_fact_type("Note", "коротко")
        assert not ok and "описание" in error

    def test_register_duplicate_rejected(self):
        ok, _ = register_fact_type("Note", "Заметки об инструментах: статус")
        assert ok
        ok, error = register_fact_type("Note", "Другое описание достаточной длины")
        assert not ok and "уже есть" in error


class TestResolveFactType:
    def test_known_type_passes(self):
        fact_type, error = resolve_fact_type("Reference")
        assert fact_type == "Reference" and error is None

    def test_unknown_without_flag_rejected_with_dictionary(self):
        fact_type, error = resolve_fact_type("Note")
        assert fact_type is None
        assert "неизвестный тип 'Note'" in error
        assert "Reference" in error and "Style" in error, \
            "словарь с описаниями обязан быть в отказе — агент по нему соотносит"

    def test_unknown_with_flag_and_description_registers(self):
        fact_type, error = resolve_fact_type(
            "Note", new_type=True,
            type_description="Заметки об инструментах: статус, наблюдения")
        assert fact_type == "Note" and error is None
        assert "Note" in get_fact_types(), "тип обязан попасть в реестр"

    def test_new_type_without_description_rejected(self):
        fact_type, error = resolve_fact_type("Note", new_type=True, type_description="")
        assert fact_type is None and "описание" in error


class TestCustomTypeRoundTrip:
    """Кастомный тип переживает полный цикл: capture → .md → ingest."""

    def test_md_with_custom_type_ingests_as_written(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        register_fact_type("Note", "Заметки об инструментах: статус, наблюдения после проб")

        md_dir = tmp_path / "learnings" / "session"
        md_dir.mkdir(parents=True)
        (md_dir / "note.md").write_text(
            "### Заметка об инструменте multica\n\n"
            "Наблюдение после недели использования инструмента.\n\n"
            "*Тип:* Note | *Статус:* Подтверждено | *Теги:* tools\n"
            "*Файл:* session/note.md\n",
            encoding="utf-8",
        )

        from curator.analyzers.ingest import ingest_directory
        from curator.backend.local import LocalBackend
        from curator.gatekeeper import Gatekeeper
        from curator.models import FactQuery
        be = LocalBackend(":memory:")
        ingest_directory(tmp_path / "learnings", be, Gatekeeper(be, check_duplicates=False))

        facts = be.query_facts(FactQuery())
        assert facts and facts[0].type == "Note", \
            ".md — источник правды rebuild: тип принимается как записан"
