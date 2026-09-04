"""Portfolio signal / closed-transaction dedupe (no Flask dependency)."""
from __future__ import annotations

from datetime import datetime, timedelta


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


def _parse_day(value) -> datetime | None:
    text = str(value or "")[:10]
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d")
    except Exception:
        return None


def _holding_days(entry_date: str, as_of_date: str) -> int | None:
    d0 = _parse_day(entry_date)
    d1 = _parse_day(as_of_date)
    if d0 is None or d1 is None:
        return None
    return max((d1.date() - d0.date()).days, 0)


def trading_days_between(start_date: str, end_date: str) -> int:
    """Count weekdays in [start, end). Friday→Monday is 1."""
    d0 = _parse_day(start_date)
    d1 = _parse_day(end_date)
    if d0 is None or d1 is None or d1 <= d0:
        return 0
    cur = d0.date()
    end = d1.date()
    cnt = 0
    while cur < end:
        if cur.weekday() < 5:
            cnt += 1
        cur += timedelta(days=1)
    return cnt


def is_continuation_entry(prev_exit: str, new_entry: str) -> bool:
    """True if this entry is the same trade rolled forward after 平倉."""
    entry = str(new_entry or "")[:10]
    exit_d = str(prev_exit or "")[:10]
    if not entry or not exit_d:
        return False
    if entry <= exit_d:
        return True
    return trading_days_between(exit_d, entry) <= 1


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


def _signal_exit_day(sig: dict) -> str:
    return str(sig.get("exit_date") or sig.get("closed_at") or "")[:10]


def latest_closed_for_slot(signals: list, sym: str, model: str) -> dict | None:
    sym_u = str(sym).strip().upper()
    model_l = str(model).strip().lower()
    last = None
    last_day = ""
    for s in signals:
        if not isinstance(s, dict):
            continue
        if str(s.get("status", "")).strip().lower() != "closed":
            continue
        if str(s.get("ticker", "")).strip().upper() != sym_u:
            continue
        if str(s.get("score_model", "")).strip().lower() != model_l:
            continue
        day = _signal_exit_day(s)
        if day >= last_day:
            last_day = day
            last = s
    return last


def slot_blocks_new_entry(signals: list, sym: str, model: str) -> bool:
    """Block a new open until the previous 平倉 setup has dropped off the scan."""
    last = latest_closed_for_slot(signals, sym, model)
    if last is None:
        return False
    return last.get("reentry_ok") is not True


def mark_closed_slots_cleared(signals: list, model: str, triggering_symbols: set[str]) -> None:
    """Allow re-entry only after the ticker is absent from today's trigger list."""
    model_l = str(model).strip().lower()
    trig = {str(x).strip().upper() for x in triggering_symbols}
    for s in signals:
        if not isinstance(s, dict):
            continue
        if str(s.get("status", "")).strip().lower() != "closed":
            continue
        if str(s.get("score_model", "")).strip().lower() != model_l:
            continue
        sym = str(s.get("ticker", "")).strip().upper()
        if sym and sym not in trig:
            s["reentry_ok"] = True


def supersede_opens_covered_by_closed(signals: list, closed_rows: list) -> int:
    """Mark leftover opens as superseded when closed_transactions already 平倉'd that slot."""
    last_exit: dict[str, str] = {}
    for r in closed_rows:
        if not isinstance(r, dict):
            continue
        slot = position_slot(r)
        ex = str(r.get("exit_date", ""))[:10]
        if ex >= last_exit.get(slot, ""):
            last_exit[slot] = ex
    n = 0
    for s in signals:
        if not isinstance(s, dict) or not is_open_signal(s):
            continue
        slot = position_slot(s)
        ex = last_exit.get(slot)
        if not ex:
            continue
        entry = str(s.get("entry_date") or s.get("date") or "")[:10]
        if entry and (entry <= ex or is_continuation_entry(ex, entry)):
            s["status"] = "superseded"
            n += 1
    return n


