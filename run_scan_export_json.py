#!/usr/bin/env python3
"""
Write daily_scan.json (+ signals_history, future_log, macro_snapshot) without Streamlit.

Universe mode (default): every ticker gets RVOL / ADX / MACD histogram + tech_score + rule-based
strategy text — no empty dashboard when strict signals miss.

Examples:
  python3 run_scan_export_json.py
      → HK list (same source as Streamlit «HK stock list»: hkstocklist.csv when present,
        else hk_top200.txt, else Tech+HSI+HKCEI). Universe mode; strategy label from score model.

  python3 run_scan_export_json.py GREEDY_HK
      → HK list plus optional hk_universe_extra.txt (one ticker per line in repo root)

  python3 run_scan_export_json.py HK
      → Same HK list as default (explicit); universe mode

  python3 run_scan_export_json.py US --sleep 0.2
      → US list

  python3 run_scan_export_json.py --signals-only TECH
      → legacy: analyze_stock() only (rows appear when signals fire)

  python3 run_scan_export_json.py --macro-only
      → refresh macro_snapshot.json only (for cron)

  Default triple export writes daily_scan_sell_put.json, daily_scan_buy_stock.json,
  daily_scan_buy_put.json, then daily_scan.json using the engine named in DAILY_SCAN_PRIMARY_MODEL
  (default: sell_put). Example: DAILY_SCAN_PRIMARY_MODEL=buy_put python3 run_scan_export_json.py

  Single-model: python3 run_scan_export_json.py --score-model buy_put --single-model
      → daily_scan_buy_put.json and daily_scan.json both use buy_put scoring.
"""

from __future__ import annotations

import gc
import importlib.util
import os
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
STOCKTRACKER = ROOT / "stocktrackeryahoo"
for p in (ROOT, STOCKTRACKER):
    ps = str(p)
    if ps not in sys.path:
        sys.path.insert(0, ps)

from daily_scanner import (  # noqa: E402
    analyze_stock,
    get_tickers,
    greedy_hk_universe,
    technical_universe_row,
    HK_UNIVERSE_TAG,
)
from schema_versioning import (  # noqa: E402
    reset_export_schema_version,
    schema_version_for_export,
    strategy_display_name,
)

try:
    import yfinance_bootstrap  # noqa: E402

    yfinance_bootstrap.enable()
except Exception:
    pass


def parse_args(argv: list[str]):
    strategy = ""
    signals_only = False
    sleep_s = 0.12
    macro_only = False
    skip_macro = False
    score_model = "sell_put"
    both_models = True
    rest: list[str] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--macro-only":
            macro_only = True
        elif a == "--skip-macro":
            skip_macro = True
        elif a == "--signals-only":
            signals_only = True
        elif a == "--sleep" and i + 1 < len(argv):
            sleep_s = float(argv[i + 1])
            i += 1
        elif a == "--strategy" and i + 1 < len(argv):
            strategy = argv[i + 1]
            i += 1
        elif a == "--score-model" and i + 1 < len(argv):
            score_model = argv[i + 1].strip().lower()
            both_models = False
            i += 1
        elif a == "--single-model":
            both_models = False
        elif a == "--scan-prefix" and i + 1 < len(argv):
            rest.insert(0, f"__scan_prefix__={argv[i + 1].strip().lower()}")
            i += 1
        else:
            rest.append(a)
        i += 1
    scan_prefix = ""
    rest2: list[str] = []
    for a in rest:
        if a.startswith("__scan_prefix__="):
            scan_prefix = a.split("=", 1)[1].strip().lower()
        else:
            rest2.append(a)
    return strategy, rest2, signals_only, sleep_s, macro_only, skip_macro, score_model, both_models, scan_prefix


def _scan_export_names(scan_prefix: str, score_model: str) -> tuple[str, list[tuple[str, str]]]:
    """Return (primary daily_scan filename, [(model, per-model filename), ...])."""
    p = (scan_prefix or "").strip().lower()
    if p == "us":
        primary = "daily_scan_us.json"
        models = [
            ("sell_put", "daily_scan_us_sell_put.json"),
            ("buy_stock", "daily_scan_us_buy_stock.json"),
            ("buy_put", "daily_scan_us_buy_put.json"),
        ]
        return primary, models
    models = [
        ("sell_put", "daily_scan_sell_put.json"),
        ("buy_stock", "daily_scan_buy_stock.json"),
        ("buy_put", "daily_scan_buy_put.json"),
    ]
    return "daily_scan.json", models


