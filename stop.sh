#!/usr/bin/env bash
# Stop Policy to Knowledge — kill all services and optionally stop Docker infrastructure
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$SCRIPT_DIR/.suite.pids"
CA_DIR="$SCRIPT_DIR/apps/explorer"

GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BOLD='\033[1m'
NC='\033[0m'

echo -e "\n${BOLD}Stopping Policy to Knowledge...${NC}\n"

# ── 1. Stop application processes ─────────────
if [ -f "$PID_FILE" ]; then
    while IFS= read -r pid; do
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
            echo -e "  ${GREEN}✓${NC} Stopped PID $pid"
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
        kill "$CA_PID" 2>/dev/null || true
        echo -e "  ${GREEN}✓${NC} Stopped Assistant PID $CA_PID"
    fi
    rm -f "$CA_DIR/.server.pid"
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