def closed_row_covers_entry(closed_rows: list, sym: str, model: str, entry_date: str) -> bool:
    """True if this ticker/model already has a 平倉 that covers this entry."""
    entry = str(entry_date or "")[:10]
    if not entry:
        return False
    last_exit = ""
    for r in closed_rows:
        if not isinstance(r, dict):
            continue
        if str(r.get("ticker", "")).strip().upper() != str(sym).strip().upper():
            continue
        if str(r.get("score_model", "")).strip().lower() != str(model).strip().lower():
            continue
        ex = str(r.get("exit_date", ""))[:10]
        if ex > last_exit:
            last_exit = ex
    if not last_exit:
        return False
    return is_continuation_entry(last_exit, entry) or entry <= last_exit


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
        group_kept: list = []
        slot_open = False
        last_exit = ""
        pending_closed: list = []

        def _flush_closed() -> None:
            nonlocal pending_closed, superseded, last_exit
            if not pending_closed:
                return
            pending_closed.sort(key=lambda x: str(x.get("entry_date", ""))[:10])
            keeper = pending_closed[0]
            group_kept.append(keeper)
            last_exit = _signal_exit_day(keeper) or last_exit
            superseded += max(0, len(pending_closed) - 1)
            pending_closed = []

        def _retract_covered_opens(exit_day: str) -> None:
            nonlocal superseded, slot_open
            if not exit_day:
                return
            remain = []
            for prev in group_kept:
                prev_entry = str(prev.get("entry_date") or prev.get("date") or "")[:10]
                if is_open_signal(prev) and prev_entry and (
                    prev_entry <= exit_day or is_continuation_entry(exit_day, prev_entry)
                ):
                    superseded += 1
                    continue
                remain.append(prev)
            group_kept[:] = remain
            slot_open = any(is_open_signal(p) for p in group_kept)

        for s in group:
            st = str(s.get("status", "open")).strip().lower()
            entry = str(s.get("entry_date") or s.get("date") or "")[:10]
            if st == "superseded":
                superseded += 1
                continue
            if st == "closed":
                pending_exit = _signal_exit_day(pending_closed[0]) if pending_closed else ""
                prev_exit = last_exit or pending_exit
                if prev_exit and is_continuation_entry(prev_exit, entry):
                    superseded += 1
                    continue
                slot_open = False
                if pending_closed and closed_exit_batch_key(pending_closed[-1]) == closed_exit_batch_key(s):
                    pending_closed.append(s)
                else:
                    _flush_closed()
                    pending_closed = [s]
                _retract_covered_opens(_signal_exit_day(s) or entry)
                continue
            _flush_closed()
            if slot_open:
                superseded += 1
                continue
            if last_exit and is_continuation_entry(last_exit, entry):
                superseded += 1
                continue
            slot_open = True
            group_kept.append(s)
        _flush_closed()
        out.extend(group_kept)
    out.sort(key=lambda x: str(x.get("entry_date") or x.get("date") or ""))
    return out, superseded


def _finalize_closed_row(keeper: dict) -> dict:
    row = dict(keeper)
    entry = str(row.get("entry_date", ""))[:10]
    exit_d = str(row.get("exit_date", ""))[:10]
    sym = str(row.get("ticker", "")).upper()
    model = str(row.get("score_model", "")).lower()
    action = str(row.get("action", "")).upper()
    ep = _to_number(row.get("entry_price"))
    xp = _to_number(row.get("exit_price"))
    hd = _holding_days(entry, exit_d)
    if hd is not None:
        row["holding_days"] = hd
    if ep is not None and xp is not None and float(ep) != 0:
        row["final_pnl_pct"] = _pnl_pct_underlying(
            float(ep), float(xp), bearish=(action == "BUY_PUT" or model == "buy_put")
        )
    row["_key"] = f"{entry}|{sym}|{action}|{model}"
    return row


def consolidate_closed_transactions(closed_rows: list) -> list:
    """One closed row per ticker/model lifecycle. Later next-day 平倉 rolls are dropped."""
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
    same_day: list = []
    for rows in groups.values():
        rows.sort(key=lambda x: str(x.get("entry_date", ""))[:10])
        same_day.append(_finalize_closed_row(rows[0]))

    by_slot: dict[tuple, list] = {}
    for row in same_day:
        slot = (str(row.get("ticker", "")).upper(), str(row.get("score_model", "")).lower())
        by_slot.setdefault(slot, []).append(row)

    out: list = []
    for rows in by_slot.values():
        rows.sort(key=lambda x: (str(x.get("exit_date", ""))[:10], str(x.get("entry_date", ""))[:10]))
        kept: list = []
        for row in rows:
            entry = str(row.get("entry_date", ""))[:10]
            if kept and is_continuation_entry(str(kept[-1].get("exit_date", ""))[:10], entry):
                continue
            kept.append(row)
        out.extend(kept)
    out.sort(key=lambda x: str(x.get("exit_date", "")))
    return out
