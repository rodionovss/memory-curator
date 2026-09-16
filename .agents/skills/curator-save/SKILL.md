---
name: curator-save
description: Сохраняет проверенные знания из сессии в базу знаний через Memory Curator. Использовать по явной просьбе («сохрани знания», /curator-save) и проактивно, когда в сессии подтверждено абстрактное правило, паттерн или принцип.
---

# Curator Save

Используй этот skill, когда нужно извлечь знания из текущей сессии и сохранить
их через Memory Curator.

## Короткий flow

1. Извлеки только подтверждённые переносимые кандидаты по правилам из
   `playbook.md` и вызови `curator_session_capture`.
2. Покажи preview кандидатов и через `question` попроси выбрать все,
   отдельные `candidate_id` или отказ.
3. Вызови `curator_capture_approve` с выбранными ID. Не отправляй candidates
   повторно и не используй `auto_approve`.
4. Если ответ содержит `status=update_project_docs` и
   `next_action=curator-update-docs`, загрузи `curator-update-docs`.
   Карту и target-документы здесь не читай и не редактируй до запуска этого
   skill.
5. Считай сохранение успешным только после ответа
   `curator_capture_complete` со `status=completed`.

## Preview contract

Показывай candidates нумерованным списком в одном формате:

```text
1. Название знания
Type: Reference
Rule: ...
Why: ...
Evidence: ...
Tags: ...
```

`Rule` и `Why` должны быть понятны без чтения исходной сессии. `Evidence` -
только локальное подтверждение для review и evaluation; не добавляй его в
сохраняемый смысл знания и не сохраняй его в общем знании. `Tags` - поисковые ключи, а не отдельная часть
знания.

Полный workflow находится в `playbook.md` рядом с этим файлом. Прочитай и
выполни его целиком. `SKILL.md` является только точкой входа и не заменяет
playbook.
