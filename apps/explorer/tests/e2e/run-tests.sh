#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# run-tests.sh — Run the Explorer Playwright E2E tests
#
# Usage:
#   ./run-tests.sh              Run all tests (headless)
#   ./run-tests.sh --headed     Run with visible browser
#   ./run-tests.sh --debug      Run in step-through debug mode
#   ./run-tests.sh <spec>       Run a specific spec file
#
# Examples:
#   ./run-tests.sh 01-graph-discovery.spec.ts
#   ./run-tests.sh --headed 05-node-deletion.spec.ts
# ──────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# ── Ensure dependencies are installed ─────────────────────────
if [ ! -d "node_modules" ]; then
  echo "📦 Installing dependencies..."
  npm install
fi

# ── Ensure Chromium browser is available ──────────────────────
if ! npx playwright install --dry-run chromium >/dev/null 2>&1; then
  echo "🌐 Installing Chromium for Playwright..."
  npx playwright install chromium
fi

# ── Check that the server is running ──────────────────────────
BASE_URL="${BASE_URL:-http://localhost:5001}"
if ! curl -s -o /dev/null -w '' --connect-timeout 3 "$BASE_URL" 2>/dev/null; then
  echo "⚠️  Server not reachable at $BASE_URL"
  echo "   Start it first:  cd ../.. && PYTHONPATH=. SERVER_PORT=5001 .venv/bin/python src/server.py"
  exit 1
fi

echo "✅ Server is up at $BASE_URL"
echo "🧪 Running Playwright tests..."
echo ""

# ── Run tests ─────────────────────────────────────────────────
npx playwright test "$@"
