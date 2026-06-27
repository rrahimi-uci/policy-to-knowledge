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
err()  { echo -e "${RED}✗${NC} $1"; }
info() { echo -e "${CYAN}→${NC} $1"; }

# ── Argument parsing ──────────────────────────────────────────────
MODE="incremental"
case "${1:-}" in
    --fresh)
        MODE="fresh"
        ;;
    --clean)
        MODE="clean"
        ;;
    --help|-h)
        echo "Usage: ./start.sh [OPTION]"
        echo ""
        echo "Options:"
        echo "  (none)      Incremental start. Preserves all existing data."
        echo "  --fresh     Clear and reload graphs, embeddings, SQLite, and Redis."
        echo "              Docker volumes (Cassandra, OpenSearch) are preserved."
        echo "  --clean     Nuclear clean. Destroys ALL data stores and rebuilds:"
        echo "              Docker volumes, JanusGraph, OpenSearch, Cassandra,"
        echo "              Redis, SQLite (app.db), and k-NN embeddings."
        echo "  --help, -h  Show this help message."
        exit 0
        ;;
    "")
        ;;
    *)
        err "Unknown option: ${1}"
        echo "Run './start.sh --help' for usage."
        exit 1
        ;;
esac

echo -e "\n${BOLD}${CYAN}╔══════════════════════════════════════════╗${NC}"
echo -e "${BOLD}${CYAN}║   Explorer                          ║${NC}"
echo -e "${BOLD}${CYAN}╚══════════════════════════════════════════╝${NC}\n"

if [ "$MODE" = "clean" ]; then
    echo -e "  ${BOLD}${RED}Mode: CLEAN${NC} — all data stores will be destroyed and rebuilt\n"
elif [ "$MODE" = "fresh" ]; then
    echo -e "  ${BOLD}${YELLOW}Mode: FRESH${NC} — graphs & embeddings reloaded from KG files\n"
else
    echo -e "  ${BOLD}${GREEN}Mode: INCREMENTAL${NC} — preserving existing data\n"
fi

# ── 0. Pre-flight checks ──────────────────────────────────────────
if ! command -v docker &>/dev/null; then
    err "Docker is not installed or not in PATH"
    exit 1
fi
if ! docker info &>/dev/null; then
    err "Docker daemon is not running. Please start Docker Desktop."
    exit 1
fi
if [ ! -d ".venv" ]; then
    err "Python virtual environment (.venv) not found."
    echo "   Run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
    exit 1
fi
log "Pre-flight checks passed"

# ── Load configuration from .env (if present) ─────────────────────
if [ -f ".env" ]; then
    set -a
    source .env
    set +a
fi
SERVER_PORT="${SERVER_PORT:-5000}"
OPENSEARCH_PORT="${OPENSEARCH_PORT:-9200}"
KNN_INDEX_NAME="${KNN_INDEX_NAME:-vertex_embeddings}"

# ── 1a. Generate config files from graphs.yaml ────────────────────
info "Generating JanusGraph config from graphs.yaml …"
.venv/bin/python3 scripts/generate_graph_config.py
log "Config files generated"

# ── 1. Kill any existing server on port ────────────────────────────
EXISTING=$(lsof -ti:${SERVER_PORT} 2>/dev/null || true)
if [ -n "$EXISTING" ]; then
    echo "$EXISTING" | xargs kill -9 2>/dev/null || true
    info "Stopped previous server on port ${SERVER_PORT}"
    sleep 1
fi
rm -f .server.pid

# ── 2. Start Docker services ──────────────────────────────────────
if [ "$MODE" = "clean" ]; then
    info "Destroying Docker volumes (Cassandra, OpenSearch, Redis) …"
    docker compose down --volumes --remove-orphans 2>/dev/null || true
    docker rm -f jg-cassandra jg-opensearch jg-redis jg-server 2>/dev/null || true
    log "Docker volumes destroyed — all persistent data removed"

    # Clear SQLite annotations database
    if [ -f "app.db" ]; then
        rm -f app.db
        log "Removed app.db (annotations, approvals, history)"
    else
        info "No app.db to remove"
    fi
else
    info "Cleaning up stale containers …"
    docker compose down --remove-orphans 2>/dev/null || true
    docker rm -f jg-cassandra jg-opensearch jg-redis jg-server 2>/dev/null || true
fi

info "Starting Docker services (Cassandra, OpenSearch, Redis, JanusGraph) …"
docker compose up -d 2>&1 | tail -5

