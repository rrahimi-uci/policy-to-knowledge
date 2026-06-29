#!/usr/bin/env bash
# Stop Policy to Knowledge — kill all services and optionally stop Docker infrastructure
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$SCRIPT_DIR/.suite.pids"
KG_DIR="$SCRIPT_DIR/apps/pipeline"
CA_DIR="$SCRIPT_DIR/apps/explorer"

GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BOLD='\033[1m'
NC='\033[0m'

load_env() {
    local f="$1"
    if [ -f "$f" ]; then
        set -a; source "$f"; set +a
    fi
}
load_env "$SCRIPT_DIR/.env"
load_env "$KG_DIR/.env"
load_env "$CA_DIR/.env"

KG_BACKEND_PORT="${KG_BACKEND_PORT:-8000}"
KG_FRONTEND_PORT="${KG_FRONTEND_PORT:-5173}"
CA_PORT="${SERVER_PORT:-${CA_PORT:-5000}}"
SUITE_PORT="${SUITE_PORT:-4000}"
ASSISTANT_RUNTIME_PORT="${ASSISTANT_RUNTIME_PORT:-4100}"

stop_pid() {
    local pid="$1"
    local label="$2"
    if ! kill -0 "$pid" 2>/dev/null; then
        return 0
    fi
    kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 10); do
        if ! kill -0 "$pid" 2>/dev/null; then
            echo -e "  ${GREEN}✓${NC} Stopped ${label} PID $pid"
            return 0
        fi
        sleep 0.5
    done
    kill -9 "$pid" 2>/dev/null || true
    echo -e "  ${GREEN}✓${NC} Force-stopped ${label} PID $pid"
}

echo -e "\n${BOLD}Stopping Policy to Knowledge...${NC}\n"

# ── 1. Stop application processes ─────────────
STOPPED=false

if [ -f "$PID_FILE" ]; then
    while IFS= read -r pid; do
        if kill -0 "$pid" 2>/dev/null; then
            stop_pid "$pid" "tracked"
            STOPPED=true
        fi
    done < "$PID_FILE"
    rm -f "$PID_FILE"
else
    echo -e "  ${YELLOW}⚠${NC} No PID file found — application processes may not be running"
fi

# Also stop Assistant's own PID file if present
if [ -f "$CA_DIR/.server.pid" ]; then
    CA_PID=$(cat "$CA_DIR/.server.pid")
    if kill -0 "$CA_PID" 2>/dev/null; then
        stop_pid "$CA_PID" "Assistant"
        STOPPED=true
    fi
    rm -f "$CA_DIR/.server.pid"
fi

# Fallback: kill listeners on the known stack ports, even if the PID file
# went stale or a process detached from its original parent.
for entry in \
    "$KG_BACKEND_PORT:KG backend" \
    "$KG_FRONTEND_PORT:KG frontend" \
    "$CA_PORT:Assistant" \
    "$SUITE_PORT:Suite shell" \
    "$ASSISTANT_RUNTIME_PORT:Assistant runtime"
do
    port="${entry%%:*}"
    label="${entry#*:}"
    PIDS=$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)
    if [ -n "$PIDS" ]; then
        for pid in $PIDS; do
            stop_pid "$pid" "$label on port $port"
            STOPPED=true
        done
    fi
done

if [ "$STOPPED" = false ]; then
    echo -e "  ${YELLOW}⚠${NC} No stack listeners were running"
fi

# ── 2. Stop Docker infrastructure ─────────────
if [ -d "$CA_DIR" ] && [ -f "$CA_DIR/docker-compose.yml" ]; then
    if docker info &>/dev/null 2>&1; then
        if [ "${1:-}" = "--infra" ] || [ "${1:-}" = "--all" ]; then
            echo ""
            echo -e "  ${YELLOW}⚠${NC} Stopping Docker infrastructure (Cassandra, OpenSearch, Redis, JanusGraph)..."
            cd "$CA_DIR"
            docker compose down --remove-orphans 2>/dev/null || true
            echo -e "  ${GREEN}✓${NC} Docker services stopped"
        else
            echo ""
            echo -e "  Docker infrastructure left running (Cassandra, OpenSearch, Redis, JanusGraph)."
            echo -e "  Use ${BOLD}./stop.sh --infra${NC} to also stop Docker containers."
        fi
    fi
fi

echo ""
echo -e "${GREEN}Done.${NC}"
