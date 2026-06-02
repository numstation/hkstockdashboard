#!/usr/bin/env python3
"""Export filtered HK market catalysts for the dashboard (v2: macro + HKEX + earnings + Yahoo)."""
from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HKT = timezone(timedelta(hours=8))
HKEX_STOCK_LIST_URL = "https://www1.hkexnews.hk/ncms/script/eds/activestock_sehk_c.json"
HKEX_SEARCH_URL = "https://www1.hkexnews.hk/search/titleSearchServlet.do"
HKEX_BASE = "https://www1.hkexnews.hk"

# Broker / roundup noise — keep company & macro catalyst headlines only.
_TITLE_BLOCK_RE = re.compile(
    r"大行|經紀|券商|首予|重申|目標價|評級|唱好|看淡|升級|降級|予買|予沽|"
    r"上調目標|下調目標|維持「|維持評|《港股》|《半日|《今早重點|半日速報|"
    r"恒指半日|恆指半日|收市報|美股三大|隔晚\(.*\)美股|十大|沽空比例|"
    r"港股ADR|預計恆指|A股|滬深300|標售|海景|維港.*房|單位獲|"
    r"港股通.*淨流入|代言|Comic Con|球星",
    re.I,
)
_ROUNDUP_TITLE_RE = re.compile(r"^《|恒指|恆指|科指|國指", re.I)
_CJK_RE = re.compile(r"[\u3400-\u9fff]")

_HKEX_KEEP_RE = re.compile(
    r"回購|購回|業績|盈利|年報|中期|公告|停牌|復牌|配股|澄清|須予|重大|合約|"
    r"授出|董事|辞任|任免|股息|分派|盈利警告|減產|并购|收購|股份變動",
    re.I,
)
_HKEX_DROP_RE = re.compile(
    r"^(翌日披露報表|月報表|證券變動月報表|於其他市場發佈的公告)$",
    re.I,
)
_HKEX_LOW_VALUE_RE = re.compile(r"公司債券|科技創新.*債券|票面利率公告", re.I)

_POSITIVE_RE = re.compile(r"回購|增長|推出|創新高|勝預期|流入|上升|急升|升逾|購回", re.I)
_NEGATIVE_RE = re.compile(r"虧損|警告|流出|下跌|急跌|降.*售|停牌|盈利警告", re.I)

_KIND_PRIORITY = {"macro": 0, "earnings": 1, "hkex": 2, "news": 3, "company": 3}


def _load_universe(csv_path: Path) -> list[str]:
    tickers: list[str] = []
    if not csv_path.is_file():
        return tickers
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue
            raw = str(row[0]).strip()
            if not raw or raw in ("代碼", "code", "Code"):
                continue
            digits = "".join(ch for ch in raw if ch.isdigit())
            if not digits:
                continue
            code = int(digits, 10)
            if code <= 0:
                continue
            sym = f"{code:04d}.HK" if code < 100_000 else f"{code}.HK"
            tickers.append(sym)
    return sorted(set(tickers))


def _ticker_hkex_code(ticker: str) -> str:
    digits = ticker.replace(".HK", "").strip()
    if digits.isdigit():
        return digits.zfill(5)
    return digits


def _hkex_code_to_ticker(code: str, allowed: set[str]) -> str | None:
    raw = re.sub(r"<[^>]+>", " ", code or "")
    for token in re.findall(r"\d{4,5}", raw):
        n = int(token, 10)
        candidates = (
            f"{n:04d}.HK",
            f"{n}.HK",
            f"{token}.HK",
        )
        for c in candidates:
            if c in allowed:
                return c
    return None


