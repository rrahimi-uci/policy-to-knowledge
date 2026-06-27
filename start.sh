#!/usr/bin/env bash
# Start Policy to Knowledge — Docker infra + KG backend/frontend + Assistant + Suite shell
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$SCRIPT_DIR/.suite.pids"

KG_DIR="$SCRIPT_DIR/apps/pipeline"
CA_DIR="$SCRIPT_DIR/apps/explorer"
ASSISTANT_RUNTIME_DIR="$SCRIPT_DIR/apps/shell/server"

# ── Colors ─────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

log()  { echo -e "${GREEN}✓${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC} $1"; }
err()  { echo -e "${RED}✗${NC} $1"; }
info() { echo -e "${CYAN}→${NC} $1"; }

# ── Load .env files ───────────────────────────
load_env() {
    local f="$1"
    if [ -f "$f" ]; then
        set -a; source "$f"; set +a
    fi
}
load_env "$SCRIPT_DIR/.env"
load_env "$KG_DIR/.env"
load_env "$CA_DIR/.env"

# ── Ports ──────────────────────────────────────
KG_BACKEND_PORT="${KG_BACKEND_PORT:-8000}"
KG_FRONTEND_PORT="${KG_FRONTEND_PORT:-5173}"
CA_PORT="${SERVER_PORT:-${CA_PORT:-5000}}"
SUITE_PORT="${SUITE_PORT:-4000}"
ASSISTANT_RUNTIME_PORT="${ASSISTANT_RUNTIME_PORT:-4100}"

export KG_BACKEND_PORT KG_FRONTEND_PORT CA_PORT SUITE_PORT ASSISTANT_RUNTIME_PORT
export P2K_BACKEND_PORT="$KG_BACKEND_PORT"
export P2K_FRONTEND_PORT="$KG_FRONTEND_PORT"
export SERVER_PORT="$CA_PORT"
export URL_PREFIX="${URL_PREFIX:-/app}"

# Tell kg-backend how to reach assistant when running on the host
# (the in-code default points at the docker-compose hostname which is not
# resolvable outside the container network).
export CA_BASE="${CA_BASE:-http://localhost:${CA_PORT}${URL_PREFIX}}"
export KG_BACKEND_BASE="${KG_BACKEND_BASE:-http://localhost:${KG_BACKEND_PORT}}"

# Policy to Knowledge-assistant resolves KG / docs / pipeline-output paths relative to /app
# inside its container.  When running directly on the host, point it at the
# repo checkout so kgs/, kbs/, conf/ and pipeline-output/ resolve correctly.
export CA_APP_ROOT="${CA_APP_ROOT:-$CA_DIR}"
# JanusGraph runs in docker — when assistant submits Groovy that opens
# a new graph, the storage.hostname / index hostname strings are resolved
# *inside the jg-server container*, where 'localhost' is the container itself.
# These *_INTERNAL vars are the names assistant injects into Groovy,
# while CASSANDRA_HOST / OPENSEARCH_HOST stay at their host-resolvable values
# (defaults from conf/config.py = "localhost") for the python clients.
export CASSANDRA_HOST_INTERNAL="${CASSANDRA_HOST_INTERNAL:-cassandra}"
export OPENSEARCH_HOST_INTERNAL="${OPENSEARCH_HOST_INTERNAL:-opensearch}"
# Make pipeline-output visible at <CA_APP_ROOT>/pipeline-output.  We symlink
# the kg-extraction pipeline-output into the assistant tree only if not
# already present so the assistant can read agent-1/agent-5 outputs locally.
if [ ! -e "$CA_DIR/pipeline-output" ] && [ -d "$KG_DIR/pipeline-output" ]; then
    ln -s "$KG_DIR/pipeline-output" "$CA_DIR/pipeline-output"
fi

# ── Helpers ────────────────────────────────────
port_in_use() { lsof -tiTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }
port_owner() { lsof -nP -iTCP:"$1" -sTCP:LISTEN 2>/dev/null | awk 'NR==2{print $1" (PID "$2")"}'; }

cleanup() {
    echo ""
    echo -e "${YELLOW}Stopping Policy to Knowledge...${NC}"
    [ -f "$PID_FILE" ] && {
        while IFS= read -r pid; do
            kill "$pid" 2>/dev/null && echo "  Stopped PID $pid" || true
        done < "$PID_FILE"
        rm -f "$PID_FILE"
    }
    exit 0
}
trap cleanup INT TERM

# ── Banner ─────────────────────────────────────
echo -e "\n${BOLD}${CYAN}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}${CYAN}║   Policy to Knowledge — Full Stack Launcher                     ║${NC}"
echo -e "${BOLD}${CYAN}╚══════════════════════════════════════════════════════════╝${NC}\n"

# ── Pre-flight checks ─────────────────────────
ERRORS=0

