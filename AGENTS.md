# AGENTS.md

Memory Curator — куратор базы знаний AI-агента (opencode / Claude Code).
Python, ядро в `core/`.

## Что это

CLI-first: агент (скилл `curator-save`) извлекает проверенные знания из
сессий, `curator save` валидирует (gatekeeper: дедуп по картотеке
заголовков), маршрутизирует по карте тем, пишет в `.md` + SQLite,
коммитит и регенерирует каталог чтения. Извлечение делает сам агент —
LLM в бэкенде нет. Фоновых процессов нет (решение 2026-10-03): MCP-сервер,
worker, improve-контур и delivery-плагины удалены.

## Как проверить за 2 команды

```bash
cd core
.venv/bin/python -m pytest tests/ -q   # все зелёные
```

Нет `.venv`? → `python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"`

## Карта репо

| Путь | Что |
|------|-----|
| `core/curator/` | код: `backend/` (SQLite), `gatekeeper.py`, `sync_engine.py`, `knowledge_routes.py` (каталог чтения), `routing/` (карта тем), `control.py` (CLI), `installer.py` |
| `core/tests/requirements/` | **главный suite**: 1 тест = 1 требование (R1-R6, N1-N5, UC2), трассировочная матрица в README там же |
| `integrations/` | что ставит `curator install`: команды, rules-секция, контракт харнесс-адаптеров |
| `.agents/skills/` | канонический source of truth product skills; workflow — в `playbook.md` |

## Соглашения

- Извлечение знаний — в слое агента; контракт: `candidates` (JSON в stdin `curator save`)
- База знаний: env `CURATOR_BASE_DIR` → `~/.curator/config.json` → дефолт `~/memory-curator`
- Факты: natural key `title`, UPSERT; статусы `verified / hypothesis / deprecated`
- Коммиты в репо — только с `CURATOR_MAINTAINER=1` (гард от автокоммитов агентов)
- Не коммитить: `.venv`, `*.db`, `.env` — закрыто `.gitignore`
