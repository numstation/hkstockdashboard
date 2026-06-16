#!/usr/bin/env python3
"""Export hk_index_membership.json for frontend HSI / HSCEI column overlay."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hk_index_data import hk_index_membership, membership_map_for_tickers, norm_hk_ticker


def _tickers_from_hkstocklist() -> list[str]:
    path = ROOT / "hkstocklist.csv"
    if not path.is_file():
        return []
    out: list[str] = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.reader(f):
            if not row or not str(row[0]).strip():
                continue
            key = str(row[0]).strip()
            if key.lower() == "code":
                continue
            digits = "".join(ch for ch in key if ch.isdigit())
            if not digits:
                continue
            n = int(digits, 10)
            sym = f"{n:04d}.HK" if n < 100_000 else f"{n}.HK"
            out.append(norm_hk_ticker(sym))
    return list(dict.fromkeys(out))


def main() -> int:
    tickers = _tickers_from_hkstocklist()
    mapping = membership_map_for_tickers(tickers)
    # Include all archive + HSCEI names so lookup works even off-universe rows
    for sym in list(mapping.keys()):
        mapping[sym] = hk_index_membership(sym)

    dest = ROOT / "frontend/data/hk_index_membership.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0",
        "source": "hkstocklist_archive_693.csv + HSCEI list",
        "labels": {"BOTH": "HSI and HSCEI constituent", "HSI": "HSI only", "HSCEI": "HSCEI only"},
        "membership": mapping,
    }
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    both_n = sum(1 for v in mapping.values() if v == "BOTH")
    print(f"Wrote {dest} ({len(mapping)} tickers, {both_n} BOTH)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
