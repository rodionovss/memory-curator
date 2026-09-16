from dataclasses import dataclass, field, replace
from curator.backend.interface import MemoryBackend
from curator.models import StructuredFact, FactQuery
from curator.eval_runner import EvalRunner


@dataclass
class Resolution:
    winner: StructuredFact
    loser: StructuredFact
    reason: str


@dataclass
class ImproveReport:
    duplicates: list[tuple[StructuredFact, StructuredFact]] = field(default_factory=list)
    stale: list[StructuredFact] = field(default_factory=list)
    contradictions: list[tuple[StructuredFact, StructuredFact]] = field(default_factory=list)
    resolutions: list[Resolution] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    events: list = field(default_factory=list)
    # Факты, переведённые этим прогоном в deprecated (dup-проигравшие,
    # stale по eval-гейту, проигравшие противоречия) — для write-back в .md
    deprecated: list[StructuredFact] = field(default_factory=list)
    # Замер пользы прогона «до → после» (демо/отчёт: coverage вырос,
    # дубли схлопнуты). None — цикл не нашёл действий.
    metrics_before: object | None = None
    metrics_after: object | None = None


class ImproveLoop:
    def __init__(self, backend: MemoryBackend):
        self.backend = backend

    def run(self) -> ImproveReport:
        # Активный набор: deprecated покинул память (забыт). Симуляция
        # eval-гейта удаляет их из измеряемого списка — этот фильтр делает
        # применение идентичным симуляции и исключает повторную обработку
        # уже деприкнутых фактов на каждом прогоне.
        all_facts = [f for f in self.backend.query_facts(FactQuery()) if f.status != "deprecated"]
        report = ImproveReport()
        runner = EvalRunner()
        report.metrics_before = runner.measure(all_facts)
        report.duplicates = self._find_duplicates(all_facts)
        report.stale = self._find_stale(all_facts)
        report.contradictions = self._find_contradictions(all_facts)
        report.stats = {
            "total_facts": len(all_facts),
            "duplicates_found": len(report.duplicates),
            "stale_found": len(report.stale),
            "contradictions_found": len(report.contradictions),
        }

        from curator.observability import Observability, ObserveEvent
        obs = Observability()

        if report.duplicates:
            action = runner.evaluate_consolidation(all_facts, report.duplicates)
            obs.log(ObserveEvent(
                action="consolidate",
                applied=action.improved,
                reason="metrics improved" if action.improved else "eval blocked — no improvement",
                facts=[f"{d[0].title} ↔ {d[1].title}" for d in report.duplicates],
                eval_before=action.before_metrics.query_coverage,
                eval_after=action.after_metrics.query_coverage,
            ))
            if action.improved:
                for _, dup in report.duplicates:
                    self.backend.store_fact(replace(dup, status="deprecated"))
                    report.deprecated.append(replace(dup, status="deprecated"))

        if report.stale:
            action = runner.evaluate_deprecation(all_facts, report.stale)
            obs.log(ObserveEvent(
                action="deprecate",
                applied=action.improved,
                reason="metrics improved" if action.improved else "eval blocked — no improvement",
                facts=[f.title for f in report.stale],
                eval_before=action.before_metrics.query_coverage,
                eval_after=action.after_metrics.query_coverage,
            ))
            if action.improved:
                for f in report.stale:
                    self.backend.store_fact(replace(f, status="deprecated"))
                    report.deprecated.append(replace(f, status="deprecated"))

        if report.contradictions:
            resolutions = self._resolve_contradictions(report.contradictions)
            report.resolutions = resolutions
            for r in resolutions:
                self.backend.store_fact(replace(r.loser, status="deprecated"))
                report.deprecated.append(replace(r.loser, status="deprecated"))
            obs.log(ObserveEvent(
                action="contradiction_resolved",
                applied=True,
                reason="%d противоречий разрешено" % len(resolutions),
                facts=[f"{r.winner.title} ← {r.loser.title} ({r.reason})" for r in resolutions],
            ))

        report.events = obs.recent(10)
        report.metrics_after = runner.measure(
            [f for f in self.backend.query_facts(FactQuery()) if f.status != "deprecated"]
        )
        return report

    def _find_duplicates(self, facts: list[StructuredFact]) -> list[tuple[StructuredFact, StructuredFact]]:
        duplicates = []
        for i, f1 in enumerate(facts):
            for f2 in facts[i + 1:]:
                if f1.type == f2.type and self._title_similarity(f1.title, f2.title) > 0.8:
                    duplicates.append(self._orient_dup_pair(f1, f2))
        return duplicates

    def _orient_dup_pair(
        self, f1: StructuredFact, f2: StructuredFact
    ) -> tuple[StructuredFact, StructuredFact]:
        """Детерминированная ориентация пары: survivor — ранее созданный
        факт, при равенстве или отсутствии created_at — лексикографически
        меньший title. Без этого проигравший зависел от порядка выдачи
        бэкенда: ORDER BY created_at DESC с секундной гранулярностью
        не гарантирует порядок тай-брейка (issue #8)."""
        if (f1.created_at or "", f1.title) > (f2.created_at or "", f2.title):
            return f2, f1
        return f1, f2

    def _find_stale(self, facts: list[StructuredFact]) -> list[StructuredFact]:
        return [f for f in facts if f.status in ("hypothesis", "deprecated")]

    def _find_contradictions(self, facts: list[StructuredFact]) -> list[tuple[StructuredFact, StructuredFact]]:
        contradictions = []
        for i, f1 in enumerate(facts):
            if f1.type != "Reference":
                continue
            for f2 in facts[i + 1:]:
                if f2.type != "Reference":
                    continue
                if not self._share_tags(f1, f2):
                    continue
                if self._oppose_titles(f1.title, f2.title):
                    contradictions.append((f1, f2))
        return contradictions

    def _share_tags(self, f1: StructuredFact, f2: StructuredFact) -> bool:
        s1 = set(f1.tags)
        s2 = set(f2.tags)
        if not s1 or not s2:
            return False
        return len(s1 & s2) / len(s1 | s2) > 0.4

    NEGATION_PATTERNS = ["не ", "нельзя", "запрещен", "избега", "никогда", "не использу"]

    def _oppose_titles(self, a: str, b: str) -> bool:
        a_low = a.lower()
        b_low = b.lower()
        a_neg = any(p in a_low for p in self.NEGATION_PATTERNS)
        b_neg = any(p in b_low for p in self.NEGATION_PATTERNS)
        if a_neg == b_neg:
            return False
        return self._title_similarity(a, b) > 0.2

    def _title_similarity(self, a: str, b: str) -> float:
        words_a = set(a.lower().split())
        words_b = set(b.lower().split())
        if not words_a or not words_b:
            return 0.0
        return len(words_a & words_b) / len(words_a | words_b)

    def _resolve_contradictions(self, pairs: list[tuple[StructuredFact, StructuredFact]]) -> list[Resolution]:
        resolutions = []
        for f1, f2 in pairs:
            winner, loser, reason = self._pick_winner(f1, f2)
            resolutions.append(Resolution(winner=winner, loser=loser, reason=reason))
        return resolutions

    STATUS_PRIORITY = {"verified": 3, "hypothesis": 1, "deprecated": 0}

    def _pick_winner(self, a: StructuredFact, b: StructuredFact) -> tuple[StructuredFact, StructuredFact, str]:
        score_a = self.STATUS_PRIORITY.get(a.status, 0)
        score_b = self.STATUS_PRIORITY.get(b.status, 0)
        if score_a != score_b:
            if score_a > score_b:
                return a, b, "%s status beats %s" % (a.status, b.status)
            else:
                return b, a, "%s status beats %s" % (b.status, a.status)

        tags_a = len(a.tags)
        tags_b = len(b.tags)
        if tags_a != tags_b:
            if tags_a > tags_b:
                return a, b, "больше тегов (%d > %d)" % (tags_a, tags_b)
            else:
                return b, a, "больше тегов (%d > %d)" % (tags_b, tags_a)

        summary_a = len(a.content_summary)
        summary_b = len(b.content_summary)
        if summary_a != summary_b:
            if summary_a > summary_b:
                return a, b, "подробнее описано (%d > %d зн.)" % (summary_a, summary_b)
            else:
                return b, a, "подробнее описано (%d > %d зн.)" % (summary_b, summary_a)

        return a, b, "равнозначны, оставлен первый"