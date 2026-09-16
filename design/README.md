# Design Docs — Архитектура

Что и почему запланировали. Спорные места — в decision-log с альтернативами.

| Файл | О чём | Когда читать |
|------|-------|-------------|
| [requirements.md](requirements.md) | Требования к продукту + матрица соответствия (6/6 мин, 5/5 доп, 4/4 xmemory) | Свериться что всё закрыто |
| [spec.md](spec.md) | Техспека: use cases, data flow, компоненты, scope | Чтобы понять «почему так устроено» |
| [decision-log.md](decision-log.md) | Архитектурные решения: xmemory+SQLite fallback, LLM вне бэкенда, отвергнутые альтернативы | Чтобы понимать причины и не переубеждать |
| [playbook-routing.md](playbook-routing.md) | Контракт Router Protocol, routing.yaml | Онбординг |
| [backlog.md](backlog.md) | Продуктовый роадмап: фичи и тех.долг (баги — в GitHub Issues) | Планирование следующих итераций |

Демо-материалы (чеклисты, сценарий записи, путеводитель по коду) — в [`demo/`](../demo/).
Day-to-day использование — в [`docs/getting-started.md`](../docs/getting-started.md).
