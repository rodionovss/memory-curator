# Re-run экспериментов с retrieval v2 (routes + query expansion, threshold 0.40)

Дата: 2026-09-17. Ветка: `feature/knowledge-routes-retrieval-v2`.

Контекст: Task 7 (route-aware candidates) + Task 8 (query_aliases, threshold 0.40)
изменили `curator.delivery.fetch_context`. Re-run против замороженных baseline-ов
(Tasks 8/11 плана knowledge-routes/retrieval-v2). Исходные артефакты экспериментов
03/04 не тронуты (флаги `--out-dir`/`--results-dir`).

## 04-storage re-run (20 замороженных запросов × 2 backend × 5 повторов)

| Метрика | baseline (S2 v1) | re-run (S2 v2) | Критерий |
|---|---|---|---|
| recall | 0.312 | **0.375** | > baseline ✅ |
| precision | 1.0 | 1.0 | высокий ✅ |
| deprecated leak | 0.0 | 0.0 | 0 ✅ |
| no-result FP | 0.0 | 0.0 | ✅ |
| deterministic | true | true | ✅ |

Артефакт: `04-storage/summary.json` (S1 без изменений: recall 1.0/precision 0.696 —
naive scan не менялся).

## 03-proactive-delivery re-run (рука Q1: реальный retriever, routing R3)

Матрица: 8 задач × Q1 × strong+weak × 3 повтора = 48 прогонов.

| Метрика | baseline Q1 (эксперимент 03) | re-run Q1 v2 |
|---|---|---|
| delivery rate | 6/48 (12.5%) | 6/48 (12.5%) — без изменений |
| silent | 42/48 | 42/48 |
| application strong | — | **24/24** |
| application weak | — | 18/24 |
| false application | 0 | 0 ✅ (weak-контроль без регрессии) |

Карточки приходят только на T06 (6/6 прогонов); остальные триггеры молчат.

## Выводы

- **Гейты Tasks 8/11 по retrieval пройдены**: recall 0.312 → 0.375 на замороженных
  storage-запросах при precision 1.0 и leak 0; threshold 0.40 подтверждён полным
  прогоном (совпадает со sweep из Task 8).
- **Delivery rate на 8 задачных триггерах не вырос** (12.5%): рост recall на
  storage-запросах не транслируется в доставку на формулировках задач эксперимента 03.
  Критерий «delivery rate информативен для live A/B» — **не выполнен** на замороженном
  corpus.
- Live A/B (Task 12) на таком corpus-уровне доставки неинформативен. План сам
  предписывает: сначала shadow-телеметрия на реальных сессиях (Task 10),
  A/B — только по её данным. Реальная delivery rate на живых сессиях — открытый
  вопрос, ответ даёт shadow mode.
- Опция Task 9 (semantic candidates) не запускалась: lexical retrieval прошёл
  пороговые гейты (условие Task 9 не наступило); повторное молчание 7/8 триггеров —
  аргумент «за» semantic, но решение о его разработке принимается по shadow-данным,
  не по этим 8 синтетическим триггерам.
