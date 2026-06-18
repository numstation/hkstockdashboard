#!/usr/bin/env python3
"""Close open 入市推介 rows that hit stop/take-profit rules (no Flask deps)."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from portfolio_reconcile import (  # noqa: E402
    consolidate_closed_transactions,
    is_open_signal,
    position_slot,
    reconcile_signals_history,
    _holding_days,
    _pnl_pct_underlying,
    _to_number,
)

SCAN_FILES = {
    "sell_put": "daily_scan_sell_put.json",
    "buy_stock": "daily_scan_buy_stock.json",
    "buy_put": "daily_scan_buy_put.json",
}

MODEL_LABELS = {
    "sell_put": "sell_put",
    "buy_stock": "buy_stock",
    "buy_put": "buy_put",
}


def _bearish(sig: dict) -> bool:
    return str(sig.get("action", "")).upper() == "BUY_PUT"


def _exit_decision(position: dict) -> dict:
    strategy = str(position.get("strategy") or "").strip().lower()
    entry = _to_number(position.get("entry_price"))
    current = _to_number(position.get("current_price"))
    atr = _to_number(position.get("atr"))
    hold = _to_number(position.get("holding_days")) or 0
    entry_vwap = _to_number(position.get("entry_vwap"))
    current_score = _to_number(position.get("current_score"))
    if entry is None or entry <= 0 or current is None:
        return {"triggered": False}
    pnl_percent = ((float(current) - float(entry)) / float(entry)) * 100.0
    atr_safe = float(atr) if atr is not None and atr > 0 else float(entry) * 0.015
    vwap_base = float(entry_vwap) if entry_vwap is not None else float(entry)

    if strategy == "sell_put":
        if current < entry - (1.5 * atr_safe) or current < vwap_base:
            return {"triggered": True, "type": "stop_loss", "reason": "❌ 跌破防線止蝕 (Hit ATR / VWAP Base)"}
        if hold >= 10 and current >= entry:
            return {"triggered": True, "type": "take_profit", "reason": "🟢 止賺收租成功 (10D Theta Collected)"}
    elif strategy == "buy_stock":
        if pnl_percent <= -5.0 or (current_score is not None and current_score < 45):
            return {"triggered": True, "type": "stop_loss", "reason": "❌ 爆發失速止蝕 (Hit -5% / Score Decay)"}
        if pnl_percent >= 15.0 or current >= entry + (3.0 * atr_safe):
            return {"triggered": True, "type": "take_profit", "reason": "🚀 動能衝頂食糊 (Hit +15% / 3x ATR)"}
    elif strategy == "buy_put":
        if hold >= 5 and current >= entry * 0.98:
            return {"triggered": True, "type": "stop_loss", "reason": "❌ 橫盤 Theta 虛耗強制止蝕 (5D Time Penalty)"}
        if current > vwap_base or pnl_percent >= 3.0:
            return {"triggered": True, "type": "stop_loss", "reason": "❌ 假跌破夾淡倉止蝕 (VWAP / +3% Reversal)"}
        if pnl_percent <= -10.0 or current <= entry - (2.0 * atr_safe):
            return {"triggered": True, "type": "take_profit", "reason": "🔥 殺跌暴賺食糊 (Short Gamma Profit)"}
    return {"triggered": False}


def _load_scan() -> dict[str, dict[str, dict]]:
    out: dict[str, dict[str, dict]] = {}
    for model, fname in SCAN_FILES.items():
        path = ROOT / fname
        per: dict[str, dict] = {}
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            for row in data.get("stocks") or []:
                if isinstance(row, dict):
                    sym = str(row.get("ticker", row.get("Ticker", ""))).strip().upper()
                    if sym:
                        per[sym] = row
        out[model] = per
    return out


def close_stale(
    *,
    signals_path: Path,
    closed_path: Path,
    before_entry: str | None = None,
    dry_run: bool = False,
) -> int:
    now = datetime.now().astimezone()
    today = now.date().isoformat()
    now_str = now.isoformat(timespec="seconds")

    sig_payload = json.loads(signals_path.read_text(encoding="utf-8"))
    closed_payload = json.loads(closed_path.read_text(encoding="utf-8"))
    signals = sig_payload.get("signals") or []
    closed_rows = closed_payload.get("closed") or []
    scan_by_model = _load_scan()

    key_set = {str(c.get("_key")) for c in closed_rows if isinstance(c, dict) and c.get("_key")}
    new_closed = 0

    open_by_slot: dict[str, list] = {}
    for sig in signals:
        if isinstance(sig, dict) and is_open_signal(sig):
            open_by_slot.setdefault(position_slot(sig), []).append(sig)

    for _slot, opens in open_by_slot.items():
        opens.sort(key=lambda s: str(s.get("entry_date") or s.get("date") or "")[:10])
        sig = opens[0]
        model = str(sig.get("score_model") or "").strip().lower()
        if model not in SCAN_FILES:
            continue
        action = str(sig.get("action") or "").strip()
        if not action:
            continue
        entry_date = str(sig.get("entry_date") or str(sig.get("date", ""))[:10])[:10]
        if before_entry and entry_date > before_entry:
            continue
        sym = str(sig.get("ticker", "")).strip().upper()
        if not sym:
            continue
        row = scan_by_model.get(model, {}).get(sym, {})
        entry_price = _to_number(sig.get("entry_price", sig.get("close")))
        current_price = _to_number(row.get("close", row.get("Close")))
        if current_price is None:
            current_price = _to_number(sig.get("latest_price"))
        if entry_price is None or current_price is None:
            continue
        holding_days = _to_number(sig.get("holding_days"))
        if holding_days is None or holding_days <= 0:
            holding_days = _holding_days(entry_date, today)
        if holding_days is None or holding_days <= 0:
            continue
        atr = _to_number(sig.get("atr")) or _to_number(row.get("atr", row.get("ATR")))
        entry_vwap = _to_number(sig.get("entry_vwap")) or _to_number(row.get("vwap", row.get("VWAP"))) or entry_price
        current_score = _to_number(row.get("tech_score", sig.get("score")))
        pos = {
            "strategy": model,
            "entry_price": entry_price,
            "current_price": current_price,
            "atr": atr,
            "holding_days": holding_days,
            "entry_vwap": entry_vwap,
            "current_score": current_score,
        }
        decision = _exit_decision(pos)
        if not decision.get("triggered"):
            continue
        key = f"{entry_date}|{sym}|{action.upper()}|{model}"
        if key in key_set:
            for o in opens:
                o["status"] = "closed"
            continue
        pnl = _pnl_pct_underlying(float(entry_price), float(current_price), bearish=_bearish(sig))
        closed_rows.append(
            {
                "_key": key,
                "exit_date": today,
                "entry_date": entry_date,
                "ticker": sym,
                "score_model": model,
                "strategy_label": MODEL_LABELS.get(model, model),
                "action": sig.get("action"),
                "entry_price": round(float(entry_price), 4),
                "exit_price": round(float(current_price), 4),
                "final_pnl_pct": pnl,
                "holding_days": int(holding_days),
                "exit_type": decision.get("type"),
                "exit_reason": decision.get("reason"),
            }
        )
        key_set.add(key)
        new_closed += 1
        for o in opens:
            o["status"] = "closed"
            o["closed_at"] = now_str
            o["exit_reason"] = decision.get("reason")
            o["exit_price"] = round(float(current_price), 4)
            o["exit_type"] = decision.get("type")

    signals, n_sup = reconcile_signals_history(signals)
    closed_rows = consolidate_closed_transactions(closed_rows)
    sig_payload["signals"] = signals
    sig_payload["last_updated"] = now_str
    closed_payload["closed"] = closed_rows
    closed_payload["last_updated"] = now_str

    if not dry_run:
        signals_path.write_text(json.dumps(sig_payload, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")
        closed_path.write_text(json.dumps(closed_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"Closed {new_closed} position(s); superseded {n_sup}; open signals now {sum(1 for s in signals if is_open_signal(s))}")
    return new_closed


def main() -> int:
    ap = argparse.ArgumentParser(description="Archive stale open 入市推介 entries")
    ap.add_argument("--signals", type=Path, default=ROOT / "signals_history.json")
    ap.add_argument("--closed", type=Path, default=ROOT / "closed_transactions.json")
    ap.add_argument("--before-entry", type=str, default=None, help="Only close entries on/before YYYY-MM-DD")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    close_stale(
        signals_path=args.signals,
        closed_path=args.closed,
        before_entry=args.before_entry,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