def _parse_pub_hkt(pub_raw: str | None) -> tuple[str, str, datetime] | None:
    if not pub_raw:
        return None
    try:
        dt = parsedate_to_datetime(pub_raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        hkt = dt.astimezone(HKT)
        return hkt.strftime("%H:%M"), hkt.strftime("%Y-%m-%d"), hkt
    except (TypeError, ValueError, OverflowError):
        return None


def _parse_hkex_dt(raw: str) -> tuple[str, str, datetime] | None:
    s = str(raw or "").strip()
    if not s:
        return None
    try:
        dt = datetime.strptime(s, "%d/%m/%Y %H:%M").replace(tzinfo=HKT)
        return dt.strftime("%H:%M"), dt.strftime("%Y-%m-%d"), dt
    except ValueError:
        return None


def _clean_title(title: str) -> str:
    s = html.unescape(re.sub(r"\s+", " ", title.strip()))
    s = re.sub(r"^《[^》]*》", "", s).strip()
    s = re.sub(r"^翌日披露報表\s*[-–—]\s*", "", s).strip()
    if len(s) > 96:
        s = s[:93].rstrip() + "…"
    return s


def _title_matches_ticker(title: str, ticker: str) -> bool:
    feed_digits = ticker.replace(".HK", "").lstrip("0") or "0"
    mentioned = re.findall(r"(\d{4,5})(?:\.HK|\)|\.HK\))", title, flags=re.I)
    if not mentioned:
        return True
    norm = {m.lstrip("0") or "0" for m in mentioned}
    return feed_digits in norm


def _title_ok(title: str, ticker: str = "") -> bool:
    t = title.strip()
    if len(t) < 6:
        return False
    if not _CJK_RE.search(t):
        return False
    if _TITLE_BLOCK_RE.search(t):
        return False
    if _ROUNDUP_TITLE_RE.search(t):
        return False
    if ticker and not _title_matches_ticker(t, ticker):
        return False
    return True


def _hkex_title_ok(title: str) -> bool:
    t = _clean_title(title)
    if len(t) < 4:
        return False
    if _HKEX_DROP_RE.match(t):
        return False
    if _HKEX_LOW_VALUE_RE.search(t):
        return False
    if _HKEX_KEEP_RE.search(t):
        return True
    if "翌日披露" in t and re.search(r"回購|購回|股份變動", t):
        return True
    return False


def _tone_for_text(text: str, kind: str, net_yi: float | None = None) -> str:
    if kind == "macro" and isinstance(net_yi, (int, float)):
        if net_yi >= 20:
            return "green"
        if net_yi <= -20:
            return "red"
    if _NEGATIVE_RE.search(text):
        return "red"
    if _POSITIVE_RE.search(text):
        return "green"
    return "neutral"


def _http_get(url: str, timeout: float = 12.0) -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; hk-dashboard-catalysts/2.0)"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _load_hkex_stock_map() -> dict[str, int]:
    try:
        data = json.loads(_http_get(HKEX_STOCK_LIST_URL, timeout=20).decode("utf-8"))
    except Exception as exc:
        print(f"  HKEX stock list skip: {exc}", file=sys.stderr)
        return {}
    out: dict[str, int] = {}
    if isinstance(data, list):
        for row in data:
            if not isinstance(row, dict):
                continue
            code = str(row.get("c") or "").strip()
            sid = row.get("i")
            if code and isinstance(sid, int):
                out[code] = sid
    return out


