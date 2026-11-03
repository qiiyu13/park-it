#!/usr/bin/env bash
# Hardware-free simulation run.
#
# Starts disposable Postgres + Redis on non-default ports, migrates the schema,
# and runs the simulator/e2e suites against in-process TCP simulators:
#
#   • Compass gate controller simulator (vehicle sensor, ticket button,
#     Wiegand/RFID, relay commands, display/audio/print frames)
#   • PASSTI e-money reader simulator (INIT/CheckBalance/Deduct, status codes)
#   • booth_bridge deduct flow with a mocked serial port
#   • print + snapshot workers in MOCK_HARDWARE mode (files, not devices)
#
# Nothing on this machine is modified: containers are removed on exit, no
# /etc/parking files are written, and no real serial/TCP hardware is used.
#
# Usage:
#   ./scripts/simulate.sh          # fast simulation (e2e + protocol suites)
#   ./scripts/simulate.sh --all    # entire test suite on the disposable stack
#   ./scripts/simulate.sh --keep   # leave containers running for manual poking
#
# Ports (override with env):
#   SIM_PG_PORT=55432  SIM_REDIS_PORT=56379

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PG_PORT="${SIM_PG_PORT:-55432}"
REDIS_PORT="${SIM_REDIS_PORT:-56379}"
PG_NAME="parking-sim-pg"
REDIS_NAME="parking-sim-redis"
PG_PASSWORD="sim_parking_pw"
REDIS_PASSWORD="sim_parking_pw"
KEEP=false
ALL=false

for arg in "$@"; do
    case "$arg" in
        --all)  ALL=true ;;
        --keep) KEEP=true ;;
        -h|--help)
            sed -n '2,26p' "$0"
            exit 0
            ;;
        *)
            echo "unknown arg: $arg" >&2
            exit 2
            ;;
    esac
done

if ! command -v docker &>/dev/null; then
    echo "ERROR: docker is required for the disposable database/Redis." >&2
    exit 1
fi
if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
    echo "ERROR: .venv missing. Run: python3.12 -m venv .venv && .venv/bin/pip install -e ." >&2
    exit 1
fi

cleanup() {
    if $KEEP; then
        echo ""
        echo "Keeping simulation services:"
        echo "  Postgres : 127.0.0.1:${PG_PORT} (db=parking/parking_test user=parking)"
        echo "  Redis    : 127.0.0.1:${REDIS_PORT} (password=${REDIS_PASSWORD}, db=15)"
        echo "  Remove   : docker rm -f ${PG_NAME} ${REDIS_NAME}"
        return
    fi
    docker rm -f "$PG_NAME" "$REDIS_NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "=== E-Parking v2 — hardware-free simulation ==="
echo "Postgres : 127.0.0.1:${PG_PORT}"
echo "Redis    : 127.0.0.1:${REDIS_PORT}"
echo ""

# Fail early if the chosen ports are already taken.
if (exec 3<>"/dev/tcp/127.0.0.1/${PG_PORT}") 2>/dev/null; then
    echo "ERROR: port ${PG_PORT} is already in use (set SIM_PG_PORT)." >&2
    exit 1
fi
if (exec 3<>"/dev/tcp/127.0.0.1/${REDIS_PORT}") 2>/dev/null; then
    echo "ERROR: port ${REDIS_PORT} is already in use (set SIM_REDIS_PORT)." >&2
    exit 1
fi

docker run -d --rm --name "$PG_NAME" \
    -e POSTGRES_USER=parking \
    -e POSTGRES_PASSWORD="$PG_PASSWORD" \
    -e POSTGRES_DB=parking_test \
    -p "127.0.0.1:${PG_PORT}:5432" \
    postgres:16-alpine >/dev/null

docker run -d --rm --name "$REDIS_NAME" \
    -p "127.0.0.1:${REDIS_PORT}:6379" \
    redis:7-alpine redis-server --requirepass "$REDIS_PASSWORD" >/dev/null

echo "Waiting for services..."
ready=false
for _ in $(seq 1 40); do
    if docker exec "$PG_NAME" pg_isready -U parking -d parking_test >/dev/null 2>&1 \
        && docker exec "$REDIS_NAME" redis-cli -a "$REDIS_PASSWORD" ping >/dev/null 2>&1; then
        ready=true
        break
    fi
    sleep 1
done
if ! $ready; then
    echo "ERROR: simulation services did not become ready." >&2
    docker logs "$PG_NAME" 2>&1 | tail -20 || true
    docker logs "$REDIS_NAME" 2>&1 | tail -20 || true
    exit 1
fi

# The real schema DB (tests/e2e, smoke) plus the throwaway test DB
# (api/tests fixtures create/drop their tables in `parking_test`).
if ! docker exec "$PG_NAME" psql -U parking -d parking_test -tAc \
    "SELECT 1 FROM pg_database WHERE datname='parking'" | grep -q 1; then
    docker exec "$PG_NAME" psql -U parking -d parking_test -c 'CREATE DATABASE parking;' >/dev/null
fi

export DB_HOST=127.0.0.1
export DB_PORT="$PG_PORT"
export DB_NAME=parking
export DB_USER=parking
export DB_PASSWORD="$PG_PASSWORD"
export REDIS_HOST=127.0.0.1
export REDIS_PORT="$REDIS_PORT"
export REDIS_DB=15
export REDIS_PASSWORD="$REDIS_PASSWORD"
export APP_ENV=test
export MOCK_HARDWARE=true
export MOCK_HARDWARE_DIR="/tmp/parking-sim-mock"
mkdir -p "$MOCK_HARDWARE_DIR"

echo "Applying migrations..."
.venv/bin/alembic upgrade head

echo "Checking migration/model drift..."
.venv/bin/alembic check

echo "Checking installer shell syntax..."
bash -n \
    install.sh \
    installer/setup.sh \
    installer/_roles/server/setup.sh \
    installer/_roles/booth_pc/setup.sh \
    installer/_roles/combo/setup.sh \
    installer/install-gui.sh \
    scripts/regen-enroll-token.sh \
    scripts/simulate.sh

if $ALL; then
    TARGETS=(api/tests workers/tests protocols/tests daemons/tests booth_bridge/tests tests)
    echo ""
    echo "Running full test suite (hardware simulated/mocked)..."
else
    TARGETS=(tests/e2e protocols/tests)
    echo ""
    echo "Running simulation suites (gate controller, PASSTI, booth bridge, full system)..."
fi

.venv/bin/python -m pytest "${TARGETS[@]}" -q

if $ALL; then
    echo ""
    echo "Running frontend unit tests..."
    if [[ -d frontend/node_modules ]] && command -v npm &>/dev/null; then
        (cd frontend && npm test -- --reporter=dot)
        echo ""
        echo "Building frontend (catches Nuxt/template errors)..."
        (cd frontend && npm run build >/dev/null)
        echo "Frontend build OK."
    else
        echo "SKIPPED: frontend/node_modules or npm missing."
    fi
fi

echo ""
echo "SIMULATION PASSED — no physical hardware used."
echo "Printed tickets/receipts (mock): ${MOCK_HARDWARE_DIR}/print"
