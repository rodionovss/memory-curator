# Memory Curator

Фоновый агент памяти для opencode и Claude Code: извлекает проверенные знания
из сессий и `.md`-документации, хранит их с валидацией, автономно улучшает
память (дубликаты, устаревание, противоречия) и возвращает знания обратно
в документацию.

Живой журнал решений: [decision-log.md](decision-log.md).

## Проблема

Знания из AI-сессий умирают вместе с чатом. `.md`-базы растут, в них копятся
дубликаты и устаревшие правила, противоречия никто не разрешает — и агент
каждый раз начинает с нуля вместо того, чтобы переиспользовать опыт.

## Что умеет

- **Ставится одной командой** — сам находит opencode и Claude Code, команды и скиллы появляются сами после перезапуска
- **Сохраняет знания из сессий** — выделяет проверенные правила и паттерны, мусор и фичевые детали отсекаются на входе
- **Меняет поведение агента сам** — правила памяти в глобальном AGENTS.md / CLAUDE.md: база в контексте каждой сессии, плагин session.idle напомнит предложить сохранить выученное
- **База — обычные `.md`-файлы** — читаются человеком, живут в гите, навигация (index.md) обновляется сама
- **Самоулучшается без тебя** — схлопывает дубликаты, разрешает противоречия, помечает устаревшее; каждое изменение проходит метрическую проверку — база не может деградировать
- **Раскладывает знания по вашей структуре** — по типам или по карте проекта, с правилами записи для каждой темы
- **Подсказывает, что реально читают** — телеметрия использования; решение за человеком, автоматика не удаляет
- **Работает офлайн** — локальная SQLite-база, сеть не нужна
- **Надёжен** — 560+ тестов, каждое требование закрыто тестом с ID, все изменения журналируются

## Как работает

Извлечение знаний делает сам агент (opencode сейчас, любой MCP-клиент,
включая Claude Code, по тому же контракту). Python валидирует кандидатов и
фиксирует выбор человека. Затем нейронный skill `curator-update-docs` смыслово
обновляет документацию по обязательной карте проекта, а Python проверяет
placement и только после этого пишет поисковую копию в project-local backend.
LLM-вызовов в бэкенде нет.

```
Агент (opencode сейчас; любой MCP-клиент по тому же контракту)
    │  candidates: готовые факты (type, title, summary, tags, evidence)
    ▼
curator_session_capture: gatekeeper + preview, без записи
    ↓ выбранные человеком candidate_id
curator_capture_approve: неизменяемый manifest + настроенный CURATOR_MAP
    ↓
curator-update-docs: смысловые патчи в локальном формате проекта
    ↓ placements
curator_capture_complete: проверка карты → project-local backend
```

CLI, ingest, demo и `SyncEngine` остаются отдельным legacy-контуром с
шаблонными Curator-секциями. Их fallback `session/{type}.md` и флаги
автоподтверждения не действуют в `/curator-save`.

## Как измеряется прогресс

Каждое требование закрыто тестом, имя теста = ID требования: 14 тестов на
12 требований, ходят только через публичные API. Трассировочная матрица -
[core/tests/requirements/README.md](core/tests/requirements/README.md).

## Измерено: переиспользование опыта

Эксперимент на 10 кодинговых задачах (в каждой спрятано правило из базы,
48 прогонов чистых агентов): без памяти - 8/10 задач, задачи-ловушки 0/6;
с Memory Curator - **10/10**, ловушки **6/6**; Fisher exact p = 0.0011.
Методология и фикстуры: [benchmark/application/](benchmark/application/).
Протокол новых экспериментов: [benchmark/experiments/](benchmark/experiments/).

## Попробовать за 2 минуты

```bash
git clone https://github.com/rodionovss/memory-curator.git
cd memory-curator
./install.sh                                                # Windows: install.bat
cd core && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest tests/ -q --ignore=tests/smoke  # все зелёные
.venv/bin/curator demo                                     # полный цикл жизни знания
```

Project-local память для текущего репозитория: `/curator-create-map`, затем
`/curator-setup` - см. [docs/getting-started.md](docs/getting-started.md).

`curator demo` - полный цикл жизни знания на изолированной tmp-базе
реальными вызовами; `--keep` оставит файлы.

Самоулучшение в фоне: [docs/self-improvement-loop.md](docs/self-improvement-loop.md).

## Развёртывание

| | Локальная база (единственный вариант) |
|--|-----------|
| Что нужно | ничего — SQLite идёт в комплекте |
| Хранение | `$CURATOR_STATE_DIR/knowledge.db` |
| Сеть | не нужна |

## Структура

| Папка | Что |
|-------|-----|
| `core/` | ядро (Python): backend (SQLite), gatekeeper, improve_loop, MCP-сервер; CLI и sync_engine (write-back в .md) |
| `core/tests/requirements/` | тесты требований — имя теста = ID требования |
| `design/` | архитектура: requirements, spec, decision-log (история), playbook-routing (контракт Router), knowledge-route-format ([контракт Knowledge Route Metadata](design/knowledge-route-format.md)), backlog |
| `benchmark/` | A/B/C-бенчмарк применения знаний, extraction eval и runbook routing/access/proactive/storage экспериментов |
| `docs/` | day-to-day: getting-started |

Живой журнал решений: [decision-log.md](decision-log.md) (корень репо).
Будущее: [design/backlog.md](design/backlog.md).
