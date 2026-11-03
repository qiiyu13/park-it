#!/usr/bin/env bash
# Real-browser UI tests (Playwright/Chromium) against a disposable stack.
#
# Starts:
#   • Postgres + Redis in throwaway containers (ports 55432 / 56379)
#   • FastAPI on 127.0.0.1:8000 (real DB, mock hardware)
#   • Nuxt dev server on 127.0.0.1:3000
#   • Quick-installs an admin so login/dashboard/POS are usable
#
# Then runs frontend/tests/e2e/ui-flow.spec.js.
#
# Requirements: docker, .venv, frontend/node_modules with @playwright/test,
# and a Playwright Chromium build (npx playwright install chromium).
#
# Usage:
#   ./scripts/ui_test.sh
#   UI_HEADED=1 ./scripts/ui_test.sh     # watch the browser

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PG_PORT="${UI_PG_PORT:-55432}"
REDIS_PORT="${UI_REDIS_PORT:-56379}"
PG_NAME="parking-ui-pg"
REDIS_NAME="parking-ui-redis"
PG_PASSWORD="ui_parking_pw"
REDIS_PASSWORD="ui_parking_pw"
TMP_DIR=$(mktemp -d /tmp/parking-ui.XXXXXX)
API_LOG="$TMP_DIR/api.log"
FRONTEND_LOG="$TMP_DIR/frontend.log"
SETUP_TOKEN_PATH="$TMP_DIR/setup-token"
ENROLL_TOKEN_PATH="$TMP_DIR/enroll-token"
ADMIN_PASSWORD_FILE="$TMP_DIR/admin-password"
ADMIN_PASSWORD="ui-test-password"
API_PID=""
FRONTEND_PID=""

cleanup() {
    if [[ -n "$FRONTEND_PID" ]]; then
        kill -- -"$FRONTEND_PID" >/dev/null 2>&1 || kill "$FRONTEND_PID" >/dev/null 2>&1 || true
    fi
    if [[ -n "$API_PID" ]]; then
        kill -- -"$API_PID" >/dev/null 2>&1 || kill "$API_PID" >/dev/null 2>&1 || true
    fi
    docker rm -f "$PG_NAME" "$REDIS_NAME" >/dev/null 2>&1 || true
    if [[ "${UI_KEEP_LOGS:-0}" != "1" ]]; then
        rm -rf "$TMP_DIR"
    else
        echo "Logs kept in $TMP_DIR"
    fi
}
trap cleanup EXIT

command -v docker >/dev/null || { echo "docker required" >&2; exit 1; }
[[ -x .venv/bin/python ]] || { echo ".venv missing" >&2; exit 1; }

if [[ ! -d frontend/node_modules/@playwright/test ]]; then
    echo "Installing frontend dev dependencies (Playwright)..."
    (cd frontend && NODE_ENV=development npm install --include=dev --no-audit --no-fund)
fi

echo "=== E-Parking v2 — Playwright UI tests ==="
echo "Postgres : 127.0.0.1:${PG_PORT}"
echo "Redis    : 127.0.0.1:${REDIS_PORT}"
echo ""

for port in "$PG_PORT" "$REDIS_PORT"; do
    if (exec 3<>"/dev/tcp/127.0.0.1/${port}") 2>/dev/null; then
        echo "ERROR: port ${port} already in use (set UI_PG_PORT / UI_REDIS_PORT)." >&2
        exit 1
    fi
done

docker run -d --rm --name "$PG_NAME" \
    -e POSTGRES_USER=parking -e POSTGRES_PASSWORD="$PG_PASSWORD" \
    -e POSTGRES_DB=parking -p "127.0.0.1:${PG_PORT}:5432" \
    postgres:16-alpine >/dev/null
docker run -d --rm --name "$REDIS_NAME" \
    -p "127.0.0.1:${REDIS_PORT}:6379" \
    redis:7-alpine redis-server --requirepass "$REDIS_PASSWORD" >/dev/null

echo "Waiting for services..."
ready=false
for _ in $(seq 1 40); do
    if docker exec "$PG_NAME" pg_isready -U parking -d parking >/dev/null 2>&1 \
        && docker exec "$REDIS_NAME" redis-cli -a "$REDIS_PASSWORD" ping >/dev/null 2>&1; then
        ready=true
        break
    fi
    sleep 1
done
$ready || { echo "services not ready" >&2; exit 1; }

