"""HSI / HSCEI index membership for .HK tickers (used by scanner + frontend overlay)."""
from __future__ import annotations

import csv
from pathlib import Path

_REPO = Path(__file__).resolve().parent
_ARCHIVE_CSV = _REPO / "hkstocklist_archive_693.csv"

# Hang Seng China Enterprises Index — kept in sync with daily_scanner.HKCEI_TICKERS
HSCEI_TICKERS = [
    _raw
    for _raw in (
        "00175.HK",
        "00267.HK",
        "00291.HK",
        "00386.HK",
        "00688.HK",
        "00700.HK",
        "00762.HK",
        "00857.HK",
        "00883.HK",
        "00939.HK",
        "00941.HK",
        "00981.HK",
        "00992.HK",
        "01024.HK",
        "01088.HK",
        "01093.HK",
        "01109.HK",
        "01211.HK",
        "01288.HK",
        "01378.HK",
        "01398.HK",
        "01658.HK",
        "01801.HK",
        "01810.HK",
        "02015.HK",
        "02020.HK",
        "02057.HK",
        "02313.HK",
        "02318.HK",
        "02319.HK",
        "02328.HK",
        "02382.HK",
        "02628.HK",
        "02899.HK",
        "03328.HK",
        "03690.HK",
        "03968.HK",
        "03988.HK",
        "06160.HK",
        "06618.HK",
        "06690.HK",
        "09618.HK",
        "09633.HK",
        "09868.HK",
        "09888.HK",
        "09961.HK",
        "09987.HK",
        "09988.HK",
        "09992.HK",
        "09999.HK",
    )
]


def norm_hk_ticker(raw: str) -> str:
    """Normalize HK ticker codes (5-digit → 4-digit prefix where applicable)."""
    s = str(raw).strip().upper()
    if not s.endswith(".HK"):
        return s
    prefix = s[:-3]
    if len(prefix) == 5 and prefix.startswith("0"):
        return prefix[1:] + ".HK"
    return s


def _code_cell_to_ticker(cell: str) -> str | None:
    digits = "".join(ch for ch in str(cell).strip() if ch.isdigit())
    if not digits:
        return None
    n = int(digits, 10)
    if n <= 0:
        return None
    sym = f"{n:04d}.HK" if n < 100_000 else f"{n}.HK"
    return norm_hk_ticker(sym)


def _load_archive_index_sets() -> tuple[set[str], set[str]]:
    hsi: set[str] = set()
    hscei: set[str] = set()
    if not _ARCHIVE_CSV.is_file():
        return hsi, hscei
    with _ARCHIVE_CSV.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.reader(f):
            if len(row) < 3:
                continue
            sym = _code_cell_to_ticker(row[0])
            if not sym:
                continue
            tag = str(row[2]).strip().upper()
            if tag in ("HSI",):
                hsi.add(sym)
            elif tag in ("HSCEI",):
                hscei.add(sym)
            elif tag in ("BOTH", "HSI+HSCEI"):
                hsi.add(sym)
                hscei.add(sym)
    return hsi, hscei


_archive_hsi, _archive_hscei = _load_archive_index_sets()
_HSI_SET = frozenset(_archive_hsi)
_HSCEI_BUILTIN = frozenset(norm_hk_ticker(t) for t in HSCEI_TICKERS)
_HSCEI_SET = _HSCEI_BUILTIN | frozenset(_archive_hscei)


def _load_archive_raw_tags() -> dict[str, str]:
    """Map normalized ticker → raw 3rd-column tag from hkstocklist_archive_693.csv."""
    out: dict[str, str] = {}
    if not _ARCHIVE_CSV.is_file():
        return out
    with _ARCHIVE_CSV.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.reader(f):
            if len(row) < 3:
                continue
            sym = _code_cell_to_ticker(row[0])
            if not sym:
                continue
            out[sym] = str(row[2]).strip().upper() or "N/A"
    return out


_ARCHIVE_RAW_TAGS = _load_archive_raw_tags()


def hk_index_membership(ticker: str) -> str:
    """
    Returns BOTH (in HSI and HSCEI), HSI, HSCEI, or N/A.
    HSI names come from hkstocklist_archive_693.csv; HSCEI from HSCEI_TICKERS + archive.
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
    in_ce_builtin = sym in _HSCEI_BUILTIN
    in_ce = sym in _HSCEI_SET
    return {
        "ticker": sym,
        "archive_tag": _ARCHIVE_RAW_TAGS.get(sym, ""),
        "hsi_from_archive": in_hsi,
        "hscei_from_list": in_ce_builtin,
        "label": hk_index_membership(sym),
    }
