#!/usr/bin/env bash
set -euo pipefail
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
.venv/bin/python -m playwright install chromium
[ -f .env ] || cp .env.example .env
