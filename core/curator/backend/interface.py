from typing import Protocol, runtime_checkable
from curator.models import StructuredFact, FactQuery, FactRef, Relation, GraphData


@runtime_checkable
class MemoryBackend(Protocol):
    """Агностик к провайдеру памяти. LocalBackend (SQLite) — единственная реализация."""

    def store_fact(self, fact: StructuredFact) -> FactRef:
        """Сохранить валидированный факт. Возвращает ссылку."""
        ...

    def query_facts(self, query: FactQuery) -> list[StructuredFact]:
        """Найти факты по фильтрам: type, tags, status, search."""
        ...

    def get_relations(self, fact_id: str) -> list[Relation]:
        """Все связи факта (исходящие и входящие)."""
        ...

    def get_graph(self) -> GraphData:
        """Весь граф для визуализации."""
        ...

    def health_check(self) -> bool:
        """Жив ли бэкенд."""
        ...

    def find_similar(self, fact: StructuredFact, threshold: float = 0.7) -> list[StructuredFact]:
        """Найти похожие факты (для dedup)."""
        ...