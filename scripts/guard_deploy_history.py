#!/usr/bin/env python3
"""
Block deploy if bundled JSON would shrink dashboard history vs live site.

Prevents the loop: fix scan → deploy → breadth loses 25–28 May → user reports → repeat.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE_URL = os.environ.get("DASHBOARD_BASE_URL", "https://hkstockdashboard.chrislau.workers.dev").rstrip("/")
UA = "Mozilla/5.0 (compatible; backtest-dashboard-guard/1.0)"


def _fetch(url_path: str) -> dict | None:
    import time

    sep = "&" if "?" in url_path else "?"
    url = f"{BASE_URL}{url_path}{sep}_={int(time.time())}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Cache-Control": "no-cache, no-store",
            "Pragma": "no-cache",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            raw = resp.read().decode("utf-8")
            if raw.lstrip().startswith("<"):
                return None
            return json.loads(raw)
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError):
        return None


def _read(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _sell_put_dates(payload: dict | None) -> set[str]:
    if not isinstance(payload, dict):
        return set()
    out: set[str] = set()
    for entry in payload.get("days") or []:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("model") or "") != "sell_put":
            continue
        d = str(entry.get("date") or "")[:10]
        if len(d) == 10:
            out.add(d)
    return out


def _check_breadth(label: str, live_path: str, local_path: Path) -> list[str]:
    live = _fetch(live_path)
    local = _read(local_path)
    live_dates = _sell_put_dates(live)
    local_dates = _sell_put_dates(local)
    if not live_dates:
        print(f"[guard] {label}: no live breadth (skip regression check)")
        return []
    lost = sorted(live_dates - local_dates)
    if lost:
        return [f"{label}: would drop sell_put dates {lost} (live={len(live_dates)} local={len(local_dates)})"]
    print(f"[guard] {label}: OK — local has all {len(live_dates)} live sell_put dates (+{len(local_dates - live_dates)} new)")
    return []


def _parse_last_updated(payload: dict | None) -> datetime | None:
    if not isinstance(payload, dict):
        return None
    raw = payload.get("last_updated")
    if raw is None:
        return None
    s = str(raw).strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _scan_trading_day(payload: dict | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    scan = payload.get("scan")
    if not isinstance(scan, dict):
        return None
    day = str(scan.get("score_today_date") or "")[:10]
    return day if len(day) == 10 else None


def _check_us_scan_regression() -> list[str]:
    live = _fetch("/frontend-us/data/daily_scan_us.json")
    local = _read(ROOT / "frontend-us" / "data" / "daily_scan_us.json")
    if not isinstance(live, dict) or not isinstance(local, dict):
        return []
    live_ts = _parse_last_updated(live)
    local_ts = _parse_last_updated(local)
    live_day = _scan_trading_day(live)
    local_day = _scan_trading_day(local)
    if live_ts and local_ts and local_ts + timedelta(minutes=2) < live_ts:
        return [
            "US daily_scan_us.json: would downgrade "
            f"(live {live.get('last_updated')} → bundle {local.get('last_updated')})"
        ]
    if live_day and local_day and local_day < live_day:
        return [
            "US daily_scan_us.json: would downgrade trading day "
            f"(live score_today_date={live_day} → bundle {local_day})"
        ]
    print(
        f"[guard] US scan: OK — bundle {local.get('last_updated')} "
        f"day={local_day} (live {live.get('last_updated')} day={live_day})"
    )
    return []


def main() -> int:
    if os.environ.get("ALLOW_HISTORY_REGRESSION", "").strip() in ("1", "true", "yes"):
        print("[guard] ALLOW_HISTORY_REGRESSION set — skipped")
        return 0

    errors: list[str] = []
    errors.extend(
        _check_breadth(
            "HK breadth",
            "/frontend/data/breadth_daily_history.json",
            ROOT / "frontend" / "data" / "breadth_daily_history.json",
        )
    )
    errors.extend(
        _check_breadth(
            "US breadth",
            "/frontend-us/data/breadth_daily_history_us.json",
            ROOT / "frontend-us" / "data" / "breadth_daily_history_us.json",
        )
    )
    errors.extend(_check_us_scan_regression())

    if errors:
        for e in errors:
            print(f"[guard] ERROR: {e}", file=sys.stderr)
        print(
            "[guard] Deploy aborted — run merge + ensure_recent_breadth, or set ALLOW_HISTORY_REGRESSION=1 to override",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
