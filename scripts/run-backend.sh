#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi

source .venv/bin/activate
export PYTHONPATH="$ROOT/backend"
exec uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
