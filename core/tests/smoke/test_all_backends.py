"""Smoke tests: локальный backend жив."""

from curator.backend.interface import MemoryBackend
from curator.backend.local import LocalBackend


class TestAllBackendsHealth:
    def test_local_healthy(self):
        be = LocalBackend(":memory:")
        assert be.health_check()

    def test_protocol_compliance_local(self):
        be = LocalBackend(":memory:")
        assert isinstance(be, MemoryBackend)
