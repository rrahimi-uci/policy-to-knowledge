#!/usr/bin/env bash
# Start Policy to Knowledge UI — backend + frontend dev servers
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"
PID_FILE="$PROJECT_ROOT/.server.pids"
BACKEND_PORT="${P2K_BACKEND_PORT:-8000}"
FRONTEND_PORT="${P2K_FRONTEND_PORT:-5173}"

pid_is_running() {
  local pid="${1:-}"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

port_in_use() {
  lsof -tiTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
}

port_owner() {
  lsof -nP -iTCP:"$1" -sTCP:LISTEN 2>/dev/null | awk 'NR==2 {print $1 " (PID " $2 ")"}'
}

# Check if already running (ignore stale PID files)
if [ -f "$PID_FILE" ]; then
  source "$PID_FILE"
  BACKEND_ALIVE=0
  FRONTEND_ALIVE=0
  if pid_is_running "${BACKEND_PID:-}"; then BACKEND_ALIVE=1; fi
  if pid_is_running "${FRONTEND_PID:-}"; then FRONTEND_ALIVE=1; fi
  if [ "$BACKEND_ALIVE" -eq 1 ] && [ "$FRONTEND_ALIVE" -eq 1 ]; then
    echo "Servers are already running on ports ${BACKEND_PORT}/${FRONTEND_PORT}. Run ./stop.sh first."
    exit 1
  fi
  echo "Cleaning up stale or partial PID file..."
  if [ "$BACKEND_ALIVE" -eq 1 ]; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
  if [ "$FRONTEND_ALIVE" -eq 1 ]; then
    kill "$FRONTEND_PID" 2>/dev/null || true
  fi
  rm -f "$PID_FILE"
fi

if port_in_use "$BACKEND_PORT"; then
  echo "Error: backend port $BACKEND_PORT is already in use by $(port_owner "$BACKEND_PORT")."
  echo "Stop that process or run P2K_BACKEND_PORT=8001 ./start.sh"
  exit 1
fi

if port_in_use "$FRONTEND_PORT"; then
  echo "Error: frontend port $FRONTEND_PORT is already in use by $(port_owner "$FRONTEND_PORT")."
  echo "Stop that process or run P2K_FRONTEND_PORT=5174 ./start.sh"
  exit 1
fi

echo "================================================"
echo "  Policy to Knowledge — Starting UI"
echo "================================================"

# 1. Install backend deps if needed
echo ""
echo "[1/3] Checking Python dependencies..."
"$PROJECT_ROOT/.venv/bin/python3" -m pip install fastapi uvicorn python-multipart 2>/dev/null | tail -1

# 2. Install frontend deps if needed
echo "[2/3] Checking frontend dependencies..."
cd "$PROJECT_ROOT/ui/frontend"
if [ ! -d "node_modules" ]; then
  echo "      Installing npm packages..."
  npm install
fi

# 3. Start both servers
echo "[3/3] Starting servers..."
echo ""
echo "  Backend:  http://localhost:$BACKEND_PORT  (API + WebSocket)"
echo "  Frontend: http://localhost:$FRONTEND_PORT  (Vite dev server)"
echo ""
echo "  Open http://localhost:$FRONTEND_PORT in your browser."
echo "  Run ./stop.sh to stop both servers."
echo "================================================"
echo ""

# Start backend in background
cd "$PROJECT_ROOT"
"$PROJECT_ROOT/.venv/bin/uvicorn" ui.backend.main:app --host 0.0.0.0 --port "$BACKEND_PORT" --reload &
BACKEND_PID=$!

# Start frontend in background
cd "$PROJECT_ROOT/ui/frontend"
export P2K_BACKEND_PORT="$BACKEND_PORT"
export P2K_FRONTEND_PORT="$FRONTEND_PORT"
npm run dev -- --port "$FRONTEND_PORT" &
FRONTEND_PID=$!

# Save PIDs
echo "BACKEND_PID=$BACKEND_PID" > "$PID_FILE"
echo "FRONTEND_PID=$FRONTEND_PID" >> "$PID_FILE"
echo "Servers started (backend=$BACKEND_PID, frontend=$FRONTEND_PID)"

# Trap to clean up on Ctrl+C
cleanup() {
  echo ""
  echo "Stopping servers..."
  kill $BACKEND_PID $FRONTEND_PID 2>/dev/null
  rm -f "$PID_FILE"
  exit 0
}
trap cleanup INT TERM

wait
