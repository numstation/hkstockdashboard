"""
Optional shared session + writable cache for yfinance ``Ticker`` / ``download``.

yfinance 1.3+ requires a **curl_cffi** session for Yahoo (not plain ``requests``).
Injecting ``requests.Session`` breaks all fetches with YFDataException or empty data.

Cache: default OS user cache can be read-only or hit SQLite lock / "unable to open database file".
We redirect caches to ``<repo>/.cache/yfinance`` before any ticker fetch.
"""
from __future__ import annotations

import os
from pathlib import Path

import yfinance as yf

_sess = None
_orig_ticker = None
_orig_download = None
_cache_configured = False


def _repo_cache_dir() -> Path:
    root = Path(__file__).resolve().parent
    custom = os.environ.get("YFINANCE_CACHE_DIR", "").strip()
    if custom:
        return Path(custom).expanduser().resolve()
    return root / ".cache" / "yfinance"


def configure_cache() -> Path:
    """Point yfinance SQLite caches at a writable project folder. Call before first fetch."""
    global _cache_configured
    cache_dir = _repo_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    if _cache_configured:
        return cache_dir
    try:
        from yfinance.cache import set_cache_location, set_tz_cache_location

        set_cache_location(str(cache_dir))
        set_tz_cache_location(str(cache_dir))
    except Exception:
        try:
            yf.set_tz_cache_location(str(cache_dir))
        except Exception:
            pass
    _cache_configured = True
    return cache_dir


def _curl_session():
    """Session type that current yfinance expects for Yahoo API calls."""
    from curl_cffi import requests as cr

    return cr.Session(impersonate="chrome")


def enable() -> None:
    global _sess, _orig_ticker, _orig_download
    configure_cache()
    if _orig_ticker is not None:
        return

    try:
        _sess = _curl_session()
    except Exception:
        # Do not install requests.Session — yfinance 1.3+ rejects it. Use library defaults.
        return

    _orig_ticker = yf.Ticker
    _orig_download = yf.download

    def Ticker(ticker, *args, session=None, **kwargs):  # noqa: ANN001
        if session is None:
            session = _sess
        return _orig_ticker(ticker, *args, session=session, **kwargs)

    def download(*args, **kwargs):  # noqa: ANN002
        kwargs.setdefault("session", _sess)
        kwargs.setdefault("threads", False)
        return _orig_download(*args, **kwargs)

    yf.Ticker = Ticker  # type: ignore[assignment]
    yf.download = download  # type: ignore[assignment]
