# Memory Curator — Core

Самообучающийся агент для структурированной базы знаний. Строит граф над `.md` файлами, обеспечивает целостность, сам улучшается с каждой итерацией. Хранилище — локальный SQLite; сеть не нужна.

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

```bash
curator status   # CLI — единственный вход (MCP-сервер удалён)
curator demo     # полный цикл жизни знания
```

## Save Flow (как работает сохранение)

1. Агент (скилл `curator-save`) извлекает кандидатов из сессии и
   показывает их пользователю.
2. `curator save` (JSON-кандидаты в stdin) запускает gatekeeper:
   формат, дубликаты по заголовкам — мусор отклоняется с причиной.
3. Подтверждение человека (`y` / флаг `--yes` для скриптов).
4. Маршрутизация по карте тем (теги ∩ токены) → write-back в `.md`
   + SQLite, каталог `knowledge-routes.md` регенерируется тем же
   коммитом, git-фиксация.

Файлы-знания: модель пишет файл темы, `curator save --doc <path>`
проверяет путь по карте и коммитит.

```bash
.venv/bin/python3 -c "from curator.demo import run_demo; run_demo()"
```

## Тесты

```bash
.venv/bin/python -m pytest tests/ -v --ignore=tests/smoke
```

# Memory Curator — Core

Самообучающийся агент для структурированной базы знаний. Строит граф над `.md` файлами, обеспечивает целостность, сам улучшается с каждой итерацией. Хранилище — локальный SQLite; сеть не нужна.

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

```bash
curator status   # CLI — единственный вход (MCP-сервер удалён)
curator demo     # полный цикл жизни знания
```

## Save Flow (как работает сохранение)

1. Агент (скилл `curator-save`) извлекает кандидатов из сессии и
   показывает их пользователю.
2. `curator save` (JSON-кандидаты в stdin) запускает gatekeeper:
   формат, дубликаты по заголовкам — мусор отклоняется с причиной.
3. Подтверждение человека (`y` / флаг `--yes` для скриптов).
4. Маршрутизация по карте тем (теги ∩ токены) → write-back в `.md`
   + SQLite, каталог `knowledge-routes.md` регенерируется тем же
   коммитом, git-фиксация.

Файлы-знания: модель пишет файл темы, `curator save --doc <path>`
проверяет путь по карте и коммитит.

```bash
.venv/bin/python3 -c "from curator.demo import run_demo; run_demo()"
```

## Тесты

```bash
.venv/bin/python -m pytest tests/ -v --ignore=tests/smoke
```

## Конфигурация

```bash
export CURATOR_STATE_DIR=~/.curator      # SQLite, логи, отчёты (default)
export CURATOR_BASE_DIR=~/memory-curator # база: env → ~/.curator/config.json → дефолт
export CURATOR_MAP=~/memory-curator/knowledge-map.md  # карта тем (опционально)
```
