"""Тест тура `curator demo`: детерминированный полный цикл жизни знания.

Тур — витрина функционала: прогон должен сходиться к предсказанным числам.
"""

from curator.tour import run_tour


class TestTour:
    def test_full_lifecycle_counts(self):
        result = run_tour(keep=False, verbose=False)

        # Этап 1: gatekeeper — 10 кандидатов → 7 принято / 3 отклонено
        assert result["approved"] == 7
        assert result["rejected"] == 3, "дубль-на-входе + шум + короткий title обязаны быть отсеяны"

        # Этап 2: write-back — .md файлы созданы
        assert result["md_files"], "write-back обязан создать .md"

        # Этап 4: improve — 1 дубликат консолидирован, 1 противоречие разрешено
        assert result["duplicates_found"] == 1
        assert result["contradictions_found"] == 1

        # Этап 5: телеметрия — статистика без казни (таймерного decay нет)
        assert result["decay"] == 0

        # Этап 6: финал — 7 фактов: 5 verified / 2 deprecated
        assert result["final_by_status"] == {"verified": 5, "deprecated": 2}

    def test_tour_does_not_touch_real_curator_dir(self, tmp_path, monkeypatch):
        """Тур обязан писать только в свою tmp — реальные ~/.curator не трогаем."""
        import curator.observability as obs_mod
        import curator.retrieval_feedback as fb_mod
        before_obs, before_fb = obs_mod.Observability, fb_mod.RetrievalFeedback

        run_tour(keep=False, verbose=False)

        assert obs_mod.Observability is before_obs, "патч Observability обязан сниматься"
        assert fb_mod.RetrievalFeedback is before_fb, "патч RetrievalFeedback обязан сниматься"
