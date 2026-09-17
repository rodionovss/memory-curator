"""Тесты детерминированной генерации Knowledge Routes (knowledge_routes)."""

import json

from curator.knowledge_routes import (
    build_routes,
    render_routes_json,
    render_routes_markdown,
)
from curator.models import StructuredFact

SUMMARY_BODY = "УНИКАЛЬНОЕ_ТЕЛО_ФАКТА_42 — полный текст, которого не должно быть в каталоге"


def make_fact(
    title: str,
    source_file: str | None = "compose.md",
    tags: list[str] | None = None,
    status: str = "verified",
    type_: str = "Reference",
    summary: str = SUMMARY_BODY,
) -> StructuredFact:
    return StructuredFact(
        type=type_,
        title=title,
        tags=list(tags or []),
        status=status,
        content_summary=summary,
        source_file=source_file,
    )


class TestBuildRoutes:
    def test_two_facts_one_file_one_route(self, tmp_path):
        result = build_routes(
            [make_fact("Fact A", tags=["compose"]), make_fact("Fact B", tags=["lists"])],
            tmp_path,
        )

        assert len(result.routes) == 1
        assert result.routes[0].source_file == "compose.md"
        assert result.validation_errors == ()

    def test_two_files_two_routes(self, tmp_path):
        result = build_routes(
            [make_fact("A", source_file="b.md"), make_fact("B", source_file="a.md")],
            tmp_path,
        )

        assert [r.source_file for r in result.routes] == ["a.md", "b.md"]

    def test_deprecated_fact_absent_from_routes(self, tmp_path):
        result = build_routes(
            [
                make_fact("Live", source_file="a.md"),
                make_fact("Dead", source_file="a.md", status="deprecated"),
            ],
            tmp_path,
        )

        assert len(result.routes) == 1
        assert result.routes[0].contains == ("Live",)

    def test_titles_appear_in_contains(self, tmp_path):
        result = build_routes(
            [make_fact("Beta"), make_fact("apple")],
            tmp_path,
        )

        assert result.routes[0].contains == ("apple", "Beta")

    def test_when_to_use_has_tags_and_titles(self, tmp_path):
        result = build_routes(
            [make_fact("Пагинация", tags=["compose", "lists"])],
            tmp_path,
        )

        when = result.routes[0].when_to_use
        assert "compose" in when
        assert "lists" in when
        assert "Пагинация" in when

    def test_route_order_stable_regardless_of_fact_order(self, tmp_path):
        facts = [
            make_fact("B", source_file="b.md"),
            make_fact("A", source_file="a.md"),
            make_fact("C", source_file="a.md", tags=["t"]),
        ]

        forward = build_routes(facts, tmp_path)
        backward = build_routes(list(reversed(facts)), tmp_path)

        assert forward == backward
        assert [r.source_file for r in forward.routes] == ["a.md", "b.md"]

    def test_source_paths_relative_posix(self, tmp_path):
        result = build_routes(
            [make_fact("A", source_file="folder/sub/compose.md")],
            tmp_path,
        )

        source = result.routes[0].source_file
        assert source == "folder/sub/compose.md"
        assert not source.startswith("/")
        assert "\\" not in source

    def test_windows_separators_converted(self, tmp_path):
        result = build_routes(
            [make_fact("A", source_file="folder\\sub\\compose.md")],
            tmp_path,
        )

        assert result.routes[0].source_file == "folder/sub/compose.md"

    def test_missing_source_file_visible_validation_item(self, tmp_path):
        result = build_routes(
            [make_fact("A", source_file=None), make_fact("B", source_file="b.md")],
            tmp_path,
        )

        assert [r.source_file for r in result.routes] == ["b.md"]
        assert len(result.validation_errors) == 1
        assert "A" in result.validation_errors[0]

    def test_unsafe_paths_rejected(self, tmp_path):
        result = build_routes(
            [
                make_fact("T", source_file="../outside.md"),
                make_fact("Abs", source_file="/etc/hosts"),
            ],
            tmp_path,
        )

        assert result.routes == ()
        assert len(result.validation_errors) == 2

    def test_absolute_path_inside_base_normalized(self, tmp_path):
        md_file = tmp_path / "kb.md"
        md_file.write_text("x", encoding="utf-8")

        result = build_routes([make_fact("A", source_file=str(md_file))], tmp_path)

        assert result.routes[0].source_file == "kb.md"

    def test_description_deterministic_from_metadata(self, tmp_path):
        result = build_routes(
            [make_fact("A", type_="Reference"), make_fact("B", type_="Tool", tags=["b-tag", "a-tag"])],
            tmp_path,
        )

        assert result.routes[0].description == "Reference/Tool knowledge from compose: a-tag, b-tag"
        assert result.routes[0].name == "compose"

    def test_description_without_tags(self, tmp_path):
        result = build_routes([make_fact("A", tags=[])], tmp_path)

        assert result.routes[0].description == "Reference knowledge from compose"


class TestRenderMarkdown:
    def test_format_matches_contract(self, tmp_path):
        result = build_routes([make_fact("Pagination", tags=["compose"])], tmp_path)

        assert render_routes_markdown(list(result.routes)) == (
            "## compose\n"
            "\n"
            "**Description:** Reference knowledge from compose: compose\n"
            "\n"
            "**When to use:**\n"
            "- compose;\n"
            "- Pagination.\n"
            "\n"
            "**Contains:**\n"
            "- Pagination.\n"
            "\n"
            "**Source:** `compose.md`\n"
        )

    def test_no_summary_body_in_output(self, tmp_path):
        result = build_routes([make_fact("A")], tmp_path)
        routes = list(result.routes)

        assert SUMMARY_BODY not in render_routes_markdown(routes)
        assert SUMMARY_BODY not in json.dumps(
            render_routes_json(routes), ensure_ascii=False
        )

    def test_identical_input_byte_identical_markdown(self, tmp_path):
        facts = [
            make_fact("A", source_file="a.md", tags=["x"]),
            make_fact("B", source_file="b/nested.md", tags=["y", "x"]),
        ]

        first = render_routes_markdown(list(build_routes(facts, tmp_path).routes))
        second = render_routes_markdown(list(build_routes(list(facts), tmp_path).routes))
        shuffled = render_routes_markdown(
            list(build_routes(list(reversed(facts)), tmp_path).routes)
        )

        assert first == second == shuffled
        assert first.endswith("\n")

    def test_empty_routes_render_empty(self):
        assert render_routes_markdown([]) == ""


class TestRenderJson:
    def test_shape(self, tmp_path):
        result = build_routes([make_fact("A", tags=["t"])], tmp_path)

        assert render_routes_json(list(result.routes)) == [
            {
                "name": "compose",
                "source_file": "compose.md",
                "description": "Reference knowledge from compose: t",
                "when_to_use": ["A", "t"],
                "contains": ["A"],
            }
        ]

    def test_empty_routes(self):
        assert render_routes_json([]) == []
