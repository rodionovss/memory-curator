# Extraction Eval

Этот eval проверяет не хранение фактов, а качество выбора знаний моделью через
`curator-save`.

```text
транскрипт сессии -> curator-save -> candidates -> разметка качества
```

Текущий `core/curator/eval_runner.py` решает другую задачу: проверяет изменения
уже сохранённой базы. Этот каталог измеряет extraction до записи в базу.

## Данные

Приватные транскрипты и рабочие разметки хранятся только в
`benchmark/extraction/local/`, который игнорируется Git. В репозитории лежат
только схема, evaluator и полностью анонимный smoke-набор.

Corpus имеет форму:

```json
{
  "sessions": [
    {
      "id": "session-1",
      "transcript": "анонимизированный текст или локальная копия",
      "gold": [
        {
          "id": "knowledge-1",
          "type": "Reference",
          "title": "Переносимое правило",
          "summary": "Что можно применить в другой задаче.",
          "evidence": "Фрагмент, подтверждающий вывод",
          "scope": "общий scope",
          "should_save": true
        }
      ]
    }
  ]
}
```

Полная JSON Schema находится в `schema.json`. `should_save=false` нужен для
явных negative-примеров: детали конкретной фичи, гипотезы, дубли и прочий
task residue.

Predictions - массив существующих `curator_session_capture` candidates с
обязательным `session_id`. Для точного сопоставления можно добавить
evaluation-only поле `gold_id`; production-контракт от этого не меняется.
Качество, которое нельзя определить детерминированно, размечается вручную в
`evaluation`:

```json
{
  "session_id": "session-1",
  "title": "Переносимое правило",
  "content_summary": "...",
  "evidence": "...",
  "gold_id": "knowledge-1",
  "evaluation": {
    "evidence_supported": true,
    "abstract": true,
    "atomic": true,
    "labels": []
  }
}
```

## Метрики

- `precision` - matched positive candidates / all predictions.
- `recall` - matched positive candidates / all positive gold items.
- `evidence_support_rate` - доля matched candidates с поддержанным evidence.
- `abstraction_rate` - доля matched candidates, переносимых за пределы задачи.
- `atomicity_rate` - доля matched candidates с одной идеей.
- `noise_rate` - доля predictions с явными error labels.
- В конце отчёта error labels сгруппированы по типам, чтобы видеть профиль
  ошибок, а не только aggregate-метрики.

Python намеренно не пытается сам решать, абстрактно ли знание или подтверждает
ли его evidence: эти свойства размечаются вручную в `evaluation`.

## Smoke eval

```bash
python3 benchmark/extraction/run_eval.py \
  --gold benchmark/extraction/fixtures/smoke_gold.json \
  --predictions benchmark/extraction/fixtures/smoke_predictions.json \
  --report benchmark/extraction/results/smoke-report.md
```

Smoke-набор проверяет только harness. Он не является оценкой текущей модели.

## Реальный baseline

1. Выбрать сбалансированный development set и holdout set через локальный
   `list_opencode_sessions`: coding, debugging, review, architecture,
   documentation, workflow.
2. Экспортировать полные тексты локально через `read_opencode_session`.
3. Заполнить для каждой сессии `ANNOTATION-TEMPLATE.json`: positive knowledge,
   evidence span, type, scope и negative examples.
4. Запустить неизменённый `curator-save` на тех же транскриптах и сохранить
   predictions только в `local/`.
5. Для каждого кандидата отметить error labels:
   `task_residue`, `hypothesis`, `weak_evidence`, `wrong_scope`, `duplicate`,
   `compound_fact` или `missed_knowledge`.
6. Запустить evaluator на development set. Только после выбора изменения
   skill прогнать holdout.

Для воспроизводимости фиксируются дата, модель, версия skill и условия запуска.
До реального baseline нельзя утверждать, что extraction улучшился.

## Текущий development baseline

На локальном development-наборе из 6 сессий и 17 кандидатов для baseline
получено:

- precision: 58.8% (10 matched candidates);
- recall: 71.4% (4 positive gold items missed);
- noise labels: 41.2% кандидатов получили хотя бы одну ошибку.

Первая строгая версия skill на том же наборе дала 100% precision, 64.3% recall
и 0% noise: она переотсекала переносимые protocol/routing-принципы. Поэтому
эта версия не принята как окончательное улучшение. Следующая версия разрешает
обобщение локального эпизода только при явно сформулированных в сессии
правиле, причине, риске или уроке; её нужно прогнать отдельно.

Набор и транскрипты находятся в игнорируемом `local/`. Это controlled
skill-following run с ручной gold-разметкой, а не финальная оценка production
модели. Для вывода о качестве модели нужен holdout-набор и повторяемый запуск
с зафиксированными моделью и prompt conditions.

## Текущий holdout-прогон

После выбора candidate проведён отдельный controlled skill-following run на
трёх независимых локальных сессиях (Compose, Dagger и Kotlin performance), не
входивших в development set. Gold-разметка и predictions находятся только в
`local/holdout-*.json`.

- precision: 100.0% (3 из 3 predictions matched positive gold);
- recall: 100.0% (3 из 3 positive gold items matched);
- evidence support: 100.0%; abstraction: 100.0%; atomicity: 100.0%;
- noise: 0.0%.

Это подтверждает отсутствие ошибок на малом holdout corpus, но не является
достаточным доказательством production-качества: набор содержит три сессии и
не заменяет более широкий blind evaluation с зафиксированной моделью.

## Локальное A/B-сравнение skills

Для ручной проверки доступны две полноценные команды:

```text
/curator-save-original
/curator-save-experiment
```

`original` использует baseline extraction rules из исходного skill, а
`experiment` - текущий candidate playbook. Обе версии используют один и тот же
актуальный протокол `capture -> approve -> curator-update-docs -> complete` и
могут реально сохранять знания после подтверждения.

Для сравнения одной сессии сначала вызови `original`, посмотри preview и
откажись от сохранения. Затем вызови `experiment` с тем же
`comparison_id`, сравни candidates и подтверди только выбранную версию. Обе
команды записывают локальные run records schema v2 в
`benchmark/extraction/local/runs/`; transcript туда не попадает, а `evidence`
сохраняется только для audit/evaluation. Старые records без schema v2
пропускаются comparator-ом и требуют повторного прогона.

Сводный отчёт строится так:

```bash
python3 benchmark/extraction/compare_versions.py \
  --gold benchmark/extraction/local/gold.json \
  --runs benchmark/extraction/local/runs \
  --report benchmark/extraction/local/version-comparison.md
```

Gold-разметка должна быть общей для обеих версий. Только она позволяет
отделить «пользователь выбрал» от объективного ответа, стоило ли сохранять
кандидат и что версия пропустила.
