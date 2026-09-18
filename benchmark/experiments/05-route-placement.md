# Experiment 05: Route Placement

## Вопрос

Experiment 01 проверил содержание route-метаданных (формат R3) внутри
`AGENTS.md`. Этот эксперимент проверяет физическое размещение каталога
маршрутов, не предполагая, что отдельный route-файл загружается в контекст
автоматически: `AGENTS.md`, указатель на файл или загрузка через OpenCode
`instructions`.

## Варианты

| ID | Placement |
|---|---|
| `M1` | компактные route-метаданные напрямую в `AGENTS.md` |
| `M2` | `AGENTS.md` указывает на `knowledge-routes.md`; route-файл не предзагружен |
| `M3` | `knowledge-routes.md` загружается через OpenCode `instructions` |

Содержание route-метаданных во всех вариантах одно и то же (контентная
база — победивший формат R3 эксперимента 01, сгруппированный по структуре
каталога маршрутов: Description / When to use / Source; контракт —
`design/knowledge-route-format.md`). Отличается только физическое
размещение:

- `M1`: каталог встроен в `AGENTS.md` workspace-а (системный контекст).
- `M2`: каталог лежит в `knowledge-routes.md` workspace-а; `AGENTS.md`
  содержит только указатель на файл. Агент должен прочитать файл сам —
  это extra hop.
- `M3`: файл `knowledge-routes.md` тот же, что у M2, `AGENTS.md`
  идентичен M2, но путь файла добавлен в массив `instructions`
  изолированного opencode-конфига — контент попадает в system message.

Variant-файлы заморожены: `corpus/placement-variants/` (+ `FROZEN.sha`).

## Corpus и задачи

Corpus тот же, что в эксперименте 01 (заморожен: `corpus/tasks.json`,
`corpus/FROZEN.sha`): задачи T01, T02, T03, T04, T06, T07, K1, K2 с
детерминированными checks. Реальная база пользователя в workspaces не
копируется — только синтетический `corpus/kb/`.

## Матрица запусков

`8 tasks × 3 variants × 3 repeats × 2 models = 144 runs`.

## Marker rule

Загрузка M3 проверяется прямым осмотром system message изолированной
сессии на уникальный маркер каталога; из результатов application
наличие загрузки не выводится.

- В содержании каталога маршрутов есть уникальная строка-маркер
  `<!-- route-catalog-marker: rp05-... -->` (константа
  `ROUTE_MARKER` в harness-е).
- У каждого прогона harness запускает probe-сессию в том же
  workspace/HOME против локального mock-провайдера (`probe_mock/capture`,
  127.0.0.1, реальный LLM не вызывается) и проверяет маркер в system
  message захваченного request payload-а. Это прямая проверка
  системного контекста, а не application-результатов.
- Правила размещения маркера:
  - `M1`: маркер в `AGENTS.md` → ожидается в system message;
  - `M2`: маркер только в `knowledge-routes.md` (файл, который агент
    должен прочитать сам) → в system message быть НЕ должно;
  - `M3`: маркер в `knowledge-routes.md`, файл предзагружен через
    `instructions` → ожидается в system message.
- Каждый прогон фиксирует `marker_present` (bool) и
  `marker_expected` (bool). Прогон, где `marker_present !=
  marker_expected` — wiring-нарушение.

## Procedure

Один прогон = (task, variant, model, repeat):

1. Свежий isolated HOME (минимальный opencode-конфиг; для M3 —
   `instructions: [<ws>/knowledge-routes.md]`).
2. Workspace: fixture + `kb/` + `AGENTS.md` варианта; для M2/M3 —
   `knowledge-routes.md` в workspace.
3. `opencode run --dir ws --title <run_id> "<task prompt>"`.
4. Probe-сессия против mock-провайдера → `marker_present`.
5. Транскрипт → события (kb reads + чтения `knowledge-routes.md`).
6. Детерминированный check → `application_pass`.
7. Результат в `results/05-route-placement/runs/<run_id>.json`
   (schemas/run.json).

## Метрики

Per-run (7 обязательных):

- `marker_present` — маркер каталога в system message сессии;
- `routing_hit` — прочитан source-файл ожидаемого факта (routing recall
  агрегируется по задачам с `expected_fact_id`);
- `application_pass` — детерминированный check прошёл (application rate);
- `source_file_reads` — чтения kb source-файлов;
- `unnecessary_reads` — чтения kb source-файлов, не совпадающие с
  ожидаемым фактом (для K1 — все kb-чтения; навигационные чтения
  `kb/index.md` не считаются);
- `input_tokens` — токены входа сессии задачи;
- `latency_ms` — время `opencode run` задачи.

Дополнительно: `routes_file_reads` — чтения `knowledge-routes.md`
(extra hop M2), `probe_valid`, `output_tokens`, `tool_calls`.

## Ожидаемый выход и decision rule

Decision rule (из плана, дословно):

- prefer M3 if its route marker is present in at least 95% of M3
  sessions, application/routing is not lower than M1, and token cost is
  lower than M2;
- prefer M1 only if M3 is not reliably auto-loaded;
- do not use M2 as the default if it adds a measurable extra hop.

`summary.json` (`route_placement_runner.py --summarize`) выдаёт входы
решения: `marker_rate` M3, дельты routing/application M3 vs M1, дельту
input tokens M3 vs M2, `routes_file_reads` по вариантам.

Запускать live-эксперимент можно только после записи placement-результата.

## Запуск

```bash
# wiring self-check: собрать все workspaces, проверить маркеры и конфиги,
# 0 LLM-сессий, ничего не пишет в results/
core/.venv/bin/python benchmark/experiments/harness/route_placement_runner.py \
    --variants M1,M2,M3 --models strong,weak --repeats 3 --tasks all --dry-run

# полный sweep 144 прогона (контроллер запускает отдельно, в фоне)
core/.venv/bin/python benchmark/experiments/harness/route_placement_runner.py \
    --variants M1,M2,M3 --models strong,weak --repeats 3 --tasks all

# агрегация после sweep
core/.venv/bin/python benchmark/experiments/harness/route_placement_runner.py --summarize
```
