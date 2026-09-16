---
type: Spec
project: Memory Curator
date: 2026-08-22
status: draft
---

# Spec: Memory Curator — Self-Improving Knowledge Base Agent

## Overview

Memory Curator — агент, который строит структурированный граф знаний над базой .md файлов (личной или проектной), обеспечивает целостность через принудительную валидацию схемы и сам улучшается с каждой итерацией.

.md файлы остаются source of truth. xmemory/memory backend — queryable structured index поверх.

---

## 1. Проблема и мотивация

См. [Decision Log](decision-log.md), раздел 1.

---

## 2. Use Cases

### UC1: Инициализация (Ingest)

Curator парсит существующие .md файлы, извлекает факты, сохраняет в xmemory с валидацией по схеме.

**Input:** директория `learnings/` (или любая указанная)
**Output:** xmemory population, .md файлы НЕ меняются (read-only ingest)

### UC2: Сохранение из сессии

Пользователь вызывает `/curator-save` (в OpenCode или Claude Code). Curator:
1. Сам агент (он LLM) извлекает из текущей сессии проверенные знания по правилам (extraction-rules / карта проекта) — кандидаты
2. Self-review: агент вызывает `curator_query` и убирает уже известные факты
3. Передаёт кандидатов в MCP-тул `curator_session_capture(candidates)` — LLM-вызова в бэкенде нет
4. Gatekeeper фильтрует: абстрактное? проверенное? не дубликат?
5. Сервер возвращает preview (одобренные/отклонённые с причинами)
6. После approve: запись в xmemory (или fallback) + write-back в .md

**Input:** candidates (JSON-массив фактов от агента)
**Output:** новые/обновлённые факты в памяти + обновлённый .md файл

### UC3: Запрос знаний (Query)

Агент запрашивает: «какие проверенные правила по JVM?», «с чем связано правило X?», «есть ли противоречия?»

**Input:** естественно-языковой запрос или structured query
**Output:** структурированный список фактов со связями

### UC4: Автономное улучшение (Improve Loop)

Раз в N часов/дней cron worker запускает:
1. Консолидация: поиск дубликатов → предложение объединения
2. Устаревание — семантическое: hypothesis-факты → deprecated (eval-гейт);
   таймерного decay по неиспользованию нет — время не делает факт ложным,
   телеметрия использования остаётся observability для человека
3. Schema evolution: xmemory анализирует read-запросы → предлагает расширение схемы
4. Обратная связь по использованию: какие факты реально использовались → повышение приоритета

**Input:** текущее состояние xmemory
**Output:** предложения по улучшению (consolidation, deprecation, schema changes)

### UC5: Двусторонняя синхронизация

Curator держит .md файлы и xmemory в sync:
- Новый факт (через UC2) → обновляет соответствующий .md файл
- Изменение .md файла (человек вручную) → переиндексирует затронутые факты
- Удаление факта (через консолидацию) → обновляет .md (помечает как устаревший или удаляет секцию)

### UC6: Отказоустойчивость (Fallback)

При недоступности xmemory (сеть/VPN/5xx) → автоматический переход на локальный
SQLite backend (`~/.curator/knowledge.db`): записи идут локально + ставятся в
offline-outbox (`~/.curator/outbox.db`), чтения деградируют на локальную базу.
При восстановлении: `curator sync` пушит outbox в xmemory — идемпотентно по
title, ретраи по записям. 4xx — ошибка запроса, деградации нет.

---

## 3. Архитектура

```
┌──────────────────────────────────────────────┐
│            .md files (Git-tracked)           │
│   reference/*.md   style/*.md   tools/*.md   │
│   project specs   playbooks   docs           │
└────────────────────┬─────────────────────────┘
                     │ двусторонняя синхронизация
┌────────────────────▼─────────────────────────┐
│        Агент (opencode / любой MCP-клиент)   │
│  Извлекает кандидатов из сессии (он сам LLM) │
│  + self-review через curator_query           │
└────────────────────┬─────────────────────────┘
                     │ candidates (готовые факты)
┌────────────────────▼─────────────────────────┐
│              Curator Agent (Python)          │
│                                              │
│  ┌──────────┐  ┌──────────┐  ┌────────────┐ │
│  │ Ingest   │  │Gatekeeper│  │ Sync Engine│ │
│  │ .md→facts│  │ filter   │  │ md↔memory  │ │
│  └──────────┘  └──────────┘  └────────────┘ │
│  ┌──────────┐  ┌──────────┐  ┌────────────┐ │
│  │ Outbox   │  │Improve   │  │ CLI + MCP  │ │
│  │ (offline)│  │ Loop     │  │ candidates │ │
│  └──────────┘  └──────────┘  └────────────┘ │
└────────────────────┬─────────────────────────┘
                     │ Memory Backend Interface (Protocol)
          ┌──────────┴──────────┐
          ▼                     ▼
   ┌─────────────┐     ┌──────────────────┐
   │   Primary   │     │     Fallback      │
   │   xmemory   │     │ SQLite (LocalBackend │
   │   (REST)    │     │ + offline-outbox) │
   └─────────────┘     └──────────────────┘
```

