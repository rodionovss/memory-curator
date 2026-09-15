---
name: curator-save
description: Сохраняет проверенные знания из сессии через Memory Curator. Использовать по явной просьбе («сохрани знания», /curator-save) и предлагать после появления подтверждённого устойчивого знания.
---

# Curator Save

Короткий orchestrator review, human approval и project write-back.

## Процесс

1. Извлеки из сессии проверенные устойчивые знания. Для каждого подготовь
   `type`, однострочный `title` (не короче 10 знаков), `content_summary`, `tags`
   и `evidence`. Вызови `curator_status` и сверяй типы с их описаниями.
   Неизвестный тип предложи зарегистрировать отдельным вопросом; после согласия
   добавь `new_type: true` и `type_description`.
2. Вызови `curator_query` по релевантным ключевым словам и убери уже известные
   факты. Передай оставшиеся `candidates` в `curator_session_capture`.
3. Из ответа со `status=needs_human_approval` покажи все `eligible` с их
   `candidate_id` и все `rejected` с причинами. Через `question` запроси выбор:
   все eligible, конкретные eligible или отказ.
4. Вызови `curator_capture_approve` с исходным `capture_id` и только выбранными
   `candidate_id`. При отказе передай пустой `selected_candidate_ids` и заверши
   процесс без сообщения о сохранении.
5. Только если ответ approval содержит точные значения
   `status=update_project_docs` и `next_action=curator-update-docs`, загрузи skill
   `curator-update-docs`. Тот же агент продолжает по нему с полным неизменённым
   объектом ответа как manifest. При любом другом ответе остановись.
6. Сообщи о сохранении только после ответа `curator_capture_complete` с точным
   `status=completed`; перечисли его `documents`.

Карту и target-документы здесь не читай, маршруты не выбирай и файлы не меняй.