def _fetch_hkex_for_ticker(
    ticker: str,
    stock_id: int,
    from_yyyymmdd: str,
    to_yyyymmdd: str,
) -> list[dict]:
    params = {
        "sortDir": "0",
        "sortByOptions": "DateTime",
        "category": "0",
        "market": "SEHK",
        "stockId": str(stock_id),
        "documentType": "-1",
        "fromDate": from_yyyymmdd,
        "toDate": to_yyyymmdd,
        "title": "",
        "searchType": "0",
        "t1code": "0",
        "t2Gcode": "-2",
        "t2code": "0",
        "rowRange": "5",
        "lang": "zh",
    }
    url = HKEX_SEARCH_URL + "?" + urllib.parse.urlencode(params)
    payload = json.loads(_http_get(url, timeout=15).decode("utf-8"))
    raw = payload.get("result")
    rows = json.loads(raw) if isinstance(raw, str) and raw else []
    if not isinstance(rows, list):
        return []

    out: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = str(row.get("TITLE") or "").strip()
        if not _hkex_title_ok(title):
            continue
        parsed = _parse_hkex_dt(str(row.get("DATE_TIME") or ""))
        if not parsed:
            continue
        ts_hkt, day, dt = parsed
        link = str(row.get("FILE_LINK") or "").strip()
        text = _clean_title(title)
        out.append(
            {
                "ts_hkt": ts_hkt,
                "date": day,
                "kind": "hkex",
                "source": "hkex",
                "ticker": ticker,
                "text": text,
                "tone": _tone_for_text(text, "hkex"),
                "link": HKEX_BASE + link if link.startswith("/") else link,
                "_sort": dt.timestamp(),
                "_priority": _KIND_PRIORITY["hkex"],
            }
        )
    return out


def _fetch_yahoo_rss(ticker: str, timeout: float = 8.0) -> list[dict]:
    url = (
        "https://feeds.finance.yahoo.com/rss/2.0/headline?"
        f"s={urllib.parse.quote(ticker)}&region=HK&lang=zh-Hant-HK"
    )
    xml_data = _http_get(url, timeout=timeout)
    root = ET.fromstring(xml_data)
    items = root.findall("./channel/item") or root.findall(".//item")
    out: list[dict] = []
    for item in items[:2]:
        title_el = item.find("title")
        link_el = item.find("link")
        pub_el = item.find("pubDate")
        title = title_el.text.strip() if title_el is not None and title_el.text else ""
        if not _title_ok(title, ticker):
            continue
        parsed = _parse_pub_hkt(pub_el.text if pub_el is not None else None)
        if not parsed:
            continue
        ts_hkt, day, dt = parsed
        out.append(
            {
                "ts_hkt": ts_hkt,
                "date": day,
                "kind": "news",
                "source": "yahoo",
                "ticker": ticker,
                "text": _clean_title(title),
                "tone": _tone_for_text(title, "news"),
                "link": link_el.text.strip() if link_el is not None and link_el.text else "",
                "_sort": dt.timestamp(),
                "_priority": _KIND_PRIORITY["news"],
            }
        )
    return out


def _macro_items(macro: dict, now_hkt: datetime) -> list[dict]:
    items: list[dict] = []
    ts = now_hkt.strftime("%H:%M")
    day = now_hkt.strftime("%Y-%m-%d")

    sb = macro.get("southbound_connect") if isinstance(macro.get("southbound_connect"), dict) else {}
    net_yi = sb.get("net_yi")
    sb_date = str(sb.get("net_yi_date") or day)[:10]
    if isinstance(net_yi, (int, float)):
        sign = "+" if net_yi >= 0 else ""
        flow = "流入支撐" if net_yi >= 0 else "抽水撤離"
        items.append(
            {
                "ts_hkt": ts,
                "date": sb_date,
                "kind": "macro",
                "source": "macro_snapshot",
                "ticker": None,
                "text": f"北水淨{'流入' if net_yi >= 0 else '流出'} {sign}{net_yi:.2f}億 → {flow}。",
                "tone": _tone_for_text("", "macro", net_yi=float(net_yi)),
                "_sort": now_hkt.timestamp(),
                "_priority": _KIND_PRIORITY["macro"],
            }
        )

    bm = macro.get("breadth_markets") if isinstance(macro.get("breadth_markets"), dict) else {}
    hk = bm.get("hk") if isinstance(bm.get("hk"), dict) else {}
    pct = hk.get("above_ma50_pct")
    sampled = hk.get("sampled")
    if isinstance(pct, (int, float)) and isinstance(sampled, (int, float)) and sampled > 0:
        above = hk.get("above_ma50")
        if not isinstance(above, (int, float)):
            above = round(float(pct) * float(sampled) / 100.0)
        text = f"港股核心 {int(sampled)} 隻中 {int(above)} 隻站穩 SMA50（{pct:.0f}%）。"
        items.append(
            {
                "ts_hkt": ts,
                "date": day,
                "kind": "macro",
                "source": "macro_snapshot",
                "ticker": None,
                "text": text,
                "tone": "green" if pct >= 55 else ("red" if pct <= 35 else "neutral"),
                "_sort": now_hkt.timestamp() - 1,
                "_priority": _KIND_PRIORITY["macro"],
            }
        )

    metrics = macro.get("metrics") if isinstance(macro.get("metrics"), list) else []
    vix_val = None
    for m in metrics:
        if isinstance(m, dict) and str(m.get("name", "")).upper() == "VIX":
            try:
                vix_val = float(str(m.get("value", "")).replace(",", ""))
            except ValueError:
                vix_val = None
            break
    if isinstance(vix_val, (int, float)):
        mood = "放心進攻" if vix_val < 18 else ("警戒" if vix_val < 25 else "高波動")
        items.append(
            {
                "ts_hkt": ts,
                "date": day,
                "kind": "macro",
                "source": "macro_snapshot",
                "ticker": None,
                "text": f"VIX {vix_val:.2f} → {mood}。",
                "tone": "green" if vix_val < 18 else ("red" if vix_val >= 25 else "neutral"),
                "_sort": now_hkt.timestamp() - 2,
                "_priority": _KIND_PRIORITY["macro"],
            }
        )

    return items


