# AGENTS.md

Memory Curator — агент памяти для opencode и Claude Code. Python, ядро в `core/`.

## Что это

Фоновый агент: извлекает проверенные знания из сессий и `.md`, хранит с
валидацией (gatekeeper), автономно улучшает память (дубликаты → консолидация,
устаревание → deprecation, противоречия → resolution, eval gate перед
изменениями) и возвращает знания в `.md` (write-back). Извлечение делает
сам агент — LLM на стороне opencode / Claude Code, бэкенд LLM-вызовов
не содержит (контракт `candidates`).

## Как проверить за 2 команды

```bash
cd core
.venv/bin/python -m pytest tests/ -q --ignore=tests/smoke   # 174 passed + 1 smoke-skip
.venv/bin/curator demo                                       # полный цикл жизни знания
```

Нет `.venv`? → `python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"`

## Карта репо

| Путь | Что |
|------|-----|
| `core/curator/` | код: `backend/` (xmemory + SQLite + outbox), `gatekeeper.py`, `improve_loop.py`, `sync_engine.py`, `server.py` (MCP, 6 тулзов), `control.py` (CLI), `tour.py` (демо-тур) |
| `core/tests/requirements/` | **главный suite**: 1 тест = 1 требование хакатона (R1-R6, N1-N5, X1-X4, UC6), трассировочная матрица в README там же |
| `design/` | архитектура: `requirements.md` (матрица сдачи), `spec.md`, `decision-log.md` |
| `demo/` | сценарий видео, чеклист записи, путеводитель по коду |
| `docs/getting-started.md` | установка, подключение к opencode, CLI, worker |
| `.agents/skills/` | канонический source of truth product skills; подробный workflow хранится в `playbook.md` |
| `docs/` | актуальная документация; authority и исторические материалы описаны в `docs/README.md` |

## Соглашения

- Извлечение знаний — в слое агента; контракт: `candidates` (подробности в
  `README.md`)
- Факты: natural key `title`, UPSERT; статусы `verified / hypothesis / deprecated`
- Не коммитить: `.venv`, `*.db`, `.env` — закрыто `.gitignore`
- Полный бэклог: `design/backlog.md`
