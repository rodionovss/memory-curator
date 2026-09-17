# Corpus: заморозка эксперимента 01 (routing format)

## Состав

8 задач — замороженная выборка из `benchmark/application` (fixtures и checks
переносятся из оригинального бенчмарка, замороженного до его прогонов:
`benchmark/application/checks/FROZEN-original.sha`).

| Задача | Класс | Ожидаемый факт | Назначение |
|---|---|---|---|
| T01 | hidden_trigger | F72 | «следуй стилю файла» — ловушка withContext |
| T02 | explicit_trigger | F109 | api-doc указывает на путь Retrofit |
| T03 | hidden_trigger | F121 | runtime-падение Dagger — причина не названа |
| T04 | looks_easy_with_rule | F86 | ревью «простого» конструктора |
| T06 | explicit_trigger | F68 | RTL-требование названо в задаче |
| T07 | consensus_task | F6 | решается и без базы (верхняя граница) |
| K1 | no_memory_control | — | ложная навигация в kb не нужна |
| K2 | false_application_control | F72 | исключение правила: withContext обязателен |

Отклонение от плана 01: класс «сложная задача без применимого факта» заменён
на `consensus_task` (T07): в замороженном corpus application-бенчмарка нет
сложной задачи без факта — вместо искусственной новой задачи зафиксирован
честный контролируемый состав из проверенных fixtures.

## Заморозка

- `tasks.json` — маппинг task → fact → check, модели strong/weak.
- `FROZEN.sha` — sha256 tasks.json, variants, kb (проверка перед прогонами):
  `shasum -a 256 -c FROZEN.sha` (из этой директории).
- Факты kb/ переформулированы из замороженных checks: правило = то, что
  check считает верным решением.
- Правки corpus после старта прогонов запрещены; новое правило — новый
  corpus и новая заморозка.

## Изоляция прогонов

- isolated HOME: минимальный opencode config (только model + provider),
  symlink на auth; глобальные AGENTS.md / instructions / mcp / plugins
  не попадают в прогон (детали: `harness/isolate.py`).
- routing-поверхность прогона — только workspace `AGENTS.md` (вариант R0 —
  без файла) + `kb/` в workspace.
