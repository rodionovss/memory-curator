"""MapRouter: маршрутизация по карте документации (формат скилла Егора).

Детерминированная попытка интеграции: путь агента (валидация против
таргетов), теги ∩ токены темы, явные types темы, glob-таргеты не
угадываем (это работа агента/скилла), on_unmatched → report + дефолт.
Фикстура — его реальная карта (tests/fixtures/egor-documentation-map.md)."""

from pathlib import Path

import pytest

from curator.models import ProposedFact
from curator.routing.map_router import MapRouter

FIXTURE = Path(__file__).parent.parent / "fixtures" / "egor-documentation-map.md"


def _fact(title="Факт про architecture слоёв приложения", tags=None, type_="Reference", source_file=None):
    return ProposedFact(
        type=type_, title=title,
        content_summary="Достаточно длинная сводка факта для маршрутизации.",
        tags=tags if tags is not None else ["architecture"],
        source_file=source_file,
    )


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("CURATOR_MAP", raising=False)
    monkeypatch.delenv("CURATOR_BASE_DIR", raising=False)


class TestRealMap:
    def test_fixture_routes_by_tag(self):
        router = MapRouter(FIXTURE)
        # тема system-architecture-and-runtime-flows: токен architecture
        path = router.route_fact(_fact(tags=["architecture"]))
        assert path == "example/backend/docs/architecture/overview.md", \
            "тег architecture → первый КОНКРЕТНЫЙ таргет темы"

    def test_no_match_falls_to_default_with_report(self, capsys):
        router = MapRouter(FIXTURE)
        path = router.route_fact(_fact(title="Совсем посторонний факт ни о чём карте",
                                       tags=["нетема"]))
        assert path == "session/reference.md"
        err = capsys.readouterr().err
        assert "нет темы" in err, "on_unmatched: report — видимая деградация"

    def test_agent_path_matching_target_is_trusted(self):
        router = MapRouter(FIXTURE)
        path = router.route_fact(_fact(source_file="example/backend/docs/domains/billing.md"))
        assert path == "example/backend/docs/domains/billing.md", \
            "скилл разрулил glob — ядро доверяет совпавшему с таргетом пути"

    def test_agent_path_not_matching_any_target_is_not_trusted(self, capsys):
        router = MapRouter(FIXTURE)
        path = router.route_fact(_fact(tags=["architecture"],
                                       source_file="evil/outside/map.md"))
        assert path == "example/backend/docs/architecture/overview.md"
        assert "не совпал" in capsys.readouterr().err

    def test_agent_path_cannot_traverse_matching_glob(self, capsys):
        router = MapRouter(FIXTURE)
        path = router.route_fact(_fact(
            tags=["нетема"],
            source_file="example/backend/docs/domains/../../DOCUMENTATION-MAP.md",
        ))
        assert path == "session/reference.md"
        assert "небезопасный путь" in capsys.readouterr().err

    def test_glob_only_topic_not_decided_by_core(self, capsys):
        # в реальной карте может не быть тем с чисто glob-таргетами выше
        # по порядку — проверяем на синтетике ниже; здесь: маршрутизация
        # хотя бы не падает на реальной карте
        router = MapRouter(FIXTURE)
        assert router.route_fact(_fact(tags=["navigation"])) in {
            "example/backend/docs/README.md", "session/reference.md"}


