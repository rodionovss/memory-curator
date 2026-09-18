# Memory Curator

Фоновый агент памяти для OpenCode и Claude Code: извлекает проверенные знания
из сессий и `.md`-документации, хранит их с валидацией, автономно улучшает
память (дубликаты, устаревание, противоречия) и возвращает знания обратно
в документацию.

Живой журнал решений: [decision-log.md](decision-log.md).

## Проблема

Знания из AI-сессий умирают вместе с чатом. `.md`-базы растут, в них копятся
дубликаты и устаревшие правила, противоречия никто не разрешает — и агент
каждый раз начинает с нуля вместо того, чтобы переиспользовать опыт.

## Что умеет

- **Сохраняет знания из сессий** — выделяет проверенные правила и паттерны, мусор и фичевые детали отсекаются на входе
- **Меняет поведение агента сам** — правила памяти в глобальном AGENTS.md / CLAUDE.md: база в контексте каждой сессии, плагин session.idle напомнит предложить сохранить выученное
- **База — обычные `.md`-файлы** — читаются человеком, живут в гите, навигация (index.md) обновляется сама
- **Самоулучшается без тебя** — схлопывает дубликаты, разрешает противоречия, помечает устаревшее; каждое изменение проходит метрическую проверку — база не может деградировать
- **Раскладывает знания по вашей структуре** — по типам или по карте проекта, с правилами записи для каждой темы
- **Подсказывает, что реально читают** — телеметрия использования; решение за человеком, автоматика не удаляет
- **Работает офлайн** — локальная SQLite-база, сеть не нужна
- **Надёжен** — 560+ тестов; каждое требование закрыто тестом с ID требования ([трассировочная матрица](core/tests/requirements/README.md))

## Как работает

Извлечение знаний делает сам агент (OpenCode сейчас, любой MCP-клиент,
включая Claude Code, по тому же контракту). Python валидирует кандидатов и
фиксирует выбор человека. Затем нейронный skill `curator-update-docs` смыслово
обновляет документацию по обязательной карте проекта, а Python проверяет
placement и только после этого пишет поисковую копию в backend базы.
LLM-вызовов в бэкенде нет.

```
Агент (OpenCode сейчас; любой MCP-клиент по тому же контракту)
    │  candidates: готовые факты (type, title, summary, tags, evidence)
    ▼
curator_session_capture: gatekeeper + preview, без записи
    ↓ выбранные человеком candidate_id
curator_capture_approve: неизменяемый manifest + настроенный CURATOR_MAP
    ↓
curator-update-docs: смысловые патчи в локальном формате проекта
    ↓ placements
curator_capture_complete: проверка карты → backend базы
```

CLI, ingest, demo и `SyncEngine` остаются отдельным legacy-контуром с
шаблонными Curator-секциями. Их fallback `session/{type}.md` и флаги
автоподтверждения не действуют в `/curator-save`.

## Измерено: переиспользование опыта

Эксперимент на 10 кодинговых задачах (в каждой спрятано правило из базы,
48 прогонов чистых агентов): без памяти - 8/10 задач, задачи-ловушки 0/6;
с Memory Curator - **10/10**, ловушки **6/6**; Fisher exact p = 0.0011.
Методология и фикстуры: [benchmark/application/](benchmark/application/).
Протокол новых экспериментов: [benchmark/experiments/](benchmark/experiments/).

## Запуск

```bash
git clone https://github.com/rodionovss/memory-curator.git
cd memory-curator
./install.sh          # Windows: install.bat — найдёт OpenCode/Claude Code, впишет MCP, команды, скиллы, плагины
cd core && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest tests/ -q --ignore=tests/smoke   # все зелёные
.venv/bin/curator demo                                      # полный цикл жизни знания; --keep оставит файлы
```

Project-local память для текущего репозитория: `/curator-create-map`, затем
`/curator-setup` - см. [docs/getting-started.md](docs/getting-started.md).
Самоулучшение в фоне: [docs/self-improvement-loop.md](docs/self-improvement-loop.md).

## Структура

- `core/` - ядро (Python): backend (SQLite), gatekeeper, improve loop, MCP-сервер, CLI, sync engine (write-back в .md)
- `core/tests/requirements/` - тесты требований, имя теста = ID требования
- `design/` - архитектура: контракты (Router, Knowledge Route Metadata), ADR, backlog
- `benchmark/` - эксперименты: применение знаний, extraction eval, retrieval-бенчмарки
- `docs/` - гайды: getting-started, self-improvement-loop

Живой журнал решений: [decision-log.md](decision-log.md) (корень репо).
Будущее: [design/backlog.md](design/backlog.md).
