#!/usr/bin/env python3
"""Export hk_index_membership.json + review CSV for HSI / HSCEI checks."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hk_index_data import hk_index_membership, membership_detail, norm_hk_ticker


def _rows_from_hkstocklist() -> list[tuple[str, str, str]]:
    """Return (code, ticker, name) from hkstocklist.csv."""
    path = ROOT / "hkstocklist.csv"
    if not path.is_file():
        return []
    out: list[tuple[str, str, str]] = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.reader(f):
            if not row or not str(row[0]).strip():
                continue
            code = str(row[0]).strip()
            if code.lower() == "code":
                continue
            name = str(row[1]).strip() if len(row) > 1 else ""
            digits = "".join(ch for ch in code if ch.isdigit())
            if not digits:
                continue
            n = int(digits, 10)
            sym = f"{n:04d}.HK" if n < 100_000 else f"{n}.HK"
            out.append((digits, norm_hk_ticker(sym), name))
    return out


def _write_review_csv(rows: list[tuple[str, str, str]], dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "code",
                "ticker",
                "name",
                "in_hsi",
                "in_hscei",
                "label",
                "correct_label",
            ]
        )
        for code, ticker, name in rows:
            d = membership_detail(ticker)
            w.writerow(
                [
                    code,
                    ticker,
                    name,
                    "Y" if d["in_hsi"] else "N",
                    "Y" if d["in_hscei"] else "N",
                    d["label"],
                    "",
                ]
            )


def main() -> int:
    rows = _rows_from_hkstocklist()
    mapping = {ticker: hk_index_membership(ticker) for _, ticker, _ in rows}

    json_dest = ROOT / "frontend/data/hk_index_membership.json"
    json_dest.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0",
        "source": "HSI.csv + HSCEI.csv",
        "labels": {"BOTH": "HSI and HSCEI constituent", "HSI": "HSI only", "HSCEI": "HSCEI only"},
        "membership": mapping,
    }
    json_dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    review_csv = ROOT / "hk_index_membership_review.csv"
    _write_review_csv(rows, review_csv)
    _write_review_csv(rows, ROOT / "frontend/data/hk_index_membership_review.csv")

    both_n = sum(1 for v in mapping.values() if v == "BOTH")
    print(f"Wrote {json_dest} ({len(mapping)} tickers, {both_n} BOTH)")
    print(f"Wrote {review_csv} (hkstocklist universe — fill correct_label if any mismatch)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
