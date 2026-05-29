#!/usr/bin/env python3
"""
Fill missing weekday rows in breadth history for the last N sessions (HK and/or US).

CI git checkout often lacks 25–28 May; merge alone cannot restore days that exist
nowhere. This rebuilds gaps from Yahoo so each deploy is self-healing.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

MARKET_BREADTH = {
    "HK": ROOT / "breadth_daily_history.json",
    "US": ROOT / "breadth_daily_history_us.json",
}


def _recent_weekdays(n: int) -> list[str]:
    """Last n calendar weekdays (Mon–Fri), oldest first."""
    out: list[str] = []
    cur = date.today()
    while len(out) < n:
        if cur.weekday() < 5:
            out.append(cur.isoformat())
        cur -= timedelta(days=1)
    return sorted(out)


def _sell_put_dates(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
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


def missing_days(path: Path, n: int) -> list[str]:
    have = _sell_put_dates(path)
    return [d for d in _recent_weekdays(n) if d not in have]


def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill missing recent breadth days from Yahoo.")
    ap.add_argument("--days", type=int, default=10, help="Look back this many weekdays")
    ap.add_argument("--market", choices=("HK", "US", "both"), default="both")
    ap.add_argument("--sleep", type=float, default=0.03)
    args = ap.parse_args()

    markets = ["HK", "US"] if args.market == "both" else [args.market.upper()]
    backfill = ROOT / "scripts" / "backfill_trading_day.py"
    py = sys.executable
    venv_py = ROOT / ".venv-scan" / "bin" / "python"
    if venv_py.is_file():
        py = str(venv_py)

    any_missing = False
    for market in markets:
        path = MARKET_BREADTH[market]
        gaps = missing_days(path, args.days)
        if not gaps:
            print(f"[ensure] {market} breadth: complete for last {args.days} weekdays")
            continue
        any_missing = True
        print(f"[ensure] {market} breadth missing {len(gaps)} day(s): {gaps}")
        for day in gaps:
            cmd = [
                py,
                str(backfill),
                "--date",
                day,
                "--market",
                market,
                "--breadth-only",
                "--sleep",
                str(max(0.0, args.sleep)),
            ]
            print(f"[ensure] running: {' '.join(cmd)}")
            rc = subprocess.call(cmd, cwd=str(ROOT))
            if rc != 0:
                print(f"[ensure] WARN: backfill {market} {day} exited {rc}", file=sys.stderr)

    return 0 if not any_missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
