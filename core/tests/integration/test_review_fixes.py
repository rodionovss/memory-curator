"""Регрессионные тесты по итогам код-ревью ядра (PR #1).

Каждый тест воспроизводит конкретный дефект из отчёта ревью:
- improve/decay затирали source_file при смене статуса (потеря provenance);
- deprecated факты пере-обрабатывались на каждом прогоне improve;
- worker decay терял привязку к .md;
- curator stop мог убить чужой процесс по переиспользованному pid.
"""

import json
import time

import pytest

import curator.observability as obs_mod
import curator.retrieval_feedback as fb_mod
from curator.backend.local import LocalBackend
from curator.gatekeeper import Gatekeeper
from curator.improve_loop import ImproveLoop
from curator.models import StructuredFact, FactQuery
from curator.observability import Observability
from curator.retrieval_feedback import RetrievalFeedback


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """ImproveLoop/worker создают Observability и RetrievalFeedback с дефолтными
    путями ВНУТРИ вызовов — патчим фабриками на tmp, как в tests/requirements."""
    events = tmp_path / "improve_events.jsonl"
    usage = tmp_path / "usage.json"
    monkeypatch.setattr(obs_mod, "Observability", lambda *a, **k: Observability(path=str(events)))
    monkeypatch.setattr(fb_mod, "RetrievalFeedback", lambda *a, **k: RetrievalFeedback(storage_path=str(usage)))
    return tmp_path


def _fact(title, tags=None, status="verified", source_file=None):
    return StructuredFact(
        type="Reference", title=title, tags=tags or ["test"], status=status,
        content_summary=f"Summary for {title}" * 2, source_file=source_file,
    )


class TestDeprecationPreservesProvenance:
    """Ревью-blocker: UPSERT при смене статуса затирал source_file/source_session."""

    def test_improve_deprecation_keeps_source_file(self, isolated_state):
        be = LocalBackend(":memory:")
        be.store_fact(_fact("Проверенное правило про котлин коллекции"))
        be.store_fact(_fact("Гипотеза про устаревший подход к кэшированию",
                            status="hypothesis", source_file="reference/kotlin.md"))

        report = ImproveLoop(be).run()
        assert report.stats["stale_found"] == 1

        facts = be.query_facts(FactQuery(search="кэшированию"))
        assert facts[0].status == "deprecated"
        assert facts[0].source_file == "reference/kotlin.md", \
            "deprecation не имеет права терять привязку к .md"

    def test_contradiction_loser_keeps_source_file(self, isolated_state):
        be = LocalBackend(":memory:")
        be.store_fact(_fact("Использовать Retrofit для сетевых запросов",
                            tags=["android"], source_file="reference/network.md"))
        be.store_fact(_fact("Не использовать Retrofit для сетевых запросов",
                            tags=["android"], status="hypothesis",
                            source_file="reference/network.md"))

        report = ImproveLoop(be).run()
        assert report.stats["contradictions_found"] == 1

        loser = [f for f in be.query_facts(FactQuery(search="Не использовать"))][0]
        assert loser.status == "deprecated"
        assert loser.source_file == "reference/network.md"


class TestDeprecatedLeaveActiveSet:
    """Ревью: deprecated не исключались из сканов — повторные store_fact
    на каждом прогоне (чурн, ложные счётчики «применено»)."""

    def test_second_run_does_not_reprocess_deprecated(self, isolated_state):
        be = LocalBackend(":memory:")
        be.store_fact(_fact("Проверенное правило про котлин коллекции"))
        be.store_fact(_fact("Гипотеза про устаревший подход к кэшированию", status="hypothesis"))

        first = ImproveLoop(be).run()
        assert first.stats["stale_found"] == 1

        second = ImproveLoop(be).run()
        assert second.stats["stale_found"] == 0, \
            "deprecated покинул активный набор — повторной обработки быть не должно"
        assert second.stats["duplicates_found"] == 0
        assert second.stats["contradictions_found"] == 0

    def test_deprecated_not_resurrected_by_scan(self, isolated_state):
        be = LocalBackend(":memory:")
        be.store_fact(_fact("Проверенное правило про котлин коллекции"))
        be.store_fact(_fact("Гипотеза про устаревший подход к кэшированию",
                            status="deprecated", source_file="reference/kotlin.md"))

        report = ImproveLoop(be).run()
        assert report.stats["total_facts"] == 1, "deprecated вне активного набора"
        assert report.stats["stale_found"] == 0


