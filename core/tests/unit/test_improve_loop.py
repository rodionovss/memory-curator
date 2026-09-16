"""Тесты ImproveLoop: similarity, contradictions, краевые случаи."""

from curator.improve_loop import ImproveLoop, ImproveReport
from curator.models import StructuredFact


def _ref(title, tags=None, status="verified", created_at=None):
    return StructuredFact(
        type="Reference", title=title,
        tags=tags or ["test"], status=status,
        content_summary=f"Summary for {title}" * 2,
        created_at=created_at,
    )


class TestTitleSimilarity:
    def setup_method(self):
        self.loop = ImproveLoop.__new__(ImproveLoop)

    def test_identical(self):
        assert self.loop._title_similarity("Правило про JVM", "Правило про JVM") == 1.0

    def test_completely_different(self):
        sim = self.loop._title_similarity("Правило про JVM", "Стиль коммитов")
        assert sim < 0.3

    def test_partial_overlap(self):
        sim = self.loop._title_similarity("Правило про JVM inline классы", "Правило про JVM бокс")
        assert sim > 0.3

    def test_different_case(self):
        sim = self.loop._title_similarity("ПРАВИЛО ПРО JVM", "правило про jvm")
        assert sim == 1.0

    def test_empty_strings(self):
        assert self.loop._title_similarity("", "") == 0.0


class TestFindDuplicates:
    def test_no_duplicates_unique(self):
        loop = ImproveLoop.__new__(ImproveLoop)
        facts = [_ref("Kotlin rules"), _ref("Python rules")]
        assert loop._find_duplicates(facts) == []

    def test_duplicates_same_type_similar_title(self):
        loop = ImproveLoop.__new__(ImproveLoop)
        f1 = _ref("Правило про JVM inline классы sealed interface бокс")
        f2 = _ref("Правило про JVM inline классы sealed interface")
        dups = loop._find_duplicates([f1, f2])
        assert len(dups) == 1

    def test_different_types_not_duplicates(self):
        loop = ImproveLoop.__new__(ImproveLoop)
        f1 = StructuredFact(type="Reference", title="Same title", tags=["test"], status="verified", content_summary="x" * 20)
        f2 = StructuredFact(type="Style", title="Same title", tags=["test"], status="verified", content_summary="x" * 20)
        assert loop._find_duplicates([f1, f2]) == []


class TestDupPairOrientation:
    """Регрессия #8: survivor пары дубликатов не зависит от порядка,
    в котором факты пришли из бэкенда."""

    def _only_pair(self, facts):
        loop = ImproveLoop.__new__(ImproveLoop)
        dups = loop._find_duplicates(facts)
        assert len(dups) == 1
        return dups[0][0], dups[0][1]

    def test_earlier_created_survives_in_any_order(self):
        early = _ref("Правило про JVM inline классы sealed", created_at="2026-09-16 10:00:00")
        late = _ref("Правило про JVM inline классы sealed бокс", created_at="2026-09-16 10:00:05")
        for facts in ([early, late], [late, early]):
            winner, loser = self._only_pair(facts)
            assert winner.title == early.title
            assert loser.title == late.title

    def test_title_tiebreak_when_created_at_equal(self):
        a = _ref("Правило про JVM inline классы sealed", created_at="2026-09-16 10:00:00")
        b = _ref("Правило про JVM inline классы sealed бокс", created_at="2026-09-16 10:00:00")
        for facts in ([a, b], [b, a]):
            winner, loser = self._only_pair(facts)
            assert winner.title == a.title
            assert loser.title == b.title

    def test_no_created_at_title_tiebreak(self):
        a = _ref("Правило про JVM inline классы sealed")
        b = _ref("Правило про JVM inline классы sealed бокс")
        for facts in ([a, b], [b, a]):
            winner, loser = self._only_pair(facts)
            assert winner.title == a.title
            assert loser.title == b.title


class TestFindStale:
    def test_finds_hypothesis(self):
        loop = ImproveLoop.__new__(ImproveLoop)
        facts = [_ref("A", status="hypothesis"), _ref("B")]
        assert len(loop._find_stale(facts)) == 1

    def test_finds_deprecated(self):
        loop = ImproveLoop.__new__(ImproveLoop)
        facts = [_ref("A", status="deprecated"), _ref("B")]
        assert len(loop._find_stale(facts)) == 1

    def test_no_stale(self):
        loop = ImproveLoop.__new__(ImproveLoop)
        facts = [_ref("A"), _ref("B")]
        assert loop._find_stale(facts) == []


class TestContradictions:
    def setup_method(self):
        self.loop = ImproveLoop.__new__(ImproveLoop)

    def test_no_contradictions_same_sentiment(self):
        f1 = _ref("Использовать ImmutableList для больших списков", ["compose", "performance"])
        f2 = _ref("ImmutableList рекомендуется для MVI", ["compose", "architecture"])
        assert self.loop._find_contradictions([f1, f2]) == []

    def test_detects_opposing_views(self):
        f1 = _ref("Использовать ImmutableList для списков в Compose", ["compose"])
        f2 = _ref("Не использовать ImmutableList в Compose", ["compose"])
        result = self.loop._find_contradictions([f1, f2])
        assert len(result) == 1

    def test_oppose_only_same_domain(self):
        f1 = _ref("Использовать data class в sealed interface", ["kotlin", "jvm"])
        f2 = _ref("Не использовать data class для Compose State", ["compose"])
        assert self.loop._find_contradictions([f1, f2]) == []

    def test_contradictions_require_reference_type(self):
        f1 = StructuredFact(type="Style", title="Использовать X", tags=["test"], status="verified", content_summary="x" * 20)
        f2 = StructuredFact(type="Style", title="Не использовать X", tags=["test"], status="verified", content_summary="x" * 20)
        assert self.loop._find_contradictions([f1, f2]) == []

    def test_share_tags_detection(self):
        f1 = _ref("A", ["kotlin", "jvm"])
        f2 = _ref("B", ["kotlin", "jvm"])
        assert self.loop._share_tags(f1, f2)

        f3 = _ref("A", ["kotlin"])
        f4 = _ref("B", ["python"])
        assert not self.loop._share_tags(f3, f4)


