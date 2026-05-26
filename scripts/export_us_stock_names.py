#!/usr/bin/env python3
"""Write frontend-us/data/us_stock_names.json from us_top200.txt (symbol → symbol)."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    src = ROOT / "us_top200.txt"
    dest = ROOT / "frontend-us" / "data" / "us_stock_names.json"
    names: dict[str, str] = {}
    if src.is_file():
        for line in src.read_text(encoding="utf-8").splitlines():
            sym = line.strip().upper()
            if sym and not sym.startswith("#"):
                names[sym] = sym
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(names, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(names)} symbols → {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
