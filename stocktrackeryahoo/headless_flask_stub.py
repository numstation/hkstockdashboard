"""
Minimal fake ``flask`` in ``sys.modules`` so ``app.py`` can be imported without
installing Flask (scanner + JSON export only use export helpers, not routes).
"""
from __future__ import annotations

import sys
import types


def install() -> None:
    if "flask" in sys.modules:
        return
    fake = types.ModuleType("flask")

    class Flask:
        def __init__(self, name: str) -> None:  # noqa: ARG002
            self.name = name

        def route(self, rule, **kwargs):  # noqa: ARG002
            def decorator(f):
                return f

            return decorator

        def after_request(self, f):
            return f

        def run(self, *args, **kwargs) -> None:  # noqa: ARG002
            pass

    fake.Flask = Flask
    fake.render_template = lambda *args, **kwargs: ""
    fake.request = types.SimpleNamespace(args={}, method="GET")
    fake.jsonify = lambda d=None: d
    sys.modules["flask"] = fake
