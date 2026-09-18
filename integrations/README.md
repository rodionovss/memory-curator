# Memory Curator в OpenCode

Установка — `curator install`: копирует оба плагина (реминдер и
proactive delivery) в `~/.config/opencode/plugins/` идемпотентно, не
трогая пользовательские плагины. Обновление плагина — повторный
`curator install`.

Вручную (global):

```bash
cp integrations/curator-context.js ~/.config/opencode/plugins/
```

или project-level: `cp integrations/curator-context.js .opencode/plugins/`.

Перезапусти opencode — готово.

## Как работает (ADR 002, issue #28)

- хук **`chat.message`** — единственный поддерживаемый lifecycle hook:
  вызывается до сохранения сообщения и до генерации ответа (`session/prompt.ts`);
- плагин берёт текст первого сообщения, вызывает CLI-контракт
  `curator context '<текст задачи>'` и добавляет ranked context cards
  в `parts` сообщения — карточки попадают в контекст LLM без ручного
  вызова tool;
- изоляция от storage: плагин знает только CLI и JSON (ADR 002) — смена
  backend его не касается;
- одна доставка на сессию (re-delivery после session.deleted), повторное
  сообщение не шумит;
- ошибки retrieval глушатся: пустой контракт → нет доставки, сессия
  продолжается;
- плагин форвардит id сессии OpenCode в env CLI (`CURATOR_SESSION_ID`) —
  события доставки привязаны к реальной сессии;
- ручной fallback остаётся: `curator get`,
  `curator context '<задача>'`.

## Режимы доставки: off / shadow / inject (Task 10)

Режим читает Python CLI (`curator context`), не плагин — контракт
плагина неизменен: один вызов `curator context` на substantive turn.

| Переменная | Значение | Что делает |
|---|---|---|
| `CURATOR_DELIVERY_MODE` | `off` (default) | пустой контракт `{"cards": []}` без retrieval |
| | `shadow` | retrieval + локальное событие; карточки **не** возвращаются |
| | `inject` | событие + возврат карточек (живая доставка) |
| `CURATOR_SESSION_ID` | id сессии | `session_id` в shadow/inject событиях; форвардит плагин |
| `CURATOR_SHADOW_LOG_PATH` | путь | лог событий; default `~/.curator/delivery-shadow.jsonl` |

Опечатка в режиме (`banana`) → безопасный `off`. Retrieval в
shadow/inject идёт с `feedback=None`: proactive доставка не считается
ручным доступом и не пишется в usage-телеметрию.

Lifecycle: в shadow CLI всегда возвращает пустой контракт — гард
one-delivery-per-session не срабатывает, и каждый substantive turn
наблюдается. В inject плагин помечает сессию delivered только после
реального добавления карточки — повторные обороты не дублируют вызовы.

### Локальный shadow-лог (только локально)

Формат — JSONL, одна строка на вызов:

```json
{"session_id": "ses_...", "trigger_hash": "sha256...", "mode": "shadow",
 "candidate_titles": ["Не оборачивай suspend DAO в withContext"],
 "scores": [0.62], "delivered": false, "silent": false, "latency_ms": 12,
 "source_files": ["reference/coroutines.md"]}
```

- кандидаты идентифицируются по `title` (natural key) — row id из базы
  в события не попадают;
- `silent: true` — retrieval ничего не нашёл; `delivered` — факт
  возврата карточек (`inject`); `latency_ms` — время retrieval;
- **приватность**: сырой промпт не персистится никогда — только
  SHA-256 хэш (`trigger_hash`);
- запись под файловым локом; ротация при 10 MB — активный файл
  переименовывается с суффиксом-таймстампом
  (`delivery-shadow.20260917T101500.jsonl`);
- лог локальный: не коммитить в shared repository.

Shadow-данные — наблюдение за тем, что proactive delivery *мог бы*
доставить в реальных сессиях. Это не доказательство, что доставка
улучшает применение знаний; live A/B включать только после сбора
shadow-данных.

## Каталог маршрутов: pointer в rules-файле (placement M2)

Каталог маршрутов `<база знаний>/knowledge-routes.md` живёт в базе и
читается агентом по требованию. `curator install` ставит короткую
pointer-секцию в глобальный AGENTS.md (OpenCode) и `~/.claude/CLAUDE.md`
(Claude Code): абсолютный путь каталога, инструкция «сначала прочти
каталог (разделы When to use), затем указанный исходник» и hint
регенерации. Контент каталога в rules-файл не попадает.

Каталог генерируется из фактов базы командой:

```bash
curator knowledge-routes --write
```

`--write` записывает каталог и обновляет pointer-секции во всех
обнаруженных харнесах; `--check` только сверяет файл с текущими
фактами, ничего не меняя. Если файла при установке ещё нет — pointer
всё равно ставится: hint регенерации входит в его текст. Решение о
placement (pointer вместо предзагрузки) — эксперимент 05, см.
[ADR 003](../design/decisions/003-delivery-decision.md).
