# Memory Curator — Быстрый старт

> Начать использовать сегодня. Без погружения в кишки.

> **CLI-only (решение 2026-10-03):** MCP-сервер, worker-демон и
> delivery-плагины удалены; минимизация 2026-11-14 снесла также
> improve-контур и demo. Единственный вход — CLI `curator` + скиллы;
> фоновых процессов нет.

## 0. Установка

```bash
git clone <repo> memory-curator
cd memory-curator
./install.sh          # mac/linux · Windows: install.bat
```

Без вопросов и флагов: скрипт поставит python-пакет и запустит
`curator install`, который сам найдёт opencode и Claude Code на машине
и впишет в них: команды `/curator-*`, три скилла (`curator-save`,
`mapping-documentation`, `curator-update-docs`) и одну секцию правил
памяти. MCP-сервер не ставится, worker не поднимается. Перезапусти
opencode / Claude Code — готово.

Новой установке `curator install` создаёт стартовую базу (`~/memory-curator`)
с дефолтной картой тем — настраивать ничего не обязательно.

- **Где база?** — `curator status`. Приоритет: env `CURATOR_BASE_DIR` →
  `~/.curator/config.json` (пишет install) → `~/memory-curator`.
- **Сменить базу** — запусти `curator install --base-dir ПУТЬ` или
  попроси агента: «смени базу знаний на D:/kb».

Разработка (тесты): `cd core && pip install -e ".[dev]"`.

## 1. Первый запуск (TERMINAL)

```bash
# Статус базы: где база, сколько фактов, capture-сводка
curator status
```

## 2. Команды (появляются после install)

| Команда | Что делает |
|---------|-----------|
| `/curator-save` | Извлечь знания из сессии → показать → подтвердить → сохранить в базу (скилл curator-save, CLI `curator save`) |
| `/curator-create-map` | Построить карту документации проекта и подключить маршрутизацию |
| `/curator-status` | Сколько фактов, по типам и статусам, где база |
| `/curator-query "kotlin"` | Поиск фактов перед работой |

Извлечение делает сам агент (он LLM), CLI управляет данными —
LLM-вызовов в бэкенде нет.

## 2а. Куда кладутся знания

Source of truth — Markdown-файлы базы знаний. `curator save`:

1. gatekeeper валидирует кандидатов и отсекает дубликаты;
2. маршрутизатор выбирает файл по карте тем (теги кандидата ∩ токены
   темы); без карты — дефолт `session/{type}.md`;
3. факты дописываются в `.md` и SQLite, каталог `knowledge-routes.md`
   регенерируется тем же коммитом;
4. git-коммит (локальный, push не выполняется никогда).

Файлы-знания (теория + грабли по теме): модель пишет файл, затем
`curator save --doc <путь>` — проверка пути по карте, коммит, событие
в журнале аналитики.

## 2б. Карта тем (маршрутизация по темам)

Хочешь, чтобы знания раскладывались не в `session/`, а по темам базы
(«kotlin → reference/kotlin.md», «стиль → style/…»)? Это делает **карта
тем** `knowledge-map.md` в корне базы (дефолтная создаётся install'ом;
для проекта построй свою через `/curator-create-map` — скилл
mapping-documentation). Формат — Markdown с YAML-темами:

```yaml
---
topics:
  - name: architecture-and-decisions
    watch_for: архитектура, решение, границы модулей
    targets:
      - path: docs/architecture.md
        captures: [knowledge, rules]
        mode: update
        instructions: Обновляй существующий раздел в локальном формате
---
```

Маршрутизация детерминированная: теги кандидата ∩ токены темы;
`mode: readonly` запрещает запись, `append` не переписывает
существующее. Детали контракта —
[design/knowledge-route-format.md](../design/knowledge-route-format.md).

## 3. Все команды (TERMINAL)

| Команда | Что делает |
|---------|-----------|
| `curator status` | Где база, сколько фактов, capture-сводка |
| `curator save` | Кандидаты (JSON из stdin, извлекает агент) → gatekeeper → подтверждение → сохранить |
| `curator save -y` | То же без подтверждения (скрипты/бенчмарки) |
| `curator save --doc <путь>` | Зафиксировать файл-знание (проверка по карте + коммит) |
| `curator get "kotlin"` | Поиск фактов |
| `curator knowledge-routes --write` | Регенерация каталога маршрутов (после save не нужна — он обновляется сам) |
| `curator install` | Установка без вопросов: автодетект opencode / Claude Code (флаги `--opencode/--claude/--base-dir` — только для скриптов) |

## 4. Ритм использования

| Когда | Что делать | Команда |
|-------|-----------|---------|
| **В течение дня** | Сохранять знания из сессий | `/curator-save` в OpenCode |
| **Перед задачей** | Свериться с базой (агент делает сам по правилам) | `/curator-query "kotlin"` |
| **Иногда** | Проверить сводку | `curator status` |

Аналитика сохранений (предложено/сохранено/отклонено) — в `curator status`
и журнале `analytics.jsonl`; историю базы показывает `git log` базы.

## 5. Конфигурация

```bash
# Все служебные файлы в одном каталоге (default: ~/.curator)
export CURATOR_STATE_DIR=/path/to/.curator

# База знаний: env → ~/.curator/config.json (пишет install) → ~/memory-curator
export CURATOR_BASE_DIR=/path/to/kb

# Карта тем (явное указание; конвенция: knowledge-map.md в корне базы)
export CURATOR_MAP=/path/to/kb/knowledge-map.md
```

## 6. Где что лежит

| Что | Где |
|-----|-----|
| `curator` CLI | `uv tool` / `.venv/bin/curator` |
| База SQLite (картотека дедупа) | `$CURATOR_STATE_DIR/knowledge.db` |
| Журнал аналитики | `$CURATOR_STATE_DIR/analytics.jsonl` |

Сгенерированный каталог маршрутов уровня файла (`knowledge-routes.md`):
контракт формата — [design/knowledge-route-format.md](../design/knowledge-route-format.md).

Placement (M2, [ADR 003](../design/decisions/003-delivery-decision.md)):
каталог живёт в базе; `curator install` публикует в rules-файлы
харнессов одну секцию-указатель, агент читает каталог по требованию.

## 7. История и эксперименты

- Решения и их причины: [decision-log.md](../decision-log.md)
- A/B скиллов curator-save vs save-knowledge завершён 14.11.2026:
  победил curator-save, save-knowledge удалён.
- Эксперименты (routing-формат, placement, extraction eval):
  [benchmark/experiments/](../benchmark/experiments/)
