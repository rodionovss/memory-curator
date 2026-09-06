"""Интеграционные тесты LocalBackend: SQLite, persistence, краевые случаи."""

import pytest
from curator.backend.local import LocalBackend
from curator.models import StructuredFact, FactQuery, FactRef


class TestLocalBackendCRUD:
    def test_store_and_retrieve(self, tmpdir):
        be = LocalBackend(str(tmpdir / "test.db"))
        f = StructuredFact(type="Reference", title="Test", tags=["t"], status="verified", content_summary="x" * 20)
        ref = be.store_fact(f)
        assert isinstance(ref, FactRef)
        assert ref.id

        results = be.query_facts(FactQuery())
        assert len(results) == 1
        assert results[0].title == f.title

    def test_query_by_type(self, tmpdir):
        be = LocalBackend(str(tmpdir / "test.db"))
        be.store_fact(StructuredFact(type="Reference", title="R1", tags=["t"], status="verified", content_summary="x" * 20))
        be.store_fact(StructuredFact(type="Style", title="S1", tags=["t"], status="verified", content_summary="x" * 20))
        assert len(be.query_facts(FactQuery(type="Reference"))) == 1
        assert len(be.query_facts(FactQuery(type="Style"))) == 1

    def test_query_by_tags(self, tmpdir):
        be = LocalBackend(str(tmpdir / "test.db"))
        be.store_fact(StructuredFact(type="Reference", title="A", tags=["jvm"], status="verified", content_summary="x" * 20))
        be.store_fact(StructuredFact(type="Reference", title="B", tags=["compose"], status="verified", content_summary="x" * 20))
        assert len(be.query_facts(FactQuery(tags=["jvm"]))) == 1
        assert len(be.query_facts(FactQuery(tags=["jvm", "compose"]))) == 2

    def test_query_by_status(self, tmpdir):
        be = LocalBackend(str(tmpdir / "test.db"))
        be.store_fact(StructuredFact(type="Reference", title="V", tags=["t"], status="verified", content_summary="x" * 20))
        be.store_fact(StructuredFact(type="Reference", title="H", tags=["t"], status="hypothesis", content_summary="x" * 20))
        assert len(be.query_facts(FactQuery(status="verified"))) == 1

    def test_query_by_search(self, tmpdir):
        be = LocalBackend(str(tmpdir / "test.db"))
        be.store_fact(StructuredFact(type="Reference", title="Unique XYZ", tags=["t"], status="verified", content_summary="x" * 20))
        be.store_fact(StructuredFact(type="Reference", title="Other", tags=["t"], status="verified", content_summary="has XYZ"))
        assert len(be.query_facts(FactQuery(search="XYZ"))) == 2

    def test_empty_db(self, tmpdir):
        be = LocalBackend(str(tmpdir / "test.db"))
        assert be.query_facts(FactQuery()) == []

    def test_query_nonexistent_tag(self, tmpdir):
        be = LocalBackend(str(tmpdir / "test.db"))
        be.store_fact(StructuredFact(type="Reference", title="T", tags=["a"], status="verified", content_summary="x" * 20))
        assert be.query_facts(FactQuery(tags=["nonexistent"])) == []


class TestPersistence:
    def test_survives_reconnect(self, tmpdir):
        db_path = str(tmpdir / "persist.db")
        be1 = LocalBackend(db_path)
        be1.store_fact(StructuredFact(type="Reference", title="Persistent", tags=["t"], status="verified", content_summary="x" * 20))

        be2 = LocalBackend(db_path)
        results = be2.query_facts(FactQuery())
        assert len(results) == 1
        assert results[0].title == "Persistent"

    def test_multiple_writes(self, tmpdir):
        db_path = str(tmpdir / "multi.db")
        be = LocalBackend(db_path)
        for i in range(10):
            be.store_fact(StructuredFact(type="Reference", title=f"Fact {i}", tags=["t"], status="verified", content_summary="x" * 20))
        assert len(be.query_facts(FactQuery())) == 10


class TestRelations:
    def test_add_and_get(self, tmpdir):
        be = LocalBackend(str(tmpdir / "test.db"))
        be.add_relation("1", "2", "related_to")
        be.add_relation("1", "3", "contradicts")
        assert len(be.get_relations("1")) == 2

    def test_no_duplicates(self, tmpdir):
        be = LocalBackend(str(tmpdir / "test.db"))
        be.add_relation("1", "2", "related_to")
        be.add_relation("1", "2", "related_to")
        assert len(be.get_relations("1")) == 1

    def test_empty_relations(self, tmpdir):
        be = LocalBackend(str(tmpdir / "test.db"))
        assert be.get_relations("nonexistent") == []


class TestHealthCheck:
    def test_new_db_healthy(self, tmpdir):
        be = LocalBackend(str(tmpdir / "test.db"))
        assert be.health_check()

    def test_broken_db_path_fails(self, tmp_path):
        parent_file = tmp_path / "not-a-directory"
        parent_file.write_text("")
        with pytest.raises((FileNotFoundError, OSError)):
            LocalBackend(str(parent_file / "test.db"))


