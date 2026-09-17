# Experiment 04: Markdown vs SQLite

## Вопрос

Нужен ли SQLite для текущего retrieval или Markdown/index даёт такое же
качество и скорость?

Это backend benchmark, без запуска модели. Поведение агента и формат ответа
должны оставаться одинаковыми.

## Варианты

| ID | Backend |
|---|---|
| `S1` | Markdown/index scan |
| `S2` | SQLite `LocalBackend` |

Оба backend получают одинаковый corpus, одинаковые titles, summaries, tags,
status и source_file.

## Запросы

20 frozen queries:

- 8 точных совпадений;
- 4 переформулированных запроса;
- 4 запроса без результата;
- 4 неоднозначных запроса.

Каждый query имеет список `expected_fact_ids`.

## Матрица запусков

`20 queries × 2 backends × 5 repeats = 200 retrieval runs`.

## Метрики

- precision;
- recall;
- false positive rate;
- deterministic order;
- p50/p95 latency;
- token size of returned result;
- фильтрация `deprecated`, tags и status.

## Интерпретация

- одинаковые precision/recall и latency: Markdown достаточен для текущего
  размера corpus;
- SQLite лучше по фильтрам/ranking/provenance: SQLite оправдан как
  структурированный retrieval backend;
- SQLite быстрее, но качество одинаковое: преимущество инфраструктурное;
- Markdown лучше по качеству: текущий SQLite ranking нужно исправить до
  продуктовых выводов.

Storage result не отвечает на вопрос, применяет ли модель найденное знание.
