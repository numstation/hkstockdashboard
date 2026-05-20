#!/usr/bin/env python3
"""Fail CI if scan JSON is mostly empty (fetch_failed) — avoids deploying bad data."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIN_OK = 50


def check(path: Path) -> tuple[int, int, str | None]:
    if not path.is_file():
        return 0, 0, "missing"
    data = json.loads(path.read_text(encoding="utf-8"))
    stocks = data.get("stocks") if isinstance(data, dict) else None
    if not isinstance(stocks, list):
        return 0, 0, "no stocks list"
    ok = sum(1 for s in stocks if isinstance(s, dict) and s.get("data_ok"))
    return ok, len(stocks), data.get("last_updated")


def main() -> int:
    files = [
        ROOT / "daily_scan_sell_put.json",
        ROOT / "daily_scan.json",
    ]
    failed = False
    for path in files:
        ok, total, lu = check(path)
        print(f"{path.name}: data_ok={ok}/{total} last_updated={lu}")
        if ok < MIN_OK:
            print(f"  ERROR: need at least {MIN_OK} data_ok rows", file=sys.stderr)
            failed = True
        scan = json.loads(path.read_text(encoding="utf-8")).get("scan") or {}
        if not scan.get("score_d1_date") and not scan.get("score_d2_date"):
            print("  WARN: missing score_d1_date / score_d2_date (3-day scores)", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
