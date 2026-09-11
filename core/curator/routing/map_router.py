"""MapRouter: маршрутизация фактов по карте документации.

Карта — формат скилла mapping-documentation (Егор): frontmatter с
topics[name, watch_for, targets[path/captures/mode/instructions]].
Наша попытка интеграции — детерминированная: LLM в ядре нет, prose-сегменты
watch_for (с пробелами) не парсим (это инструкция агенту); сегменты
БЕЗ пробелов — теги-токены и участвуют в матчинге (теги ∩ токены).

Порядок решения:
1. source_file, предложенный агентом (скилл разрулил glob-таргет):
   валидируем против таргетов карты (fnmatch); не совпал — не верим.
2. Теги факта ∩ токены темы (имя темы + watch_for-сегменты без пробелов,
   без and/or-семантики, просто токены). При равенстве пересечений
   побеждает тема, объявленная раньше в карте.
3. Явное поле types в теме (наш словарь фактов) — расширение формата,
   «явное вместо выведенного»: карта сама говорит, каким типам сюда.
4. Тема с glob-таргетами — ядро не угадывает, какой файл «подходящий»:
   это работа агента/скилла (report + дефолт).
5. on_unmatched: report → stderr + дефолт session/{type}.md.

Подключение: ROUTER_CLASS=curator.routing.map_router.MapRouter
Карта: env CURATOR_MAP → <CURATOR_BASE_DIR>/DOCUMENTATION-MAP.md
"""

import fnmatch
import os
import re
import sys
from pathlib import Path

from curator.models import ProposedFact
from curator.routing.default import DefaultRouter

VALID_MODES = ("update", "append", "readonly")


def _map_path() -> Path | None:
    env = os.getenv("CURATOR_MAP", "").strip()
    if env:
        return Path(env).expanduser()
    base = os.getenv("CURATOR_BASE_DIR", "").strip()
    if base:
        candidate = Path(base).expanduser() / "DOCUMENTATION-MAP.md"
        if candidate.exists():
            return candidate
    return None


def _note(message: str) -> None:
    # Видимая деградация — как в get_router(): молчаливый откат
    # перенаправил бы факты непонятно куда
    print(f"[curator] карта: {message}", file=sys.stderr)


def target_modes(map_path: Path) -> list[tuple[str, str]]:
    """(glob, mode) всех таргетов карты — write-back дисциплина SyncEngine."""
    router = MapRouter(map_path)
    return [(t.path, t.mode) for t in router._all_targets]


class _Target:
    __slots__ = ("path", "mode", "is_glob")

    def __init__(self, path: str, mode: str):
        self.path = path
        self.mode = mode
        self.is_glob = any(ch in path for ch in "*?[")


class _Topic:
    __slots__ = ("name", "tokens", "types", "targets")

    def __init__(self, name: str, tokens: set[str], types: set[str], targets: list[_Target]):
        self.name = name
        self.tokens = tokens
        self.types = types
        self.targets = targets


