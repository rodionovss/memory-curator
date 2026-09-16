---
name: curator-save-experiment
description: Current candidate extraction flow for comparing curator-save versions. Uses the current human-approved save protocol.
---

# Curator Save Experiment

Это текущая candidate-версия extraction (`0.2.0-candidate`). Используй её для
A/B-сравнения с `curator-save-original`, а не как молчаливую замену обычного
`curator-save`.

## Extraction

Сначала прочитай `../curator-save/playbook.md` (относительно каталога этого
skill) и выполни его правила. В частности, сохраняй только выводы, которые
прошли проверки:

1. Изменение понимания - найдено правило, причина, риск или урок, а не описание
   сделанной правки.
2. Evidence - конкретный фрагмент сессии подтверждает вывод.
3. Переносимость - summary не зависит от файла, пути, PR, версии или текущего
   проекта, если сессия явно не сформулировала общий принцип.
4. Атомарность - один кандидат содержит одну идею.
5. Тип утверждения - проверенный факт, стиль, инструментальный совет или
   спецификация, но не гипотеза.

Затем вызови `curator_status`, выбери тип по описанию, вызови `curator_query`,
убери дубликаты и передай candidates в `curator_session_capture` без
`auto_approve` и `source_file`. Покажи preview и через `question` запроси все,
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

После выбора вызови `curator_capture_approve` только с `capture_id` и выбранными
ID. Если approval вернул `status=update_project_docs` и
`next_action=curator-update-docs`, загрузи `curator-update-docs` и следуй его
manifest. Успех сообщай только после `curator_capture_complete` со
`status=completed`. При отказе не вызывай save/write-back.

## A/B logging

Переиспользуй `comparison_id` из текущей сессии или создай новый и покажи его
пользователю. После preview и решения запиши локальный run record в
`benchmark/extraction/local/runs/` через `benchmark/extraction/run_log.py`.
Используй `schema_version=2`, `skill_version=0.2.0-candidate` и commit текущей
ветки из `git rev-parse HEAD`. В каждой prediction обязательно сохрани
`evidence`. Record должен содержать version, skill_version, skill_commit,
comparison_id, session_id, predictions, decision, selected_candidate_ids и
rejection_reasons. Не записывай transcript.