### Компоненты

| Компонент | Ответственность | Кто предоставляет |
|-----------|-----------------|-------------------|
| **Memory Backend Interface** | Абстрактный протокол: store_fact, query_facts, get_relations, get_graph | Пишем (Python Protocol) |
| **xmemory Backend** | Schema-enforced storage + query через REST | xmemory (SaaS) |
| **LocalBackend (SQLite)** | То же самое, локально: персистентный файл + offline-outbox | Пишем |
| **Curator: Ingest** | Парсинг .md → список фактов (детерминированный regex-парсер) | Пишем |
| **Curator: Gatekeeper** | Фильтрация фактов: абстрактность, проверенность, dedup | Пишем |
| **Извлечение из сессий** | Сам агент (opencode/скилл) — вне ядра, передаёт candidates | Скилл-слой |
| **Curator: Sync Engine** | Write-back фактов в .md | Пишем |
| **Curator: Improve Loop** | Консолидация, поиск устаревших, обратная связь по использованию | Пишем (cron/worker.py) |
| **MCP Server + CLI** | Единый контракт candidates для opencode/Claude Code и терминала | Пишем (Python MCP) |

### Memory Backend Interface

```python
class MemoryBackend(Protocol):
    """Агностик к провайдеру. xmemory, LocalBackend (SQLite)."""

    def store_fact(self, fact: StructuredFact) -> Result[FactRef]:
        """Сохранить валидированный факт."""
        ...

    def query_facts(self, query: FactQuery) -> list[StructuredFact]:
        """Найти факты по фильтрам: type, tags, status."""
        ...

    def get_relations(self, fact_id: str) -> list[Relation]:
        """Все связи факта."""
        ...

    def get_graph(self) -> GraphData:
        """Весь граф для визуализации."""
        ...

    def health_check(self) -> bool:
        """Жив ли бэкенд."""
        ...
```

### Data Models

> Актуальные модели — `core/curator/models.py`. Связи (Relation, GraphData) —
> отдельные структуры, часть контракта MemoryBackend.

```python
@dataclass
class StructuredFact:
    type: Literal["Reference", "Style", "Tool", "Spec"]
    title: str                    # required, natural key
    tags: list[str]              # required
    status: Literal["verified", "hypothesis", "deprecated"]  # required
    content_summary: str          # краткое описание (не полный текст!)
    source_file: str | None       # путь к .md файлу
    source_session: str | None    # из какой сессии (если из сессии)
```

### XMD Schema (для xmemory backend)

```yaml
xmd_version: v1
title: Knowledge Base

objects:
  Reference:
    description: Проверенное техническое знание — факт, правило, паттерн.
    fields:
      title:         { type: str, required: true }
      tags:          { type: str, required: true }        # comma-separated
      status:        { type: str, required: true, enum: [verified, hypothesis, deprecated] }
      content_summary: { type: str, required: true }
      source_file:   { type: str, required: false }
      source_session: { type: str, required: false }
    primary_key: [title]

  Style:
    description: Правило стиля — соглашение, принцип, предпочтение.
    fields:
      title:         { type: str, required: true }
      tags:          { type: str, required: true }        # comma-separated
      status:        { type: str, required: true, enum: [verified, hypothesis, deprecated] }
      content_summary: { type: str, required: true }
      source_file:   { type: str, required: false }
      source_session: { type: str, required: false }
    primary_key: [title]

relations:
  reference_links:
    description: Связь между двумя Reference-фактами.
    objects:
      source:  { type: Reference, on_delete: cascade }
      target:  { type: Reference, on_delete: cascade }
    keys:
      one_link_per_pair: [source, target]

  reference_contradicts:
    description: Один Reference-факт противоречит другому.
    objects:
      source:  { type: Reference, on_delete: cascade }
      target:  { type: Reference, on_delete: cascade }
    keys:
      one_contradiction_per_pair: [source, target]
```

