"""Тесты routing: Router Protocol, DefaultRouter, get_router."""

from curator.routing.interface import Router
from curator.routing.default import DefaultRouter
from curator.routing import get_router
from curator.models import ProposedFact


def _fact(type="Reference", title="Test", tags=None):
    return ProposedFact(type=type, title=title, content_summary="x" * 20, tags=tags or ["test"])


class TestDefaultRouter:
    def test_route_reference(self):
        r = DefaultRouter()
        path = r.route_fact(_fact("Reference"))
        assert path == "session/reference.md"

    def test_route_style(self):
        r = DefaultRouter()
        path = r.route_fact(_fact("Style"))
        assert path == "session/style.md"

    def test_list_routes(self):
        r = DefaultRouter()
        routes = r.list_routes()
        assert len(routes) == 1
        assert routes[0]["path"] == "session/"

    def test_reload_noop(self):
        r = DefaultRouter()
        r.reload()


class TestRouterProtocol:
    def test_default_is_protocol(self):
        r = DefaultRouter()
        assert isinstance(r, Router)

class TestGetRouter:
    def test_returns_default_when_no_env(self, tmp_path, monkeypatch):
        # изоляция от прод-env: launchd задаёт CURATOR_BASE_DIR глобально,
        # без очистки find_map_path нашёл бы прод-карту и вернул MapRouter
        monkeypatch.delenv("ROUTER_CLASS", raising=False)
        monkeypatch.delenv("CURATOR_MAP", raising=False)
        monkeypatch.setenv("CURATOR_BASE_DIR", str(tmp_path))
        r = get_router()
        assert isinstance(r, DefaultRouter)

    def test_returns_default_when_invalid_class(self):
        import os
        os.environ["ROUTER_CLASS"] = "nonexistent.module.NoSuchClass"
        r = get_router()
        assert isinstance(r, DefaultRouter)
        del os.environ["ROUTER_CLASS"]

    def test_invalid_class_logs_to_stderr(self, capsys):
        """Регрессия ревью: тихий откат на DefaultRouter прятал опечатку в
        ROUTER_CLASS — деградация обязана быть видимой."""
        import os
        os.environ["ROUTER_CLASS"] = "nonexistent.module.NoSuchClass"
        try:
            r = get_router()
            assert isinstance(r, DefaultRouter)
            err = capsys.readouterr().err
            assert "ROUTER_CLASS" in err
            assert "DefaultRouter" in err
        finally:
            del os.environ["ROUTER_CLASS"]