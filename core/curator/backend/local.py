import sqlite3
import json
import threading
import uuid
import os
from curator.models import StructuredFact, FactQuery, FactRef, Relation, GraphData


class LocalBackend:
    """SQLite backend. Персистентный файл или :memory:, без API-ключей."""

    def __init__(self, db_path: str = "~/.curator/knowledge.db"):
        db_path = os.path.expanduser(db_path)
        self._memory = False
        # Сериализация доступа к одному соединению: MCP-хендлеры уходят в
        # asyncio.to_thread и могут выполняться конкурентно
        self._lock = threading.Lock()

        if db_path == ":memory:":
            self._memory = True
            self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        else:
            os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
            self._conn = sqlite3.connect(db_path, check_same_thread=False)
            self._db_path = db_path

        self._init_db()

    def _init_db(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS facts (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                title TEXT NOT NULL UNIQUE,
                tags TEXT NOT NULL,
                status TEXT NOT NULL,
                content_summary TEXT NOT NULL,
                source_file TEXT,
                source_session TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS relations (
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                PRIMARY KEY (source_id, target_id, kind)
            )
        """)
        # Легаси-БД: таблица могла быть создана старой схемой (title без
        # UNIQUE) — CREATE TABLE IF NOT EXISTS её не апгрейдит, и upsert
        # ON CONFLICT(title) падал. Самолечение уникальным индексом.
        try:
            self._conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_facts_title ON facts(title)")
        except sqlite3.IntegrityError:
            # Дубликаты в легаси-данных: индекс не строится, база читается
            # как есть (upsert для такой базы остаётся недоступен)
            pass
        self._conn.commit()

    def store_fact(self, fact: StructuredFact) -> FactRef:
        fact_id = str(uuid.uuid4())[:8]
        with self._lock:
            self._conn.execute(
                "INSERT INTO facts (id, type, title, tags, status, content_summary, source_file, source_session) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(title) DO UPDATE SET "
                "status=excluded.status, content_summary=excluded.content_summary, "
                "tags=excluded.tags, "
                "source_file=COALESCE(excluded.source_file, facts.source_file), "
                "source_session=COALESCE(excluded.source_session, facts.source_session), "
                "updated_at=datetime('now')",
                (fact_id, fact.type, fact.title, json.dumps(fact.tags), fact.status,
                 fact.content_summary, fact.source_file, fact.source_session)
            )
            # На конфликте UPSERT оставляет старый id — возвращаем реальный id строки
            row = self._conn.execute(
                "SELECT id FROM facts WHERE title = ?", (fact.title,)
            ).fetchone()
            self._conn.commit()
        return FactRef(id=row[0], title=fact.title)

    def query_facts(self, query: FactQuery) -> list[StructuredFact]:
        # type/status — узкие эквивалентные фильтры, остаются в SQL.
        # search и tags — в Python: SQLite LIKE регистронезависим только
        # для ASCII (кириллица не матчилась), а tags вообще не входили в
        # search (бенчмарк T09: факт, опознаваемый только тегами, не
        # находился). Персональная база — сотни строк, полный скан дешев.
        conditions = []
        params = []
        if query.type:
            conditions.append("type = ?")
            params.append(query.type)
        if query.status:
            conditions.append("status = ?")
            params.append(query.status)

        where = " AND ".join(conditions) if conditions else "1=1"
        sql = f"SELECT * FROM facts WHERE {where} ORDER BY created_at DESC"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()

        search = query.search.casefold() if query.search else None
        wanted_tags = {t.casefold() for t in query.tags} if query.tags else None

        result = []
        for row in rows:
            tags = json.loads(row[3])
            if search:
                haystacks = [row[2].casefold(), row[5].casefold()]
                haystacks += [t.casefold() for t in tags]
                if not any(search in h for h in haystacks):
                    continue
            if wanted_tags is not None:
                if not wanted_tags.intersection({t.casefold() for t in tags}):
                    continue
            result.append(StructuredFact(
                type=row[1], title=row[2], tags=tags,
                status=row[4], content_summary=row[5],
                source_file=row[6], source_session=row[7]
            ))
        return result

    def get_relations(self, fact_id: str) -> list[Relation]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT source_id, target_id, kind FROM relations WHERE source_id = ? OR target_id = ?",
                (fact_id, fact_id)
            ).fetchall()
        return [Relation(source_id=r[0], target_id=r[1], kind=r[2]) for r in rows]

    def get_graph(self) -> GraphData:
        with self._lock:
            facts = self._conn.execute("SELECT * FROM facts").fetchall()
            edges = self._conn.execute("SELECT source_id, target_id, kind FROM relations").fetchall()
        return GraphData(
            nodes=[StructuredFact(
                type=r[1], title=r[2], tags=json.loads(r[3]),
                status=r[4], content_summary=r[5]
            ) for r in facts],
            edges=[Relation(source_id=r[0], target_id=r[1], kind=r[2]) for r in edges]
        )

    def health_check(self) -> bool:
        try:
            with self._lock:
                self._conn.execute("SELECT 1")
            return True
        except Exception:
            return False

    def find_similar(self, fact: StructuredFact, threshold: float = 0.7) -> list[StructuredFact]:
        keywords = " ".join(fact.title.split()[:3])
        candidates = self.query_facts(FactQuery(type=fact.type, search=keywords))
        result = []
        for c in candidates:
            if c.title == fact.title:
                continue
            if self._title_similarity(fact.title, c.title) >= threshold:
                result.append(c)
        return result

    def _title_similarity(self, a: str, b: str) -> float:
        words_a = set(a.lower().split())
        words_b = set(b.lower().split())
        if not words_a or not words_b:
            return 0.0
        return len(words_a & words_b) / len(words_a | words_b)

    def add_relation(self, source_id: str, target_id: str, kind: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO relations (source_id, target_id, kind) VALUES (?, ?, ?)",
                (source_id, target_id, kind)
            )
            self._conn.commit()