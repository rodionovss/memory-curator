# Тесты требований — трассировочная матрица

> Каждый тест = одно требование из `design/requirements.md`. Запуск:
> ```bash
> .venv/bin/python -m pytest tests/requirements/ -v
> ```
> Названия тестов = ID требований. Только публичные API (ingest, MCP-функции,
> backend Protocol, CLI-функции) — внутренние рефакторинги не могут «обнулить» тест.

## MUST HAVE (6/6)

| ID | Требование | Тест | Статус |
|----|-----------|------|--------|
| R1 | Поток задач из источника (.md → факты) | `test_must_have.py::test_R1_поток_задач_из_источника_ingest` | ✅ |
| R2 | Цикл «выполнил → оценил → извлёк урок» (review → approve → docs → complete → store) | `unit/test_session_capture.py` (`TestReview`, `TestApprove`, `TestComplete`) | ✅ |
| R3 | Менять поведение на основе опыта (improve консолидирует дубликаты) | `test_R3_поведение_меняется_на_основе_опыта` | ✅ |
| R4 | Память между рестартами (персистентный файл, не :memory:) | `test_R4_память_между_рестартами` | ✅ |
| R5 | Реальные данные (фикстуры = структура learnings) | `test_R5_реальные_данные_структуры_learnings` | ✅ |
| R6 | Дельта «до/после» (clean принимает / trained отклоняет дубли) | `test_R6_дельта_до_и_после` | ✅ |

## NICE TO HAVE (5/5)

| ID | Требование | Тест | Статус |
|----|-----------|------|--------|
| N1 | Забывание: семантическое устаревание (hypothesis → deprecated по eval-гейту), таймерного decay нет — телеметрия = observability | `test_nice_to_have.py::test_N1_забывание_семантическое` | ✅ |
| N2 | Противоречия: verified побеждает hypothesis | `test_N2_противоречия_разрешаются` | ✅ |
| N3 | Eval gate: блокирует ухудшение метрик, разрешает чистку | `test_N3_eval_блокирует_ухудшение` | ✅ |
| N4 | Human-in-the-loop: review не меняет документы/backend, approve принимает только выбранные ID | `unit/test_session_capture.py::TestReview::test_returns_json_preview_without_side_effects`, `TestApprove::test_freezes_selected_subset_and_returns_manifest` | ✅ |
| N5 | Observability: JSONL-лог всех improve-действий | `test_N5_observability_логирует_улучшения` | ✅ |

## Spec UC (spec.md)

| ID | Требование | Тест | Статус |
|----|-----------|------|--------|
| UC2 | Project write-back: три MCP tools, neural preflight, сначала документы, затем backend, placement по обязательной карте | `unit/test_session_capture.py::test_mcp_schema_exposes_three_step_capture_without_legacy_fields`, `TestComplete::test_writable_placement_saves_canonical_source`, `unit/test_skill_contracts.py` | ✅ |

UC2 описывает новый MCP `/curator-save`. Requirement-тесты ingest и CLI,
integration-тесты `SyncEngine` и E2E demo проверяют legacy-контур отдельно;
универсальный `session/{type}.md`, повторная отправка candidates и `AUTO_MODE` не
являются контрактом нового flow.

## Регрессии, пойманные этим подходом

- **R4**: persistence в `:memory:` терял данные при «рестарте» — зелёные юнит-тесты
  это не ловили (проверяли код, а не требование). Requirement-тест упал бы сразу.