# ── 3. Wait for Cassandra ─────────────────────────────────────────
info "Waiting for Cassandra …"
RETRIES=0
MAX=40
while ! docker exec jg-cassandra cqlsh -e 'DESCRIBE KEYSPACES' &>/dev/null; do
    RETRIES=$((RETRIES + 1))
    if [ "$RETRIES" -ge "$MAX" ]; then
        err "Cassandra did not become ready after ${MAX} checks ($(( MAX * 3 ))s)."
        echo "   Run: docker logs jg-cassandra"
        exit 1
    fi
    printf "."
    sleep 3
done
echo ""
log "Cassandra is ready"

# ── 4. Wait for OpenSearch ─────────────────────────────────────────
info "Waiting for OpenSearch …"
RETRIES=0
MAX=30
while ! curl -sf http://localhost:${OPENSEARCH_PORT}/_cluster/health &>/dev/null; do
    RETRIES=$((RETRIES + 1))
    if [ "$RETRIES" -ge "$MAX" ]; then
        err "OpenSearch did not become ready after ${MAX} checks ($(( MAX * 2 ))s)."
        echo "   Run: docker logs jg-opensearch"
        exit 1
    fi
    printf "."
    sleep 2
done
echo ""
log "OpenSearch is ready"

# ── 5. Wait for JanusGraph (real Gremlin readiness) ───────────────
info "Waiting for JanusGraph Gremlin server …"
RETRIES=0
MAX=40
while true; do
    if .venv/bin/python3 -c "
from src.graph_connection import get_traversal
with get_traversal() as (g, conn):
    g.V().limit(1).toList()
" &>/dev/null; then
        break
    fi
    RETRIES=$((RETRIES + 1))
    if [ "$RETRIES" -ge "$MAX" ]; then
        err "JanusGraph Gremlin did not become ready after ${MAX} checks ($(( MAX * 3 ))s)."
        echo "   Run: docker logs jg-server"
        exit 1
    fi
    printf "."
    sleep 3
done
echo ""
log "JanusGraph Gremlin server is ready"

# ── 6. Load graphs ────────────────────────────────────────────────
if [ "$MODE" = "clean" ]; then
    info "Clean mode: loading all knowledge graphs from scratch …"
    .venv/bin/python3 -m src.main setup
elif [ "$MODE" = "fresh" ]; then
    info "Fresh mode: clearing and reloading all knowledge graphs …"

    # Clear SQLite annotations database
    if [ -f "app.db" ]; then
        rm -f app.db
        log "Removed app.db (annotations, approvals, history)"
    fi

    # Flush Redis cache
    if command -v redis-cli &>/dev/null; then
        redis-cli -p "${REDIS_PORT:-6379}" FLUSHALL &>/dev/null && log "Redis cache flushed" || warn "Could not flush Redis"
    else
        docker exec jg-redis redis-cli FLUSHALL &>/dev/null && log "Redis cache flushed" || warn "Could not flush Redis"
    fi

    .venv/bin/python3 -m src.main setup
else
    info "Checking existing graph data …"
    .venv/bin/python3 -m src.main setup-if-empty
fi

