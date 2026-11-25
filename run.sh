#!/usr/bin/env bash
# Build the C++ layer (if needed) and start the backend + dashboard.
# Reads ./.env automatically via backend/app/config.py.
set -e
cd "$(dirname "$0")"

if [ ! -x cpp/build/hwmon ]; then
  echo "== building C++ layer =="
  cmake -S cpp -B cpp/build -DCMAKE_BUILD_TYPE=Release
  cmake --build cpp/build -j"$(nproc)"
fi

HOST="${MULTI_AI_HOST:-127.0.0.1}"
PORT="${MULTI_AI_PORT:-8000}"
echo "== starting server on http://${HOST}:${PORT} =="
cd backend
exec python3 -m uvicorn app.main:app --host "$HOST" --port "$PORT" "$@"
