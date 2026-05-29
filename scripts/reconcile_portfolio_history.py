#!/usr/bin/env python3
"""Repair signals_history.json + closed_transactions.json (dedupe daily re-triggers)."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from portfolio_reconcile import consolidate_closed_transactions, reconcile_signals_history  # noqa: E402


def main() -> int:
    sig_path = ROOT / "signals_history.json"
    closed_path = ROOT / "closed_transactions.json"
    sig_payload = json.loads(sig_path.read_text(encoding="utf-8"))
    closed_payload = json.loads(closed_path.read_text(encoding="utf-8"))
    signals = sig_payload.get("signals") or []
    closed = closed_payload.get("closed") or []

    before_s = len(signals)
    before_c = len(closed)
    signals, n_sup = reconcile_signals_history(signals)
    closed = consolidate_closed_transactions(closed)
    now = datetime.now().astimezone().isoformat(timespec="seconds")

    sig_payload["signals"] = signals
    sig_payload["last_updated"] = now
    closed_payload["closed"] = closed
    closed_payload["last_updated"] = now

    sig_path.write_text(json.dumps(sig_payload, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")
    closed_path.write_text(json.dumps(closed_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"signals: {before_s} → {len(signals)} (superseded {n_sup})")
    print(f"closed:  {before_c} → {len(closed)}")
    for model in ("buy_stock", "buy_put", "sell_put"):
        n = sum(1 for r in closed if r.get("score_model") == model)
        print(f"  {model}: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