class MapRouter:
    """Роутер по карте. Невалидная/отсутствующая карта — видимая деградация
    на дефолт session/{type}.md, батч сохранения не валится."""

    def __init__(self, map_path: Path | None = None):
        self._default = DefaultRouter()
        path = map_path if map_path is not None else _map_path()
        if path is None or not path.exists():
            if path is not None:
                _note(f"карта не найдена: {path} — дефолт session/{{type}}.md")
            self._topics: list[_Topic] = []
            self._all_targets: list[_Target] = []
            return
        topics, targets, errors = self._parse(path)
        self._topics = topics
        self._all_targets = targets
        if errors:
            shown = "; ".join(errors[:3])
            more = f" (+{len(errors) - 3})" if len(errors) > 3 else ""
            _note(f"карта {path.name}: {len(errors)} ошибок валидации: {shown}{more} "
                  f"— проблемные элементы пропущены")

    def route_fact(self, fact: ProposedFact) -> str:
        # 1. Путь от агента: доверяем, если он совпал с таргетом карты
        # (sandbox-безопасность проверяет SyncEngine._resolve_md_path)
        if fact.source_file:
            if not self._all_targets:
                return fact.source_file  # карты нет — sandbox проверит sync
            if any(self._matches(fact.source_file, t.path) for t in self._all_targets):
                return fact.source_file
            _note(f"путь от агента '{fact.source_file}' не совпал ни с одним "
                  f"таргетом карты — маршрутизируем по правилам")

        # 2. Теги ∩ токены имени темы
        if fact.tags:
            tag_set = {t.lower() for t in fact.tags}
            best, best_overlap = None, 0
            for topic in self._topics:
                overlap = len(topic.tokens & tag_set)
                if overlap > best_overlap:
                    best, best_overlap = topic, overlap
            if best is not None:
                concrete = self._concrete_target(best)
                if concrete:
                    return concrete
                _note(f"тема '{best.name}' знает только glob-таргеты — какой "
                      f"файл 'подходящий', решает агент/скилл; факт в дефолт")

        # 3. Явные types темы (наш словарь, без перевода таксономий)
        for topic in self._topics:
            if fact.type in topic.types:
                concrete = self._concrete_target(topic)
                if concrete:
                    return concrete
                _note(f"тема '{topic.name}' (types) знает только glob-таргеты — факт в дефолт")

        # 4. on_unmatched: report — честный дефолт вместо угадывания
        _note(f"нет темы для '{fact.title[:50]}' — дефолт session/{fact.type.lower()}.md")
        return self._default.route_fact(fact)

    def list_routes(self) -> list[dict]:
        if not self._topics:
            return self._default.list_routes()
        routes = []
        for topic in self._topics:
            for target in topic.targets:
                extra = []
                if topic.types:
                    extra.append("types: " + ", ".join(sorted(topic.types)))
                routes.append({
                    "path": f"{target.path} (mode: {target.mode})",
                    "type": topic.name,
                    "description": f"тема карты{'; ' + '; '.join(extra) if extra else ''}",
                })
        return routes

    def reload(self):
        self.__init__()

    @staticmethod
    def _matches(source: str, pattern: str) -> bool:
        return fnmatch.fnmatch(source, pattern)

    @staticmethod
    def _concrete_target(topic: _Topic) -> str | None:
        for target in topic.targets:
            if not target.is_glob:
                return target.path
        return None

    def _parse(self, path: Path) -> tuple[list[_Topic], list[_Target], list[str]]:
        import yaml

        errors: list[str] = []
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as e:
            return [], [], [f"не читается: {e}"]
        if not content.startswith("---"):
            return [], [], ["нет YAML frontmatter"]
        end = content.find("\n---", 3)
        if end == -1:
            return [], [], ["frontmatter не закрыт"]
        try:
            data = yaml.safe_load(content[4:end])
        except yaml.YAMLError as e:
            return [], [], [f"YAML не парсится: {e}"]
        if not isinstance(data, dict):
            return [], [], ["frontmatter не словарь"]

        if "topics" not in data:
            # структурно битая карта (например, topics в теле после frontmatter)
            # — это маршрутная карта, молчать нельзя: 0 тем были бы тихим откатом
            return [], [], ["frontmatter без ключа topics — карта не маршрутная "
                            "(topics должны быть ВНУТРИ frontmatter)"]
        topics_raw = data["topics"]
        if not isinstance(topics_raw, list):
            return [], [], ["topics не список"]

        topics: list[_Topic] = []
        all_targets: list[_Target] = []
        for i, t in enumerate(topics_raw, 1):
            if not isinstance(t, dict):
                errors.append(f"topic#{i} не словарь")
                continue
            name = str(t.get("name", "")).strip()
            if not name:
                errors.append(f"topic#{i} без name")
                continue
            targets_raw = t.get("targets", [])
            if not isinstance(targets_raw, list):
                errors.append(f"тема '{name}': targets не список")
                continue
            targets = []
            for j, tr in enumerate(targets_raw, 1):
                if not isinstance(tr, dict):
                    errors.append(f"тема '{name}': target#{j} не словарь")
                    continue
                tp = str(tr.get("path", "")).strip()
                mode = str(tr.get("mode", "update")).strip()
                if not tp:
                    errors.append(f"тема '{name}': target#{j} без path")
                    continue
                # path-safety: таргет строго внутри базы
                if tp.startswith("/") or ".." in tp or "\n" in tp or "\r" in tp:
                    errors.append(f"тема '{name}': path '{tp}' вне корня/некорректен")
                    continue
                if mode not in VALID_MODES:
                    errors.append(f"тема '{name}': mode '{mode}' не из {VALID_MODES}")
                    continue
                targets.append(_Target(tp, mode))
            types_raw = t.get("types", [])
            if isinstance(types_raw, str):
                types_raw = [types_raw]
            types = {str(x).strip() for x in types_raw if str(x).strip()} if isinstance(types_raw, list) else set()
            tokens = {tok for tok in re.split(r"[-_]+", name.lower()) if tok}
            # watch_for: сегменты без пробелов — теги-токены (наш формат карты);
            # prose-сегменты (с пробелами) — инструкция агенту, в матчинге не участвуют
            for seg in str(t.get("watch_for", "") or "").strip().split(","):
                seg = seg.strip().lower()
                if seg and " " not in seg:
                    tokens.add(seg)
            topic = _Topic(name, tokens, types, targets)
            topics.append(topic)
            all_targets.extend(targets)
        return topics, all_targets, errors
