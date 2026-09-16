"""Критерии блока xmemory — design/requirements.md, «Критерии блока xmemory».

| ID | Требование | Источник |
|----|-----------|----------|
| X1 | Значимый цикл write → read и durability | xmemory #1 (smoke — требует VPN) |
| X2 | Схема под задачу | xmemory #2 |
| X3 | xmemory как часть продукта (primary backend) | xmemory #3 |
| X4 | Наглядность результата | xmemory #4 |
"""

import os
import time
from pathlib import Path

import pytest

from curator.backend.local import LocalBackend
from curator.models import StructuredFact, FactQuery
import curator.server as server_mod

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "xmd_kb.yaml"


class TestXmemoryCriteria:
    @pytest.mark.skipif(
        not os.getenv("XMEMORY_API_KEY") or not os.getenv("XMEMORY_INSTANCE_ID"),
        reason="Требуется VPN + XMEMORY_API_KEY / XMEMORY_INSTANCE_ID",
    )
    def test_X1_durability_write_read(self):
        """X1: write → новый инстанс (рестарт) → read: данные в xmemory на месте."""
        from curator.backend.xmemory import XMemoryBackend

        key = os.environ["XMEMORY_API_KEY"]
        inst = os.environ["XMEMORY_INSTANCE_ID"]
        title = f"Durability smoke {int(time.time())}"

        XMemoryBackend(api_key=key, instance_id=inst).store_fact(StructuredFact(
            type="Reference", title=title, tags=["smoke"], status="verified",
            content_summary="Проверка durability: запись и чтение через разные инстансы бэкенда.",
        ))

        restarted = XMemoryBackend(api_key=key, instance_id=inst)
        found = restarted.query_facts(FactQuery(search=title[:24]))
        assert any(f.title == title for f in found), "факт обязан пережить «рестарт» в xmemory"

    def test_X2_схема_под_задачу(self):
        """X2: XMD-схема валидна — required поля, enum статусов, primary_key по title."""
        import yaml

        schema = yaml.safe_load(SCHEMA_PATH.read_text(encoding="utf-8"))

        assert "objects" in schema
        for name in ("Reference", "Style"):
            obj = schema["objects"][name]
            assert obj["primary_key"] == ["title"], f"{name}: natural key = title (детерминированный dedup)"
            fields = obj["fields"]
            for required_field in ("title", "tags", "status", "content_summary"):
                assert fields[required_field].get("required") is True, \
                    f"{name}.{required_field} обязано быть required"
            assert set(fields["status"]["enum"]) == {"verified", "hypothesis", "deprecated"}

        assert "reference_contradicts" in schema["relations"], "схема описывает противоречия"

    def test_X3_xmemory_primary_backend(self, monkeypatch):
        """X3: MEMORY_BACKEND=xmemory → активен XMemoryBackend; local — fallback."""
        from curator.backend.xmemory import XMemoryBackend

        monkeypatch.setenv("MEMORY_BACKEND", "xmemory")
        monkeypatch.setenv("XMEMORY_API_KEY", "key")
        monkeypatch.setenv("XMEMORY_INSTANCE_ID", "inst")
        assert isinstance(server_mod._get_backend(), XMemoryBackend)

        monkeypatch.setenv("MEMORY_BACKEND", "local")
        assert isinstance(server_mod._get_backend(), LocalBackend)

    def test_X4_наглядность_статуса(self, server_memory):
        """X4: curator_status показывает счётчики — рост базы виден."""
        assert "Всего фактов: 0" in server_mod._status()

        server_memory.store_fact(StructuredFact(
            type="Reference", title="Правило для наглядного статуса базы знаний",
            tags=["status"], status="verified",
            content_summary="Факт для проверки счётчиков статуса базы.",
        ))
        out = server_mod._status()
        assert "Всего фактов: 1" in out
        assert "Reference" in out
        assert "verified" in out
