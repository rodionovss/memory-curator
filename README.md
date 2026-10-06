<div align="center">

# Memory Curator

Библиотекарь для базы знаний AI-агента.

Знания из сессий не умирают вместе с чатом: модель пишет, куратор решает
«куда», ловит дубликаты, фиксирует git-коммит и ведёт журнал аналитики.

</div>

> **Статус: stable, build for myself, use it if you want.**
> Работающий инструмент: CLI + скилл curator-save, детерминированные
> проверки (без LLM в бэкенде), оффлайн. История решений -
> [decision-log.md](decision-log.md).

---

## Установка

```bash
git clone https://github.com/rodionovss/memory-curator.git
cd memory-curator
uv tool install --force ./core   # CLI `curator` в PATH
```

Проверка:

```bash
cd core && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest tests/ -q --ignore=tests/smoke   # все зелёные
.venv/bin/curator demo                                      # полный цикл жизни знания
```

База знаний задаётся `CURATOR_BASE_DIR` (по умолчанию
`~/Documents/AI/personal/learnings`).

## Что делает

Контент всегда пишет модель - куратор отвечает за размещение и дисциплину:

- **Карта тем** (`knowledge-map.md`) - единственный рукописный источник
  «тема → файл». Маршрутизация детерминированная: теги кандидата ∩
  токены темы. Каталог `knowledge-routes.md` - генеримая проекция карты
  для навигации (чтение).
- **Карточки**: `curator save --yes` - валидация формата, дедуп
  (совпадение заголовков по словам → отказ с подсказкой), маршрутизация,
  запись в `.md` + SQLite, git-коммит.
- **Файлы-знания**: модель пишет файл темы (теория + грабли), затем
  `curator save --doc <path>` - проверка пути по карте, git-коммит,
  событие в журнале аналитики.
- **Журнал аналитики** (`analytics.jsonl`) - каждое событие: что
  предлагалось, что сохранено, что отклонено и почему.
- **Гигиена**: `curator improve` - дубликаты, противоречия, устаревшее
  (правила над базой, без LLM).

База - обычные `.md`-файлы (человекочитаемы, живут в гите) + локальная
SQLite-копия для поиска. Работает офлайн.

## Измерено

10 кодинговых задач со спрятанными правилами, 48 прогонов чистых агентов:
без памяти - 8/10 (ловушки 0/6), с Memory Curator - **10/10 (ловушки 6/6)**,
Fisher exact p = 0.0011. Методология: [benchmark/application/](benchmark/application/),
протокол экспериментов: [benchmark/experiments/](benchmark/experiments/).

## Структура

| Папка | Что |
|-------|-----|
| `core/` | ядро (Python): backend, gatekeeper, improve loop, routing, CLI, harness-чеки |
| `core/tests/requirements/` | тесты требований - имя теста = ID требования |
| `design/` | контракты (Router, Knowledge Route Metadata), ADR, backlog |
| `benchmark/` | эксперименты: применение знаний, extraction eval, retrieval |
| `docs/` | гайды: getting-started, self-improvement-loop |

Решения и их причины - [decision-log.md](decision-log.md).
Будущее - [design/backlog.md](design/backlog.md).
