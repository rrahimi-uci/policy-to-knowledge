#!/usr/bin/env bash
# Stop Policy to Knowledge UI — kill backend + frontend dev servers
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$SCRIPT_DIR/.server.pids"
BACKEND_PORT="${P2K_BACKEND_PORT:-8000}"
FRONTEND_PORT="${P2K_FRONTEND_PORT:-5173}"

if [ ! -f "$PID_FILE" ]; then
  echo "No running servers found (no PID file at $PID_FILE)."
  echo "Checking for processes on ports $BACKEND_PORT and $FRONTEND_PORT..."
  # Fallback: kill by port
  KILLED=0
  for PORT in "$BACKEND_PORT" "$FRONTEND_PORT"; do
    PID=$(lsof -ti :$PORT 2>/dev/null || true)
    if [ -n "$PID" ]; then
      echo "  Killing process $PID on port $PORT"
      kill $PID 2>/dev/null || true
      KILLED=1
    fi
  done
  if [ "$KILLED" -eq 0 ]; then
    echo "  No processes found on ports $BACKEND_PORT or $FRONTEND_PORT."
  fi
  exit 0
fi

echo "Stopping Policy to Knowledge servers..."

# Read PIDs
source "$PID_FILE"

if [ -n "${BACKEND_PID:-}" ]; then
  if kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill "$BACKEND_PID" 2>/dev/null
    echo "  Backend stopped (PID $BACKEND_PID)"
  else
    echo "  Backend already stopped (PID $BACKEND_PID)"
  fi
fi

if [ -n "${FRONTEND_PID:-}" ]; then
  if kill -0 "$FRONTEND_PID" 2>/dev/null; then
    kill "$FRONTEND_PID" 2>/dev/null
    echo "  Frontend stopped (PID $FRONTEND_PID)"
  else
    echo "  Frontend already stopped (PID $FRONTEND_PID)"
  fi
fi

rm -f "$PID_FILE"
echo "Done."
