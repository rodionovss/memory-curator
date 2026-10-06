"""Routing module — контракт и реализации.

Кастомный роутер подключается через ROUTER_CLASS (см. interface.py —
контракт Router). Дефолт (0.5.0): карта в базе есть → MapRouter,
нет → DefaultRouter. До 0.5.0 MapRouter требовал ROUTER_CLASS - в проде
env не был задан, роутер по карте молча не работал и факты уезжали
в session/ (найдено смоуком 06.10).
"""

from curator.routing.interface import Router
from curator.routing.default import DefaultRouter


def get_router() -> Router:
    import os
    import sys
    import importlib
    cls_path = os.getenv("ROUTER_CLASS", "")
    if cls_path and "." in cls_path:
        try:
            mod_name, cls_name = cls_path.rsplit(".", 1)
            mod = importlib.import_module(mod_name)
            router_cls = getattr(mod, cls_name)
            return router_cls()
        except Exception as e:
            # Откат на DefaultRouter допустим, но деградация обязана быть видимой:
            # иначе опечатка в ROUTER_CLASS молча перенаправляет все факты в session/
            print(f"[curator] ROUTER_CLASS '{cls_path}' не загрузился: {e} — использую DefaultRouter",
                  file=sys.stderr)
            return DefaultRouter()
    # Дефолт: карта базы есть → MapRouter (невалидная карта внутри него
    # деградирует на DefaultRouter с заметкой); карты нет → DefaultRouter
    from curator.routing.map_router import MapRouter, find_map_path
    if find_map_path() is not None:
        return MapRouter()
    return DefaultRouter()


def route_fact_safe(router: Router, fact) -> str:
    """route_fact с изоляцией сбоя стороннего роутера: исключение роутера
    отправляет факт на дефолтный маршрут вместо обрушения батча сохранения."""
    try:
        return router.route_fact(fact)
    except Exception as e:
        import sys
        print(f"[curator] router упал на '{getattr(fact, 'title', '?')}': {e} — маршрут DefaultRouter",
              file=sys.stderr)
        return DefaultRouter().route_fact(fact)