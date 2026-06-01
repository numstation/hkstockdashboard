#!/usr/bin/env python3
"""Fail CI if scan JSON is mostly empty (fetch_failed) — avoids deploying bad data."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _min_ok() -> int:
    raw = os.environ.get("SCAN_VALIDATE_MIN_OK", "50").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 50


def check(path: Path) -> tuple[int, int, str | None]:
    if not path.is_file():
        return 0, 0, "missing"
    data = json.loads(path.read_text(encoding="utf-8"))
    stocks = data.get("stocks") if isinstance(data, dict) else None
    if not isinstance(stocks, list):
        return 0, 0, "no stocks list"
    ok = sum(1 for s in stocks if isinstance(s, dict) and s.get("data_ok"))
    return ok, len(stocks), data.get("last_updated")


def _hk_model_files() -> list[Path]:
    return [
        ROOT / "daily_scan_sell_put.json",
        ROOT / "daily_scan_buy_stock.json",
        ROOT / "daily_scan_buy_put.json",
    ]


def check_hk_models_aligned() -> bool:
    """All three HK per-model scans should share universe size, market, and same scan run."""
    from datetime import datetime

    rows = []
    for path in _hk_model_files():
        if not path.is_file():
            print(f"  WARN: missing {path.name}", file=sys.stderr)
            return False
        data = json.loads(path.read_text(encoding="utf-8"))
        scan = data.get("scan") if isinstance(data.get("scan"), dict) else {}
        stocks = data.get("stocks") if isinstance(data.get("stocks"), list) else []
        hkish = sum(
            1
            for s in stocks[:30]
            if str(s.get("ticker", s.get("Ticker", ""))).upper().endswith(".HK")
        )
        lu_raw = str(data.get("last_updated") or "")
        lu_dt = None
        try:
            lu_dt = datetime.fromisoformat(lu_raw.replace("Z", "+00:00"))
        except Exception:
            pass
        rows.append(
            {
                "name": path.name,
                "total": scan.get("total") or len(stocks),
                "lu": lu_raw,
                "lu_dt": lu_dt,
                "model": str(scan.get("score_model") or ""),
                "hk_sample": hkish,
            }
        )
    totals = {r["total"] for r in rows}
    if len(totals) > 1:
        print(
            f"  ERROR: HK model files disagree on universe total: "
            + ", ".join(f"{r['name']}={r['total']}" for r in rows),
            file=sys.stderr,
        )
        return False
    ref_total = next(iter(totals))
    if ref_total > 160:
        print(
            f"  ERROR: HK scan total={ref_total} looks like US contamination (expect ~133)",
            file=sys.stderr,
        )
        return False
    for r in rows:
        if r["hk_sample"] < 10:
            print(f"  ERROR: {r['name']} tickers do not look like HK (.HK)", file=sys.stderr)
            return False
    dts = [r["lu_dt"] for r in rows if r["lu_dt"] is not None]
    if len(dts) == len(rows):
        spread_s = (max(dts) - min(dts)).total_seconds()
        if spread_s > 900:
            print(
                "  ERROR: HK model files last_updated spread "
                f"{spread_s:.0f}s (>15m — stale model file?): "
                + ", ".join(f"{r['name']}={r['lu']}" for r in rows),
                file=sys.stderr,
            )
            return False
    print(f"  HK models aligned: total={ref_total} last_updated≈{rows[-1]['lu']}")
    return True


def main() -> int:
    min_ok = _min_ok()
    print(f"validate_scan_json: SCAN_VALIDATE_MIN_OK={min_ok}")
    env_list = os.environ.get("SCAN_VALIDATE_FILES", "").strip()
    if env_list:
        files = [ROOT / p.strip() for p in env_list.split(",") if p.strip()]
    else:
        files = [
            ROOT / "daily_scan_sell_put.json",
            ROOT / "daily_scan.json",
        ]
    failed = False
    for path in files:
        ok, total, lu = check(path)
        print(f"{path.name}: data_ok={ok}/{total} last_updated={lu}")
        if ok < min_ok:
            print(
                f"  ERROR: need at least {min_ok} data_ok rows "
                f"(set SCAN_VALIDATE_MIN_OK to relax for flaky CI)",
                file=sys.stderr,
            )
            failed = True
        if path.is_file():
            scan = json.loads(path.read_text(encoding="utf-8")).get("scan") or {}
            if not scan.get("score_d1_date") and not scan.get("score_d2_date"):
                print("  WARN: missing score_d1_date / score_d2_date (3-day scores)", file=sys.stderr)
    if os.environ.get("SCAN_VALIDATE_SKIP_HK_ALIGN", "").strip() not in ("1", "true", "yes"):
        if not check_hk_models_aligned():
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
