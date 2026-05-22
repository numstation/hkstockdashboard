#!/usr/bin/env python3
"""Write frontend/data/hk_stock_names.json from hkstocklist.csv (no yfinance)."""
from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _norm_code(raw: str) -> str:
    s = raw.strip().upper()
    if not s.endswith(".HK"):
        return s
    prefix = s[:-3]
    if len(prefix) == 5 and prefix.startswith("0"):
        return prefix[1:] + ".HK"
    return s


def _short_stock_name(full: str) -> str:
    s = str(full or "").strip()
    if not s:
        return ""
    for suf in (
        " Holdings Limited",
        " Holding Limited",
        " Holdings Ltd.",
        " Holdings Ltd",
        " Holdings Plc.",
        " Holdings Plc",
        " Holdings",
        " Limited",
        " Ltd.",
        " Ltd",
        " Plc.",
        " Plc",
        " Inc.",
        " Inc",
        " Corporation",
        " Corp.",
        " Corp",
        " Co. Ltd.",
        " Co., Ltd.",
        " Company Limited",
        " Group Limited",
        " Group Ltd.",
        " Group Inc.",
        " Group",
    ):
        if s.endswith(suf):
            s = s[: -len(suf)].strip()
    s = s.replace("  ", " ").strip()
    if len(s) > 40:
        s = s[:37].rstrip() + "…"
    return s


def load_name_map(csv_path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not csv_path.is_file():
        return out
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.reader(f):
            if not row or not str(row[0]).strip():
                continue
            key = str(row[0]).strip()
            if key.lower() == "code":
                continue
            digits = "".join(ch for ch in key if ch.isdigit())
            if not digits:
                continue
            code = int(digits, 10)
            if code <= 0:
                continue
            sym = _norm_code(f"{code:04d}.HK" if code < 100_000 else f"{code}.HK")
            short = _short_stock_name(row[1].strip() if len(row) > 1 else "")
            if short:
                out[sym] = short
    return out


def main() -> int:
    src = ROOT / "hkstocklist.csv"
    dest = ROOT / "frontend" / "data" / "hk_stock_names.json"
    names = load_name_map(src)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(names, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(names)} names → {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
