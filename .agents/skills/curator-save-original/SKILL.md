---
name: curator-save-original
description: Baseline extraction flow for comparing curator-save versions. Uses the current human-approved save protocol.
---

# Curator Save Original

Это immutable baseline extraction-поведение `curator-save` до candidate
playbook. Используй его только для A/B-сравнения с `curator-save-experiment`.

## Extraction

1. Извлеки проверенные устойчивые знания. Для каждого подготовь `type`,
   однострочный `title` длиной не менее 10 знаков, `content_summary`, `tags` и
   `evidence`.
2. Вызови `curator_status`, выбери тип по его описанию, затем вызови
   `curator_query` и убери уже известные факты.
3. Передай кандидатов в `curator_session_capture` без `auto_approve` и
   `source_file`.
4. Покажи `eligible` и `rejected`, через `question` попроси выбрать все,
   отдельные `candidate_id` или отказ.

## Preview contract

Показывай candidates нумерованным списком:

```text
1. Название знания
Type: Reference
Rule: ...
Why: ...
Evidence: ...
Tags: ...
```

`Rule` и `Why` - сохраняемый смысл. `Evidence` - только локальное подтверждение
для review и evaluation, не сохраняй его в общем знании. `Tags` - поисковые
ключи, а не отдельное знание.

## Save

После выбора вызови `curator_capture_approve` с `capture_id` и выбранными
ID. Не отправляй candidates повторно. Если approval вернул
`status=update_project_docs` и `next_action=curator-update-docs`, загрузи
`curator-update-docs` и следуй его manifest. Успех сообщай только после
`curator_capture_complete` со `status=completed`.

При отказе не вызывай save/write-back и не сообщай, что данные сохранены.

## A/B logging

Для сравнения создай или продолжи `comparison_id` в текущей сессии. В начале
покажи пользователю версию `original` и этот ID. После preview и решения запиши
локальный run record в `benchmark/extraction/local/runs/` через
`benchmark/extraction/run_log.py`. Record должен содержать version, skill_version,
skill_commit, comparison_id, session_id, predictions, decision,
selected_candidate_ids и rejection_reasons. Не записывай transcript.