export DB_HOST=127.0.0.1 DB_PORT="$PG_PORT" DB_NAME=parking
export DB_USER=parking DB_PASSWORD="$PG_PASSWORD"
export REDIS_HOST=127.0.0.1 REDIS_PORT="$REDIS_PORT" REDIS_DB=15
export REDIS_PASSWORD="$REDIS_PASSWORD"
export APP_TIMEZONE=Asia/Jakarta
export MOCK_HARDWARE=true
export MOCK_HARDWARE_DIR="$TMP_DIR/mock"
export SETUP_TOKEN_PATH ENROLL_TOKEN_PATH
export APP_ENV=development

echo "Migrating..."
.venv/bin/alembic upgrade head >/dev/null

echo "Provisioning quick-install admin..."
printf '%s' "$ADMIN_PASSWORD" > "$ADMIN_PASSWORD_FILE"
chmod 600 "$ADMIN_PASSWORD_FILE"
QUICKSTART_NOTES_PATH="$TMP_DIR/install-notes.txt" \
QUICKSTART_SUMMARY_PATH="$TMP_DIR/install-summary.json" \
QUICKSTART_ENROLL_TOKEN_PATH="$ENROLL_TOKEN_PATH" \
    .venv/bin/python scripts/quickstart_provision.py \
        --admin-username ui-admin \
        --admin-full-name "UI Admin" \
        --admin-password-file "$ADMIN_PASSWORD_FILE" \
        --site-name "UI Test" \
        --in-count 1 --out-count 1 >/dev/null

echo "Starting API..."
INTERNAL_API_KEY=ui-test-key \
RATE_LIMIT_DISABLED=true \
CORS_ORIGINS="http://127.0.0.1:3000,http://localhost:3000" \
    setsid .venv/bin/uvicorn api.app.main:app --host 127.0.0.1 --port 8000 \
    >"$API_LOG" 2>&1 &
API_PID=$!

echo "Building frontend (production build — disables DEV_ADMIN fallback)..."
cd "$ROOT/frontend"
NODE_ENV=production \
NUXT_PUBLIC_API_BASE_URL="http://127.0.0.1:8000" \
NUXT_PUBLIC_WS_BASE_URL="ws://127.0.0.1:8000" \
NUXT_PUBLIC_BOOTH_BRIDGE_URL="ws://127.0.0.1:5678" \
    npm run build >"$FRONTEND_LOG" 2>&1 || {
        echo "Frontend build failed:" >&2
        tail -40 "$FRONTEND_LOG" >&2
        exit 1
    }

echo "Starting frontend (Nitro)..."
HOST=127.0.0.1 PORT=3000 NODE_ENV=production \
    setsid node .output/server/index.mjs \
    >>"$FRONTEND_LOG" 2>&1 &
FRONTEND_PID=$!

echo "Waiting for API and frontend..."
api_ok=false
ui_ok=false
for _ in $(seq 1 90); do
    if ! $api_ok && curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
        api_ok=true
    fi
    if ! $ui_ok && curl -fsS http://127.0.0.1:3000/login >/dev/null 2>&1; then
        ui_ok=true
    fi
    $api_ok && $ui_ok && break
    sleep 1
done
if ! $api_ok || ! $ui_ok; then
    echo "Stack failed to start." >&2
    echo "--- API log ---" >&2; tail -30 "$API_LOG" >&2 || true
    echo "--- Frontend log ---" >&2; tail -30 "$FRONTEND_LOG" >&2 || true
    exit 1
fi

PLAYWRIGHT_ARGS=(test --project=chromium)
if [[ "${UI_HEADED:-0}" == "1" ]]; then
    PLAYWRIGHT_ARGS+=(--headed)
fi

echo "Running Playwright..."
UI_BASE_URL="http://127.0.0.1:3000" \
UI_API_URL="http://127.0.0.1:8000" \
UI_ADMIN_USER="ui-admin" \
UI_ADMIN_PASSWORD="$ADMIN_PASSWORD" \
UI_PG_CONTAINER="$PG_NAME" \
UI_DB_USER="parking" \
UI_DB_NAME="parking" \
UI_SETUP_TOKEN_PATH="$SETUP_TOKEN_PATH" \
UI_SCREENSHOTS="${UI_SCREENSHOTS:-0}" \
    npx playwright "${PLAYWRIGHT_ARGS[@]}"

echo ""
echo "UI TESTS PASSED — real browser, disposable backend, no hardware."
