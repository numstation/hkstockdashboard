#!/usr/bin/env bash
# Replace DASHBOARD_REFRESH_KEY placeholder in copied dashboard HTML.
set -euo pipefail

HTML="${1:?usage: inject_refresh_key.sh path/to/index.html}"
KEY="${REFRESH_PUBLIC_KEY:-}"

if [[ ! -f "$HTML" ]]; then
  echo "::warning:: inject_refresh_key: missing $HTML"
  exit 0
fi

export HTML KEY
python3 - <<'PY'
import json
import os
from pathlib import Path

path = Path(os.environ["HTML"])
text = path.read_text(encoding="utf-8")
key = os.environ.get("KEY", "")
needle = 'const DASHBOARD_REFRESH_KEY = "__DASHBOARD_REFRESH_KEY__";'
if needle not in text:
    raise SystemExit(0)
replacement = f"const DASHBOARD_REFRESH_KEY = {json.dumps(key)};"
path.write_text(text.replace(needle, replacement), encoding="utf-8")
print(f"inject_refresh_key: {'set' if key else 'empty'} → {path.name}")
PY