class TestImproveReport:
    def test_empty_report(self):
        r = ImproveReport()
        assert r.stats == {}
        assert r.duplicates == []
        assert r.stale == []
        assert r.contradictions == []


class TestResolution:
    def setup_method(self):
        self.loop = ImproveLoop.__new__(ImproveLoop)

    def test_verified_beats_hypothesis(self):
        f1 = _ref("Использовать X", status="verified")
        f2 = _ref("Не использовать X", status="hypothesis")
        winner, loser, reason = self.loop._pick_winner(f1, f2)
        assert winner.status == "verified"
        assert "verified" in reason

    def test_more_tags_beats_fewer(self):
        f1 = _ref("Использовать X", tags=["compose", "android"], status="verified")
        f2 = _ref("Не использовать X", tags=["compose"], status="verified")
        winner, loser, reason = self.loop._pick_winner(f1, f2)
        assert len(winner.tags) > len(loser.tags)

    def test_more_summary_beats_shorter(self):
        f1 = _ref("Использовать X", status="verified")
        f2 = _ref("Не использовать X", status="verified")
        f1.content_summary = "x" * 100
        f2.content_summary = "x" * 20
        winner, loser, reason = self.loop._pick_winner(f1, f2)
        assert winner == f1

    def test_resolve_multiple_pairs(self):
        f1 = _ref("Использовать Y", status="verified")
        f2 = _ref("Не использовать Y", status="hypothesis")
        f3 = _ref("Делать Z", status="verified")
        f4 = _ref("Не делать Z", status="deprecated")
        resolutions = self.loop._resolve_contradictions([(f1, f2), (f3, f4)])
        assert len(resolutions) == 2
        assert all(r.winner.status == "verified" for r in resolutions)

class TestDeprecatedContract:
    """report.deprecated — все факты, переведённые прогоном в deprecated
    (dup-проигравшие, stale по гейту, проигравшие противоречий): write-back
    в .md идёт по этому списку."""

    def _loop(self, be):
        from curator.improve_loop import ImproveLoop
        return ImproveLoop(be)

    def test_dup_loser_in_deprecated(self, tmpdir):
        from curator.backend.local import LocalBackend
        from curator.models import StructuredFact
        be = LocalBackend(str(tmpdir / "t.db"))
        be.store_fact(StructuredFact(type="Reference", title="Одно и то же правило про kotlin классы", tags=["kotlin"], status="verified", content_summary="x" * 30))
        be.store_fact(StructuredFact(type="Reference", title="Одно и то же правило про kotlin классы бокс", tags=["kotlin"], status="verified", content_summary="y" * 30))

        report = self._loop(be).run()

        assert any(f.status == "deprecated" for f in report.deprecated), \
            "dup-проигравший обязан попасть в report.deprecated"

    def test_contradiction_loser_in_deprecated(self, tmpdir):
        from curator.backend.local import LocalBackend
        from curator.models import StructuredFact
        be = LocalBackend(str(tmpdir / "t.db"))
        be.store_fact(StructuredFact(type="Reference", title="Всегда используй rxjava в новых модулях", tags=["rx", "java"], status="verified", content_summary="короткая сводка"))
        be.store_fact(StructuredFact(type="Reference", title="Никогда не используй rxjava в новых модулях", tags=["rx", "java"], status="verified", content_summary="подробная сводка подлиннее для победы"))

        report = self._loop(be).run()

        assert len(report.resolutions) == 1
        loser_titles = {f.title for f in report.deprecated}
        assert report.resolutions[0].loser.title in loser_titles

    def test_clean_base_empty_deprecated(self, tmpdir):
        from curator.backend.local import LocalBackend
        from curator.models import StructuredFact
        be = LocalBackend(str(tmpdir / "t.db"))
        be.store_fact(StructuredFact(type="Reference", title="Уникальное правило про compose стейт", tags=["compose"], status="verified", content_summary="x" * 30))

        report = self._loop(be).run()

        assert report.deprecated == []


class TestMetricsBeforeAfter:
    """metrics_before/after — замер пользы прогона для отчёта/демо:
    coverage, факты, verified-доля до и после применения."""

    def test_metrics_present_and_shrink_on_consolidation(self, tmpdir):
        from curator.backend.local import LocalBackend
        be = LocalBackend(str(tmpdir / "t.db"))
        be.store_fact(StructuredFact(type="Reference", title="Одно и то же правило про kotlin классы", tags=["kotlin"], status="verified", content_summary="x" * 30))
        be.store_fact(StructuredFact(type="Reference", title="Одно и то же правило про kotlin классы бокс", tags=["kotlin"], status="verified", content_summary="y" * 30))

        report = ImproveLoop(be).run()

        assert report.metrics_before is not None and report.metrics_after is not None
        assert report.metrics_before.total_facts == 2
        assert report.metrics_after.total_facts == 1, \
            "консолидация сжимает активный набор — метрики это показывают"
