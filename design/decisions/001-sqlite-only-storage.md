---
type: Decision
id: 001
title: SQLite-only storage — единственный persistence backend
project: Memory Curator
date: 2026-09-17
status: accepted
---

# ADR 001: SQLite-only storage — единственный persistence backend

## Контекст

xmemory (schema-grounded SaaS) был выбран primary backend на хакатоне для
пункта «использование движка». После хакатона (пост-мортем Sprint #2,
решение 16.09 по MCP) стало ясно:

- delivery-гэп («знания не доходят до контекста агента», retrieval промах
  9/10) решается на слое доставки, а не хранения; движок — за контрактом
- преимуществами xmemory (деревья, схема, облако) не пользовались; локальный
  SQLite закрывает текущую боль
- лишняя поддержка: REST-клиент, offline-fallback, outbox-очередь, sync,
  dual-backend-тесты — всё ради неиспользуемого облака
- сеть как зависимость хранилища знаний для персонального использования —
  чистый минус (VPN-издержки ещё до этого подтверждены)

## Решение

1. **LocalBackend (SQLite) — единственный persistence/index backend.**
   Markdown-файлы остаются source of truth; SQLite — производный
   поисковый индекс и хранилище фактов.
2. **Удаляется полностью:** `backend/xmemory.py`, `outbox.py`,
   `schemas/xmd_kb.yaml`, CLI `curator sync`, env `MEMORY_BACKEND`,
   `XMEMORY_API_KEY`, `XMEMORY_INSTANCE_ID`, зависимость `httpx`,
   offline-fallback и идемпотентный push.
3. **Сохраняются контракты:** `MemoryBackend` Protocol (агностик —
   новый backend вернётся через реализацию того же протокола),
   capture flow `capture → approve → update-docs → complete`,
   `SyncEngine` (write-back в .md), arrive/retrieve-интерфейсы MCP.
4. **MCP остаётся интерфейсом-адаптером**, судьба транспорта решается
   экспериментом доставки (Epic #15/#18), не этим ADR.

## Альтернативы

- **Оставить xmemory как есть** — тянет сеть, ключи, fallback-логику
  и dual-backend тесты ради неиспользуемой функциональности.
- **Оставить только интерфейс без реализации** — резервирует dead code
  до появления второго backend; возврат делается дешёво по Protocol.

## Последствия

- Окружение упрощается: нет сетевых зависимостей, ключей и очередей.
- Старые `~/.curator/outbox.db` игнорируются (данные не терялись:
  fallback дублировал факты в `knowledge.db`; файл можно удалить).
- Облачные данные xmemory не мигрируются автоматически (не использовались).
- Требования: X1-X4 и UC6 (fallback/sync) удалены из матрицы; persistence
  SQLite закрыт R4 (`test_R4_память_между_рестартами`).

## Источники

- Epic #17 (SQLite-only storage), решение сессии 16.09.
- Пост-мортем Hacker Sprint #2: «хранение не важно — важна доставка».
