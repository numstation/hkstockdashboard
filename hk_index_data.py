"""HSI / HSCEI index membership for .HK tickers (used by scanner + frontend overlay)."""
from __future__ import annotations

import csv
from pathlib import Path

_REPO = Path(__file__).resolve().parent
_HSI_CSV = _REPO / "HSI.csv"
_HSCEI_CSV = _REPO / "HSCEI.csv"


def norm_hk_ticker(raw: str) -> str:
    """Normalize HK ticker codes (5-digit → 4-digit prefix where applicable)."""
    s = str(raw).strip().upper()
    if not s.endswith(".HK"):
        return s
    prefix = s[:-3]
    if len(prefix) == 5 and prefix.startswith("0"):
        return prefix[1:] + ".HK"
    return s


def _load_index_csv(path: Path) -> set[str]:
    out: set[str] = set()
    if not path.is_file():
        return out
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return out
        code_key = next((k for k in reader.fieldnames if k.strip().upper() == "CODE"), None)
        if not code_key:
            return out
        for row in reader:
            code = str(row.get(code_key) or "").strip()
            if not code:
                continue
            sym = norm_hk_ticker(code)
            if sym.endswith(".HK"):
                out.add(sym)
    return out


def _ticker_sort_key(t: str) -> tuple[int, str]:
    prefix = t[:-3]
    try:
        return int(prefix), t
    except ValueError:
        return 999_999, t


_HSI_SET = frozenset(_load_index_csv(_HSI_CSV))
_HSCEI_SET = frozenset(_load_index_csv(_HSCEI_CSV))

HSI_TICKERS = tuple(sorted(_HSI_SET, key=_ticker_sort_key))
HSCEI_TICKERS = tuple(sorted(_HSCEI_SET, key=_ticker_sort_key))
HKCEI_TICKERS = HSCEI_TICKERS  # alias used by daily_scanner


def hk_index_membership(ticker: str) -> str:
    """
    Returns BOTH (in HSI and HSCEI), HSI, HSCEI, or N/A.
    Source: HSI.csv and HSCEI.csv in repo root.
    """
    s = str(ticker).strip().upper()
    if not s.endswith(".HK"):
        return "N/A"
    sym = norm_hk_ticker(s)
    in_hsi = sym in _HSI_SET
    in_ce = sym in _HSCEI_SET
    if in_hsi and in_ce:
        return "BOTH"
    if in_hsi:
        return "HSI"
    if in_ce:
        return "HSCEI"
    return "N/A"


def membership_map_for_tickers(tickers: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for t in tickers:
        key = norm_hk_ticker(str(t).strip().upper())
        if not key.endswith(".HK"):
            continue
        out[key] = hk_index_membership(key)
    return out


def membership_detail(ticker: str) -> dict[str, str | bool]:
    sym = norm_hk_ticker(str(ticker).strip().upper())
    in_hsi = sym in _HSI_SET
    in_ce = sym in _HSCEI_SET
    return {
        "ticker": sym,
        "in_hsi": in_hsi,
        "in_hscei": in_ce,
        "label": hk_index_membership(sym),
    }
