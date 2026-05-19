#!/usr/bin/env python3
"""Sync signals_history.json triggers from existing daily_scan_*.json (no full rescan)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STOCKTRACKER = ROOT / "stocktrackeryahoo"
for p in (ROOT, STOCKTRACKER):
    ps = str(p)
    if ps not in sys.path:
        sys.path.insert(0, ps)

try:
    import flask  # noqa: F401
except ImportError:
    import headless_flask_stub  # noqa: E402

    headless_flask_stub.install()

spec = importlib.util.spec_from_file_location("scsp_web_app", STOCKTRACKER / "app.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

if __name__ == "__main__":
    n = mod.export_trade_signals_from_scan_files()
    print(f"Done. New triggers logged: {n} | ROOT={ROOT}")