# Collect per-graph and total counts across loaded graphs (those with KG files)
GRAPH_STATS=$(.venv/bin/python3 -c "
from src.graph_connection import get_traversal
from conf.graph_manifest import get_graph_configs, get_loaded_traversal_sources
import json
configs = get_graph_configs()
total_v = total_e = 0
rows = []
for ts in get_loaded_traversal_sources():
    try:
        with get_traversal(ts) as (g, conn):
            v = g.V().count().next()
            e = g.E().count().next()
            total_v += v
            total_e += e
            name = configs.get(ts, {}).get('name', ts)
            rows.append({'name': name, 'ts': ts, 'v': v, 'e': e})
    except Exception:
        pass
print(json.dumps({'total_v': total_v, 'total_e': total_e, 'graphs': rows}))
" 2>/dev/null || echo '{"total_v":0,"total_e":0,"graphs":[]}')

VERTEX_COUNT=$(echo "$GRAPH_STATS" | .venv/bin/python3 -c "import sys,json; print(json.load(sys.stdin)['total_v'])" 2>/dev/null || echo "0")
EDGE_COUNT=$(echo "$GRAPH_STATS" | .venv/bin/python3 -c "import sys,json; print(json.load(sys.stdin)['total_e'])" 2>/dev/null || echo "0")

if [ "$VERTEX_COUNT" -gt 0 ] 2>/dev/null; then
    log "Setup complete — ${BOLD}${VERTEX_COUNT} vertices${NC}, ${BOLD}${EDGE_COUNT} edges${NC} loaded across all graphs"
else
    err "Setup ran but graphs are still empty. Check logs above for errors."
    exit 1
fi

# ── 7. Check semantic search index ────────────────────────────────
info "Checking semantic search index …"
EMBED_COUNT=$(curl -sf http://localhost:${OPENSEARCH_PORT}/${KNN_INDEX_NAME}/_count 2>/dev/null \
    | .venv/bin/python3 -c "import sys,json; print(json.load(sys.stdin).get('count',0))" 2>/dev/null \
    || echo "0")

if [ "$EMBED_COUNT" -gt 0 ] 2>/dev/null; then
    log "Semantic search index has ${BOLD}${EMBED_COUNT} embeddings${NC}"
else
    warn "Embedding index is empty — it will be created when the server starts"
fi

# ── 8. Start the Flask server ─────────────────────────────────────
export URL_PREFIX="${URL_PREFIX:-/app}"
info "Starting Explorer server …"
.venv/bin/python3 -m src.server > /dev/null 2>&1 &
SERVER_PID=$!
echo "$SERVER_PID" > .server.pid

# Wait for server to be ready
RETRIES=0
MAX=30
while ! curl -sf http://localhost:${SERVER_PORT}${URL_PREFIX}/ &>/dev/null; do
    RETRIES=$((RETRIES + 1))
    if [ "$RETRIES" -ge "$MAX" ]; then
        err "Server did not start within $(( MAX * 2 ))s. Check: .venv/bin/python3 -m src.server"
        kill "$SERVER_PID" 2>/dev/null || true
        rm -f .server.pid
        exit 1
    fi
    # Check if process is still alive
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        err "Server process exited unexpectedly."
        echo "   Debug: .venv/bin/python3 -m src.server"
        rm -f .server.pid
        exit 1
    fi
    printf "."
    sleep 2
done
echo ""
log "Server started (PID: ${SERVER_PID})"

# ── 9. Summary ────────────────────────────────────────────────────
NUM_GRAPHS=$(echo "$GRAPH_STATS" | .venv/bin/python3 -c "import sys,json; print(len(json.load(sys.stdin)['graphs']))" 2>/dev/null || echo "?")

echo ""
echo -e "${BOLD}${GREEN}╔════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}${GREEN}║          Explorer is ready!                      ║${NC}"
echo -e "${BOLD}${GREEN}╠════════════════════════════════════════════════════════╣${NC}"
printf "${GREEN}║${NC}  %-14s ${BOLD}%-38s${NC} ${GREEN}║${NC}\n" "URL:" "http://p2k:${SERVER_PORT}${URL_PREFIX}"
printf "${GREEN}║${NC}  %-14s ${BOLD}%-38s${NC} ${GREEN}║${NC}\n" "Mode:" "${MODE}"
printf "${GREEN}║${NC}  %-14s ${BOLD}%-38s${NC} ${GREEN}║${NC}\n" "Graphs:" "$NUM_GRAPHS"
printf "${GREEN}║${NC}  %-14s ${BOLD}%-38s${NC} ${GREEN}║${NC}\n" "Vertices:" "$VERTEX_COUNT (total)"
printf "${GREEN}║${NC}  %-14s ${BOLD}%-38s${NC} ${GREEN}║${NC}\n" "Edges:" "$EDGE_COUNT (total)"
printf "${GREEN}║${NC}  %-14s ${BOLD}%-38s${NC} ${GREEN}║${NC}\n" "Embeddings:" "$EMBED_COUNT"
printf "${GREEN}║${NC}  %-14s ${BOLD}%-38s${NC} ${GREEN}║${NC}\n" "PID:" "$SERVER_PID"
echo -e "${BOLD}${GREEN}╠════════════════════════════════════════════════════════╣${NC}"

# Per-graph breakdown
echo "$GRAPH_STATS" | .venv/bin/python3 -c "
import sys, json
data = json.load(sys.stdin)
for g in data['graphs']:
    line = f\"  {g['name']:<26} {g['v']:>4}V  {g['e']:>4}E\"
    # pad to 54 chars for box alignment
    print(f'\033[0;32m║\033[0m{line:<54} \033[0;32m║\033[0m')
" 2>/dev/null || true

echo -e "${BOLD}${GREEN}╚════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${CYAN}Stop:${NC}  ./stop.sh"
echo -e "  ${CYAN}Logs:${NC}  .venv/bin/python3 -m src.server  (foreground mode)"
echo ""
