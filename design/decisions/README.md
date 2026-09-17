# Architecture Decisions

Здесь хранятся принятые архитектурные решения Curator-а. Файл решения должен
содержать контекст, принятое решение, альтернативы и последствия.

| ADR | Решение | Статус |
|-----|---------|--------|
| [001-sqlite-only-storage.md](001-sqlite-only-storage.md) | SQLite — единственный persistence backend; xmemory удалён | accepted |
| [002-delivery-contract.md](002-delivery-contract.md) | Delivery contract: query → ranked context cards | accepted |
| [003-delivery-decision.md](003-delivery-decision.md) | Routing primary, retrieval bottleneck, MCP → debug fallback | accepted |

Исторический `design/decision-log.md` остаётся источником контекста до
постепенного переноса решений в отдельные ADR-файлы. Новые решения следует
добавлять сюда, а не разбрасывать по README, demo или execution plan.
