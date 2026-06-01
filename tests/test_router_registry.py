from __future__ import annotations

from types import SimpleNamespace

from igris.web import router_registry


class _FakeApp:
    def __init__(self) -> None:
        self.included = []

    def include_router(self, router) -> None:
        self.included.append(router)


def test_include_core_routers_uses_create_router(monkeypatch) -> None:
    app = _FakeApp()
    deps = object()

    def _fake_import(name: str):
        return SimpleNamespace(create_router=lambda d: (name, d))

    monkeypatch.setattr(router_registry.importlib, "import_module", _fake_import)
    router_registry.include_core_routers(app, deps, modules=("m1", "m2"))

    assert app.included == [("m1", deps), ("m2", deps)]


def test_include_optional_api_routers_best_effort(monkeypatch) -> None:
    app = _FakeApp()

    def _fake_import(name: str):
        if name == "bad.mod":
            raise ImportError("missing")
        return SimpleNamespace(router=f"router:{name}")

    monkeypatch.setattr(router_registry.importlib, "import_module", _fake_import)
    router_registry.include_optional_api_routers(
        app,
        routers=(("ok.mod", "router"), ("bad.mod", "router"), ("ok2.mod", "router")),
    )

    assert app.included == ["router:ok.mod", "router:ok2.mod"]