def _load_earnings_cache(cache_path: Path) -> dict[str, str]:
    if not cache_path.is_file():
        return {}
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        by = data.get("by_ticker")
        return {str(k): str(v) for k, v in by.items()} if isinstance(by, dict) else {}
    except Exception:
        return {}


def _save_earnings_cache(cache_path: Path, by_ticker: dict[str, str], now_hkt: datetime) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "last_updated": now_hkt.isoformat(timespec="seconds"),
                "by_ticker": by_ticker,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _fetch_next_earnings(ticker: str) -> str | None:
    try:
        import pandas as pd
        import yfinance as yf
    except ImportError:
        return None

    try:
        t = yf.Ticker(ticker)
        ed = getattr(t, "earnings_dates", None)
        if ed is not None and not ed.empty:
            now = pd.Timestamp.now(tz="UTC")
            idx = ed.index
            if idx.tz is None:
                idx = idx.tz_localize("UTC")
            else:
                idx = idx.tz_convert("UTC")
            future = ed[idx > now]
            if not future.empty:
                return future.index[0].strftime("%Y-%m-%d")
        cal = getattr(t, "calendar", None)
        if isinstance(cal, dict):
            raw = cal.get("Earnings Date") or cal.get("Earnings Date High")
            if isinstance(raw, list) and raw:
                raw = raw[0]
            if hasattr(raw, "strftime"):
                return raw.strftime("%Y-%m-%d")
            if raw:
                return str(raw)[:10]
    except Exception:
        return None
    return None