if ! command -v docker &>/dev/null; then
    err "Docker is not installed or not in PATH"; ERRORS=1
elif ! docker info &>/dev/null 2>&1; then
    err "Docker daemon is not running — start Docker Desktop"; ERRORS=1
fi

if [ ! -d "$KG_DIR" ]; then
    err "KG Extraction repo not found at $KG_DIR"; ERRORS=1
fi
if [ ! -d "$CA_DIR" ]; then
    err "Assistant repo not found at $CA_DIR"; ERRORS=1
fi

if [ ! -f "$KG_DIR/.venv/bin/python" ]; then
    err "KG Extraction venv not found — run: python3 -m venv $KG_DIR/.venv && $KG_DIR/.venv/bin/pip install -r $KG_DIR/requirements.txt"; ERRORS=1
fi
if [ ! -f "$CA_DIR/.venv/bin/python" ]; then
    err "Assistant venv not found — run: python3 -m venv $CA_DIR/.venv && $CA_DIR/.venv/bin/pip install -r $CA_DIR/requirements.txt"; ERRORS=1
fi

if [ "$ERRORS" -ne 0 ]; then
    echo ""
    err "Pre-flight checks failed. Fix the issues above and retry."
    exit 1
fi

# Check port conflicts
for p in "$KG_BACKEND_PORT" "$KG_FRONTEND_PORT" "$CA_PORT" "$SUITE_PORT" "$ASSISTANT_RUNTIME_PORT"; do
    if port_in_use "$p"; then
        err "Port $p already in use by $(port_owner "$p")"
        ERRORS=1
    fi
done
if [ "$ERRORS" -ne 0 ]; then
    err "Free the ports above or override with env vars (KG_BACKEND_PORT, KG_FRONTEND_PORT, CA_PORT, SUITE_PORT)."
    exit 1
fi

log "Pre-flight checks passed"
echo ""

# ── 1. Docker infrastructure (Assistant) ──
echo -e "${BOLD}[1/6] Starting Docker infrastructure${NC} (Cassandra, OpenSearch, Redis, JanusGraph)..."
cd "$CA_DIR"

# Generate JanusGraph configs if the script exists
if [ -f "scripts/generate_graph_config.py" ]; then
    info "Generating JanusGraph config from graphs.yaml..."
    .venv/bin/python3 scripts/generate_graph_config.py 2>/dev/null || true
fi

docker compose up -d 2>&1 | tail -5

# Wait for Cassandra
info "Waiting for Cassandra..."
RETRIES=0; MAX=40
while ! docker exec jg-cassandra cqlsh -e 'DESCRIBE KEYSPACES' &>/dev/null; do
    RETRIES=$((RETRIES + 1))
    if [ "$RETRIES" -ge "$MAX" ]; then
        err "Cassandra did not become ready. Run: docker logs jg-cassandra"
        exit 1
    fi
    printf "."
    sleep 3
done
echo ""; log "Cassandra is ready"

# Wait for OpenSearch
info "Waiting for OpenSearch..."
OPENSEARCH_PORT="${OPENSEARCH_PORT:-9200}"
RETRIES=0; MAX=30
while ! curl -sf "http://localhost:${OPENSEARCH_PORT}/_cluster/health" &>/dev/null; do
    RETRIES=$((RETRIES + 1))
    if [ "$RETRIES" -ge "$MAX" ]; then
        err "OpenSearch did not become ready. Run: docker logs jg-opensearch"
        exit 1
    fi
    printf "."
    sleep 2
done
echo ""; log "OpenSearch is ready"

# Wait for JanusGraph (check Gremlin WebSocket port is accepting connections)
JANUSGRAPH_PORT="${JANUSGRAPH_PORT:-8182}"
info "Waiting for JanusGraph (port $JANUSGRAPH_PORT)..."
RETRIES=0; MAX=60
while ! nc -z localhost "$JANUSGRAPH_PORT" 2>/dev/null; do
    RETRIES=$((RETRIES + 1))
    if [ "$RETRIES" -ge "$MAX" ]; then
        err "JanusGraph did not become ready. Run: docker logs jg-server"
        exit 1
    fi
    printf "."
    sleep 3
done
echo ""; log "JanusGraph is ready"
echo ""

# ── 2. KG Extraction Backend ──────────────────
echo -e "${BOLD}[2/6] Starting KG Extraction backend${NC} (port $KG_BACKEND_PORT)..."
cd "$KG_DIR"
.venv/bin/python -m uvicorn ui.backend.main:app \
    --host 0.0.0.0 --port "$KG_BACKEND_PORT" \
    --reload --reload-dir "$KG_DIR" \
    --app-dir "$KG_DIR" > /dev/null 2>&1 &
echo $! > "$PID_FILE"
log "KG backend started (PID $!)"

