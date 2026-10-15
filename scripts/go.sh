#!/usr/bin/env bash
# One command: set up (first time only), check .env, run the tests, then run the portal.
# Usage: ./scripts/go.sh [--skip-tests] [--fail-at login|session_check|perform] [--code-source totp|relay]
set -euo pipefail
cd "$(dirname "$0")/.."

SKIP_TESTS=0; FAIL_AT=""; SRC="totp"
while [ $# -gt 0 ]; do
  case "$1" in
    --skip-tests) SKIP_TESTS=1 ;;
    --fail-at) FAIL_AT="${2:-}"; shift ;;
    --code-source) SRC="${2:-totp}"; shift ;;
    *) echo "unknown option: $1"; exit 2 ;;
  esac; shift
done

PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null || { echo "Python 3.9+ is required (python3 not found)."; exit 1; }
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)' || { echo "Python 3.9+ is required."; exit 1; }

if [ ! -x .venv/bin/python ]; then "$PY" -m venv .venv; fi
if [ ! -f .venv/.deps-ok ]; then
  .venv/bin/python -m pip install --quiet --upgrade pip
  .venv/bin/python -m pip install --quiet -r requirements.txt
  if [ -z "${PW_CHANNEL:-}" ]; then .venv/bin/python -m playwright install chromium; fi
  touch .venv/.deps-ok
fi

if [ ! -f .env ]; then cp .env.example .env; echo "Created .env. Fill in the values (it is git-ignored), then run this again."; exit 1; fi

# Check required names are filled, without printing any value.
missing=""
for k in PORTAL_EMAIL PORTAL_PASSWORD ZOHO_ORG_ID $([ "$SRC" = totp ] && echo PORTAL_TOTP_SECRET); do
  v="$(grep -E "^${k}=" .env | head -1 | cut -d= -f2- || true)"
  [ -n "${v// /}" ] || missing="$missing $k"
done
if [ -n "$missing" ]; then echo "Fill these in .env, then run again:$missing"; exit 1; fi

if [ "$SKIP_TESTS" -eq 0 ]; then .venv/bin/python -m pytest -q; fi

ARGS=(-m portal_runner run --inputs inputs/invoice.json --code-source "$SRC")
[ -n "$FAIL_AT" ] && ARGS+=(--fail-at "$FAIL_AT")
.venv/bin/python "${ARGS[@]}"
echo "Done. See outputs/ (manifest.json, captured files)."
