from portfolio_reconcile import (
    closed_row_covers_entry,
    consolidate_closed_transactions,
    is_continuation_entry,
    mark_closed_slots_cleared,
    reconcile_signals_history,
    slot_blocks_new_entry,
    trading_days_between,
)


def test_trading_days_friday_to_monday():
    assert trading_days_between("2026-05-22", "2026-05-25") == 1


def test_continuation_same_day_and_next_day():
    assert is_continuation_entry("2026-05-26", "2026-05-26") is True
    assert is_continuation_entry("2026-05-26", "2026-05-22") is True
    assert is_continuation_entry("2026-05-26", "2026-05-27") is True
    assert is_continuation_entry("2026-05-26", "2026-06-22") is False


def test_consolidate_drops_rolled_closes():
    rows = [
        {
            "ticker": "1186.HK",
            "score_model": "buy_put",
            "action": "BUY_PUT",
            "entry_date": "2026-05-20",
            "exit_date": "2026-05-26",
            "entry_price": 10,
            "exit_price": 9.5,
        },
        {
            "ticker": "1186.HK",
            "score_model": "buy_put",
            "action": "BUY_PUT",
            "entry_date": "2026-05-22",
            "exit_date": "2026-05-27",
            "entry_price": 10.1,
            "exit_price": 9.6,
        },
        {
            "ticker": "1186.HK",
            "score_model": "buy_put",
            "action": "BUY_PUT",
            "entry_date": "2026-06-22",
            "exit_date": "2026-06-24",
            "entry_price": 11,
            "exit_price": 10,
        },
    ]
    out = consolidate_closed_transactions(rows)
    assert len(out) == 2
    assert [r["exit_date"] for r in out] == ["2026-05-26", "2026-06-24"]


def test_consolidate_all_three_models():
    rows = []
    for model, action in (
        ("sell_put", "SELL_PUT"),
        ("buy_stock", "BUY_CALL"),
        ("buy_put", "BUY_PUT"),
    ):
        rows.append(
            {
                "ticker": "0005.HK",
                "score_model": model,
                "action": action,
                "entry_date": "2026-05-20",
                "exit_date": "2026-05-26",
                "entry_price": 100,
                "exit_price": 99,
            }
        )
        rows.append(
            {
                "ticker": "0005.HK",
                "score_model": model,
                "action": action,
                "entry_date": "2026-05-21",
                "exit_date": "2026-05-27",
                "entry_price": 100,
                "exit_price": 98,
            }
        )
    out = consolidate_closed_transactions(rows)
    assert len(out) == 3
    assert {r["score_model"] for r in out} == {"sell_put", "buy_stock", "buy_put"}


def test_reconcile_supersedes_next_day_reopen():
    signals = [
        {
            "ticker": "1876.HK",
            "score_model": "buy_put",
            "action": "BUY_PUT",
            "entry_date": "2026-05-23",
            "status": "closed",
            "exit_date": "2026-05-26",
            "exit_price": 10,
        },
        {
            "ticker": "1876.HK",
            "score_model": "buy_put",
            "action": "BUY_PUT",
            "entry_date": "2026-05-26",
            "status": "open",
        },
        {
            "ticker": "1876.HK",
            "score_model": "buy_put",
            "action": "BUY_PUT",
            "entry_date": "2026-07-02",
            "status": "open",
        },
    ]
    out, n_sup = reconcile_signals_history(signals)
    assert n_sup == 1
    statuses = [(s["entry_date"], s["status"]) for s in out]
    assert ("2026-05-23", "closed") in statuses
    assert ("2026-07-02", "open") in statuses
    assert ("2026-05-26", "open") not in statuses


def test_reconcile_retracts_open_once_closed():
    signals = [
        {
            "ticker": "1186.HK",
            "score_model": "buy_put",
            "action": "BUY_PUT",
            "entry_date": "2026-05-20",
            "status": "open",
        },
        {
            "ticker": "1186.HK",
            "score_model": "buy_put",
            "action": "BUY_PUT",
            "entry_date": "2026-05-20",
            "status": "closed",
            "exit_date": "2026-05-26",
            "exit_price": 10,
        },
    ]
    out, n_sup = reconcile_signals_history(signals)
    assert n_sup == 1
    assert len(out) == 1
    assert out[0]["status"] == "closed"


def test_reentry_blocked_until_setup_clears():
    signals = [
        {
            "ticker": "9626.HK",
            "score_model": "buy_put",
            "status": "closed",
            "exit_date": "2026-05-26",
        }
    ]
    assert slot_blocks_new_entry(signals, "9626.HK", "buy_put") is True
    mark_closed_slots_cleared(signals, "buy_put", {"9999.HK"})
    assert signals[0]["reentry_ok"] is True
    assert slot_blocks_new_entry(signals, "9626.HK", "buy_put") is False


def test_closed_row_covers_overlapping_entry():
    closed = [
        {
            "ticker": "3690.HK",
            "score_model": "buy_put",
            "exit_date": "2026-05-29",
            "entry_date": "2026-05-28",
        }
    ]
    assert closed_row_covers_entry(closed, "3690.HK", "buy_put", "2026-05-29") is True
    assert closed_row_covers_entry(closed, "3690.HK", "buy_put", "2026-06-22") is False


def test_supersede_opens_covered_by_closed_file():
    from portfolio_reconcile import supersede_opens_covered_by_closed

    signals = [
        {
            "ticker": "0762.HK",
            "score_model": "buy_stock",
            "action": "BUY_CALL",
            "entry_date": "2026-05-18",
            "status": "open",
        }
    ]
    closed = [
        {
            "ticker": "0762.HK",
            "score_model": "buy_stock",
            "exit_date": "2026-05-29",
            "entry_date": "2026-05-20",
        }
    ]
    n = supersede_opens_covered_by_closed(signals, closed)
    assert n == 1
    assert signals[0]["status"] == "superseded"