# ── 3. KG Extraction Frontend ─────────────────
echo -e "${BOLD}[3/6] Starting KG Extraction frontend${NC} (port $KG_FRONTEND_PORT)..."
cd "$KG_DIR/ui/frontend"
[ ! -d node_modules ] && npm install --silent
npx vite --port "$KG_FRONTEND_PORT" > /dev/null 2>&1 &
echo $! >> "$PID_FILE"
log "KG frontend started (PID $!)"

# ── 4. Assistant ───────────────────────
echo -e "${BOLD}[4/6] Starting Assistant${NC} (port $CA_PORT)..."
cd "$CA_DIR"

# Ensure graph data is loaded
info "Checking graph data..."
.venv/bin/python3 -m src.main setup-if-empty 2>/dev/null || warn "Graph setup check skipped"

.venv/bin/python3 -m src.server > /dev/null 2>&1 &
CA_PID=$!
echo $CA_PID >> "$PID_FILE"

# Wait for assistant to be ready
RETRIES=0; MAX=30
while ! curl -sf "http://localhost:${CA_PORT}${URL_PREFIX}/" &>/dev/null; do
    RETRIES=$((RETRIES + 1))
    if [ "$RETRIES" -ge "$MAX" ]; then
        err "Assistant did not start. Debug: $CA_DIR/.venv/bin/python3 -m src.server"
        break
    fi
    if ! kill -0 "$CA_PID" 2>/dev/null; then
        err "Assistant process exited. Debug: $CA_DIR/.venv/bin/python3 -m src.server"
        break
    fi
    printf "."
    sleep 2
done
echo ""; log "Assistant started (PID $CA_PID)"

# ── 5. Policy to Knowledge Shell ─────────────────────
echo -e "${BOLD}[5/6] Starting Policy to Knowledge shell${NC} (port $SUITE_PORT)..."
cd "$SCRIPT_DIR/apps/shell"
[ ! -d node_modules ] && npm install --silent
npx vite --port "$SUITE_PORT" > /dev/null 2>&1 &
echo $! >> "$PID_FILE"
log "Suite shell started (PID $!)"

# ── 6. Assistant Runtime (optional) ──────────
if [ -f "$ASSISTANT_RUNTIME_DIR/package.json" ]; then
    echo -e "${BOLD}[6/6] Starting assistant runtime${NC} (port $ASSISTANT_RUNTIME_PORT)..."
    cd "$ASSISTANT_RUNTIME_DIR"
    [ ! -d node_modules ] && npm install --silent
    RUNTIME_ENTRY="${ASSISTANT_RUNTIME_ENTRY:-assistant-runtime.mjs}"
    if [ ! -f "$RUNTIME_ENTRY" ]; then
        RUNTIME_ENTRY="$(find . -maxdepth 1 -type f -name '*.mjs' | head -n 1)"
    fi
    if [ -n "${RUNTIME_ENTRY:-}" ] && [ -f "$RUNTIME_ENTRY" ]; then
        ASSISTANT_RUNTIME_PORT="$ASSISTANT_RUNTIME_PORT" node "$RUNTIME_ENTRY" > /dev/null 2>&1 &
        echo $! >> "$PID_FILE"
        log "Assistant runtime started (PID $!)"
    else
        info "Assistant runtime entrypoint not found — skipping"
    fi
else
    info "Assistant runtime not found — skipping (enable in Settings)"
fi

# ── Summary ───────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}${GREEN}║          Policy to Knowledge is ready!                          ║${NC}"
echo -e "${BOLD}${GREEN}╠══════════════════════════════════════════════════════════╣${NC}"
printf "${GREEN}║${NC}  %-24s %-32s ${GREEN}║${NC}\n" "Suite Shell:" "http://localhost:$SUITE_PORT"
printf "${GREEN}║${NC}  %-24s %-32s ${GREEN}║${NC}\n" "KG Extraction API:" "http://localhost:$KG_BACKEND_PORT"
printf "${GREEN}║${NC}  %-24s %-32s ${GREEN}║${NC}\n" "KG Extraction UI:" "http://localhost:$KG_FRONTEND_PORT"
printf "${GREEN}║${NC}  %-24s %-32s ${GREEN}║${NC}\n" "Assistant:" "http://localhost:$CA_PORT$URL_PREFIX"
printf "${GREEN}║${NC}  %-24s %-32s ${GREEN}║${NC}\n" "Assistant Runtime:" "http://localhost:$ASSISTANT_RUNTIME_PORT"
printf "${GREEN}║${NC}  %-24s %-32s ${GREEN}║${NC}\n" "Docker (infra):" "Cassandra, OpenSearch, Redis, JanusGraph"
echo -e "${BOLD}${GREEN}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  Open ${BOLD}http://localhost:$SUITE_PORT${NC} in your browser."
echo -e "  Press ${BOLD}Ctrl+C${NC} or run ${BOLD}./stop.sh${NC} to stop all services."
echo ""

wait
