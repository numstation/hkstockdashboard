#!/usr/bin/env python3
"""Sync US universe from us_top300.txt → us_stock_names.json + us_breadth_universe.csv."""
from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _norm_us_ticker(sym: str) -> str:
    s = sym.strip().upper()
    if len(s) >= 3 and s[-2] == "." and s[-1].isalpha():
        return f"{s[:-2]}-{s[-1]}"
    return s


def _load_us_universe() -> tuple[list[str], Path | None]:
    for name in ("us_top300.txt", "us_top200.txt"):
        path = ROOT / name
        if not path.is_file():
            continue
        symbols: list[str] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            sym = _norm_us_ticker(line.split("#", 1)[0])
            if sym:
                symbols.append(sym)
        symbols = list(dict.fromkeys(symbols))
        if symbols:
            return symbols, path
    return [], None


def main() -> int:
    symbols, src = _load_us_universe()
    if not symbols:
        print("No US universe file found (us_top300.txt / us_top200.txt)", flush=True)
        return 1

    names = {sym: sym for sym in symbols}
    names_path = ROOT / "frontend-us" / "data" / "us_stock_names.json"
    names_path.parent.mkdir(parents=True, exist_ok=True)
    names_path.write_text(json.dumps(names, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(names)} symbols → {names_path} (from {src.name})")

    breadth_path = ROOT / "us_breadth_universe.csv"
    with breadth_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["代碼", "名稱"])
        for sym in symbols:
            writer.writerow([sym, sym])
    print(f"Wrote {len(symbols)} symbols → {breadth_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
