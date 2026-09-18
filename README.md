<div align="center">

# Memory Curator

Фоновый агент памяти для OpenCode и Claude Code.

Знания из AI-сессий не умирают вместе с чатом - извлекаются, валидируются
и возвращаются в следующую задачу.

</div>

---

## Установка

```bash
git clone https://github.com/rodionovss/memory-curator.git
cd memory-curator
./install.sh          # Windows: install.bat
```

Инсталлер сам находит OpenCode / Claude Code и вписывает MCP-сервер,
команды `/curator-*`, скиллы, плагины и worker. Перезапусти харнес - готово.

```bash
# проверка
cd core && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest tests/ -q --ignore=tests/smoke   # все зелёные
.venv/bin/curator demo                                      # полный цикл жизни знания
```

Project-local память для репозитория: `/curator-create-map`, затем
`/curator-setup` - см. [docs/getting-started.md](docs/getting-started.md).

## Что делает

- **Сохраняет** проверенные знания из сессий (человек подтверждает кандидатов)
- **Доставляет** их в следующие сессии - каталог маршрутов в глобальном AGENTS.md, proactive-доставка в OpenCode
- **Самоулучшается** - схлопывает дубликаты, разрешает противоречия, помечает устаревшее; eval-гейт не даёт базе деградировать

База - обычные `.md`-файлы (человекочитаемы, живут в гите) + локальная
SQLite-копия для поиска. LLM-вызовов в бэкенде нет. Работает офлайн.

## Измерено

10 кодинговых задач со спрятанными правилами, 48 прогонов чистых агентов:
без памяти - 8/10 (ловушки 0/6), с Memory Curator - **10/10 (ловушки 6/6)**,
Fisher exact p = 0.0011. Методология: [benchmark/application/](benchmark/application/),
протокол экспериментов: [benchmark/experiments/](benchmark/experiments/).

## Структура

| Папка | Что |
|-------|-----|
| `core/` | ядро (Python): backend, gatekeeper, improve loop, MCP-сервер, CLI, harness-чеки |
| `core/tests/requirements/` | тесты требований - имя теста = ID требования |
| `design/` | контракты (Router, Knowledge Route Metadata), ADR, backlog |
| `benchmark/` | эксперименты: применение знаний, extraction eval, retrieval |
| `docs/` | гайды: getting-started, self-improvement-loop |

Решения и их причины - [decision-log.md](decision-log.md).
Будущее - [design/backlog.md](design/backlog.md).
