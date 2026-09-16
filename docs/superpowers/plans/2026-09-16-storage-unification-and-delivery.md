# Storage Unification & Delivery Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Убрать раздвоение session/learnings, замерить read-path и подготовить эксперимент «A/B/C/D» для выбора механизма доставки знаний в сессию.

**Architecture:** Markdown-файлы — источник истины (один файл на тему, атомарные секции-факты). SQLite (~/.curator/knowledge.db) — локальный индекс. session/ ликвидируется миграцией в thematic-файлы reference/. Доставка знаний выбирается экспериментом, не заранее.

**Tech Stack:** Python 3 (curator CLI, sqlite3), Bash, Markdown (OKF frontmatter). Без новых зависимостей.

## Global Constraints

- **Executor-протокол:** у каждого Task есть `Executor`. Пакеты с `Executor: BF glm-5.3` выполняются моделью `bifrost_GA/glm-5.3` (запуск: `opencode run -m bifrost_GA/glm-5.3 "<текст задачи>"` или сессия с этой моделью). Fallback на другую модель запрещён: модель недоступна — стоп и отчёт об ошибке.
- **BF-пакеты не принимают архитектурных решений**: целевые файлы, форматы и границы заданы в задаче; любое отклонение — не править самому, а записать в «Открытые вопросы» отчёта.
- **Ревью-гейт:** после каждого пакета с `Executor: BF` — ревью diff сильной моделью до перехода к следующему.
- xmemory и MCP НЕ трогать до конца эксперимента (рука B использует текущий стек).
- Формат секции-факта внутри тематического файла:

```markdown
## <Название факта>

Rule: <переносимое правило одной строкой-абзацем>
Why: <почему, кратко>
Tags: <теги через запятую>
```

- Ничего не коммитить в main напрямую: ветка `curator/storage-unification`, PR после ревью. Коммит-хук репо требует `CURATOR_MAINTAINER=1` только для правок кода куратора; этот план правит доки/базу знаний, но коммиты в репо — через PR как обычно.
- Личная база: `~/Documents/AI/personal/learnings/` (не git-репо для изменений — правки прямые, без веток). Репо memory-curator: правки через ветку/PR.

---

### Task 1: Инвентаризация session/ и карты миграции

**Executor: BF glm-5.3**
**Mode: read-only + один новый файл-отчёт. Код и знания не менять.**

**Files:**
- Read: `~/Documents/AI/personal/learnings/session/*.md` (12 файлов)
- Read: `~/Documents/AI/personal/learnings/reference/*.md` + `reference/index.md`
- Read: `~/Documents/AI/personal/learnings/DOCUMENTATION-MAP.md`
- Create: `/Users/rodionovsergej/Documents/GitHub/memory-curator/docs/superpowers/reports/2026-09-16-migration-map.md`

**Interfaces:**
- Produces: отчёт-карта миграции. Task 3 исполняет ТОЛЬКО строки, утверждённые на ревью Task 2.