class TestStopPidVerification:
    """Ревью: curator stop убивал по stale pid без верификации процесса.

    Ревью-2 уточнило матчинг: задокументированный entrypoint `curator-worker`
    обязан матчится, подстрочные совпадения чужих процессов — нет.
    """

    def test_stop_does_not_kill_foreign_process(self, tmp_path, monkeypatch, capsys):
        from curator import control
        from curator import daemon

        monkeypatch.setattr(daemon, "_pid_file", lambda: tmp_path / "worker.pid")
        monkeypatch.setattr(daemon, "read_pid", lambda: 1)  # pid 1 = launchd, точно не наш worker
        monkeypatch.setattr(daemon, "is_running", lambda pid: True)
        killed = []
        monkeypatch.setattr(daemon.os, "kill", lambda pid, sig: killed.append((pid, sig)))

        control.cmd_stop()

        out = capsys.readouterr().out
        assert "не похож" in out, "чужой процесс обязан быть распознан и не тронут"
        assert not (tmp_path / "worker.pid").exists()
        assert killed == []

    def test_matches_documented_entrypoint(self, monkeypatch):
        """`python -m curator.worker` (start_worker) и `curator-worker`
        (entrypoint из worker.py) — наши; `rg curator.worker` — чужой."""
        from curator import daemon

        def fake_ps(command_line: str):
            def run(cmd, **kwargs):
                class R:
                    stdout = command_line
                return R()
            return run

        monkeypatch.setattr(daemon.subprocess, "run", fake_ps(
            "/somewhere/curator-worker --daemon"))
        assert daemon.pid_is_curator_worker(42) is True

        monkeypatch.setattr(daemon.subprocess, "run", fake_ps(
            "/usr/bin/python -m curator.worker --daemon"))
        assert daemon.pid_is_curator_worker(42) is True

        monkeypatch.setattr(daemon.subprocess, "run", fake_ps(
            "rg curator.worker"))
        assert daemon.pid_is_curator_worker(42) is False, "подстрока в чужом argv не матч"

        monkeypatch.setattr(daemon.subprocess, "run", fake_ps(
            "tail -f /tmp/curator.worker.log"))
        assert daemon.pid_is_curator_worker(42) is False


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


class TestUsageJsonCrossProcess:
    """Ревью-2: фиксированный tmp-файл ронял второй процесс (FileNotFoundError
    на replace); RMW-окно теряло счётчики. Теперь flock + tmp с pid."""

    def test_parallel_writers_never_crash(self, tmp_path):
        import subprocess
        import sys

        path = tmp_path / "usage.json"
        script = (
            "from curator.retrieval_feedback import RetrievalFeedback\n"
            "import sys\n"
            "rf = RetrievalFeedback(sys.argv[1])\n"
            "for i in range(30):\n"
            "    rf.record_query(1, [f'proc-{sys.argv[2]}-fact-{i}'])\n"
        )
        procs = [
            subprocess.Popen([sys.executable, "-c", script, str(path), str(p)])
            for p in range(3)
        ]
        for p in procs:
            assert p.wait(timeout=30) == 0, "процесс не имеет права упасть на записи"

        data = json.loads(path.read_text())
        assert len(data) == 90, "все записи всех процессов обязаны сохраниться"

    def test_stats_are_fresh_across_instances(self, tmp_path):
        """Ревью-3: предыдущая версия теста была подогнана (rf2 создавался
        ПОСЛЕ записи). Живой инстанс, созданный ДО чужой записи, обязан
        видеть её — чтение с диска, не снапшот конструктора."""
        path = tmp_path / "usage.json"
        rf1 = RetrievalFeedback(str(path))
        rf2 = RetrievalFeedback(str(path))  # создан ДО записи rf1
        rf1.record_query(1, ["Fact A"])

        assert rf2.get_stats(10), "живой инстанс обязан видеть чужую запись"


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

    def test_midline_meta_allowed_but_ignored_by_parser(self, tmp_path):
        """Mid-line мета в summary проходит gatekeeper, но парсер меты
        (line-start) её игнорирует — раунд-трип не подменяет метаданные."""
        from curator.analyzers.ingest import parse_md_file
        from curator.sync_engine import SyncEngine
        from curator.backend.local import LocalBackend

        be = LocalBackend(":memory:")
        base = tmp_path / "learnings"
        engine = SyncEngine(be, base)
        fact = StructuredFact(
            type="Tool", title="Знание с mid-line метой в описании факта",
            tags=["real-tag"], status="verified",
            content_summary="Пиши в документах *Теги:* injected, evil — это просто текст.",
            source_file="docs/test.md",
        )
        engine.write_fact_to_md(fact)

        parsed = parse_md_file(base / "docs" / "test.md")
        assert len(parsed) == 1
        assert parsed[0].type == "Tool", "тистип факта обязан переживать раунд-трип"
        assert parsed[0].tags == ["real-tag"], "mid-line *Теги:* — текст, не метаданные"


