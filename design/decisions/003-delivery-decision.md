---
type: Decision
id: 003
title: Delivery decision — routing primary, retrieval bottleneck, MCP в debug fallback
project: Memory Curator
date: 2026-09-17
status: accepted
---

# ADR 003: Delivery decision по итогам четырёх экспериментов

## Контекст

Epic #18 (issue #33): превратить результаты controlled-экспериментов
(01 routing, 02 access path, 03 proactive delivery, 04 storage; всего
776 прогонов: 192+192+192+200, детерминированные checks, сильная
bifrost_GA/glm-5.3 и слабая bifrost_GA/GA.Qwen3.6 модели) в архитектурное
решение. Предыдущее решение (decision-log #11): судьба MCP-слоя — через A/B,
не решением впрок. Эти прогоны — тот A/B.

## Evidence

| Находка | Эксперимент | Цифры |
|---|---|---|
| Routing-указатель меняет поведение агента | 01 | T01-ловушка: 0/6 без указателя → 3/6 с любым; application 73.8% → 88.1% |
| Лучший формат — skill-метаданные; явная таблица вредит слабой модели | 01 | R3 88.1%; weak R2 14/24 < R0 15/24 |
| Агент никогда не вызывает curator сам | 02 | 1/192 вызовов при доступных MCP-тулах; +8k токенов на дефиниции |
| Access-добавки поверх живого routing не дают прироста | 02 | weak: P0 17/24 → P3 17/24 |
| Oracle-карточка закрывает то, что routing не может | 03 | T01: 3/6 → 6/6; weak +2 |
| Реальный retriever молчит на реальных формулировках | 03+04 | Q1 silent 42/48; S2 recall 0.31, precision 1.0 |
| Markdown scan: recall 1.0, но шум + deprecated-утечки | 04 | S1 precision 0.696, deprecated leak 1.0 |

## Решение

1. **Primary delivery path — routing-слой**: skill-метаданные в
   workspace/глобальном AGENTS.md (формат R3: name, description,
   when-to-use, source). Не явные таблицы trigger-слов (вредят слабым
   моделям), не абстрактный указатель «сверься с базой».
2. **Proactive plugin остаётся установленным**, признаётся second path:
   механизм доказан (oracle T01 6/6), silence безопасен (42/48 — без
   вреда), но до улучшения retrieval его live-эффект около нуля. Вред
   возможен только при плохой доставке на слабых моделях (T06 Q1 weak).
3. **Узкое место системы — retrieval, не транспорт и не хранение.**
   Следующий рычаг: реформулировочный матчинг/порог в curator_context
   (recall 0.31 → цель паритета с oracle-выдачей). Улучшение retrieval
   — кандидат в отдельный epic до любых live A/B.
4. **Резидентный MCP curator — debug fallback, не дефолт.** 1/192
   самостоятельных вызовов при +8k токенов контекста: пассивные тулы
   не применяются. Установка MCP становится опциональной
   (cli/плагин — основной путь); тулы curator_* остаются доступны
   по явному запросу (manual fallback по контракту ADR 002).
5. **SQLite остаётся retrieval-бэкендом** (ADR 001): precision 1.0,
   deprecated-фильтрация, provenance, единый API. Markdown scan
   проигрывает по шуму и статусам, выигрывает по recall — recall
   чинится в scoring-слое, не сменой хранилища.

## Альтернативы

- **Оставить MCP в дефолте** — платит 8k токенов за 0.5% использования.
- **Убрать proactive plugin целиком** — механизм доказан (oracle),
  молчание безопасно; правильный фикс — retrieval, не удаление.
- **Перейти на Markdown-scan как retriever** — regresión по статусам
  и шуму; recall-преимущество решается в scoring.

## Последствия

- Инсталлер: MCP-регистрация — флаг/optional, не дефолтный шаг.
- Приоритет разработки: retrieval quality (reformulations, threshold) —
  измеряется повторным прогоном 03 Part B + 04.
- Live A/B на реальных сессиях (изначальная идея Epic #18) откладывается
  до починки retrieval: при delivery rate 12.5% полевой эксперимент
  не даст сигнала.
- Метрики для повторных прогонов заморожены: corpus FROZEN.sha,
  schemas/run.json, report.py.

## Источники

- benchmark/experiments/results/{01-routing-format,02-access-path,
  03-proactive-delivery,04-storage}/ — отчёты и run-файлы.
- Пост-мортем Sprint #2: «доступность ≠ применение» — воспроизведён
  на уровне тулов (02) и routing-слоя (01).

## Приложение: Placement-эксперимент 05 и решение M2 (144 прогона)

**Вопрос:** как доставлять каталог маршрутов `knowledge-routes.md`
агенту — встроить в глобальный rules-файл (M1), оставить короткую
pointer-секцию с путём (M2) или предзагружать через OpenCode
`instructions` (M3)? 144 прогона (2 модели × 3 варианта × 24 прогона,
`benchmark/experiments/results/05-route-placement/`), автоправило
решения не сработало — trade-off разрешён человеком по данным.

| Вариант | Application | Routing recall | Токены (input, mean) | Особое |
|---|---|---|---|---|
| M1 — каталог в AGENTS.md | 0.833 | 0.619 | 21319 | ~5.4k always-on |
| **M2 — pointer-секция (решение)** | **0.881** | 0.667 | 23732 | hop 0.646 — каталог читается по требованию |
| M3 — instructions preload | 0.643 | 0.762 | 19466 | marker 1.0 (загрузка подтверждена), ~5.4k always-on |

Per-model (24 прогона на ячейку):

- **strong M2**: routing 1.0 (указатель читает 24/24), application
  0.952 — лучшая пара метрик эксперимента.
- **weak M2**: каталог читает 29% нужных прогонов; после чтения
  маршрутизирует 7/7 — проблема инициативы, не понимания.
- **M3-weak routing 0.524 > M1-weak 0.286** — гипотеза: позиция
  в system message помогает слабой модели замечать каталог.

**Решение (human, data review):**

- **M2 — единственный placement**: короткая pointer-секция в глобальном
  rules-файле каждого харнеса (AGENTS.md / CLAUDE.md); каталог живёт
  в базе и грузится pay-per-use. Почему: кросс-агентность (instructions —
  только OpenCode, у Claude @import, у Codex нет), 0 always-on токенов
  на старте, strong compliance 1.0.
- **M3 — tested-and-removed**: application 0.643 ниже M1/M2 при
  always-on ~5.4k токенов и OpenCode-only. Код удалён; воскрешение
  из git-истории тривиально.
- **M1 — отвергнут**: ~5.4k always-on, application-преимущество
  в зоне шума.
- **Override правила «M2 проигрывает из-за extra hop»**: pay-per-use
  бьёт always-on при смешанном паттерне реальных сессий (не каждая
  сессия касается тем базы), strong-модель следует указателю 24/24.

**Coverage пропусков** (weak читает каталог в 29% нужных прогонов):
плагин proactive delivery (shadow) + ручной `/curator-query`.

Status: `accepted` без изменений.