---

## 4. Data Flow: Session Capture (UC2)

```
┌─────────────────────────┐
│ Пользователь в агенте   │
│ (OpenCode и др.)         │
│ /curator-save           │
└───────────┬─────────────┘
            ▼
┌─────────────────────────┐
│ Агент (LLM)             │
│ 1. Извлекает кандидатов │
│    из текущей сессии    │
│ 2. Self-review:         │
│    curator_query →      │
│    убирает известное    │
└───────────┬─────────────┘
            │ candidates (JSON)
            ▼
┌─────────────────────────┐
│ MCP Server (Python)     │
│ curator_session_capture │
│ (LLM-вызовов нет)       │
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│ Gatekeeper              │
│                         │
│ Для каждого факта:      │
│ • Абстрактное? (не      │
│   фичевая деталь)       │
│ • Проверенное? (не      │
│   гипотеза)             │
│ • Не дубликат?          │
│                         │
│ Возвращает preview:    │
│ approved / rejected     │
└───────────┬─────────────┘
            │ approve (auto_approve)
            ▼
┌─────────────────────────┐
│ Memory Backend          │
│ → store_fact(fact)      │
│ (xmemory или offline:   │
│  SQLite + outbox)       │
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│ Sync Engine             │
│ → write-back в .md      │
│ (дописывает секцию или  │
│  обновляет существ.)    │
└─────────────────────────┘
```

---

## 5. Data Flow: Improve Loop (UC4)

```
┌──────────────────────────────┐
│ Cron worker (worker.py)      │
│ Запуск: раз в N часов        │
└───────────┬──────────────────┘
            │
            ▼
┌──────────────────────────────┐
│ Consolidation                │
│ • Запрос к xmemory: find     │
│   similar facts              │
│ • Группировка по темам       │
│ • Предложение мержа          │
└───────────┬──────────────────┘
            │
            ▼
┌──────────────────────────────┐
│ Поиск устаревших знаний      │
│ • Факты без обращений > N    │
│   дней                       │
│ • Факты status=hypothesis    │
│   старше M дней              │
│ • → предложение deprecation  │
└───────────┬──────────────────┘
            │
            ▼
┌──────────────────────────────┐
│ Schema Evolution (xmemory)   │
│ • Анализ read-запросов       │
│ • Непокрытые поля/объекты    │
│ • → предложение расширения   │
│   схемы                      │
└───────────┬──────────────────┘
            │
            ▼
┌──────────────────────────────┐
│ Обратная связь по            │
│ использованию                │
│ • Какие факты использовались │
│ • Повышение приоритета       │
│ • Неиспользуемые → затухание │
└──────────────────────────────┘
```

---

## 6. Worker Daemon (автономный improve)

Improve-контур запускается через cron worker (`worker.py --daemon`) или однократно (`worker.py`):

```bash
# Разовый прогон
curator-worker

# Демон каждые N минут
IMPROVE_INTERVAL_MINUTES=1440 curator-worker --daemon

# Следить за директорией с .md файлами
curator-worker --watch ~/Documents/AI/personal/learnings/
```

Worker не зависит от агентов (opencode и др.) — работает автономно через нашего MemoryBackend.

### Ingest (внутренний механизм)

Ingest .md файлов — детерминированный (regex, без LLM):
- Ручной запуск через `demo.py` (`run_ingest_demo`) / `ingest_directory()`
- Режим `curator-worker --watch <dir>` — следит за .md и переиндексирует при изменениях
- Авто-ingest при старте сервера нет (watcher-триггер — backlog)

---

## 7. Auto Mode vs Manual Mode

Curator поддерживает два режима, переключаемых через `AUTO_MODE` env/конфиг:

| Режим | Write (сохранение) | Improve | Для кого |
|-------|-------------------|---------|----------|
| `auto_mode: false` (default) | Ручной вызов `/curator-save` + approve для каждого факта | Автономно (cron) | Production, качество важнее скорости |
| `auto_mode: true` | Worker сам сохраняет после каждой сессии, без approve | Автономно | Демка, эксперименты |

`auto_mode` — не просто демо-флаг, а полноценная фича. В будущем gatekeeper можно обучить быть достаточно умным для безопасного auto_mode.

## 8. OpenCode Integration

