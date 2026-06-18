"""Portfolio signal / closed-transaction dedupe (no Flask dependency)."""
from __future__ import annotations

from datetime import datetime


def _to_number(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if text.endswith("x"):
        text = text[:-1]
    if text.endswith("%"):
        text = text[:-1]
    try:
        return float(text)
    except Exception:
        return None


def _holding_days(entry_date: str, as_of_date: str) -> int | None:
    try:
        d0 = datetime.strptime(str(entry_date)[:10], "%Y-%m-%d").date()
        d1 = datetime.strptime(str(as_of_date)[:10], "%Y-%m-%d").date()
        return max((d1 - d0).days, 0)
    except Exception:
        return None


def _pnl_pct_underlying(entry: float, current: float, *, bearish: bool) -> float:
    if not entry:
        return 0.0
    raw = ((current - entry) / entry) * 100.0
    return round(-raw if bearish else raw, 2)


def position_slot(sig: dict) -> str:
    sym = str(sig.get("ticker", "")).strip().upper()
    model = str(sig.get("score_model", "")).strip().lower()
    return f"{sym}|{model}"


def is_open_signal(sig: dict) -> bool:
    st = str(sig.get("status", "open")).strip().lower()
    return st not in ("closed", "superseded")


def closed_exit_batch_key(sig: dict) -> tuple:
    ex = str(sig.get("exit_date") or sig.get("closed_at") or "")[:10]
    px = _to_number(sig.get("exit_price"))
    return (
        ex,
        round(float(px), 2) if px is not None else None,
        str(sig.get("exit_reason") or sig.get("exit_type") or ""),
    )


def reconcile_signals_history(signals: list) -> tuple[list, int]:
    if not signals:
        return [], 0
    by_slot: dict[str, list] = {}
    for s in signals:
        if isinstance(s, dict):
            by_slot.setdefault(position_slot(s), []).append(s)
    out: list = []
    superseded = 0
    for group in by_slot.values():
        group.sort(key=lambda x: str(x.get("entry_date") or x.get("date") or "")[:10])
        slot_open = False
        pending_closed: list = []

        def _flush_closed() -> None:
            nonlocal pending_closed, superseded
            if not pending_closed:
                return
            pending_closed.sort(key=lambda x: str(x.get("entry_date", ""))[:10])
            out.append(pending_closed[0])
            superseded += max(0, len(pending_closed) - 1)
            pending_closed = []

        for s in group:
            st = str(s.get("status", "open")).strip().lower()
            if st == "superseded":
                superseded += 1
                continue
            if st == "closed":
                slot_open = False
                if pending_closed and closed_exit_batch_key(pending_closed[-1]) == closed_exit_batch_key(s):
                    pending_closed.append(s)
                else:
                    _flush_closed()
                    pending_closed = [s]
                continue
            if slot_open:
                superseded += 1
                continue
            slot_open = True
            out.append(s)
        _flush_closed()
    out.sort(key=lambda x: str(x.get("entry_date") or x.get("date") or ""))
    return out, superseded


def consolidate_closed_transactions(closed_rows: list) -> list:
    """One closed row per ticker/model/exit day (earliest entry wins)."""
    groups: dict[tuple, list] = {}
    for r in closed_rows:
        if not isinstance(r, dict):
            continue
        gkey = (
            str(r.get("ticker", "")).upper(),
            str(r.get("score_model", "")).lower(),
            str(r.get("exit_date", ""))[:10],
        )
        groups.setdefault(gkey, []).append(r)
    out: list = []
    for rows in groups.values():
        rows.sort(key=lambda x: str(x.get("entry_date", ""))[:10])
        keeper = dict(rows[0])
        entry = str(keeper.get("entry_date", ""))[:10]
        exit_d = str(keeper.get("exit_date", ""))[:10]
        sym = str(keeper.get("ticker", "")).upper()
        model = str(keeper.get("score_model", "")).lower()
        action = str(keeper.get("action", "")).upper()
        ep = _to_number(keeper.get("entry_price"))
        xp = _to_number(keeper.get("exit_price"))
        hd = _holding_days(entry, exit_d)
        if hd is not None:
            keeper["holding_days"] = hd
        if ep is not None and xp is not None and float(ep) != 0:
            keeper["final_pnl_pct"] = _pnl_pct_underlying(
                float(ep), float(xp), bearish=(action == "BUY_PUT" or model == "buy_put")
            )
        keeper["_key"] = f"{entry}|{sym}|{action}|{model}"
        out.append(keeper)
    out.sort(key=lambda x: str(x.get("exit_date", "")))
    return out
