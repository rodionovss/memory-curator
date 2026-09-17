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
