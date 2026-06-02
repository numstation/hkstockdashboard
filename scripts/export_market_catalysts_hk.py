#!/usr/bin/env python3
"""Export filtered HK market catalysts (macro + 133-universe Yahoo RSS) for the dashboard."""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HKT = timezone(timedelta(hours=8))

# Broker / roundup noise — keep company & macro catalyst headlines only.
_TITLE_BLOCK_RE = re.compile(
    r"大行|經紀|券商|首予|重申|目標價|評級|唱好|看淡|升級|降級|予買|予沽|"
    r"上調目標|下調目標|維持「|維持評|《港股》|《半日|《今早重點|半日速報|"
    r"恒指半日|恆指半日|收市報|美股三大|隔晚\(.*\)美股|十大|沽空比例|"
    r"港股ADR|預計恆指|A股|滬深300|標售|海景|維港.*房|單位獲|"
    r"港股通.*淨流入",
    re.I,
)
_ROUNDUP_TITLE_RE = re.compile(r"^《|恒指|恆指|科指|國指", re.I)
_CJK_RE = re.compile(r"[\u3400-\u9fff]")

_POSITIVE_RE = re.compile(r"回購|增長|推出|創新高|勝預期|流入|上升|急升|升逾", re.I)
_NEGATIVE_RE = re.compile(r"虧損|警告|流出|下跌|急跌|降.*售|停牌", re.I)


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


def _clean_title(title: str) -> str:
    s = re.sub(r"\s+", " ", title.strip())
    s = re.sub(r"^《[^》]*》", "", s).strip()
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


def _fetch_yahoo_rss(ticker: str, timeout: float = 8.0) -> list[dict]:
    url = (
        "https://feeds.finance.yahoo.com/rss/2.0/headline?"
        f"s={urllib.parse.quote(ticker)}&region=HK&lang=zh-Hant-HK"
    )
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; hk-dashboard-catalysts/1.0)"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        xml_data = resp.read()
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
                "kind": "company",
                "ticker": ticker,
                "text": _clean_title(title),
                "tone": _tone_for_text(title, "company"),
                "link": link_el.text.strip() if link_el is not None and link_el.text else "",
                "_sort": dt.timestamp(),
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
                "ticker": None,
                "text": f"北水淨{'流入' if net_yi >= 0 else '流出'} {sign}{net_yi:.2f}億 → {flow}。",
                "tone": _tone_for_text("", "macro", net_yi=float(net_yi)),
                "link": "",
                "_sort": now_hkt.timestamp(),
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
                "ticker": None,
                "text": text,
                "tone": "green" if pct >= 55 else ("red" if pct <= 35 else "neutral"),
                "link": "",
                "_sort": now_hkt.timestamp() - 1,
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
                "ticker": None,
                "text": f"VIX {vix_val:.2f} → {mood}。",
                "tone": "green" if vix_val < 18 else ("red" if vix_val >= 25 else "neutral"),
                "link": "",
                "_sort": now_hkt.timestamp() - 2,
            }
        )

    return items


def export_catalysts(
    *,
    universe_csv: Path,
    macro_path: Path,
    out_path: Path,
    sleep_sec: float = 0.12,
    max_items: int = 20,
    skip_rss: bool = False,
    hours: int = 24,
) -> dict:
    now_hkt = datetime.now(HKT)
    cutoff = now_hkt - timedelta(hours=hours)
    tickers = _load_universe(universe_csv)

    macro: dict = {}
    if macro_path.is_file():
        macro = json.loads(macro_path.read_text(encoding="utf-8"))

    items = _macro_items(macro, now_hkt)

    seen_titles: set[str] = set()
    if not skip_rss:
        for i, ticker in enumerate(tickers):
            try:
                for row in _fetch_yahoo_rss(ticker):
                    if row["_sort"] < cutoff.timestamp():
                        continue
                    key = re.sub(r"\s+", "", row["text"].lower())
                    if key in seen_titles:
                        continue
                    seen_titles.add(key)
                    items.append(row)
            except Exception as exc:
                print(f"  RSS skip {ticker}: {exc}", file=sys.stderr)
            if sleep_sec > 0 and i + 1 < len(tickers):
                time.sleep(sleep_sec)

    items.sort(key=lambda x: x.get("_sort", 0), reverse=True)

    # One company headline per ticker; macro lines always kept.
    seen_tickers: set[str] = set()
    deduped: list[dict] = []
    for row in items:
        if row.get("kind") == "company":
            tk = str(row.get("ticker") or "")
            if tk in seen_tickers:
                continue
            seen_tickers.add(tk)
        deduped.append(row)

    trimmed = deduped[:max_items]
    for row in trimmed:
        row.pop("_sort", None)
        if row.get("link") == "":
            row.pop("link", None)

    payload = {
        "schema_version": "1.0",
        "last_updated": now_hkt.isoformat(timespec="seconds"),
        "universe_size": len(tickers),
        "items": trimmed,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    ap = argparse.ArgumentParser(description="Export HK market catalysts JSON")
    ap.add_argument("--universe", type=Path, default=ROOT / "hk_breadth_universe.csv")
    ap.add_argument("--macro", type=Path, default=ROOT / "macro_snapshot.json")
    ap.add_argument("--out", type=Path, default=ROOT / "market_catalysts_hk.json")
    ap.add_argument("--sleep", type=float, default=0.12, help="Pause between Yahoo RSS calls")
    ap.add_argument("--max-items", type=int, default=20)
    ap.add_argument("--hours", type=int, default=24, help="Keep headlines from last N hours")
    ap.add_argument("--skip-rss", action="store_true", help="Macro lines only (fast local test)")
    args = ap.parse_args()

    payload = export_catalysts(
        universe_csv=args.universe,
        macro_path=args.macro,
        out_path=args.out,
        sleep_sec=args.sleep,
        max_items=args.max_items,
        skip_rss=args.skip_rss,
        hours=args.hours,
    )
    print(
        f"Wrote {len(payload.get('items') or [])} catalysts "
        f"(universe {payload.get('universe_size')}) → {args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
