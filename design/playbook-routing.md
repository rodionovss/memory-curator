# Playbook: Реализация RoutingRouter (Блок 1)

> Для AI-агента. Как подключить кастомный роутинг фактов по папкам к Memory Curator.

## Что нужно сделать

Реализовать класс `RoutingRouter` который читает `routing.yaml` и определяет в какую папку сохранять каждый извлечённый факт.

## Архитектура

```
Твой код (НЕ в репозитории curator):
  routing_router.py  ← твой класс RoutingRouter
  routing.yaml       ← твой конфиг структуры папок

Ядро curator (НЕ трогать):
  curator/routing/interface.py  ← контракт Router (прочитай один раз)
  curator/routing/__init__.py   ← get_router() — создаёт твой роутер по ROUTER_CLASS

Подключение:
  ROUTER_CLASS=routing_router.RoutingRouter curator-mcp-server
```

## Шаг 1: Прочитай контракт

Файл: `core/curator/routing/interface.py`

```python
class Router(Protocol):
    def route_fact(self, fact: ProposedFact) -> str:
        """Возвращает source_file для факта. Например: 'reference/kotlin/data.md'."""
        ...

    def list_routes(self) -> list[dict]:
        """Возвращает текущие маршруты для MCP-тулза curator_routes."""
        ...
```

Тебе нужно реализовать эти два метода.

## Шаг 2: Создай routing.yaml

В любом месте (например `~/.curator/routing.yaml`):

```yaml
routes:
  - path: "reference/kotlin/"
    rules:
      - tags_contains: ["kotlin", "jvm", "performance"]
      - type: "Reference"
  - path: "reference/compose/"
    rules:
      - tags_contains: ["compose", "android"]
      - type: "Reference"
  - path: "style/"
    rules:
      - type: "Style"
  - path: "docs/ai-process/"
    rules:
      - tags_contains: ["mcp", "agent", "llm"]
      - type: "Reference"
  default: "general/"
```

Каждый route проверяет факт на соответствие всем правилам (AND). Если подходит — факт сохраняется в этот путь. Если ни один не подходит — `default`.

## Шаг 3: Напиши RoutingRouter

Файл: `routing_router.py` (куда угодно, например рядом с `core/`)

```python
"""RoutingRouter — читает routing.yaml, определяет source_file для факта."""

import yaml
from pathlib import Path
from curator.routing.interface import Router
from curator.models import ProposedFact


class RoutingRouter:
    def __init__(self, config_path="~/.curator/routing.yaml"):
        self._config_path = config_path
        config_path = Path(config_path).expanduser()
        if not config_path.exists():
            raise FileNotFoundError(f"routing.yaml не найден: {config_path}")
        self.config = yaml.safe_load(config_path.read_text())
        self.routes = self.config.get("routes", [])
        self.default = self.config.get("default", "general/")

    def route_fact(self, fact: ProposedFact) -> str:
        for route in self.routes:
            if self._matches(fact, route):
                return self._filepath(route["path"], fact)
        return self._filepath(self.default, fact)

    def _matches(self, fact: ProposedFact, route: dict) -> bool:
        for rule in route.get("rules", []):
            if "type" in rule and fact.type != rule["type"]:
                return False
            if "tags_contains" in rule:
                required = set(rule["tags_contains"])
                if not required & set(fact.tags):
                    return False
        return True

    def _filepath(self, path: str, fact: ProposedFact) -> str:
        filename = fact.title.lower().replace(" ", "-")[:40] + ".md"
        return f"{path.rstrip('/')}/{filename}"

    def list_routes(self) -> list[dict]:
        return [
            {"path": r["path"], "rules": r.get("rules", []), "description": "routing.yaml"}
            for r in self.routes
        ]

    def reload(self):
        """Перезагрузить конфиг без перезапуска."""
        config_path = Path(self._config_path).expanduser()
        self.config = yaml.safe_load(config_path.read_text())
        self.routes = self.config.get("routes", [])
        self.default = self.config.get("default", "general/")
```

## Шаг 4: Подключи

```bash
# Положи routing_router.py в PYTHONPATH (например ~/projects/curator-extras/)
export ROUTER_CLASS=routing_router.RoutingRouter
export CURATOR_ROUTING_CONFIG=~/.curator/routing.yaml
curator-mcp-server
```

Или для теста:
```bash
ROUTER_CLASS=routing_router.RoutingRouter .venv/bin/python3 -c "
from curator.routing import get_router
r = get_router()
print(type(r).__name__)
print(f'Routes: {len(r.list_routes())}')
from curator.models import ProposedFact
path = r.route_fact(ProposedFact(type='Reference', title='Kotlin rule', tags=['kotlin', 'jvm'], content_summary='x'*20))
print(f'Kotlin fact → {path}')
path = r.route_fact(ProposedFact(type='Style', title='Commit style', tags=['git'], content_summary='x'*20))
print(f'Style fact → {path}')
"
```

## Шаг 5: Проверь

```bash
.venv/bin/python -m pytest tests/unit/test_routing.py -v
```

Эти тесты проверяют что DefaultRouter и Protocol работают. Твой RoutingRouter должен проходить те же контракты.

## Что не трогать

```
curator/gatekeeper.py   ← валидация (уже работает)
curator/backend/        ← SQLite (уже работает)
curator/improve_loop.py ← автоулучшение (уже работает)
curator/server.py       ← MCP-сервер (уже работает, вызывает router.route_fact())
```

Ты работаешь только с `routing_router.py` и `routing.yaml`. Ядро подхватывает твой роутер автоматически через `ROUTER_CLASS`.

## Отладка

Если роутер не подхватывается — `get_router()` молча падает на DefaultRouter. Чтобы увидеть ошибку:

```python
from curator.routing import get_router
r = get_router()
print(type(r).__name__)  # Должно быть "RoutingRouter", не "DefaultRouter"
```

## Что дальше

Когда роутер готов — он работает прозрачно. `curator_session_capture` вызывает `router.route_fact(fact)` и сохраняет факт в нужную папку. `curator_routes` показывает текущие маршруты. `curator_improve` при consolidation тоже использует роутер.