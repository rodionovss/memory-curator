# Memory Curator — Быстрый старт

> Начать использовать сегодня. Без погружения в кишки.

## 0. Установка

```bash
git clone <repo> memory-curator
cd memory-curator
./install.sh          # mac/linux · Windows: install.bat
```

Без вопросов и флагов: скрипт поставит python-пакет и запустит `curator
install`, который сам найдёт opencode и Claude Code на машине и впишет
в них всё: MCP-сервер (тулзы `curator_*`), команды `/curator-*`, три
скилла для настройки и нейронного write-back (`curator-save`,
`mapping-documentation`, `curator-update-docs`) и worker. Перезапусти
opencode / Claude Code — готово.

### Шаг 1 — установи, шаг 2 — настрой

- **Шаг 1.** `./install.sh` — ставит всё, кроме карты.
- **Шаг 2.** Создай карту: `/curator-create-map`, затем `/curator-setup`
  и перезапуск клиента. Без карты `/curator-save` дойдёт до approve и
  остановится с подсказкой «карта не настроена — вызови /curator-setup».

**Как сервер находит карту (приоритет):**

1. env `CURATOR_MAP` — явное указание, всегда главное;
2. `DOCUMENTATION-MAP.md` в корне базы (`CURATOR_BASE_DIR`) — конвенция,
   работает без env: достаточно положить карту в корень базы;
3. нет нигде — сохранение останавливается с подсказкой настроить.
- **Где legacy-база CLI?** — `curator status` (или `/curator-status` в
  opencode). По умолчанию `~/memory-curator`; путь можно было указать при
  установке флагом `--base-dir ПУТЬ`.
- **Сменить legacy-базу** — попроси агента в opencode: «смени базу знаний на
  D:/kb» — агент поправит `CURATOR_BASE_DIR` в конфиге (спросит
  подтверждение) и попросит перезапустить. Руками: env `CURATOR_BASE_DIR`
  в секции `mcp.memory-curator` конфига opencode (или `.mcp.json`
  проекта для Claude Code).

Разработка (тесты): `pip install -e ".[dev]"` — клиенту `[dev]` не нужен.

## 1. Первый запуск (TERMINAL)

```bash
# Тур: полный цикл жизни знания за 1 минуту
# (gatekeeper → write-back → query → improve → телеметрия, всё на изолированной базе)
curator demo            # посмотреть и удалить
curator demo --keep     # оставить файлы для осмотра

# Статус базы / worker
curator status

# Запустить worker daemon (авто-улучшение раз в сутки)
curator start
```

## 2. Команды (появляются после install)

| Команда | Что делает |
|---------|-----------|
| `/curator-save` | Review → выбор человека → нейронный write-back в проектные документы → project-local backend |
| `/curator-create-map` | Построить карту документации проекта и подключить маршрутизацию |
| `/curator-setup` | Привязать MCP, состояние и карту к текущему репозиторию |
| `/curator-status` | Сколько фактов, по типам (с описаниями-словарём) и статусам |
| `/curator-query "kotlin"` | Поиск фактов перед работой |
| `/curator-report` | Статус + топ запросов + improve-лог |
| `/curator-start` / `/curator-stop` / `/curator-worker` | Управление фоновым worker |

Извлечение делает сам агент (он LLM), бэкенд управляет данными —
LLM-вызовов в сервере нет.

## 2а. Куда кладутся знания

Для `/curator-save` source of truth — существующая документация текущего
проекта. Нейронный `curator-update-docs` сначала обновляет разрешённые картой
файлы в их локальном формате. После успешной проверки placement Python пишет
поисковую копию в project-local backend, обычно
`<project>/.curator/knowledge.db`.

Общая база `~/memory-curator`, шаблонные секции, `index.md` и
`session/{type}.md` относятся к legacy CLI/`SyncEngine`/ingest. Успешный
`/curator-save` generic session-файл не создаёт.

## 2б. Карта документации проекта (маршрутизация по темам)

Хочешь, чтобы знания раскладывались не по типам, а по темам проекта
(«архитектура → docs/architecture.md», «стиль → style/…»)? Это делает
**карта документации**. Для `/curator-save` она обязательна: явный
`CURATOR_MAP` или `DOCUMENTATION-MAP.md` в корне базы (шаг 2 установки).

**Проектный флоу:**

1. В opencode открой проект с документацией и набери `/curator-create-map`.
2. Скилл mapping-documentation построит карту: сам спросит границы
   поиска и куда сохранить внутри проекта.
3. Набери `/curator-setup`. Команда настроит project-local MCP, добавит
   `.curator/` в `.gitignore` и свяжет сервер с найденной картой.
4. Полностью перезапусти opencode. `/curator-save` сначала обновляет
   writable-targets карты, затем сохраняет поисковую копию в проектную SQLite.

Итоговая project-local MCP-конфигурация:

```json
{
  "MEMORY_BACKEND": "local",
  "CURATOR_STATE_DIR": "<project>/.curator",
  "CURATOR_BASE_DIR": "<project>",
  "CURATOR_MAP": "<project>/docs/documentation-map.md",
  "ROUTER_CLASS": "curator.routing.map_router.MapRouter"
}
```

`CURATOR_STATE_DIR` хранит SQLite, outbox, логи, usage, reports, реестр типов
и состояние worker. `CURATOR_BASE_DIR` остаётся sandbox-корнем путей карты.
`ROUTER_CLASS` нужен legacy `SyncEngine`; новый `/curator-save` маршрутизирует
нейронный skill и проверяет Python по `CURATOR_MAP`.

