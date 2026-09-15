# Memory Curator — Core

Самообучающийся агент для структурированной базы знаний. Строит граф над `.md` файлами, обеспечивает целостность через enforced схему (xmemory), сам улучшается с каждой итерацией.

## Архитектура

```
Агент (opencode / Claude Code) извлекает знания из сессии
    ↓ candidates (JSON: type, title, content_summary, tags, evidence)
curator_session_capture → gatekeeper.py → preview
    ↓ выбор человека: candidate_id
curator_capture_approve → immutable manifest + CURATOR_MAP
    ↓
нейронный curator-update-docs → смысловые патчи в документацию проекта
    ↓ placements
curator_capture_complete → проверка карты → project-local backend
```

**Ключевое решение:** извлечение знаний делает сам агент (LLM уже есть там),
а Python валидирует кандидатов, фиксирует выбранный набор и проверяет placement.
Документацию в локальном стиле меняет нейронный `curator-update-docs`; только
после этого Python сохраняет поисковую копию в backend. В бэкенде нет
LLM-вызовов.

## Установка

```bash
cd core
python -m venv .venv
.venv/bin/pip install -e .
```

## Запуск

### Локально (без внешних сервисов)
```bash
MEMORY_BACKEND=local curator-mcp-server
```

### С xmemory (требуется API-ключ)
```bash
MEMORY_BACKEND=xmemory XMEMORY_API_KEY=your-key curator-mcp-server
```

## MCP-тулзы

| Тул | Описание |
|-----|----------|
| `curator_session_capture` | Review: проверить кандидатов и вернуть preview с неизменяемыми `candidate_id`; ничего не сохраняет |
| `curator_capture_approve` | Approve: зафиксировать выбранные человеком ID и вернуть manifest для `curator-update-docs` |
| `curator_capture_complete` | Complete: проверить placements по карте и сохранить поисковую копию фактов |
| `curator_query` | Поиск фактов по типу / тегам / статусу / тексту |
| `curator_status` | Статистика: total_facts, by_type, by_status |
| `curator_improve` | Запуск автономного improve: дубликаты + stale + противоречия + eval gate |
| `curator_feedback` | Статистика использования: топ запросов, забытые факты |
| `curator_routes` | Текущие правила маршрутизации фактов по папкам |

## Approval Flow (как работает подтверждение)

1. Агент извлекает кандидатов, вызывает `curator_query` и убирает известное.
2. `curator_session_capture(candidates=[...])` запускает gatekeeper и возвращает `capture_id`, `eligible` и `rejected`. Backend и документы не меняются.
3. Пользователь выбирает все, часть или ни одного `candidate_id`.
4. `curator_capture_approve(capture_id, selected_candidate_ids)` фиксирует выбранный набор. Содержимое candidates повторно не отправляется.
5. При `status=update_project_docs` нейронный skill `curator-update-docs` читает настроенный `CURATOR_MAP`, выбирает writable target по `watch_for`, `captures`, `mode` и `instructions` и сначала меняет документацию проекта.
6. `curator_capture_complete(capture_id, placements)` проверяет размещение по карте и только затем пишет факты с каноническим `source_file` в project-local backend.

Для `/curator-save` карта обязательна: `CURATOR_MAP` должен быть настроен и
указывать на существующий файл. Unmatched, ambiguous и `readonly` останавливают
весь набор; fallback в `session/{type}.md` в этом flow отсутствует. `AUTO_MODE`
не обходит review и human approval.

## CLI и legacy SyncEngine

CLI `curator save`, ingest, demo и `SyncEngine` остаются отдельным legacy-
контуром. Они не используют review/approve/complete и не выполняют нейронный
project write-back. Их шаблонные Curator-секции и default route
`session/{type}.md` не описывают поведение `/curator-save`.

```bash
curator save      # кандидаты (JSON из stdin) → gatekeeper → y/N → БД + .md
curator save -y   # то же без подтверждения (скрипты/бенчмарки)
curator sync      # пуш offline-outbox в xmemory (после восстановления сети)
curator get 'kotlin'
curator status / report / improve / routes / start / stop
```

Пример:
```bash
echo '[{"type":"Reference","title":"...","content_summary":"...","tags":["kotlin"]}]' | curator save -y
```

## Self-review (два уровня)

**Агент (до отправки):** скилл инструктирует вызвать `curator_query` и убрать уже известные факты.
**Бэкенд (gatekeeper, `gatekeeper.py`):** 6 правил на каждого кандидата:
- Длина заголовка (10-200 символов)
- Длина описания (>20)
- Шум-паттерны («поменять цвет», «сдвинуть на 2px»)
- Обязательные теги
- Проверка на дубликаты (Jaccard similarity по title)
- LLM в бэкенде не нужен — валидация детерминированная

## Offline-fallback (UC6)

При недоступности xmemory (сеть/VPN/5xx):
- записи идут в локальную БД (`~/.curator/knowledge.db`) + outbox (`~/.curator/outbox.db`)
- чтения деградируют на локальную БД
- при восстановлении: `curator sync` пушит outbox в xmemory (идемпотентно по title)
- 4xx — ошибка запроса, деградации нет

## Конфигурация

### Extraction rules (правила извлечения — для агента/скилла)
Файл `~/.curator/extraction-rules.yaml` — читает агент при извлечении кандидатов (не бэкенд):
```yaml
focus:
  - "Технические правила и паттерны (kotlin, jvm, compose, android)"
  - "Архитектурные решения и их обоснования"
ignore:
  - "Конкретные баги и их фиксы"
  - "Временные решения и workaround'ы"
```
> Заменяется «картой» Егора (watch_for/targets) — единый конфиг проекта.

### Router Protocol (legacy-маршрутизация)
`curator/routing/interface.py` — контракт маршрутизации для `SyncEngine`, CLI и
ingest. Подключение: `ROUTER_CLASS=your.module.YourRouter`.

`DefaultRouter` сохраняет всё в `session/{type}.md`, но только в legacy-контуре.
В `/curator-save` нейронный `curator-update-docs` работает по обязательному
`CURATOR_MAP`, а Python проверяет заявленные placements.

## Демо-режимы

```bash
.venv/bin/python3 -c "from curator.demo import run_time_lapse; run_time_lapse()"
.venv/bin/python3 -c "from curator.demo import run_ingest_demo; run_ingest_demo()"
.venv/bin/python3 -c "from curator.demo import run_durability_demo; run_durability_demo()"
.venv/bin/python3 -c "from curator.demo import run_opencode_demo; run_opencode_demo(3)"
.venv/bin/python3 -c "from curator.demo import run_demo; run_demo()"
```

## Тесты

```bash
.venv/bin/python -m pytest tests/ -v --ignore=tests/smoke
```

## MCP конфигурация

```json
{
  "mcpServers": {
    "memory-curator": {
      "command": "curator-mcp-server",
      "env": {
        "MEMORY_BACKEND": "local",
        "CURATOR_STATE_DIR": "/path/to/project/.curator",
        "CURATOR_BASE_DIR": "/path/to/project",
        "CURATOR_MAP": "/path/to/project/docs/documentation-map.md"
      }
    }
  }
}
```
