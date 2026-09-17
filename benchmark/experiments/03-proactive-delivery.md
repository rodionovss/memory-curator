# Experiment 03: Proactive Delivery

## Вопрос

Помогает ли автоматическая карточка и умеет ли текущий retriever выбрать
правильную карточку без ручного участия?

Эксперимент состоит из двух независимых частей, потому что иначе нельзя
отделить пользу карточки от качества retrieval.

## Part A: Oracle card

Использовать правильную карточку из `expected_fact_id`. Вызова SQLite
retriever нет.

### Варианты

| ID | Что получает модель |
|---|---|
| `O0` | Текущий routing/access path без карточки |
| `O1` | Та же сессия + правильная карточка в первом содержательном user turn |

Матрица: `8 tasks × 2 variants × 3 repeats × 2 models = 96 runs`.

### Метрики

- application rate;
- false application rate на control tasks;
- token overhead карточки;
- latency добавления карточки.

### Интерпретация

- O1 > O0: явная доставка правильного факта полезна.
- O1 ≈ O0: карточки не меняют поведение модели на этом corpus.
- O1 хуже O0 на control tasks: карточка вызывает false application.

## Part B: Real retriever

Использовать реальный путь:

```text
task text -> curator_context -> SQLite ranking -> threshold -> card
```

### Варианты

| ID | Что получает модель |
|---|---|
| `Q0` | Текущий access path без proactive card |
| `Q1` | Реальная карточка, выбранная `curator_context` |

Матрица: `8 tasks × 2 variants × 3 repeats × 2 models = 96 runs`.

### Метрики

- `retrieval_precision`: выбранный факт совпал с expected fact;
- `retrieval_recall`: expected fact был среди кандидатов;
- `application_rate` при найденном правильном факте;
- `noise_rate`;
- token overhead;
- retrieval latency.

### Интерпретация

- O1 > O0, но Q1 ≈ Q0: карточки полезны, retriever выбирает плохо.
- O1 > O0 и Q1 > Q0: proactive delivery работает end-to-end.
- O1 ≈ O0: улучшать retriever преждевременно, сначала проверить corpus и
  формат фактов.

## Правило первого сообщения

Карточка добавляется после получения первого содержательного user message и
до генерации первого ответа. Если trigger пустой и карточка не выбрана,
записывается `silent_delivery`; это не считается failure.

Не делать query до появления темы задачи: без trigger невозможно выбрать
релевантное знание, а prewarm последних фактов загрязняет context.
