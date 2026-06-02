#!/usr/bin/env python3
"""Pick newer JSON by last_updated (or mtime) between two paths; write winner to dest."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


def _parse_ts(raw: object) -> datetime | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _json_ts(path: Path) -> datetime | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return _parse_ts(data.get("last_updated"))


def pick_newer(a: Path, b: Path) -> Path | None:
    if a.is_file() and not b.is_file():
        return a
    if b.is_file() and not a.is_file():
        return b
    if not a.is_file() and not b.is_file():
        return None
    ta, tb = _json_ts(a), _json_ts(b)
    if ta and tb:
        return a if ta >= tb else b
    if ta:
        return a
    if tb:
        return b
    return a if a.stat().st_mtime >= b.stat().st_mtime else b


def main() -> int:
    ap = argparse.ArgumentParser(description="Write the newer of two JSON files to dest.")
    ap.add_argument("dest", type=Path)
    ap.add_argument("candidate_a", type=Path, help="Usually live-pulled copy")
    ap.add_argument("candidate_b", type=Path, help="Usually repo/workspace copy")
    args = ap.parse_args()

    winner = pick_newer(args.candidate_a, args.candidate_b)
    if winner is None:
        print(f"[pick_newer] no source for {args.dest.name}", file=sys.stderr)
        return 1
    args.dest.parent.mkdir(parents=True, exist_ok=True)
    args.dest.write_text(winner.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"[pick_newer] {args.dest.name} ← {winner}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
