# Decision Log

Живой журнал решений проекта Memory Curator: что обсуждали, что решили, что сделали и почему. Отменённое фиксируется с причиной. Новые записи добавляются сверху.

Предыстория до хакатона (эпоха xmemory) - в `design/decision-log.md`. Глубокие решения с данными - в ADR: `design/decisions/001-sqlite-only-storage.md` (SQLite-only), `design/decisions/002-delivery-contract.md` (транспорт-агностик delivery), `design/decisions/003-delivery-decision.md` (shadow-режим и выбор placement).

## 2026-09-18 - закрытие разработки

Аудит после сдачи (161 коммит за 2026-08-29 - 2026-09-18): retrieval recall 0.312→0.375, precision 1.0, leak 0, но delivery rate на корпусе не вырос (12.5%) → решили: разработку закрываем, включаем shadow-телеметрию, решение о live-доставке примем по живым данным. Эпик improve loop (#16/#34/#35/#36) закрыт как «отложено до shadow-данных», заведены и закрыты deferred #49 (semantic retrieval) и #50 (live A/B). Влит фикс: `curator_query` по умолчанию скрывает deprecated-факты - до этого они утекали агенту. Снесены пер-рановые JSON экспериментов 01-03: шум в репо, восстановимы из git.

Днём доведено до конца: личная база приведена к контракту (104 → 243 факта, style/ и tools/ в факт-формате, `###`-секции + мета), карта и каталог выровнены - 18 тем, чтение и запись симметричны (проверено: все 18 маршрутизируют верно, DB↔.md 243/243). Playbook save-knowledge дописан (`###`-контракт). Shadow включён в реальном конфиге, плагин curator-context на диске обновлён (копия была без фикса exitCode - inject был мёртв). Новые темы/файлы проверены тестом на tmp-копии: правка карты → рестарт харнеса → роутинг; новый .md → ingest → каталог.

**Статус: с 2026-09-18 продукт в реальном использовании, разработка остановлена. Фоном собирается shadow-телеметрия; решение о доработках (live-доставка #50, semantic #49, improve-петля #16) - по данным через 2-3 недели.**

## 2026-09-17 - knowledge-routes/retrieval v2 (PR #48)

Решили, как агент находит нужные факты без bloat в контексте → влита retrieval v2: каталог `knowledge-routes.md`, route-aware retrieval, алиасы запросов, threshold 0.40 по sweep-у (`results/04-storage/threshold-sweep.json`). Placement-эксперимент (144 прогона): выбран M2 pointer - короткая секция-указатель в глобальных rules, каталог читается по требованию; M1 full-embedding отвергнут (bloat ~5.4k токенов always-on), M3 instructions-плагина проверен, сработал хуже и удалён (см. ADR 003 appendix). Shadow mode: `CURATOR_DELIVERY_MODE=off/shadow/inject` + flock/ротация лога; попутно найден мёртвый inject из-за бага proc.ok→exitCode в Bun Shell.

## 2026-09-15/16 - вклад Егора (egor-integration)

Расширили retrieval под реальные сценарии → влито: `query_facts` по тегам, `watch_for` в роутере, migration gate.

## 2026-09-13 - поворот на личный продукт

Хакатонный контекст снят, Memory Curator продолжаем как личный продукт → improve-loop переведён с самопальной базы на GitHub Issues + ops/ (крон curator-maintainer), написан пост-мортем спринта 2 (`design/postmortem-hacker-sprint-2.md`).

## 2026-09-11 - ADR 001 SQLite-only

Обсуждали, тянуть ли распределённую архитектуру → решили: нет, мёртвый код режет сложность → выпилены XMemoryBackend, outbox, remote sync, httpx (ADR 001).

## 2026-09-03/07 - read-side и майнинг сессий

Нужен был замкнутый контур: факты не только пишутся, но и читаются агентом → сделали reader сессий + sessions CLI, правила памяти в AGENTS.md + плагин `session.idle`. A/B/C-бенчмарк применения: 10/10 задач с памятью vs 8/10 без, ловушки 6/6 vs 0/6, Fisher p=0.0011 - память доказанно применяется. Extraction eval → curator-save 0.2.0. A/B-обвязка extraction позже проверена и удалена - не справлялась с задачей.

## 2026-08-30/31 - финализация хакатона

Доводили до сдачи: install wizard с «нулевыми вопросами», README/PRESENTATION. Таймерный decay заменён на семантический - актуальность факта определяется смыслом, не временем. Проведён аудит тестов.

## 2026-08-29 - сдача core (PR #1)

Заложен фундамент: candidates contract (MCP+CLI), offline outbox, write-back в `.md`, improve loop + eval-гейт, requirement-тесты R1-R6/N1-N5.
