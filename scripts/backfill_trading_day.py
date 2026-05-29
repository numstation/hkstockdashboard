#!/usr/bin/env python3
"""
Backfill a missing HK trading day into score_daily_history.json and breadth_daily_history.json.

Recomputes per-ticker scores from Yahoo daily bars (same engine as daily_scanner) so
「連續性」/ Score 2·1·0 arcs are not broken by calendar gaps (e.g. missing 2026-05-27).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
STOCKTRACKER = ROOT / "stocktrackeryahoo"
for p in (ROOT, STOCKTRACKER):
    ps = str(p)
    if ps not in sys.path:
        sys.path.insert(0, ps)

try:
    import yfinance_bootstrap  # noqa: E402

    yfinance_bootstrap.enable()
except Exception:
    pass

from daily_scanner import (  # noqa: E402
    MIN_OHLCV_BARS,
    _signal_band_from_score,
    _tech_score_from_bar,
    get_indicator_df,
    get_tickers,
)
from schema_versioning import strategy_display_name  # noqa: E402

SCORE_HISTORY_RETENTION_DAYS = 120

MARKET_FILES = {
    "HK": ("score_daily_history.json", "breadth_daily_history.json"),
    "US": ("score_daily_history_us.json", "breadth_daily_history_us.json"),
}


def _read_json(path: Path, default: dict) -> dict:
    try:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return dict(default)


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _prune_score_date_map(date_map: dict, *, today: str, retention_days: int) -> dict:
    from datetime import datetime

    if not date_map:
        return {}
    try:
        today_dt = datetime.strptime(today, "%Y-%m-%d").date()
    except Exception:
        return dict(date_map)
    out = {}
    for d, sc in date_map.items():
        try:
            dd = datetime.strptime(str(d)[:10], "%Y-%m-%d").date()
        except Exception:
            continue
        if (today_dt - dd).days <= retention_days:
            try:
                out[str(d)[:10]] = int(round(float(sc)))
            except (TypeError, ValueError):
                continue
    return out


def export_daily_breadth_snapshot(
    *,
    date: str,
    score_model: str,
    strong: int,
    watch: int,
    caution: int,
    breadth_path: Path,
) -> None:
    from datetime import datetime

    now_str = datetime.now().astimezone().isoformat(timespec="seconds")
    day = str(date or "")[:10]
    model = str(score_model or "sell_put").strip().lower()
    payload = _read_json(breadth_path, {"schema_version": "8.0", "last_updated": now_str, "days": []})
    days = payload.get("days")
    if not isinstance(days, list):
        days = []
    entry = {
        "date": day,
        "model": model,
        "strong": int(strong),
        "watch": int(watch),
        "caution": int(caution),
        "total": int(strong) + int(watch) + int(caution),
    }
    days = [d for d in days if not (isinstance(d, dict) and d.get("date") == day and d.get("model") == model)]
    days.append(entry)
    days.sort(key=lambda x: (str(x.get("date", "")), str(x.get("model", ""))))
    if len(days) > 400:
        days = days[-400:]
    payload["days"] = days
    payload["last_updated"] = now_str
    _write_json(breadth_path, payload)

MODELS = ("sell_put", "buy_stock", "buy_put")


def _bar_index_for_date(df: pd.DataFrame, target: str) -> int | None:
    if df is None or df.empty:
        return None
    for i, idx in enumerate(df.index):
        try:
            day = pd.Timestamp(idx).strftime("%Y-%m-%d")
        except Exception:
            continue
        if day == target:
            return i
    return None


def _band_kind(band: str) -> str:
    u = str(band or "").upper()
    if "STRONG" in u:
        return "strong"
    if "CAUTION" in u:
        return "caution"
    return "watch"


def backfill_day(
    target: str,
    *,
    tickers: list[str],
    breadth_path: Path,
    score_path: Path | None = None,
    breadth_only: bool = False,
    sleep_s: float = 0.08,
) -> tuple[int, int]:
    """Returns (scores_written, breadth_models_updated)."""
    history = _load_score_daily_history(score_path) if score_path and not breadth_only else None
    models_root = history.setdefault("models", {}) if history else {}
    scores_written = 0
    models_updated = 0
    breadth_counts: dict[str, dict[str, int]] = {m: {"strong": 0, "watch": 0, "caution": 0} for m in MODELS}

    # Cache OHLCV once per ticker (scores differ by model only).
    bar_cache: dict[str, tuple[pd.DataFrame, int] | None] = {}

    for n, ticker in enumerate(tickers, 1):
        sym = str(ticker).strip().upper()
        if not sym:
            continue
        if sym not in bar_cache:
            try:
                df = get_indicator_df(sym, period="6mo")
            except Exception:
                df = None
            bi = _bar_index_for_date(df, target) if df is not None and len(df) >= MIN_OHLCV_BARS else None
            if bi is not None and bi < 2:
                bi = None
            bar_cache[sym] = (df, bi) if bi is not None and df is not None else None
            if sleep_s > 0:
                time.sleep(sleep_s)
        cached = bar_cache.get(sym)
        if not cached:
            continue
        df, bi = cached

        for model in MODELS:
            score = _tech_score_from_bar(df, bi, model)
            if score is None:
                continue
            if history is not None:
                model_map = models_root.setdefault(model, {})
                ticker_map = model_map.setdefault(sym, {})
                if not isinstance(ticker_map, dict):
                    ticker_map = {}
                    model_map[sym] = ticker_map
                ticker_map[target] = int(score)
                ticker_map.update(
                    _prune_score_date_map(ticker_map, today=target, retention_days=SCORE_HISTORY_RETENTION_DAYS)
                )
                scores_written += 1
            trading_name = strategy_display_name(model, "")
            band = _signal_band_from_score(int(score), trading_name)
            breadth_counts[model][_band_kind(band)] += 1

        if n % 20 == 0:
            print(f"  … {n}/{len(tickers)} tickers", flush=True)

    for model in MODELS:
        counts = breadth_counts[model]
        total = counts["strong"] + counts["watch"] + counts["caution"]
        if total <= 0:
            print(f"[warn] {model}: no scores for {target} — skipped breadth", file=sys.stderr)
            continue
        export_daily_breadth_snapshot(
            date=target,
            score_model=model,
            strong=counts["strong"],
            watch=counts["watch"],
            caution=counts["caution"],
            breadth_path=breadth_path,
        )
        models_updated += 1
        print(f"  breadth {model}: strong={counts['strong']} watch={counts['watch']} caution={counts['caution']} total={total}")

    if history is not None:
        _save_score_daily_history(history, score_path)
    return scores_written, models_updated


def _load_score_daily_history(score_path: Path) -> dict:
    data = _read_json(score_path, {"schema_version": "1.0", "last_updated": None, "models": {}})
    if "models" not in data or not isinstance(data["models"], dict):
        data["models"] = {}
    return data


def _save_score_daily_history(payload: dict, score_path: Path) -> None:
    from datetime import datetime

    payload["last_updated"] = datetime.now().astimezone().isoformat(timespec="seconds")
    _write_json(score_path, payload)


def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill missing trading day scores + breadth.")
    ap.add_argument("--date", required=True, help="Trading day YYYY-MM-DD (e.g. 2026-05-27)")
    ap.add_argument("--market", choices=("HK", "US"), default="HK", help="HK or US universe")
    ap.add_argument("--breadth-only", action="store_true", help="Only update breadth history (faster)")
    ap.add_argument("--sleep", type=float, default=0.08, help="Pause between Yahoo fetches")
    args = ap.parse_args()
    target = str(args.date).strip()[:10]
    if len(target) != 10:
        print("Invalid --date", file=sys.stderr)
        return 1

    market = str(args.market).upper()
    score_name, breadth_name = MARKET_FILES[market]
    score_path = ROOT / score_name
    breadth_path = ROOT / breadth_name

    tickers = get_tickers(market)
    if not tickers:
        print(f"No {market} tickers found", file=sys.stderr)
        return 1

    print(f"Backfill {target} for {len(tickers)} {market} tickers → {breadth_name} …")
    scores, breadth = backfill_day(
        target,
        tickers=tickers,
        breadth_path=breadth_path,
        score_path=score_path,
        breadth_only=args.breadth_only,
        sleep_s=max(0.0, args.sleep),
    )
    print(f"Done. score rows written={scores} breadth_models={breadth}")
    return 0 if breadth > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
