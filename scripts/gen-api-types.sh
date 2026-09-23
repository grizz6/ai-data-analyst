#!/usr/bin/env bash
# Regenerate frontend/src/generated/api-schema.ts from the backend's OpenAPI schema.
#
# The backend's Pydantic models are the single source of truth for the API's
# shape; the frontend's TypeScript types are generated from them rather than
# written by hand. CI runs this and fails if the committed file is out of date.
#
# Uses backend/.venv by default; set PYTHON to use another interpreter.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${PYTHON:-$ROOT/backend/.venv/bin/python}"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

PYTHONPATH="$ROOT/backend" "$PYTHON" -c '
import json, sys
from app.main import app
json.dump(app.openapi(), sys.stdout, indent=2, sort_keys=True)
' > "$WORK/openapi.json"

cd "$ROOT/frontend"
# --empty-objects-unknown: Python dict[str, Any] fields (preview rows, chart JSON)
# become Record<string, unknown> rather than objects with no allowed keys.
npx --no-install openapi-typescript "$WORK/openapi.json" --empty-objects-unknown -o src/generated/api-schema.ts