class TestIngestTypeRoundTrip:
    """Ревью-3 (pre-existing): _extract_type брал всю строку после *Тип:* —
    рендер пишет `*Тип:* Tool | *Статус:* ...` → тип всегда терялся в
    Reference при реингесте .md → DB."""

    def test_type_survives_roundtrip_for_all_types(self, tmp_path):
        from curator.analyzers.ingest import parse_md_file
        from curator.sync_engine import SyncEngine
        from curator.backend.local import LocalBackend

        be = LocalBackend(":memory:")
        base = tmp_path / "learnings"
        engine = SyncEngine(be, base)
        for ftype in ("Tool", "Style", "Spec", "Reference"):
            engine.write_fact_to_md(StructuredFact(
                type=ftype, title=f"Знание типа {ftype} про раунд-трип меты",
                tags=["meta"], status="verified",
                content_summary="Описание для проверки сохранности типа.",
                source_file=f"docs/{ftype}.md",
            ))

        for ftype in ("Tool", "Style", "Spec", "Reference"):
            parsed = parse_md_file(base / "docs" / f"{ftype}.md")
            assert parsed[0].type == ftype, f"тип {ftype} обязан переживать раунд-трип"
            assert parsed[0].tags == ["meta"], "теги обязаны переживать раунд-трип"


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

    def test_title_with_hashes_inside_survives(self, tmp_path):
        from curator.analyzers.ingest import parse_md_file
        from curator.sync_engine import SyncEngine

        be = LocalBackend(":memory:")
        base = tmp_path / "learnings"
        engine = SyncEngine(be, base)
        title = "Как использовать ### заголовки в markdown правильно"
        engine.write_fact_to_md(StructuredFact(
            type="Reference", title=title, tags=["md"], status="verified",
            content_summary="Про разметку заголовков в документах.",
            source_file="docs/md.md",
        ))

        parsed = parse_md_file(base / "docs" / "md.md")
        assert parsed[0].title == title, "title с ### внутри обязан переживать раунд-трип"


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


class TestUsageJsonRobustness:
    """Ревью-4/5: битые записи usage.json (не dict) валили get_stats/get_unused."""

    def test_corrupted_entries_skipped(self, tmp_path):
        path = tmp_path / "usage.json"
        path.write_text(json.dumps({
            "Good Fact": {"count": 3, "last_access": time.time()},
            "broken": "not-a-dict",
            "another": 42,
        }))

        rf = RetrievalFeedback(str(path))
        stats = rf.get_stats(10)
        assert [s["title"] for s in stats] == ["Good Fact"]
        assert rf.get_unused(90) == []

    def test_corrupted_fields_skipped(self, tmp_path):
        """Раунд-5: dict с битыми полями (count строкой, нет last_access)."""
        path = tmp_path / "usage.json"
        path.write_text(json.dumps({
            "Good Fact": {"count": 3, "last_access": time.time()},
            "count_str": {"count": "3", "last_access": 1.0},
            "no_last": {"count": 1},
        }))

        rf = RetrievalFeedback(str(path))
        assert [s["title"] for s in rf.get_stats(10)] == ["Good Fact"]
        assert rf.get_unused(90) == []


class TestDeprecatedMarkerPrecision:
    """Раунд-5 фаззинг: '[УСТАРЕЛО]' в тегах/описании легитимного факта
    дропал секцию целиком при реингесте (молчаливая потеря знания)."""

    def test_stale_word_in_tag_or_summary_survives(self, tmp_path):
        from curator.analyzers.ingest import parse_md_file
        from curator.sync_engine import SyncEngine

        be = LocalBackend(":memory:")
        base = tmp_path / "learnings"
        engine = SyncEngine(be, base)
        engine.write_fact_to_md(StructuredFact(
            type="Reference", title="Знание про пометку устаревших API версий",
            tags=["[УСТАРЕЛО] апи"], status="verified",
            content_summary="Работа с [УСТАРЕЛО] эндпоинтами легаси.",
            source_file="docs/api.md",
        ))

        parsed = parse_md_file(base / "docs" / "api.md")
        assert len(parsed) == 1, "подстрока [УСТАРЕЛО] в тегах/описании не дропает факт"
        assert parsed[0].tags == ["[УСТАРЕЛО] апи"]

    def test_deprecated_title_line_still_skipped(self, tmp_path):
        from curator.analyzers.ingest import parse_md_file
        from curator.sync_engine import SyncEngine

        be = LocalBackend(":memory:")
        base = tmp_path / "learnings"
        engine = SyncEngine(be, base)
        fact = StructuredFact(
            type="Reference", title="Старое правило про пагинацию каталога",
            tags=["api"], status="deprecated",
            content_summary="Устаревшее знание.", source_file="docs/old.md",
        )
        engine.write_fact_to_md(fact)
        engine.remove_fact_from_md(fact)

        parsed = parse_md_file(base / "docs" / "old.md")
        assert parsed == [], "маркер [УСТАРЕЛО] в заголовке обязан пропускать секцию"


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
