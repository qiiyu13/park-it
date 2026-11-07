#!/bin/bash
set -euo pipefail

# E-Parking v2 Development Start Script
# Usage: ./scripts/dev-start.sh [--infra-only]

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOGS_DIR="$PROJECT_ROOT/logs"
PIDS_DIR="$PROJECT_ROOT/pids"
INFRA_ONLY=false

if [[ "${1:-}" == "--infra-only" ]]; then
    INFRA_ONLY=true
fi

echo "=== E-Parking v2 Development Start ==="

# 1. Start infrastructure (single compose file: docker/docker-compose.prod.yml)
echo "[1/5] Starting PostgreSQL and Redis..."
cd "$PROJECT_ROOT"
COMPOSE_FILE=docker/docker-compose.prod.yml
docker compose -f "$COMPOSE_FILE" up -d postgres redis

# Wait for PostgreSQL
echo "[2/5] Waiting for PostgreSQL..."
for i in {1..30}; do
    if docker compose -f "$COMPOSE_FILE" exec -T postgres pg_isready -U parking -d parking >/dev/null 2>&1; then
        echo "  PostgreSQL is ready!"
        break
    fi
    sleep 1
done

# 3. Run migrations
echo "[3/5] Running database migrations..."
source .venv/bin/activate
alembic upgrade head

# 4. Seed if needed
echo "[4/5] Seeding development data (if needed)..."
python scripts/seed.py

if $INFRA_ONLY; then
    echo "=== Infrastructure ready ==="
    echo "  PostgreSQL: localhost:5432"
    echo "  pgBouncer:  localhost:6432"
    echo "  Redis:      localhost:6379"
    exit 0
fi

# 5. Start API
echo "[5/5] Starting services..."

# API
if [[ -f "$PIDS_DIR/api.pid" ]] && kill -0 "$(cat "$PIDS_DIR/api.pid")" 2>/dev/null; then
    echo "  API already running (PID $(cat "$PIDS_DIR/api.pid"))"
else
    nohup .venv/bin/uvicorn api.app.main:app --reload --host 0.0.0.0 --port 8000 > "$LOGS_DIR/api.log" 2>&1 &
    echo $! > "$PIDS_DIR/api.pid"
    echo "  API started (PID $!) -> http://localhost:8000"
fi

# Frontend
if [[ -f "$PIDS_DIR/frontend.pid" ]] && kill -0 "$(cat "$PIDS_DIR/frontend.pid")" 2>/dev/null; then
    echo "  Frontend already running (PID $(cat "$PIDS_DIR/frontend.pid"))"
else
    cd "$PROJECT_ROOT/frontend"
    nohup npm run dev > "$LOGS_DIR/frontend.log" 2>&1 &
    echo $! > "$PIDS_DIR/frontend.pid"
    echo "  Frontend started (PID $!) -> http://localhost:3000"
fi

echo ""
echo "=== All services started ==="
echo "  API:      http://localhost:8000"
echo "  Frontend: http://localhost:3000"
echo "  API Docs: http://localhost:8000/docs"
echo ""
echo "  Logs:     $LOGS_DIR/"
echo "  PIDs:     $PIDS_DIR/"
echo ""
echo "  To stop:  ./scripts/dev-stop.sh"