def load_exporters():
    try:
        import flask  # noqa: F401  # pyright: ignore[reportMissingModuleSource]
    except ImportError:
        import headless_flask_stub  # noqa: E402  # pyright: ignore[reportMissingImports]

        headless_flask_stub.install()
    spec = importlib.util.spec_from_file_location(
        "scsp_web_app", STOCKTRACKER / "app.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def gather_results_signals(tickers: list[str], sleep_s: float) -> list[dict]:
    results: list[dict] = []
    for t in tickers:
        try:
            res = analyze_stock(t)
        except Exception as e:
            print(f"[warn] {t}: {e}", file=sys.stderr)
            res = None
        if res:
            results.append(res)
        print(".", end="", flush=True)
        time.sleep(sleep_s)
    print()
    return results


def gather_results_universe(tickers: list[str], sleep_s: float, score_model: str = "sell_put") -> list[dict]:
    results: list[dict] = []
    for i, t in enumerate(tickers):
        try:
            row = technical_universe_row(t, score_model=score_model)
        except Exception as e:
            print(f"[warn] {t}: {e}", file=sys.stderr)
            row = {
                "Ticker": t,
                "Signal": "NO DATA",
                "Why": "exception",
                "scan_mode": "universe",
                "data_ok": False,
            }
        results.append(row)
        print(".", end="", flush=True)
        time.sleep(sleep_s)
        if (i + 1) % 25 == 0:
            gc.collect()
    print()
    gc.collect()
    return results


def _ancillary_subset(df: pd.DataFrame | None, *, universe_mode: bool) -> pd.DataFrame | None:
    """Avoid flooding history/log when exporting the full universe."""
    if df is None or df.empty or not universe_mode:
        return df
    if "tech_score" not in df.columns:
        return df
    work = df.copy()
    ts = pd.to_numeric(work["tech_score"], errors="coerce")
    work["_ts"] = ts
    hi = work[work["_ts"] >= 62].drop(columns=["_ts"], errors="ignore")
    if hi.empty:
        return None
    return hi


def _future_log_subset(df: pd.DataFrame | None, *, universe_mode: bool) -> pd.DataFrame | None:
    if df is None or df.empty:
        return df
    if not universe_mode:
        return df
    if "tech_score" not in df.columns:
        return df.head(25)
    work = df.copy()
    work["_ts"] = pd.to_numeric(work["tech_score"], errors="coerce")
    top = work.sort_values("_ts", ascending=False).head(25).drop(columns=["_ts"], errors="ignore")
    return top


def main() -> int:
    argv = [a.strip() for a in sys.argv[1:] if a.strip()]
    strategy, pos, signals_only, sleep_s, macro_only, skip_macro, score_model, both_models, scan_prefix = parse_args(
        argv
    )
    primary_scan_name, model_export_names = _scan_export_names(scan_prefix, score_model)
    us_only = scan_prefix == "us"

    if macro_only:
        exporters = load_exporters()
        reset_export_schema_version()
        schema_ver = schema_version_for_export(bump=True)
        ok = exporters.export_macro_snapshot_to_json(schema_version=schema_ver)
        print(
            f"Macro-only export → macro_snapshot.json | schema={schema_ver} | success={ok} | ROOT={ROOT}"
        )
        return 0 if ok else 1

    if not pos:
        tickers = get_tickers("HK")
        label = f"HK (default, {HK_UNIVERSE_TAG})"
    elif len(pos) == 1 and pos[0].upper() in (
        "HK",
        "TECH",
        "HSI",
        "HKCEI",
        "US",
        "GREEDY_HK",
    ):
        tickers = get_tickers(pos[0].upper())
        label = pos[0].upper()
    else:
        tickers = pos
        label = "custom"

    if not tickers:
        print("No tickers to scan.")
        return 1

    mode_s = "strict signals" if signals_only else "universe (all rows + tech_score)"
    model_desc = "both models" if (both_models and not signals_only) else score_model
    print(
        f"Scan → JSON | {label} | {len(tickers)} ticker(s) | {mode_s} | "
        f"strategy={strategy!r} | score_model={model_desc}"
    )

    exporters = load_exporters()
    reset_export_schema_version()
    schema_ver = schema_version_for_export(bump=True)
    mirror: str | None = None
    if signals_only:
        results = gather_results_signals(tickers, sleep_s)
        universe_mode = False
        df = pd.DataFrame(results) if results else pd.DataFrame()
        exporters.export_results_to_json(df, strategy, schema_version=schema_ver)
        hist_df = _ancillary_subset(df, universe_mode=universe_mode)
        exporters.export_signals_history_to_json(
            hist_df if hist_df is not None else pd.DataFrame(), strategy, schema_version=schema_ver
        )
        log_df = _future_log_subset(df, universe_mode=universe_mode)
        exporters.append_future_log_to_json(
            log_df if log_df is not None else pd.DataFrame(), strategy, schema_version=schema_ver
        )
    else:
        model_runs = model_export_names if both_models else [(score_model, f"daily_scan_{score_model}.json")]
        if us_only and not both_models:
            model_runs = [(score_model, f"daily_scan_us_{score_model}.json")]
        dfs_by_model: dict[str, pd.DataFrame] = {}
        for m, out_name in model_runs:
            print(f"\n[model] computing {m} ...")
            gc.collect()
            results = gather_results_universe(tickers, sleep_s, score_model=m)
            df_m = pd.DataFrame(results) if results else pd.DataFrame()
            dfs_by_model[m] = df_m
            strategy_m = strategy_display_name(m, strategy)
            exporters.export_results_to_json(
                df_m, strategy_m, filename=out_name, score_model_slug=m, schema_version=schema_ver
            )
        mirror = os.environ.get("DAILY_SCAN_PRIMARY_MODEL", "sell_put").strip().lower()
        if mirror not in dfs_by_model:
            mirror = "sell_put" if "sell_put" in dfs_by_model else next(iter(dfs_by_model.keys()))
        df_primary_scan = dfs_by_model[mirror]
        strategy_primary = strategy_display_name(mirror, strategy)
        exporters.export_results_to_json(
            df_primary_scan,
            strategy_primary,
            filename=primary_scan_name,
            score_model_slug=mirror,
            schema_version=schema_ver,
        )
        exported_first_df = dfs_by_model.get("sell_put")
        if exported_first_df is None or exported_first_df.empty:
            exported_first_df = df_primary_scan
        df = exported_first_df
        universe_mode = True
        if not us_only:
            trade_logged = 0
            for m, df_m in dfs_by_model.items():
                strategy_m = strategy_display_name(m, strategy)
                try:
                    trade_logged += exporters.export_trade_signals_history_to_json(
                        df_m, strategy_m, score_model_slug=m, schema_version=schema_ver
                    )
                except Exception as e:
                    print(f"[warn] trade history export failed ({m}): {e}", file=sys.stderr)
            print(f"Trade triggers logged this run: {trade_logged}")
            try:
                synced = exporters.export_trade_signals_from_scan_files(strategy_name=strategy)
                if synced:
                    print(f"Trade triggers synced from scan JSON files: {synced}")
            except Exception as e:
                print(f"[warn] scan-file trade sync failed: {e}", file=sys.stderr)
            for m, out_name in model_runs:
                try:
                    exporters.backfill_daily_breadth_from_scan_json(out_name, m)
                except Exception as e:
                    print(f"[warn] breadth backfill failed ({out_name}): {e}", file=sys.stderr)
            log_df = _future_log_subset(df, universe_mode=universe_mode)
            exporters.append_future_log_to_json(
                log_df if log_df is not None else pd.DataFrame(), strategy, schema_version=schema_ver
            )
        else:
            print("US scan-only export (skipped HK trade history / future_log / breadth backfill).")
    if not skip_macro and not us_only:
        exporters.export_macro_snapshot_to_json(schema_version=schema_ver)
    elif skip_macro or us_only:
        print("Skipped macro_snapshot export (--skip-macro or US scan-only).")

    n_ok = int(df["data_ok"].sum()) if universe_mode and not df.empty and "data_ok" in df.columns else len(df)
    print(
        f"Done. Rows: {len(df)} | data_ok≈{n_ok} | schema={schema_ver} | "
        f"primary={primary_scan_name!r} | ROOT={ROOT}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
