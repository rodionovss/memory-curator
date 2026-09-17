# Experiment 01: Routing Format

## Вопрос

Какой формат лучше объясняет агенту, когда и где искать знание:
текущий Personal Setup, структурированный `AGENTS.md` или skill trigger?

Этот эксперимент не проверяет SQLite и proactive cards. Все варианты имеют
одинаковый набор source files, но не имеют доступа к `curator_query/get`.

## Варианты

| ID | Контекст модели |
|---|---|
| `R0` | Только task prompt, без указателя |
| `R1` | Текущий `PERSONAL_SETUP.md`: общие ссылки и инструкция свериться с базой |
| `R2` | GoldApple-style `AGENTS.md`: topic, trigger, source file, when-to-read |
| `R3` | Skill metadata: name, description, activation conditions, source file |

R1-R3 указывают на один и тот же corpus. Текст самого факта не загружается
до действия модели.

## Corpus и задачи

Использовать 8 synthetic tasks с `task.json`:

| Класс | Количество | Назначение |
|---|---:|---|
| Явный trigger и применимый факт | 2 | базовый routing |
| Скрытый trigger и применимый факт | 2 | проверка понимания смысла |
| Простая на вид задача с применимым фактом | 1 | ошибка классификации «легко» |
| Сложная задача без применимого факта | 1 | не провоцировать лишний поиск |
| Задача без памяти | 2 | false positive control |

Каждая задача содержит `expected_fact_id` или `null` и deterministic check.

## Матрица запусков

`8 tasks × 4 variants × 3 repeats × 2 models = 192 runs`.

## Procedure

1. Создать новую сессию с одним model ID.
2. Подключить ровно один вариант R0-R3.
3. Отправить task prompt без дополнительных пояснений.
4. Разрешить модели только обычные file tools.
5. Сохранить все tool calls, прочитанные пути и финальное состояние fixture.
6. Запустить deterministic check.
7. Сохранить строку результата по `schemas/run.json`.

## Метрики

- `routing_recall` - модель открыла правильный source file на задаче с
  `expected_fact_id`;
- `routing_precision` - модель не пошла за памятью на задаче с `null`;
- `index_follow_rate` - модель прошла по указанному указателю;
- `application_rate` - deterministic check прошёл;
- `unnecessary_reads` - прочитаны нерелевантные файлы;
- `input_tokens` и `tool_calls`.

## Ожидаемый выход

Сравнение R1/R2/R3 отвечает, какой формат стоит использовать в production.
R0 нужен как нижняя граница.

- R2 выше R1: структурированная карта лучше общего Personal Setup.
- R3 выше R2: skill trigger лучше карты.
- R1-R3 одинаковы: формат указателя не является главным ограничением.
- `weak` сильно хуже `strong`: инструкции недостаточно, нужен более
  автоматический retrieval.
