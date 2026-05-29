#!/usr/bin/env python3
"""
Merge live dashboard JSON into repo-root files before CI scan/deploy.

Git checkout often has stale history (e.g. breadth only through 2026-05-22).
Each auto-deploy overwrote Cloudflare with that baseline + today's scan, wiping
mid-week days. This unions live + repo (longest history wins per day/model).

Also merges US breadth_daily_history_us.json (separate from HK).
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE_URL = os.environ.get("DASHBOARD_BASE_URL", "https://hkstockdashboard.chrislau.workers.dev").rstrip("/")
UA = "Mozilla/5.0 (compatible; backtest-dashboard-merge/1.0)"


def _fetch(url_path: str) -> dict | list | None:
    url = f"{BASE_URL}{url_path}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            raw = resp.read().decode("utf-8")
            if raw.lstrip().startswith("<"):
                print(f"[merge] skip fetch {url_path}: HTML response (404?)", file=sys.stderr)
                return None
            return json.loads(raw)
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as e:
        print(f"[merge] skip fetch {url_path}: {e}", file=sys.stderr)
        return None


def _read(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _scan_universe_total(scan_path: Path, default: int) -> int:
    scan = _read(scan_path)
    if not isinstance(scan, dict):
        return default
    scan_block = scan.get("scan") if isinstance(scan.get("scan"), dict) else {}
    total = scan_block.get("total")
    if isinstance(total, int) and total > 0:
        return total
    stocks = scan.get("stocks")
    if isinstance(stocks, list) and stocks:
        return len(stocks)
    return default


def _breadth_score(entry: dict, expected_total: int = 133) -> tuple:
    """Higher is better: valid universe total, then band sum."""
    total = int(entry.get("total") or 0)
    bands = int(entry.get("strong") or 0) + int(entry.get("watch") or 0) + int(entry.get("caution") or 0)
    total_ok = 0
    if expected_total > 0 and abs(total - expected_total) <= max(5, expected_total * 0.25):
        total_ok = 2
    elif expected_total >= 150 and 150 <= total <= 210:
        total_ok = 2
    elif 100 <= total <= 160:
        total_ok = 1
    return (total_ok, bands, total)


def merge_breadth(repo: dict | None, live: dict | None, *, expected_total: int = 133, extra: dict | None = None) -> dict | None:
    if not isinstance(live, dict) and not isinstance(repo, dict) and not isinstance(extra, dict):
        return repo
    out = dict(repo or live or extra or {})
    days_map: dict[tuple[str, str], dict] = {}
    for src in (repo, live, extra):
        if not isinstance(src, dict):
            continue
        for entry in src.get("days") or []:
            if not isinstance(entry, dict):
                continue
            day = str(entry.get("date") or "")[:10]
            model = str(entry.get("model") or "sell_put").strip().lower()
            if len(day) != 10:
                continue
            key = (day, model)
            prev = days_map.get(key)
            if prev is None or _breadth_score(entry, expected_total) >= _breadth_score(prev, expected_total):
                days_map[key] = entry
    if not days_map:
        return repo
    days = sorted(days_map.values(), key=lambda x: (str(x.get("date", "")), str(x.get("model", ""))))
    if len(days) > 400:
        days = days[-400:]
    out["days"] = days
    return out


def _signal_key(item: dict) -> str:
    return (
        f"{item.get('entry_date') or item.get('date') or ''}|"
        f"{item.get('ticker', '')}|{item.get('action', '')}|{item.get('score_model', '')}"
    )


def merge_signals(repo: dict | None, live: dict | None) -> dict | None:
    if not isinstance(live, dict) and not isinstance(repo, dict):
        return repo
    out = dict(repo or live or {})
    merged: dict[str, dict] = {}
    for src in (repo, live):
        if not isinstance(src, dict):
            continue
        for item in src.get("signals") or []:
            if isinstance(item, dict):
                merged[_signal_key(item)] = item
    if not merged:
        return repo
    signals = list(merged.values())
    signals.sort(key=lambda x: (str(x.get("date") or ""), str(x.get("ticker") or "")))
    max_entries = 5000
    if len(signals) > max_entries:
        signals = signals[-max_entries:]
    out["signals"] = signals
    return out


def merge_score_history(repo: dict | None, live: dict | None) -> dict | None:
    if not isinstance(live, dict) and not isinstance(repo, dict):
        return repo
    out = dict(repo or live or {})
    models: dict = {}
    for src in (repo, live):
        if not isinstance(src, dict):
            continue
        for model, tickers in (src.get("models") or {}).items():
            if not isinstance(tickers, dict):
                continue
            models.setdefault(model, {})
            for ticker, by_day in tickers.items():
                if not isinstance(by_day, dict):
                    continue
                models[model].setdefault(ticker, {})
                for day, score in by_day.items():
                    if day not in models[model][ticker]:
                        models[model][ticker][day] = score
    if models:
        out["models"] = models
    return out


def _sell_put_dates(payload: dict | None) -> set[str]:
    if not isinstance(payload, dict):
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


def _merge_breadth_file(
    filename: str,
    url_path: str,
    expected_total: int,
    frontend_copy: str | None = None,
) -> bool:
    path = ROOT / filename
    repo = _read(path)
    live = _fetch(url_path)
    extra = _read(ROOT / frontend_copy) if frontend_copy else None
    before_dates = _sell_put_dates(repo) | _sell_put_dates(live) | _sell_put_dates(extra)
    merged = merge_breadth(repo, live, expected_total=expected_total, extra=extra)
    if not isinstance(merged, dict):
        return False
    after_dates = _sell_put_dates(merged)
    if before_dates and not before_dates.issubset(after_dates):
        lost = sorted(before_dates - after_dates)
        print(f"[merge] ERROR: {filename} would lose sell_put dates {lost}", file=sys.stderr)
        return False
    before = len((repo or {}).get("days") or [])
    after = len(merged.get("days") or [])
    sell_dates = sorted(
        {str(d.get("date", ""))[:10] for d in merged.get("days") or [] if d.get("model") == "sell_put"}
    )
    if merged != repo:
        _write(path, merged)
        print(f"[merge] {filename}: updated (rows {before} → {after}) sell_put dates: {sell_dates[-8:]}")
        return True
    print(f"[merge] {filename}: unchanged ({after} rows) sell_put dates: {sell_dates[-8:]}")
    return False


def main() -> int:
    if os.environ.get("SKIP_MERGE_LIVE_JSON", "").strip() in ("1", "true", "yes"):
        print("[merge] SKIP_MERGE_LIVE_JSON set — skipped")
        return 0

    hk_total = _scan_universe_total(ROOT / "daily_scan.json", 133)
    us_total = _scan_universe_total(ROOT / "daily_scan_us.json", 200)

    changed = 0
    if _merge_breadth_file(
        "breadth_daily_history.json",
        "/frontend/data/breadth_daily_history.json",
        hk_total,
        "frontend/data/breadth_daily_history.json",
    ):
        changed += 1
    if _merge_breadth_file(
        "breadth_daily_history_us.json",
        "/frontend-us/data/breadth_daily_history_us.json",
        us_total,
        "frontend-us/data/breadth_daily_history_us.json",
    ):
        changed += 1

    for filename, url_path, merge_fn in [
        ("signals_history.json", "/frontend/data/signals_history.json", merge_signals),
        ("signals_history_us.json", "/frontend-us/data/signals_history_us.json", merge_signals),
        ("score_daily_history.json", "/frontend/data/score_daily_history.json", merge_score_history),
    ]:
        path = ROOT / filename
        repo = _read(path)
        live = _fetch(url_path)
        merged = merge_fn(repo, live)
        if not isinstance(merged, dict):
            continue
        before = len((repo or {}).get("signals") or [])
        after = len(merged.get("signals") or [])
        if merged != repo:
            _write(path, merged)
            changed += 1
            print(f"[merge] {filename}: updated (rows {before} → {after})")
        else:
            print(f"[merge] {filename}: unchanged ({after} rows)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
