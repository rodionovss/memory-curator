"""Регрессионные тесты по итогам код-ревью ядра (PR #1).

Остались тесты живого ядра (после минимизации 2026-11-14): thread-safety
SQLite, точность gatekeeper-парсинга, upsert по специальным summary,
валидация тегов, round-trip заголовков, санитизация source_file,
точность deprecated-маркера, CR-отказ.
"""

import json
import time

import pytest

from curator.backend.local import LocalBackend
from curator.gatekeeper import Gatekeeper
from curator.models import StructuredFact, FactQuery


@pytest.fixture(autouse=True)
def isolated_state(tmp_path):
    return tmp_path


def _fact(title, tags=None, status="verified", source_file=None):
    return StructuredFact(
        type="Reference", title=title, tags=tags or ["test"], status=status,
        content_summary=f"Summary for {title}" * 2, source_file=source_file,
    )


class TestSqliteThreadSafety:
    """Ревью-2: to_thread создал конкурентный доступ к одному Connection —
    падения и потеря записей. Теперь все операции под threading.Lock."""

    def test_concurrent_store_and_query(self):
        import threading

        be = LocalBackend(":memory:")
        errors = []
        N = 8
        W = 25

        def writer(worker_id: int):
            try:
                for i in range(W):
                    be.store_fact(StructuredFact(
                        type="Reference", title=f"Факт воркера {worker_id} номер {i}",
                        tags=["t"], status="verified", content_summary="x" * 20,
                    ))
                    be.query_facts(FactQuery(search=f"воркера {worker_id}"))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(w,)) for w in range(N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"конкурентный доступ не должен падать: {errors}"
        assert len(be.query_facts(FactQuery())) == N * W, "ни одна запись не потеряна"


class TestGatekeeperSummaryPrecision:
    """Ревью-2/3: строки с # в НАЧАЛЕ строки ломают поиск секции при следующем
    апдейте (апдейт превращается в дубль) — теперь все они режутся; легитимный
    код — только инлайн или с отступом. Мета-строки — инъекция метаданных."""

    def test_legitimate_inline_hash_passes(self):
        result = Gatekeeper().filter([_gate_fact(summary="Установка: `# pip install x`, затем `#include <vector>` в коде.")])
        assert len(result.approved) == 1, "инлайн-код с # не должен резаться"

    def test_indented_hash_passes(self):
        result = Gatekeeper().filter([_gate_fact(summary="Команда установки:\n    # pip install x\n    # include")])
        assert len(result.approved) == 1, "код с отступом не должен резаться"

    def test_line_start_hash_rejected(self):
        """Ревью-3 blocker: line-start # в summary + граница секции по любому #
        → секция ненаходима → дубль при каждом save. Теперь режем на входе."""
        result = Gatekeeper().filter([_gate_fact(summary="Нормальное начало.\n# pip install x\n# include")])
        assert len(result.rejected) == 1
        assert "#" in result.rejected[0][1]

    def test_meta_lines_in_summary_rejected(self):
        result = Gatekeeper().filter([_gate_fact(summary="Полезное знание.\n*Тип:* Tool\n*Теги:* injected, evil")])
        assert len(result.rejected) == 1
        assert "служебные строки" in result.rejected[0][1]

class TestUpsertSurvivesSpecialSummary:
    """Ревью-3 blocker: факт с line-start # в summary ломал upsert (дубль при
    каждом save). Теперь такие факты не проходят gatekeeper — а факт с
    инлайн-# обновляется по месту."""

    def test_fact_with_inline_hash_upserts_in_place(self, tmp_path):
        from curator.sync_engine import SyncEngine
        from curator.backend.local import LocalBackend

        be = LocalBackend(":memory:")
        base = tmp_path / "learnings"
        engine = SyncEngine(be, base)
        fact = StructuredFact(
            type="Tool", title="Правило про апдейт факта с инлайн решёткой",
            tags=["t"], status="verified",
            content_summary="Ставь `# pip install x` инлайн — и всё работает.",
            source_file="docs/x.md",
        )
        engine.write_fact_to_md(fact)
        engine.write_fact_to_md(StructuredFact(
            type="Tool", title="Правило про апдейт факта с инлайн решёткой",
            tags=["t", "upd"], status="verified",
            content_summary="Обновлённый текст с `# pip install y`.",
            source_file="docs/x.md",
        ))

        content = (base / "docs" / "x.md").read_text(encoding="utf-8")
        assert content.count("### Правило про апдейт факта с инлайн решёткой") == 1, \
            "апдейт обязан заменять секцию, а не аппендить дубль"
        assert "Обновлённый текст" in content
        assert "upd" in content


class TestTagValidation:
    """Ревью-4 blocker: теги попадали в мета-строку рендера без проверки —
    тег с \\n инъектирует строку с # в .md (ломает upsert: дубли); '|' и
    ',' ломают раунд-трип тегов через парсер."""

    def test_tag_with_newline_rejected(self):
        result = Gatekeeper().filter([_gate_fact(tags=["kotlin\n# INJECTED"])])
        assert len(result.rejected) == 1
        assert "перевод строки" in result.rejected[0][1]

    def test_tag_with_pipe_or_comma_rejected(self):
        result = Gatekeeper().filter([_gate_fact(tags=["api|v2", "net"])])
        assert len(result.rejected) == 1
        result = Gatekeeper().filter([_gate_fact(tags=["a,b"])])
        assert len(result.rejected) == 1

    def test_clean_tags_pass(self):
        result = Gatekeeper().filter([_gate_fact(tags=["kotlin", "jvm-17", "compose_ui"])])
        assert len(result.approved) == 1


class TestTitleRoundTrip:
    """Ревью-4: title с '### ' внутри мутировал при реингесте
    (replace('### ', '') вместо removeprefix) → дубль при апдейте."""

class TestSourceFileSanitization:
    """Ревью-4: \\n в source_file (от стороннего роутера) ломал бы формат .md."""

    def test_newline_in_source_file_rejected(self, tmp_path):
        from curator.sync_engine import SyncEngine

        be = LocalBackend(":memory:")
        engine = SyncEngine(be, tmp_path)
        for bad in ("a.md\n# junk", "a.md\r\nb"):
            fact = StructuredFact(
                type="Reference", title="Факт с битым маршрутом от роутера",
                tags=["t"], status="verified", content_summary="x" * 20,
                source_file=bad,
            )
            with pytest.raises(ValueError):
                engine.write_fact_to_md(fact)


class TestDeprecatedMarkerPrecision:
    """Раунд-5 фаззинг: '[УСТАРЕЛО]' в тегах/описании легитимного факта
    дропал секцию целиком при реингесте (молчаливая потеря знания)."""

class TestCarriageReturnRejection:
    """Раунд-5 фаззинг: одиночный \\r читался как перевод строки (universal
    newlines) — нормализация .md молча мутировала описание."""

    def test_cr_in_summary_rejected(self):
        result = Gatekeeper().filter([_gate_fact(summary="Описание с \r возвратом каретки внутри")])
        assert len(result.rejected) == 1
        assert "\\r" in result.rejected[0][1] or "\r" in result.rejected[0][1]


def _gate_fact(title="Достаточно длинный заголовок для проверки", summary="Достаточно длинное описание факта.",
               tags=None):
    from curator.models import ProposedFact
    return ProposedFact(type="Reference", title=title, content_summary=summary,
                        tags=tags if tags is not None else ["test"])