class TestFindSimilar:
    def test_finds_by_tags(self, tmpdir):
        be = LocalBackend(str(tmpdir / "test.db"))
        be.store_fact(StructuredFact(type="Reference", title="Правило JVM inline классы", tags=["jvm"], status="verified", content_summary="x" * 20))
        be.store_fact(StructuredFact(type="Reference", title="Compose text style", tags=["compose"], status="verified", content_summary="x" * 20))
        similar = be.find_similar(StructuredFact(type="Reference", title="Правило JVM", tags=["jvm"], status="verified", content_summary="x" * 20), threshold=0.2)
        assert len(similar) >= 1
        assert "Compose" not in [s.title for s in similar]

    def test_no_self_match(self, tmpdir):
        be = LocalBackend(str(tmpdir / "test.db"))
        f = StructuredFact(type="Reference", title="Unique", tags=["u"], status="verified", content_summary="x" * 20)
        be.store_fact(f)
        similar = be.find_similar(f, threshold=0.5)
        assert "Unique" not in [s.title for s in similar]


class TestUpsertSemantics:
    """Регрессии код-ревью: контракт UPSERT по natural key title."""

    def test_conflict_returns_existing_id(self, tmpdir):
        """FactRef.id на конфликте обязан ссылаться на реальную строку, а не на
        свежесгенерированный uuid, которого нет в базе."""
        be = LocalBackend(str(tmpdir / "test.db"))
        f = StructuredFact(type="Reference", title="Same title", tags=["t"], status="verified", content_summary="x" * 20)
        ref1 = be.store_fact(f)
        ref2 = be.store_fact(StructuredFact(type="Reference", title="Same title", tags=["t"],
                                            status="deprecated", content_summary="y" * 20))
        assert ref1.id == ref2.id

    def test_re_store_without_source_preserves_it(self, tmpdir):
        """Re-store без source_file (deprecation/decay) не должен затирать
        provenance NULL-ом — write-back терял привязку к .md."""
        be = LocalBackend(str(tmpdir / "test.db"))
        be.store_fact(StructuredFact(type="Reference", title="Fact with source", tags=["t"],
                                     status="verified", content_summary="x" * 20,
                                     source_file="kotlin.md", source_session="s1"))
        be.store_fact(StructuredFact(type="Reference", title="Fact with source", tags=["t"],
                                     status="deprecated", content_summary="x" * 20))

        facts = be.query_facts(FactQuery(search="source"))
        assert facts[0].source_file == "kotlin.md"
        assert facts[0].source_session == "s1"


class TestLegacySchemaMigration:
    """Dogfooding (живая БД): таблица, созданная старой схемой (title без
    UNIQUE), ломала весь write-путь — ON CONFLICT(title) не находил
    constraint, CREATE TABLE IF NOT EXISTS не апгрейдит таблицу.
    _init_db самолечит уникальным индексом."""

    def _legacy_db(self, db_path: str):
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.execute("""CREATE TABLE facts (
            id TEXT PRIMARY KEY, type TEXT NOT NULL, title TEXT NOT NULL,
            tags TEXT NOT NULL, status TEXT NOT NULL, content_summary TEXT NOT NULL,
            source_file TEXT, source_session TEXT,
            created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now')))""")
        conn.execute("""CREATE TABLE relations (
            source_id TEXT NOT NULL, target_id TEXT NOT NULL, kind TEXT NOT NULL,
            PRIMARY KEY (source_id, target_id, kind))""")
        conn.commit()
        return conn

    def test_legacy_db_self_heals_and_upserts(self, tmpdir):
        db_path = str(tmpdir / "legacy.db")
        conn = self._legacy_db(db_path)
        conn.close()

        be = LocalBackend(db_path)
        ref1 = be.store_fact(StructuredFact(type="Reference", title="Факт из легаси базы знаний", tags=["t"],
                                            status="verified", content_summary="x" * 20))
        ref2 = be.store_fact(StructuredFact(type="Reference", title="Факт из легаси базы знаний", tags=["t"],
                                            status="deprecated", content_summary="y" * 20))
        assert ref1.id == ref2.id, "upsert по title обязан заработать после самолечения"
        assert len(be.query_facts(FactQuery())) == 1

    def test_new_db_unaffected(self, tmpdir):
        """Свежая БД (UNIQUE в CREATE TABLE) — индекс дублирует constraint,
        поведение не меняется."""
        be = LocalBackend(str(tmpdir / "fresh.db"))
        be.store_fact(StructuredFact(type="Reference", title="Обычный факт свежей базы", tags=["t"],
                                      status="verified", content_summary="x" * 20))
        be.store_fact(StructuredFact(type="Reference", title="Обычный факт свежей базы", tags=["t"],
                                      status="deprecated", content_summary="y" * 20))
        assert len(be.query_facts(FactQuery())) == 1

    def test_legacy_db_with_duplicates_still_connects(self, tmpdir):
        """Дубликаты в легаси-данных не должны ронять init: база читается,
        недоступность upsert для неё — прежнее поведение."""
        db_path = str(tmpdir / "legacy_dupes.db")
        conn = self._legacy_db(db_path)
        for i in range(2):
            conn.execute(
                "INSERT INTO facts (id, type, title, tags, status, content_summary) VALUES (?, ?, ?, ?, ?, ?)",
                (f"legacy-{i}", "Reference", "Дубликат из легаси базы", "[]", "verified", "x" * 20),
            )
        conn.commit()
        conn.close()

        be = LocalBackend(db_path)
        assert len(be.query_facts(FactQuery(search="легаси"))) == 2
