# CLAUDE.md — E-Parking v2

## Project Overview

E-Parking v2 = parking management system for Indonesian facilities. Supports e-money cards (Mandiri eMoney, BRI Brizzi, BNI TapCash, BCA Flazz), cash, RFID member cards. Controls physical gates, cameras, thermal printers, barcode scanners, LED displays.

**Stack:** FastAPI (Python 3.12+) · PostgreSQL 16 · Redis 7 · Nuxt 3 (Vue 3) · Tailwind CSS 4 · systemd

## Repository Structure

```
api/              FastAPI backend (routes, models, services, middleware)
api/app/models/   SQLAlchemy ORM models (25+ tables)
api/app/routes/   REST + WebSocket endpoints (prefixed /api)
api/migrations/   Alembic migration files
frontend/         Nuxt 3 SPA (Vue 3 + Pinia + Tailwind)
daemons/          Hardware gateway daemons (state machines)
protocols/        Hardware protocol implementations (Compass, ENET, PASSTI, ESC/POS)
workers/          ARQ async job queue (critical: print/snapshot, background: settlement)
booth_bridge/     Serial-to-WebSocket bridge for booth PCs
shared/           Cross-cutting: config, logging, events (Redis IPC schemas)
docker/           Docker Compose files
systemd/          Service unit files
scripts/          Deployment and utility scripts
tests/            E2E, smoke, load tests
```

## Quick Start

```bash
# Backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # edit with your credentials
docker compose up -d           # PostgreSQL + Redis
cd api && alembic upgrade head
uvicorn api.app.main:app --reload

# Frontend (separate terminal)
cd frontend && npm install && npm run dev
```

- Frontend: http://localhost:3000
- API docs: http://localhost:8000/api/docs

## Common Commands

```bash
# Backend
cd api && alembic upgrade head              # apply migrations
cd api && alembic revision -m "description" # create migration
cd api && alembic downgrade -1              # rollback one
pytest                                       # run all tests (api, workers, protocols, daemons)
ruff check .                                 # lint
mypy .                                       # type check

# Frontend
cd frontend && npm run dev                   # dev server
cd frontend && npm run build                 # production build
cd frontend && npm run lint                  # lint
```

## Architecture

### Unified Gate Model

Single `Gate` table with `direction='IN'|'OUT'` — replaces old `GateIn`/`GateOut` split. Old tables dropped in migration `f0bd4bac1599`. Query by direction: `GET /api/gates?direction=IN`.

### Event-Driven IPC

- **Redis Pub/Sub:** Daemon -> API (vehicle_detected, gate_opened, deduct_result)
- **Redis Streams:** API -> Daemon (open_gate_command, close_gate_command) with ACK-based reliability
- **WebSocket:** API -> Frontend POS (real-time vehicle/payment notifications)
- Event schemas: `shared/events.py` (Pydantic models)

### Gate Daemons / Exit Lane

- `daemons/gate_in.py` — Entry gate state machine (IDLE -> VEHICLE_DETECTED -> WAITING_PRINT -> OPEN -> ...). Includes IN2 trigger on IN1 presence.
- Entry point: `daemons/cli.py` (reads gate config from DB)
- Heartbeat every 30s, never import `api.database` (independent engine)
- **Exit lane has no autonomous daemon.** `daemons/gate_out.py` was removed (commit `f4a3eb0`). Exit lane is driven directly by `booth_bridge/`:
  - `booth_bridge/omnikey_poller.py` — Omnikey 5427 evdev RFID poll loop, calls `/api/payments/rfid/booth`, fires local relay (replaced legacy `uhf_poller.py`)
  - `booth_bridge/gate_opener.py` — writes serial open hex to local relay, sleeps `close_delay_seconds` (default 3s), writes close hex
  - `booth_bridge/api_client.py` — async HTTP client (X-API-Key auth) for gate config + booth RFID exit endpoint
  - `booth_bridge/websocket_server.py` — emoney_deduct SUCCESS fires local relay open + broadcasts `emoney_payment_completed`
  - `booth_bridge/main.py` — per-task supervisor with backoff (commit `9d2b13a`)

### Two-Step Exit Flow (Cash)