- [ ] **Step 1: Собрать инвентарь session/**

Для каждого файла из `session/` перечислить каждую секцию-факт (`## Заголовок` + Rule/Why/Tags): заголовок, 1-строчное резюме, теги.

- [ ] **Step 2: Собрать инвентарь reference/**

То же для существующих thematic-файлов reference/ (compose.md, android.md, kotlin.md, mvi-state.md, agent-memory.md, vpn-nodemaven-clash.md и др.): темы файла, какие секции уже есть.

- [ ] **Step 3: Найти пересечения и дубли**

Отметить: (а) коллизии имён — например, `reference/agent-memory.md` (обзор ландшафта памяти) vs `session/agent-memory.md` (факты куратора); (б) тематические дубли — `session/compose.md` vs `reference/compose.md`, `session/kotlin.md` vs `reference/kotlin.md`, `session/android.md` vs `reference/android.md`, `session/vpn.md` vs `reference/vpn-nodemaven-clash.md`, `session/mvi.md` vs `reference/mvi-state.md`; (в) факты в session/, дублирующие по смыслу секции в reference/.

- [ ] **Step 4: Построить карту миграции**

Таблица вида: `секция (файл+заголовок) → целевой файл → действие (merge|new|drop) → обоснование (1 строка) → duplicate-of (если есть)`.

Предлагаемые дефолты (отклонения — только в «Открытые вопросы»):
- session/compose.md → reference/compose.md (merge)
- session/mvi.md → reference/mvi-state.md (merge)
- session/kotlin.md → reference/kotlin.md (merge)
- session/android.md → reference/android.md (merge)
- session/agent-memory.md → reference/agent-memory.md (merge; существующий обзор — секцией «Ландшафт», факты — секциями ниже)
- session/agents-skills.md → reference/agents-skills.md (new)
- session/code-review.md → reference/code-review.md (new; НЕ сливать с bot-review-system.md — там про CI-бота)
- session/workflow.md → reference/workflow.md (new)
- session/vpn.md → reference/vpn-nodemaven-clash.md (merge)
- session/reference.md, session/general.md, session/style.md → разнести по темам каждого факта

- [ ] **Step 5: Зафиксировать риски**

Список: факты без темы, слабые/устаревшие секции (кандидаты на drop), нарушения формата.

- [ ] **Step 6: Записать отчёт**

`docs/superpowers/reports/2026-09-16-migration-map.md`: инвентари (Step 1-2), дубли (Step 3), карта (Step 4), риски (Step 5), «Открытые вопросы» (что не смог решить в рамках задачи).

**Стоп-условие:** никакие файлы знаний не изменены; создан только отчёт.

---

### Task 2: Ревью карты миграции (гейт)

**Executor: сильная модель**

- [ ] **Step 1:** Прочитать отчёт Task 1. Проверить каждую строку карты: правильность целевого файла, отсутствие потерянных фактов, обоснованность drop.
- [ ] **Step 2:** Разрешить «Открытые вопросы» и коллизии из Step 3-5 (решение записать в конец отчёта: «Ревью: принято/изменено — <вердикт по каждой спорной строке>»).
- [ ] **Step 3:** Отметить в отчёте строки карты как `approved` / `rejected`. Task 3 исполняет только approved.

---

### Task 3: Миграция session/ в тематические файлы

**Executor: BF glm-5.3. Запускать только после ревью Task 2 (вердикты — в разделе 7 отчёта migration-map).**

**Files:**
- Modify: `~/Documents/AI/personal/learnings/reference/*.md` (merge-цели по карте)
- Create: `~/Documents/AI/personal/learnings/reference/{agents-skills,code-review,workflow}.md` (new-цели) с frontmatter `type: Reference`, `tags: [...]`, `description: ...`; секции `##` на факт
- Modify: `~/Documents/AI/personal/learnings/reference/index.md` (добавить новые файлы строкой с description; merge-файлы уже там)
- Modify: `~/Documents/AI/personal/learnings/reference/agent-memory-sprint2-lessons.md` — ТОЛЬКО intro-ссылка `session/agent-memory.md` → `reference/agent-memory.md`
- Delete: `~/Documents/AI/personal/learnings/session/*.md` (в конце, после проверки)
- Modify: `~/Documents/AI/personal/learnings/DOCUMENTATION-MAP.md` (таргеты тем на новые пути; тема general → `reference/workflow.md`)
- Modify: `~/.curator/knowledge.db` — только через `sqlite3` CLI в bash (вне cwd — файловые инструменты не пройдут permission)

**Interfaces:**
- Consumes: approved-карта из Task 2 (раздел 4 отчёта + вердикты раздела 7: android №2/№5 → reference/compose.md; agent-memory №9 — drop; формат — дословный перенос).
- Produces: единая база без session/; DOCUMENTATION-MAP на reference/*; SQLite source_file без `session/%`.

- [ ] **Step 1: Перенести approved-строки**

Каждую approved секцию — в целевой файл по карте. Переносить ДОСЛОВНО:
проза + «Пруф» + footer `*Тип/Статус/Теги*` без изменений. Уровень заголовков
подстроить под целевой файл (в существующих файлах — как у их секций; в новых
файлах — `##`). Спец-структуры по вердиктам: reference/agent-memory.md — после
narrative-обзора заголовок `## Проверенные факты`, факты ниже;
vpn-nodemaven-clash.md — блок `## Краткие правила` в конец; android №2 и №5 —
в reference/compose.md в/рядом секцию «Миграция с View на Compose».

- [ ] **Step 2: Не тащить мусор**

Строки drop не переносить (agent-memory №9). Конвертацию формата и правку
содержания НЕ делать (включая рус/англ теги) — только перенос.

- [ ] **Step 3: Обновить reference/index.md и intro-ссылку**

Новые файлы — строками по образцу существующих (путь + description).
В agent-memory-sprint2-lessons.md заменить только intro-ссылку
`session/agent-memory.md` → `reference/agent-memory.md`.

- [ ] **Step 4: Обновить DOCUMENTATION-MAP.md**

В frontmatter topics: `session/X.md` → новые пути по карте; тема general →
`reference/workflow.md`. `watch_for`, `mode: update`, `instructions` не менять.

- [ ] **Step 5: Обновить SQLite source_file**

```bash
cp ~/.curator/knowledge.db ~/.curator/knowledge.db.bak-20260916
sqlite3 ~/.curator/knowledge.db "SELECT DISTINCT source_file FROM facts;"   # в отчёт
# затем по карте: sqlite3 ~/.curator/knowledge.db "UPDATE facts SET source_file='<новый путь>' WHERE source_file='session/<старый>.md';"
# drop-строка (agent-memory №9) → source_file='reference/agents-skills.md'
sqlite3 ~/.curator/knowledge.db "SELECT COUNT(*) FROM facts; SELECT COUNT(*) FROM facts WHERE source_file LIKE 'session/%';"
```

Гейт: COUNT(*) не изменился; строк с `source_file LIKE 'session/%'` — 0.

- [ ] **Step 6: Проверить целостность**

```bash
ls ~/Documents/AI/personal/learnings/session/  # ожидание: пусто
grep -c '^## \|^### ' ~/Documents/AI/personal/learnings/reference/compose.md
grep -rn 'session/' ~/Documents/AI/personal/learnings/reference/index.md ~/Documents/AI/personal/learnings/DOCUMENTATION-MAP.md  # ожидание: 0 упоминаний путей session/
```

- [ ] **Step 7: Отчёт о миграции**

Дополнить `docs/superpowers/reports/2026-09-16-migration-map.md` разделом
«Выполнено (Task 3)»: что перенесено (по файлам), что отброшено, список
DISTINCT source_file до/после, результат гейтов Step 5-6.

**Стоп-условие:** session/ пуст; все ссылки валидны; SQLite без session/%; COUNT не изменился. Если что-то нельзя выполнить — не импровизировать, а стоп + «Открытые вопросы».

---

### Task 4: Замеры read-path представлений

**Executor: BF glm-5.3. Можно параллельно Task 1-3 (не зависит).**

**Files:**
- Read: `~/.curator/knowledge.db` (таблицы: facts, relations; сейчас 203 факта)
- Create: `/Users/rodionovsergej/Documents/GitHub/memory-curator/docs/superpowers/reports/2026-09-16-read-path-sizes.md`

**Interfaces:**
- Produces: таблица размеров трёх представлений при N = 203 (реальная база) и синтетических N = 100 / 500 / 1000. Вход для дизайна эксперимента (Task 5).

- [ ] **Step 1: Снять схему и реальный размер**

```bash
sqlite3 ~/.curator/knowledge.db ".schema facts"
sqlite3 ~/.curator/knowledge.db "SELECT COUNT(*) FROM facts;"
sqlite3 ~/.curator/knowledge.db "SELECT status, COUNT(*) FROM facts GROUP BY status;"
```

Зафиксировать поля (title, content_summary/summary, tags, source_file, type, status и т.д.).

- [ ] **Step 2: Собрать каталог (формат скиллов)**

Скриптом (python3 + sqlite3, без новых зависимостей) сгенерировать каталог: для каждого verified/подтверждённого факта строка `**{title}** — {description_1строка}; читать: {source_file}`. Замерить: символы (`wc -c`), токены (approx: chars/4 для EN/RU смеси — указать метод), строк, время генерации.

- [ ] **Step 3: Замерить сравниваемые представления**

- PERSONAL_SETUP.md целиком: `wc -c ~/Documents/AI/personal/PERSONAL_SETUP.md`
- Типичный вывод `curator get "<тема>"` (3-5 запросов по реальным темам: compose, mvi, code-review): снять размер вывода каждого
- Полный дамп одного факта: `curator get` по точному заголовку

- [ ] **Step 4: Синтетическое масштабирование**

Сгенерировать каталоги на N = 100 / 500 / 1000 фактов (копии реальных строк с суффиксом номера — только для замера размера, в отчёт, не в базу). Замерить размер каталога на каждом N.

- [ ] **Step 5: Отчёт**

`docs/superpowers/reports/2026-09-16-read-path-sizes.md`: таблица «представление × N → символы / ~токены / время»; вывод: до какого N плоский каталог влезает в ~2K токенов (порог комфорта по образцу скилл-листов); рекомендация, с какого N нужна иерархия (секции → подтягивание по теме).

**Стоп-условие:** без изменений в knowledge.db (read-only к базе); создан только отчёт.

---

### Task 5: Дизайн эксперимента «A/B/C/D» (следующий план)

**Executor: сильная модель. Отдельный план по образцу benchmark/application.**

- [ ] **Step 1:** Взять результаты Task 4 (размеры) и benchmark/application (методология: дискриминирующие задачи, детерминированные чеки, frozen sha, повторы).
- [ ] **Step 2:** Составить план эксперимента: руки A/B/C/D из direction-дока, каждая рука — отдельный прогон, комбинации запрещены; задачи-ловушки из мигрированной базы; метрики (прочитано/применено/повтор/ложное/контекст/стоимость).
- [ ] **Step 3:** Утвердить у пользователя, сохранить как `docs/superpowers/plans/2026-09-XX-delivery-experiment.md`.

---

### Task 6: Выпил xmemory (гейт: после эксперимента)

**Executor: сначала сильная модель (план удаления), затем BF glm-5.3 (исполнение). Запускать только после Task 5-результатов.**

Ориентиры (детализировать в отдельном плане на момент запуска):
- убрать `core/curator/backend/xmemory*` + offline-outbox для xmemory;
- `MEMORY_BACKEND=local` — единственный путь;
- legacy SyncEngine/`curator sync` — по факту использования;
- обновить installer, README, getting-started, тесты (падение пула тестов недопустимо);
- ревью diff — только сильная модель.

---

## Порядок и гейты

```text
Task 1 (BF, read-only)
  → Task 2 (сильная: ревью карты)  ← ГЕЙТ
  → Task 3 (BF: миграция)
  → Task 4 (BF: замеры; можно параллельно Task 1-3)
  → Task 5 (сильная: дизайн эксперимента)  ← ГЕЙТ (утверждение пользователем)
  → [эксперимент] → Task 6 (выпил xmemory)
```

После каждого BF-пакета: ревью diff сильной моделью до следующего пакета.