Карта — Markdown с YAML-темами:

```yaml
---
topics:
  - name: architecture-and-decisions
    watch_for: Архитектурные решения, границы модулей и их обоснования
    targets:
      - path: docs/architecture/*.md
        captures: [knowledge, rules]
        mode: update
        instructions: Обновляй существующий раздел в локальном формате
---
```

После preview пользователь выбирает `candidate_id`, а не отправляет candidates
повторно. `curator_capture_approve` возвращает неизменяемый manifest и точный
`map_path`. Нейронный skill `curator-update-docs` до первой правки выбирает
маршруты для всего набора по `watch_for`, `captures`, `mode` и `instructions`, делает
смысловые патчи и передаёт placements в `curator_capture_complete`. Python
проверяет topic, target, capture и пути; backend обновляется только после
документации. Unmatched, ambiguous и `readonly` останавливают весь набор.

## 2в. Демонстрация заявленного

E2E-сценарий `core/tests/e2e/test_full_lifecycle.py` проверяет новый capture
`review → approve → semantic docs → complete`, query, backend improve,
телеметрию и offline-fallback. Legacy `SyncEngine` и rebuild проверяются
отдельными integration-тестами. Прогон: `pytest tests/e2e/test_full_lifecycle.py -v`.

## 3. Все команды (TERMINAL, legacy-контур)

Терминальные `curator save`, `curator sync`, ingest и demo не являются
эквивалентом `/curator-save`: они сохраняют старый CLI/`SyncEngine` flow и не
запускают `curator-update-docs`.

| Команда | Что делает |
|---------|-----------|
| `curator start` | Запустить worker daemon в фоне |
| `curator stop` | Остановить worker |
| `curator status` | Worker жив? Фактов в базе? Последний improve? |
| `curator report` | Сводка за всё время: топ запросов, improve события, забытые факты |
| `curator report -d 3` | Сводка за последние 3 дня |
| `curator save` | Кандидаты (JSON из stdin, извлекает агент) → gatekeeper → подтверждение → сохранить |
| `curator save -y` | То же без подтверждения (скрипты/бенчмарки) |
| `curator get "kotlin"` | Поиск фактов |
| `curator improve` | Ручной запуск improve цикла |
| `curator routes` | Правила маршрутизации фактов по папкам |
| `curator sync` | Пуш offline-outbox в xmemory (после восстановления сети) |
| `curator install` | Установка без вопросов: автодетект opencode / Claude Code (флаги `--opencode/--claude/--base-dir` — только для скриптов) |
| `curator demo` | Тур: полный жизненный цикл знания на изолированной базе (для быстрой проверки) |

## 4. План на 2 недели

| Когда | Что делать | Команда |
|-------|-----------|---------|
| **Сегодня** | Запустить worker | `curator start` |
| **В течение дня** | Сохранять знания из сессий | `/curator-save` в OpenCode |
| **Перед задачей** | Поискать релевантные правила | `/curator-query "kotlin"` |
| **Раз в 3 дня** | Проверить что улучшается | `curator report -d 3` |
| **Пятница** | Итоги недели | `curator report` |
| **Перед демкой** | Полный отчёт за 2 недели | `curator report` |

Worker делает всё в фоне. Ты только смотришь `curator report` когда удобно.

## 5. Что происходит в фоне (автономно)

Раз в сутки worker просыпается и:

1. **Дубликаты** — находит → consolidation (с eval-проверкой)
2. **Устаревшие** — hypothesis → deprecation (с eval-проверкой)
3. **Противоречия** — детект + авто-разрешение (verified > hypothesis > deprecated)
4. **Телеметрия** — usage-статистика (`curator report`, `/curator-report`):
   какие знания читают, какие забыты — совет человеку, автоматика не казнит
   (таймерного decay нет: время не делает факт ложным)
5. **Observability** — JSONL запись всех действий с метриками до/после

Интервал: `IMPROVE_INTERVAL_MINUTES` (default: 1440 = сутки).

## 6. Конфигурация

```bash
# Локальный бэкенд (SQLite) — для разработки
export MEMORY_BACKEND=local

# Все служебные файлы в одном каталоге
export CURATOR_STATE_DIR=/path/to/project/.curator

# Корень semantic write-back; карта для /curator-save ищется цепочкой:
# CURATOR_MAP (явно) → $CURATOR_BASE_DIR/DOCUMENTATION-MAP.md (конвенция)
export CURATOR_BASE_DIR=/path/to/project
export CURATOR_MAP=/path/to/project/docs/documentation-map.md

# xmemory бэкенд — для прода
export MEMORY_BACKEND=xmemory
export XMEMORY_API_KEY=<your-key>
export XMEMORY_INSTANCE_ID=<your-instance-id>

# Интервал improve (минуты)
export IMPROVE_INTERVAL_MINUTES=1440  # сутки
```

## 7. Где что лежит

| Что | Где |
|-----|-----|
| `curator` CLI | `.venv/bin/curator` |
| Worker лог | `$CURATOR_STATE_DIR/worker.log` |
| Offline-outbox | `$CURATOR_STATE_DIR/outbox.db` |
| Improve-лог | `$CURATOR_STATE_DIR/improve_events.jsonl` |
| Usage-статистика | `$CURATOR_STATE_DIR/usage.json` |
| Worker отчёты | `$CURATOR_STATE_DIR/reports/improve_*.json` |
| База SQLite (local) | `$CURATOR_STATE_DIR/knowledge.db` |

Если `CURATOR_STATE_DIR` не задан, используется `~/.curator`.