Cash payment does NOT auto-open gate. Flow: operator pays -> receipt prints (ARQ) -> operator presses Space/button -> booth_bridge fires local relay open. RFID and e-money auto-open (pre-verified via booth bridge).

### E-Money Payment Path (single path; no more manless variant)

- Card tap -> Booth Bridge PASSTI serial -> API `/emoney/booth-result` (API key auth) -> on SUCCESS booth_bridge fires `gate_opener` local relay + broadcasts `emoney_payment_completed` WS event.

## Key Files

| File | Purpose |
|------|---------|
| `api/app/main.py` | FastAPI app factory (middleware, routers) |
| `api/app/models/gate.py` | Unified Gate model (source of truth) |
| `api/app/models/parking_transaction.py` | Core business entity |
| `api/app/services/payment.py` | Cash/RFID/E-money payment orchestration |
| `api/app/routes/payments.py` | Payment endpoints |
| `api/app/routes/gates_unified.py` | Gate CRUD + open/close commands |
| `daemons/base.py` | Abstract daemon (Redis Streams, heartbeat) |
| `daemons/gate_in.py` | Entry gate state machine |
| `booth_bridge/main.py` | Booth Bridge supervisor (drives exit lane) |
| `booth_bridge/gate_opener.py` | Exit lane local relay open/close |
| `booth_bridge/omnikey_poller.py` | Booth RFID poller (Omnikey 5427 evdev) |
| `booth_bridge/websocket_server.py` | Booth POS WS server (PASSTI e-money + relay) |
| `shared/config.py` | Pydantic Settings (reads .env) |
| `shared/events.py` | Redis IPC event schemas |
| `workers/settings.py` | ARQ worker configuration |
| `frontend/pages/index.vue` | POS operator page |
| `frontend/pages/gate-in.vue` | Gate-in monitoring page |
| `frontend/stores/gate.js` | Gate state Pinia store |

## Code Conventions

- **Python:** ruff (line-length 100, py312 target), mypy strict, Google-style docstrings
- **Database:** async SQLAlchemy + asyncpg, `DateTime(timezone=True)` always, JSONB for flexible configs, models inherit `Base + IntPKMixin + TimestampMixin`
- **API:** JWT via httpOnly cookies, responses wrapped in `SuccessResponse`/`ErrorResponse`, auth decorators `require_admin`/`require_operator`, all routes prefixed `/api`
- **Frontend:** relative API URLs (`/api/...`) for nginx proxy, Pinia stores with `useApi()` composable, shadcn-vue UI components
- **Daemons:** systemd templates with `%i` for gate ID, never import from `api.database`
- **Tests:** pytest with asyncio_mode=auto, test paths: `api/tests`, `workers/tests`, `protocols/tests`, `daemons/tests`

## Environment Variables

Key variables in `.env` (see `.env.example` for full list):

- `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` — PostgreSQL
- `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD` — Redis
- `JWT_SECRET`, `JWT_ALGORITHM` — Authentication
- `CORS_ORIGINS` — Allowed frontend origins
- `INTERNAL_API_KEY` — Booth bridge machine-to-machine auth
- `DEFAULT_PAYMENT_TIMEOUT_SECONDS` — Payment timeout (default 120)

## graphify

Knowledge graph at graphify-out/ — god nodes, communities, cross-file relationships. 3530 nodes, 4945 edges (80% EXTRACTED, 20% INFERRED), 9 hyperedges.

**Navigation strategy (hyperedge-first):**

1. Read GRAPH_REPORT.md for god nodes + surprising connections + hyperedges
2. Cross-module questions: start at hyperedges — they model Redis Pub/Sub + Streams flows AST can't see (daemon↔API IPC, e-money dual path, settlement pipeline). Then navigate member nodes.
3. Single-node context: `graphify explain "<concept>"`
4. A→B traversal: `graphify path "<A>" "<B>"`
5. Broad exploration: `graphify query "<question>"`
6. Prefer graph over grep for cross-module questions (traverses EXTRACTED + INFERRED edges)
7. After code changes: `graphify update .` (AST-only, no API cost)

## @RTK.md

RTK (Rust Token Killer) installed for shell command output compression. Reduces token usage 60-90% on common dev commands.
