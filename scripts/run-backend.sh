#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  .venv/bin/python -m pip install -r requirements.txt
fi

# `python -m` instead of the .venv/bin/uvicorn launcher: launchers hard-code the
# folder path they were installed at, so they break if the project folder moves.
export PYTHONPATH="$ROOT/backend"
exec .venv/bin/python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
