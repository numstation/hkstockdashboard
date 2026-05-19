"""
Dashboard JSON schema version: bump once per export run; major increases every 10 updates.

Version string is major-only: 1.0 (updates 1–9), 2.0 (10–19), 3.0 (20–29), …
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

UPDATES_PER_MAJOR = 10
META_FILENAME = "schema_version_meta.json"

_REPO_ROOT = Path(__file__).resolve().parent
_META_PATH = _REPO_ROOT / META_FILENAME

_run_version: str | None = None

SCORE_MODEL_LABELS = {
    "sell_put": "Sell Put 穩健收租",
    "buy_stock": "Buy Stock 極限爆發",
    "buy_put": "Buy Put 恐慌破底",
}


def repo_root() -> Path:
    return _REPO_ROOT


def _now_iso() -> str:
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz).isoformat(timespec="seconds")


def version_from_update_count(count: int) -> str:
    """Updates 1–9 → 1.0, 10–19 → 2.0, 20–29 → 3.0, …"""
    c = max(0, int(count))
    if c <= 0:
        return "1.0"
    major = c // UPDATES_PER_MAJOR + 1
    return f"{major}.0"


def _legacy_version_to_count(ver: str) -> int:
    """Map legacy strings like 1.3 → 13 updates (so next display is 2.0)."""
    s = str(ver or "").strip()
    if not s:
        return 0
    try:
        return max(0, int(round(float(s) * 10)))
    except ValueError:
        return 0


def _seed_count_from_repo_json() -> int:
    best = 0
    for path in _REPO_ROOT.glob("*.json"):
        if path.name == META_FILENAME:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        ver = data.get("schema_version")
        if ver:
            best = max(best, _legacy_version_to_count(str(ver)))
    return best


def load_meta() -> dict:
    if _META_PATH.is_file():
        try:
            data = json.loads(_META_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    seeded = _seed_count_from_repo_json()
    return {"update_count": seeded, "seeded_from_legacy": True}


def save_meta(meta: dict) -> None:
    meta = dict(meta)
    meta["last_saved_at"] = _now_iso()
    _META_PATH.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def current_schema_version() -> str:
    meta = load_meta()
    return version_from_update_count(int(meta.get("update_count", 0)))


def bump_schema_version(*, persist: bool = True) -> str:
    meta = load_meta()
    count = int(meta.get("update_count", 0)) + 1
    version = version_from_update_count(count)
    if persist:
        meta["update_count"] = count
        meta["last_version"] = version
        meta["last_bumped_at"] = _now_iso()
        save_meta(meta)
    return version


def reset_export_schema_version() -> None:
    global _run_version
    _run_version = None


def schema_version_for_export(*, bump: bool = False) -> str:
    """One version per scan run; call reset_export_schema_version() at run start."""
    global _run_version
    if bump or _run_version is None:
        if bump:
            _run_version = bump_schema_version(persist=True)
        else:
            _run_version = current_schema_version()
    return _run_version


def strategy_display_name(score_model_slug: str | None, raw_strategy: str = "") -> str:
    """Human-readable strategy for dashboard (no CLI Export / ScoreModel tags)."""
    slug = str(score_model_slug or "sell_put").strip().lower()
    if slug not in SCORE_MODEL_LABELS:
        slug = "sell_put"

    s = str(raw_strategy or "").strip()
    s = re.sub(r"^CLI\s*Export\s*\|?\s*", "", s, flags=re.I).strip()
    s = re.sub(r"(\s*\|\s*)?ScoreModel\s*=\s*\S+", "", s, flags=re.I).strip()
    s = re.sub(r"(\s*\|\s*)?AutoDual\s*=\s*\S+", "", s, flags=re.I).strip()
    s = re.sub(r"^\|+\s*|\s*\|+\s*$", "", s).strip()
    if s and not re.fullmatch(r"CLI\s*Export", s, flags=re.I):
        cn = re.search(r"[\u4e00-\u9fff]{2,}(?:[\u4e00-\u9fff\s·]*)?", s)
        if cn:
            return cn.group(0).strip()
        head = s.split("|")[0].strip()
        if head and not re.fullmatch(r"CLI\s*Export", head, flags=re.I):
            return head
    return SCORE_MODEL_LABELS[slug]