```json
// ~/.opencode/mcp.json (или .mcp.json в проекте)
{
  "mcpServers": {
    "memory-curator": {
      "command": "curator-mcp-server",
      "env": {
        "MEMORY_BACKEND": "xmemory",
        "AUTO_MODE": "false"
      }
    }
  }
}
```

Доступные тулзы через MCP:
- `curator_session_capture` — принять кандидатов от агента (candidates), gatekeeper, preview, сохранение
- `curator_query` — запросить факты (тип, теги, статус, поиск)
- `curator_status` — статистика: сколько фактов, типов, статусов
- `curator_improve` — запустить консолидацию / поиск устаревших / противоречия
- `curator_feedback` — статистика использования фактов
- `curator_routes` — текущие правила маршрутизации

---

## 9. Scope

### Core (обязательно)
- [x] Memory Backend Interface (Python Protocol)
- [x] xmemory Backend: REST API, store_fact, query_facts, get_relations
- [x] LocalBackend (fallback): персистентный SQLite + :memory: для тестов + health_check
- [x] Контракт candidates: извлечение в слое агента, бэкенд принимает готовые факты
- [x] Gatekeeper: фильтр абстрактности/проверенности/dedup
- [x] Sync Engine: .md → backend (ingest), backend → .md (write-back)
- [x] MCP Server: 8 тулзов (curator_session_capture, curator_capture_approve, curator_capture_complete, curator_query, curator_status, curator_improve, curator_feedback, curator_routes)
- [x] XMD Schema: Reference, Style типы + relations
- [x] Background Worker: cron/daemon для автономного improve loop
- [x] Retrieval Feedback: отслеживание использования фактов
- [x] Eval Runner: gate перед изменениями памяти
- [x] Observability: JSONL лог всех improve-действий
- [x] Contradiction Resolution: автоматическое разрешение через _pick_winner()
- [x] Offline-fallback (UC6): сетевые ошибки → файловая SQLite + outbox, `curator sync`
- [x] Тестовая пирамида: requirements + unit + integration + e2e + smoke (см. `pytest tests/ -q`)
- [x] Fallback: XMemoryBackend → LocalBackend авто, взаимная независимость
- [x] Extraction rules (extraction-rules.yaml — читает агент при извлечении кандидатов)
- [x] Router Protocol: модульная маршрутизация фактов по папкам

### Near-term (сделано)
- [x] Worker: фоновый улучшающий агент (cron)
- [x] Консолидация: поиск дубликатов
- [x] Поиск устаревших знаний
- [x] Router Protocol (модульный роутинг)

### Future
- [ ] Schema evolution (xmemory auto-suggest)
- [ ] Multi-project scoping
- [ ] Интерфейс разрешения конфликтов
- [ ] Общая память для команды
- [ ] Write-back deprecation в .md (improve помечает в БД, .md синк — backlog)
- [ ] Graph HTML-визуализация (вырезана как мёртвый код)

---

## 10. Проверка соответствия требованиям

| Требование | Status | Как |
|-----------|--------|-----|
| «автономно обрабатывает поток задач» | ✅ | UC4 Цикл улучшения: консолидация, поиск устаревших — автономно |
| «с каждой итерацией становится лучше» | ✅ | Schema evolution + обратная связь по использованию |
| «извлекает уроки из результатов» | ✅ | UC2 Сохранение из сессии с gatekeeper |
| «копит опыт» | ✅ | Структурированные факты в xmemory с принудительной валидацией схемы |
| «переиспользует в следующих задачах» | ✅ | UC3 Query: агент запрашивает факты перед работой (например, «какие правила по JVM?») |
| Open-source компоненты + своё | ✅ | свой curator + xmemory |
| Бонус: xmemory | ✅ | Primary backend |
| Рабочее демо | ✅ | Min: UC1 Ingest + UC2 Session Capture + UC3 Query |

---

## 11. Технический стек

| Слой | Технология |
|------|-----------|
| Язык | Python 3.12+ |
| Memory (primary) | xmemory (REST, SaaS) |
| Memory (fallback) | SQLite (LocalBackend) + offline-outbox |
| MCP server | Python MCP SDK (`mcp` package) |
| Извлечение знаний | Сам агент (LLM на стороне opencode / Claude Code, не в бэкенде) |
| Routing | Router Protocol (extensible, DefaultRouter из коробки) |
| Background agent | cron worker (`worker.py --daemon`) |
| .md sync | Git (существующие файлы) |