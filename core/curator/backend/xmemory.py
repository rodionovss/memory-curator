"""xmemory REST API backend с offline-fallback (UC6).

Сетевые ошибки (ConnectError/timeout/5xx) при записи:
    факт → локальная файловая БД ($CURATOR_STATE_DIR/knowledge.db) + outbox-очередь.
    При восстановлении `curator sync` пушит outbox в xmemory.
Сетевые ошибки при чтении:
    деградация на локальную БД (может быть не полной — честное поведение).
Пустые ключи (нет кредов):
    in-memory fallback — только для тестов, персистентности нет.
"""

import threading

import httpx
from curator.models import StructuredFact, FactQuery, FactRef, Relation, GraphData
from curator.backend.local import LocalBackend
from curator.state import state_path


class XMemoryBackend:
    BASE_URL = "https://api.xmemory.ai"

    def __init__(
        self,
        api_key: str = "",
        instance_id: str | None = None,
        local_path: str | None = None,
        outbox_path: str | None = None,
    ):
        self._api_key = api_key
        self._instance_id = instance_id
        self._client = None
        self._no_credentials = not (api_key and instance_id)
        # Ленивая инициализация вызывается из to_thread — гонка создала бы
        # дубли LocalBackend/Outbox/httpx.Client на одних файлах
        self._init_lock = threading.Lock()

        # Персистентный fallback при сетевых ошибках (лениво).
        self._local_path = local_path or str(state_path("knowledge.db"))
        self._outbox_path = outbox_path or str(state_path("outbox.db"))
        self._offline: LocalBackend | None = None
        self._outbox = None

        # In-memory для режима без кредов (тесты).
        self._mem: LocalBackend | None = LocalBackend(":memory:") if self._no_credentials else None

    @property
    def _active(self) -> bool:
        return not self._no_credentials

    def _get_client(self) -> httpx.Client:
        if self._client is None and self._active:
            with self._init_lock:
                if self._client is None:
                    self._client = httpx.Client(
                        base_url=self.BASE_URL,
                        headers={
                            "Authorization": f"Bearer {self._api_key}",
                            "Content-Type": "application/json",
                        },
                        timeout=60.0,
                    )
        return self._client

    @staticmethod
    def _is_network_error(e: Exception) -> bool:
        """Сетевой сбой = деградация. 4xx — наша ошибка, не деградируем."""
        if isinstance(e, (httpx.ConnectError, httpx.TimeoutException)):
            return True
        if isinstance(e, httpx.HTTPStatusError):
            return e.response.status_code >= 500
        return False

    def _ensure_offline(self):
        if self._offline is None:
            with self._init_lock:
                if self._offline is None:
                    from curator.outbox import Outbox
                    local = LocalBackend(self._local_path)
                    outbox = Outbox(self._outbox_path)
                    # _offline — sentinel fast-path'а: публикуем ПОСЛЕДНИМ,
                    # чтобы конкурент не увидел его без готового _outbox
                    self._outbox = outbox
                    self._offline = local

    def _http_store(self, fact: StructuredFact) -> FactRef:
        text = self._fact_to_text(fact)
        resp = self._get_client().post(
            f"/instances/{self._instance_id}/write",
            json={"text": text, "extraction_logic": "fast"},
        )
        resp.raise_for_status()
        data = resp.json()
        write_id = data["items"][0]["write_id"]
        return FactRef(id=write_id, title=fact.title)

    def store_fact(self, fact: StructuredFact) -> FactRef:
        if self._mem:
            return self._mem.store_fact(fact)
        try:
            return self._http_store(fact)
        except Exception as e:
            if self._is_network_error(e):
                self._ensure_offline()
                self._outbox.enqueue(fact)
                return self._offline.store_fact(fact)
            raise

    def push_direct(self, fact: StructuredFact) -> FactRef:
        """HTTP-запись без failover — для `curator sync`. Сбой = исключение."""
        return self._http_store(fact)

    def query_facts(self, query: FactQuery) -> list[StructuredFact]:
        if self._mem:
            return self._mem.query_facts(query)
        try:
            nl_query = self._build_nl_query(query)
            resp = self._get_client().post(
                f"/instances/{self._instance_id}/read",
                json={"query": nl_query, "mode": "raw-tables"},
            )
            resp.raise_for_status()
            data = resp.json()
            result = data["items"][0].get("reader_result")

            if not result or not result.get("rows"):
                return []

            columns = [c["name"] for c in result["columns"]]
            return [self._row_to_fact(columns, row) for row in result["rows"]]
        except Exception as e:
            if self._is_network_error(e):
                self._ensure_offline()
                return self._offline.query_facts(query)
            raise

    def get_relations(self, fact_id: str) -> list[Relation]:
        if self._mem:
            return self._mem.get_relations(fact_id)
        return []

    def get_graph(self) -> GraphData:
        if self._mem:
            return self._mem.get_graph()
        facts = self.query_facts(FactQuery())
        return GraphData(nodes=facts, edges=[])

    def health_check(self) -> bool:
        if self._mem:
            return self._mem.health_check()
        try:
            resp = self._get_client().get("/healthz")
            return resp.is_success
        except Exception:
            return False

    def find_similar(self, fact: StructuredFact, threshold: float = 0.7) -> list[StructuredFact]:
        if self._mem:
            return self._mem.find_similar(fact, threshold)
        return self.query_facts(FactQuery(type=fact.type, search=fact.title[:50]))

    def _fact_to_text(self, fact: StructuredFact) -> str:
        tags = ", ".join(fact.tags)
        parts = [f"This is a {fact.type} object."]
        parts.append(f"Title: {fact.title}")
        parts.append(f"Summary: {fact.content_summary}")
        parts.append(f"Tags: {tags}")
        parts.append(f"Status: {fact.status}")
        if fact.source_file:
            parts.append(f"Source file: {fact.source_file}")
        if fact.source_session:
            parts.append(f"Session: {fact.source_session}")
        return "\n".join(parts)

    def _build_nl_query(self, query: FactQuery) -> str:
        obj_type = "facts"
        if query.type:
            obj_type = query.type + " objects"

        parts = [f"Show all {obj_type}"]
        conditions = []

        if query.status:
            conditions.append(f"with status {query.status}")
        if query.tags:
            tags = ", ".join(query.tags)
            conditions.append(f"tagged with any of: {tags}")
        if query.search:
            conditions.append(f"mentioning '{query.search}'")

        if conditions:
            parts.append(" that are " + " and ".join(conditions))

        parts.append(". Return fields: title, content_summary, tags, status, source_file, source_session, type.")
        return " ".join(parts)

    def _row_to_fact(self, columns: list[str], row: list) -> StructuredFact:
        data = dict(zip(columns, row))
        tags_str = data.get("tags", "")
        tags = [t.strip() for t in tags_str.split(",") if t.strip()] if tags_str else []
        fact_type = data.get("type", "Reference")
        fact_type = fact_type if isinstance(fact_type, str) and fact_type else "Reference"

        return StructuredFact(
            type=fact_type,
            title=str(data.get("title", "")),
            tags=tags,
            status=str(data.get("status", "verified")),
            content_summary=str(data.get("content_summary", "")),
            source_file=data.get("source_file"),
            source_session=data.get("source_session"),
        )