class TestSyntheticMap:
    def _write(self, tmp_path, topics_yaml):
        map_file = tmp_path / "MAP.md"
        map_file.write_text(
            "---\n"
            "status: draft\n"
            "categories: [knowledge, rules, records]\n"
            "modes: [update, append, readonly]\n"
            "on_unmatched: report\n"
            f"topics:\n{topics_yaml}"
            "---\n",
            encoding="utf-8",
        )
        return map_file

    def test_glob_only_topic_reported(self, tmp_path, capsys):
        map_file = self._write(tmp_path, (
            "  - name: domains\n"
            "    watch_for: домены\n"
            "    targets:\n"
            "      - path: docs/domains/*.md\n"
            "        captures: [knowledge]\n"
            "        mode: update\n"
        ))
        router = MapRouter(map_file)
        path = router.route_fact(_fact(tags=["domains"]))
        assert path == "session/reference.md", "glob не решаем ядром"
        assert "glob-таргеты" in capsys.readouterr().err

    def test_explicit_types_field(self, tmp_path):
        map_file = self._write(tmp_path, (
            "  - name: personal-style\n"
            "    types: [Style]\n"
            "    targets:\n"
            "      - path: style/rules.md\n"
            "        captures: [rules]\n"
            "        mode: update\n"
        ))
        router = MapRouter(map_file)
        assert router.route_fact(_fact(type_="Style", tags=["нетема"])) == "style/rules.md"
        # Reference в эту тему не попадает (нет вывода — только явное поле)
        assert router.route_fact(_fact(type_="Reference", tags=["нетема"])) == "session/reference.md"

    def test_tag_tokens_beat_types(self, tmp_path):
        map_file = self._write(tmp_path, (
            "  - name: kotlin\n"
            "    targets:\n"
            "      - path: docs/kotlin.md\n"
            "        captures: [knowledge]\n"
            "        mode: update\n"
            "  - name: other\n"
            "    types: [Reference]\n"
            "    targets:\n"
            "      - path: docs/other.md\n"
            "        captures: [knowledge]\n"
            "        mode: update\n"
        ))
        router = MapRouter(map_file)
        assert router.route_fact(_fact(tags=["kotlin"])) == "docs/kotlin.md"

    def test_invalid_map_degrades_visibly(self, tmp_path, capsys):
        map_file = self._write(tmp_path, (
            "  - name: bad\n"
            "    targets:\n"
            "      - path: ../../../etc/hosts\n"
            "        mode: update\n"
            "      - path: ok.md\n"
            "        mode: hack\n"
        ))
        router = MapRouter(map_file)
        assert router.route_fact(_fact(tags=["bad"])) == "session/reference.md"
        err = capsys.readouterr().err
        assert "ошибок валидации" in err
        assert "вне корня" in err and "не из" in err

    def test_watch_for_tokens_route_tags(self, tmp_path):
        map_file = self._write(tmp_path, (
            "  - name: mvi\n"
            "    watch_for: mvi, state, viewmodel, effect\n"
            "    targets:\n"
            "      - path: session/mvi.md\n"
            "        mode: update\n"
            "        captures: [knowledge]\n"
            "  - name: compose\n"
            "    watch_for: compose, composable, modifier\n"
            "    targets:\n"
            "      - path: session/compose.md\n"
            "        mode: update\n"
            "        captures: [knowledge]\n"
        ))
        router = MapRouter(map_file)
        # два пересечения по watch_for-токенам бьют одно по name-токену
        assert router.route_fact(_fact(tags=["viewmodel", "mvi", "compose"])) == "session/mvi.md"
        # пересечение только по watch_for-токену
        assert router.route_fact(_fact(tags=["effect"])) == "session/mvi.md"
        # name-токен по-прежнему работает
        assert router.route_fact(_fact(tags=["compose"])) == "session/compose.md"

    def test_watch_for_prose_segments_ignored(self, tmp_path):
        map_file = self._write(tmp_path, (
            "  - name: prose-topic\n"
            "    watch_for: >-\n"
            "      Появляется знание о предметной области, состояние UI меняется.\n"
            "    targets:\n"
            "      - path: docs/prose.md\n"
            "        mode: update\n"
        ))
        router = MapRouter(map_file)
        # все prose-сегменты (с пробелами) — инструкция агенту, не токены:
        # тег «состояние» из prose-текста не матчится
        assert router.route_fact(_fact(tags=["состояние"])) == "session/reference.md"

    def test_topics_in_body_is_visible_degradation(self, tmp_path, capsys):
        # регресс инцидента 11.09: topics в теле (после закрытия frontmatter)
        # раньше давали 0 тем БЕЗ единой ошибки — тихий откат на дефолт
        map_file = tmp_path / "MAP.md"
        map_file.write_text(
            "---\ntitle: Карта без topics в frontmatter\n---\n\n"
            "# Карта\n\ntopics:\n  - name: mvi\n    targets:\n"
            "      - path: session/mvi.md\n        mode: update\n",
            encoding="utf-8",
        )
        router = MapRouter(map_file)
        assert router.route_fact(_fact(tags=["mvi"])) == "session/reference.md"
        err = capsys.readouterr().err
        assert "без ключа topics" in err, "структурно битая карта — не молчим"

    def test_no_map_default(self, tmp_path, capsys):
        router = MapRouter(tmp_path / "nonexistent.md")
        assert router.route_fact(_fact()) == "session/reference.md"

    def test_list_routes_shows_modes(self, tmp_path):
        map_file = self._write(tmp_path, (
            "  - name: kotlin\n"
            "    targets:\n"
            "      - path: docs/kotlin.md\n"
            "        captures: [knowledge]\n"
            "        mode: append\n"
        ))
        routes = MapRouter(map_file).list_routes()
        assert routes and "docs/kotlin.md (mode: append)" == routes[0]["path"]
        assert routes[0]["type"] == "kotlin"

    def test_list_routes_preserves_semantic_map_fields(self, tmp_path):
        map_file = self._write(tmp_path, (
            "  - name: kotlin\n"
            "    watch_for: Изменилось устойчивое правило Kotlin\n"
            "    targets:\n"
            "      - path: docs/{style,architecture}.md\n"
            "        captures: [knowledge, rules]\n"
            "        mode: update\n"
            "        instructions: Обнови канонический раздел\n"
        ))

        route = MapRouter(map_file).list_routes()[0]

        assert route["topic"] == "kotlin"
        assert route["target"] == "docs/{style,architecture}.md"
        assert route["captures"] == ["knowledge", "rules"]
        assert route["watch_for"] == "Изменилось устойчивое правило Kotlin"
        assert route["instructions"] == "Обнови канонический раздел"
        assert MapRouter.matches_target("docs/style.md", route["target"])
        assert not MapRouter.matches_target("docs/other.md", route["target"])
        assert not MapRouter.matches_target("docs/private/style.md", "docs/*.md")
        assert not MapRouter.matches_target("docs//style.md", "docs/*/style.md")
        assert not MapRouter.matches_target("docs/./style.md", "docs/*/style.md")

    def test_exact_topic_and_target_lookup(self, tmp_path):
        map_file = self._write(tmp_path, (
            "  - name: kotlin\n"
            "    targets:\n"
            "      - path: docs/kotlin.md\n"
            "        captures: [knowledge]\n"
            "        mode: update\n"
        ))
        router = MapRouter(map_file)

        assert router.target_config("kotlin", "docs/kotlin.md") == {
            "topic": "kotlin",
            "target": "docs/kotlin.md",
            "captures": ["knowledge"],
            "mode": "update",
            "watch_for": "",
            "instructions": "",
        }
        assert router.target_config("Kotlin", "docs/kotlin.md") is None

    @pytest.mark.parametrize("target", [
        "      - path: docs/missing-mode.md\n        captures: [knowledge]\n",
        "      - path: docs/missing-captures.md\n        mode: update\n",
        "      - path: docs/empty-captures.md\n        captures: []\n        mode: update\n",
        "      - path: docs/unknown-capture.md\n        captures: [unknown]\n        mode: update\n",
    ])
    def test_incomplete_target_is_not_writable(self, tmp_path, target, capsys):
        map_file = self._write(tmp_path, "  - name: incomplete\n    targets:\n" + target)

        router = MapRouter(map_file)

        path = target.split("path: ", 1)[1].splitlines()[0]
        assert router.target_config("incomplete", path) is None
        assert "ошибок валидации" in capsys.readouterr().err
