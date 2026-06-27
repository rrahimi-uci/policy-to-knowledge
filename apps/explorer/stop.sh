#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

log()  { echo -e "${GREEN}✓${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC} $1"; }
info() { echo -e "${CYAN}→${NC} $1"; }

STOP_DOCKER=false
if [[ "${1:-}" == "--all" || "${1:-}" == "-a" ]]; then
    STOP_DOCKER=true
fi

echo -e "\n${BOLD}${CYAN}Stopping Explorer …${NC}\n"

# ── 1. Stop the Python server ─────────────────────────────────────
STOPPED=false

if [ -f .server.pid ]; then
    PID=$(cat .server.pid)
    if kill -0 "$PID" 2>/dev/null; then
        kill "$PID" 2>/dev/null || true
        # Wait for graceful shutdown (up to 5s), then force
        for i in $(seq 1 10); do
            if ! kill -0 "$PID" 2>/dev/null; then break; fi
            sleep 0.5
        done
        if kill -0 "$PID" 2>/dev/null; then
            kill -9 "$PID" 2>/dev/null || true
        fi
        log "Server stopped (PID: $PID)"
        STOPPED=true
    fi
    rm -f .server.pid
fi

# Fallback: kill anything on port ${SERVER_PORT:-5000}
PIDS=$(lsof -ti:${SERVER_PORT:-5000} 2>/dev/null || true)
if [ -n "$PIDS" ]; then
    echo "$PIDS" | xargs kill -9 2>/dev/null || true
    if [ "$STOPPED" = false ]; then
        log "Killed process(es) on port ${SERVER_PORT:-5000}"
    fi
    STOPPED=true
fi

if [ "$STOPPED" = false ]; then
    info "No server was running"
fi

# ── 2. Stop Docker services (if --all flag) ───────────────────────
if [ "$STOP_DOCKER" = true ]; then
    info "Stopping Docker services …"
    docker compose down 2>&1 | tail -3
    log "Docker services stopped"
    echo ""
    echo -e "  ${CYAN}Note:${NC} Data is preserved in Docker volumes."
    echo -e "  ${CYAN}To remove all data:${NC} ./start.sh --clean"
else
    info "Docker services still running (use ${BOLD}./stop.sh --all${NC} to stop everything)"
fi

echo ""
log "Explorer stopped"
echo ""
