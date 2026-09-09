#!/usr/bin/env bash
# Start backend (auto-reload) and the Vite dev server side by side.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
( cd "$ROOT/backend" && "$ROOT/.venv/bin/python" -m uvicorn app.main:app --reload --port 8000 ) &
( cd "$ROOT/frontend" && npm run dev ) &
echo "Backend: http://127.0.0.1:8000   Frontend (dev): http://localhost:5173"
wait