def _earnings_items(
    tickers: list[str],
    *,
    cache_path: Path,
    now_hkt: datetime,
    horizon_days: int = 14,
    refresh: bool = False,
    sleep_sec: float = 0.08,
) -> list[dict]:
    cache_age_ok = False
    if cache_path.is_file() and not refresh:
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            lu = cached.get("last_updated")
            if lu:
                dt = datetime.fromisoformat(str(lu))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=HKT)
                cache_age_ok = (now_hkt - dt.astimezone(HKT)) < timedelta(hours=24)
        except Exception:
            cache_age_ok = False

    if cache_age_ok:
        by_ticker = _load_earnings_cache(cache_path)
    else:
        by_ticker = {}
        for i, ticker in enumerate(tickers):
            nxt = _fetch_next_earnings(ticker)
            if nxt:
                by_ticker[ticker] = nxt
            if sleep_sec > 0 and i + 1 < len(tickers):
                time.sleep(sleep_sec)
        _save_earnings_cache(cache_path, by_ticker, now_hkt)

    horizon = now_hkt.date() + timedelta(days=horizon_days)
    items: list[dict] = []
    for ticker, iso in sorted(by_ticker.items()):
        try:
            d = datetime.strptime(iso[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
        if d < now_hkt.date() or d > horizon:
            continue
        days = (d - now_hkt.date()).days
        when = "今日" if days == 0 else (f"{days} 日後" if days <= 7 else iso[:10])
        items.append(
            {
                "ts_hkt": "09:00",
                "date": now_hkt.strftime("%Y-%m-%d"),
                "kind": "earnings",
                "source": "yfinance",
                "ticker": ticker,
                "text": f"{when}（{iso[:10]}）。",
                "tone": "neutral",
                "_sort": datetime.combine(d, datetime.min.time(), tzinfo=HKT).timestamp(),
                "_priority": _KIND_PRIORITY["earnings"],
            }
        )
    items.sort(key=lambda x: x["_sort"])
    return items[:8]


def _clean_row(row: dict) -> dict:
    out = dict(row)
    out.pop("_sort", None)
    out.pop("_priority", None)
    if out.get("link") == "":
        out.pop("link", None)
    return out


def _finalize_timed_section(
    rows: list[dict],
    *,
    max_items: int,
    sort_desc: bool = True,
    one_per_ticker: bool = False,
) -> list[dict]:
    rows.sort(key=lambda x: x.get("_sort", 0), reverse=sort_desc)
    seen_titles: set[str] = set()
    seen_tickers: set[str] = set()
    out: list[dict] = []
    for row in rows:
        ticker = str(row.get("ticker") or "")
        if one_per_ticker and ticker:
            if ticker in seen_tickers:
                continue
            seen_tickers.add(ticker)
        title_key = re.sub(r"\s+", "", str(row.get("text") or "").lower())
        if title_key and title_key in seen_titles:
            continue
        if title_key:
            seen_titles.add(title_key)
        out.append(_clean_row(row))
        if len(out) >= max_items:
            break
    return out


def _build_sections(
    *,
    earnings: list[dict],
    hkex: list[dict],
    news: list[dict],
    limits: dict[str, int],
) -> dict[str, list[dict]]:
    return {
        "news": _finalize_timed_section(
            news, max_items=limits.get("news", 8), sort_desc=True, one_per_ticker=True
        ),
        "hkex": _finalize_timed_section(
            hkex, max_items=limits.get("hkex", 12), sort_desc=True, one_per_ticker=True
        ),
        "earnings": _finalize_timed_section(
            earnings, max_items=limits.get("earnings", 8), sort_desc=False
        ),
    }


def export_catalysts(
    *,
    universe_csv: Path,
    macro_path: Path,
    out_path: Path,
    earnings_cache_path: Path,
    sleep_sec: float = 0.12,
    max_items: int = 24,
    skip_rss: bool = False,
    skip_hkex: bool = False,
    skip_earnings: bool = False,
    refresh_earnings: bool = False,
    hours: int = 24,
    hkex_workers: int = 8,
) -> dict:
    now_hkt = datetime.now(HKT)
    cutoff = now_hkt - timedelta(hours=hours)
    tickers = _load_universe(universe_csv)

    earnings_rows: list[dict] = []
    hkex_rows: list[dict] = []
    news_rows: list[dict] = []

    if not skip_earnings:
        earnings_rows = _earnings_items(
            tickers,
            cache_path=earnings_cache_path,
            now_hkt=now_hkt,
            refresh=refresh_earnings,
            sleep_sec=max(0.05, sleep_sec * 0.5),
        )

    if not skip_hkex:
        stock_map = _load_hkex_stock_map()
        from_d = (now_hkt - timedelta(days=2)).strftime("%Y%m%d")
        to_d = now_hkt.strftime("%Y%m%d")
        jobs = []
        for ticker in tickers:
            sid = stock_map.get(_ticker_hkex_code(ticker))
            if sid:
                jobs.append((ticker, sid))

        if jobs:
            with ThreadPoolExecutor(max_workers=max(1, hkex_workers)) as pool:
                futs = {
                    pool.submit(_fetch_hkex_for_ticker, tk, sid, from_d, to_d): tk
                    for tk, sid in jobs
                }
                for fut in as_completed(futs):
                    ticker = futs[fut]
                    try:
                        for row in fut.result():
                            if row["_sort"] >= cutoff.timestamp():
                                hkex_rows.append(row)
                    except Exception as exc:
                        print(f"  HKEX skip {ticker}: {exc}", file=sys.stderr)

    if not skip_rss:
        hkex_tickers = {str(r.get("ticker") or "") for r in hkex_rows}
        for i, ticker in enumerate(tickers):
            try:
                for row in _fetch_yahoo_rss(ticker):
                    if row["_sort"] >= cutoff.timestamp():
                        if ticker in hkex_tickers:
                            continue
                        news_rows.append(row)
            except Exception as exc:
                print(f"  RSS skip {ticker}: {exc}", file=sys.stderr)
            if sleep_sec > 0 and i + 1 < len(tickers):
                time.sleep(sleep_sec)

    per_section = {
        "news": max(6, min(10, max_items - 14)),
        "hkex": 12,
        "earnings": 8,
    }
    sections = _build_sections(
        earnings=earnings_rows,
        hkex=hkex_rows,
        news=news_rows,
        limits=per_section,
    )
    flat = sections["news"] + sections["hkex"] + sections["earnings"]

    payload = {
        "schema_version": "2.2",
        "last_updated": now_hkt.isoformat(timespec="seconds"),
        "universe_size": len(tickers),
        "sources": ["hkex", "yfinance", "yahoo"],
        "sections": sections,
        "items": flat,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    ap = argparse.ArgumentParser(description="Export HK market catalysts JSON")
    ap.add_argument("--universe", type=Path, default=ROOT / "hk_breadth_universe.csv")
    ap.add_argument("--macro", type=Path, default=ROOT / "macro_snapshot.json")
    ap.add_argument("--out", type=Path, default=ROOT / "market_catalysts_hk.json")
    ap.add_argument(
        "--earnings-cache",
        type=Path,
        default=ROOT / "market_catalysts_earnings_hk.json",
    )
    ap.add_argument("--sleep", type=float, default=0.12, help="Pause between Yahoo RSS calls")
    ap.add_argument("--max-items", type=int, default=24)
    ap.add_argument("--hours", type=int, default=24, help="Keep headlines from last N hours")
    ap.add_argument("--hkex-workers", type=int, default=8)
    ap.add_argument("--skip-rss", action="store_true", help="Skip Yahoo RSS")
    ap.add_argument("--skip-hkex", action="store_true", help="Skip HKEX announcements")
    ap.add_argument("--skip-earnings", action="store_true", help="Skip earnings calendar")
    ap.add_argument("--refresh-earnings", action="store_true", help="Force refresh earnings cache")
    args = ap.parse_args()

    payload = export_catalysts(
        universe_csv=args.universe,
        macro_path=args.macro,
        out_path=args.out,
        earnings_cache_path=args.earnings_cache,
        sleep_sec=args.sleep,
        max_items=args.max_items,
        skip_rss=args.skip_rss,
        skip_hkex=args.skip_hkex,
        skip_earnings=args.skip_earnings,
        refresh_earnings=args.refresh_earnings,
        hours=args.hours,
        hkex_workers=args.hkex_workers,
    )
    sec = payload.get("sections") if isinstance(payload.get("sections"), dict) else {}
    counts = {k: len(v) for k, v in sec.items() if isinstance(v, list)}
    print(
        f"Wrote {len(payload.get('items') or [])} catalysts "
        f"(universe {payload.get('universe_size')}, sections {counts}) → {args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
