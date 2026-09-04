#!/usr/bin/env python3
"""Repair signals_history.json + closed_transactions.json (dedupe daily re-triggers)."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from portfolio_reconcile import consolidate_closed_transactions, reconcile_signals_history, supersede_opens_covered_by_closed  # noqa: E402

PAIRS = (
    (ROOT / "signals_history.json", ROOT / "closed_transactions.json"),
    (ROOT / "signals_history_us.json", ROOT / "closed_transactions_us.json"),
    (ROOT / "frontend/data/signals_history.json", ROOT / "frontend/data/closed_transactions.json"),
    (ROOT / "frontend-us/data/signals_history_us.json", ROOT / "frontend-us/data/closed_transactions_us.json"),
)


def _repair(sig_path: Path, closed_path: Path) -> None:
    if not sig_path.is_file() or not closed_path.is_file():
        print(f"skip missing {sig_path.name} / {closed_path.name}")
        return
    sig_payload = json.loads(sig_path.read_text(encoding="utf-8"))
    closed_payload = json.loads(closed_path.read_text(encoding="utf-8"))
    signals = sig_payload.get("signals") or []
    closed = closed_payload.get("closed") or []

    before_s = len(signals)
    before_c = len(closed)
    signals, n_sup = reconcile_signals_history(signals)
    n_cover = supersede_opens_covered_by_closed(signals, closed)
    if n_cover:
        signals, n2 = reconcile_signals_history(signals)
        n_sup += n_cover + n2
    closed = consolidate_closed_transactions(closed)
    now = datetime.now().astimezone().isoformat(timespec="seconds")

    sig_payload["signals"] = signals
    sig_payload["last_updated"] = now
    closed_payload["closed"] = closed
    closed_payload["last_updated"] = now

    sig_path.write_text(json.dumps(sig_payload, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")
    closed_path.write_text(json.dumps(closed_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"{sig_path.name}: signals {before_s} → {len(signals)} (superseded {n_sup})")
    print(f"{closed_path.name}: closed  {before_c} → {len(closed)}")
    for model in ("buy_stock", "buy_put", "sell_put"):
        n = sum(1 for r in closed if r.get("score_model") == model)
        print(f"  {model}: {n}")


def main() -> int:
    for sig_path, closed_path in PAIRS:
        _repair(sig_path, closed_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
