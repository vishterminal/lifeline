#!/usr/bin/env bash
# Lifeline - one-command launcher (macOS / Linux)
set -e
cd "$(dirname "$0")"
PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)'; then PY="$c"; break; fi
done
[ -z "$PY" ] && { echo "Python 3.10+ is required: https://www.python.org/downloads/"; exit 1; }

if [ ! -x backend/.venv/bin/python ]; then
  echo "[1/3] Creating a private Python environment..."
  "$PY" -m venv backend/.venv
fi
VPY="$(pwd)/backend/.venv/bin/python"
if [ ! -f backend/.venv/.lifeline-installed ]; then
  echo "[2/3] Installing dependencies (first run only, 1-3 minutes)..."
  "$VPY" -m pip install --disable-pip-version-check -q --upgrade pip
  "$VPY" -m pip install --disable-pip-version-check -q -r backend/requirements.txt
  touch backend/.venv/.lifeline-installed
fi
if [ ! -f frontend/dist/index.html ]; then
  echo "Web app build missing - building with npm..."
  (cd frontend && npm install && npm run build)
fi
echo "[3/3] Starting Lifeline at http://localhost:8000  (Ctrl+C to stop)"
( sleep 4; (command -v open >/dev/null && open http://localhost:8000) || (command -v xdg-open >/dev/null && xdg-open http://localhost:8000) || true ) &
cd backend
exec "$VPY" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
