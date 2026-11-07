# E-Parking v2 — Development & Testing Guide

> **Version:** 2.1.0  
> **Last Updated:** 27 April 2026  
> **Purpose:** Step-by-step testing procedures to validate the system before production deployment

---

## Table of Contents

1. [Testing Strategy](#testing-strategy)
2. [Environment Setup](#environment-setup)
3. [Level 1: Code Quality](#level-1-code-quality)
4. [Level 2: Unit Tests](#level-2-unit-tests)
5. [Level 3: API Tests](#level-3-api-tests)
6. [Level 4: Database Tests](#level-4-database-tests)
7. [Level 5: Frontend Tests](#level-5-frontend-tests)
8. [Level 6: Integration Tests](#level-6-integration-tests)
9. [Level 7: Smoke Tests](#level-7-smoke-tests)
10. [Level 8: Hardware Simulation](#level-8-hardware-simulation)
11. [Level 9: Load Tests](#level-9-load-tests)
12. [Pre-Deployment Checklist](#pre-deployment-checklist)
13. [Continuous Integration](#continuous-integration)

---

## Testing Strategy

E-Parking v2 uses a **9-level testing pyramid** before any code reaches production:

```
        ╱╲
       ╱  ╲     Level 9: Load Tests (locust)
      ╱    ╲
     ╱──────╲    Level 8: Hardware Simulation
    ╱        ╲
   ╱──────────╲   Level 7: Smoke Tests (fast)
  ╱            ╲
 ╱──────────────╲  Level 6: Integration Tests (E2E)
╱                ╲
╱──────────────────╲ Level 5: Frontend Build + Type Check
╱                    ╲
╱──────────────────────╲ Level 4: Database Migration Tests
╱                        ╲
╱──────────────────────────╲ Level 3: API Route Tests
╱                            ╲
╱──────────────────────────────╲ Level 2: Unit Tests
╱                                ╲
╱──────────────────────────────────╲ Level 1: Code Quality (lint, format)
```

**Rule:** All levels must pass before deployment. No exceptions.

---

## Environment Setup

### Required Services

```bash
# Start PostgreSQL and Redis
docker compose --env-file .env -f docker/docker-compose.prod.yml up -d postgres redis

# Verify services are healthy
docker compose --env-file .env -f docker/docker-compose.prod.yml ps
```

### Python Environment

```bash
# Activate virtual environment
source .venv/bin/activate

# Install dev dependencies (includes pytest, mypy, ruff)
pip install -e ".[dev]"
```

### Frontend Environment

```bash
cd frontend
npm install
cd ..
```

### Test Database

```bash
# Create test database (separate from dev database)
docker exec -it parking-postgres psql -U postgres -c "CREATE DATABASE parking_test;"
docker exec -it parking-postgres psql -U postgres -c "GRANT ALL PRIVILEGES ON DATABASE parking_test TO parking;"

# Set test DB URL for tests
export TEST_DATABASE_URL="postgresql+asyncpg://parking:parking_secret@localhost:5432/parking_test"
```

---

## Level 1: Code Quality

**Goal:** Catch syntax errors, style issues, and type mismatches before running any tests.

**Time:** ~30 seconds

```bash
# Lint Python code
ruff check api/ daemons/ protocols/ shared/ workers/ tests/

# Format check (ensure code is properly formatted)
ruff format --check api/ daemons/ protocols/ shared/ workers/ tests/

# Type check with mypy
mypy api/app/models/ api/app/routes/ api/app/schemas/ --ignore-missing-imports
```

**Expected:** All checks pass with zero errors.

**If failures:**
```bash
# Auto-fix lint issues
ruff check --fix api/ daemons/ protocols/ shared/ workers/ tests/

# Auto-format code
ruff format api/ daemons/ protocols/ shared/ workers/ tests/
```

---

## Level 2: Unit Tests

**Goal:** Test individual functions, models, and schemas in isolation.

**Time:** ~2 minutes

```bash
# Run all unit tests
pytest tests/unit/ -x -q --tb=short

# Run with coverage report
pytest tests/unit/ --cov=api/app --cov-report=term-missing
```

### What to Test

| Component | Test File | Coverage Target |
|-----------|-----------|-----------------|
| Models | `tests/unit/test_models.py` | >80% |
| Schemas | `tests/unit/test_schemas.py` | >90% |
| Utilities | `tests/unit/test_utils.py` | >80% |
| Protocol parsers | `tests/unit/test_protocols.py` | >85% |

### Writing New Unit Tests

```python
# Example: Testing Gate model helper methods
def test_gate_is_entry():
    gate = Gate(direction="IN")
    assert gate.is_entry is True
    assert gate.is_exit is False

def test_gate_peripheral_enabled():
    gate = Gate(
        hardware_config={
            "rfid": {"enabled": True},
            "emoney": {"enabled": False}
        }
    )
    assert gate.is_peripheral_enabled("rfid") is True
    assert gate.is_peripheral_enabled("emoney") is False
    assert gate.is_peripheral_enabled("camera") is False  # default
```

---

## Level 3: API Tests

**Goal:** Verify all API routes respond correctly, validate request/response schemas, and enforce auth.

**Time:** ~3 minutes

```bash
# Run API route tests
pytest tests/api/ -x -q --tb=short

# Run with TestClient (no external server needed)
pytest tests/api/ -k "test_routes" -v
```

### Key Tests

```python
# Example: Testing unified gate routes
def test_list_gates_unauthorized(client):
    response = client.get("/api/gates")
    assert response.status_code == 401

def test_create_gate_admin(client, admin_token):
    response = client.post(
        "/api/gates",
        json={
            "name": "Test Gate",
            "code": "TEST01",
            "direction": "IN",
            "protocol": "compass",
            "hardware_config": {
                "rfid": {"enabled": True, "wiegand_channel": "W"}
            }
        },
        cookies={"access_token": admin_token}
    )
    assert response.status_code == 201
    data = response.json()
    assert data["direction"] == "IN"
    assert data["hardware_config"]["rfid"]["enabled"] is True

def test_pos_by_ip_endpoint_exists(client):
    # Should return 401 (needs auth), not 404
    response = client.get("/api/pos/by-ip")
    assert response.status_code == 401
```

### Route Existence Test

```bash
# Quick check: verify all expected routes return non-404
pytest tests/smoke/test_smoke_go_live.py::TestApiRoutesSmoke -v
```

---

## Level 4: Database Tests

**Goal:** Verify migrations work correctly, schema is valid, and data integrity is maintained.

**Time:** ~2 minutes

### Migration Tests

```bash
# Test upgrade (apply all migrations)
alembic upgrade head

# Test downgrade (rollback all migrations)
alembic downgrade base

# Test upgrade again (idempotency check)
alembic upgrade head

# Verify current version
alembic current
```

### Schema Validation

```bash
# Connect to database and verify tables exist
psql -U parking -d parking -c "\dt"

# Verify new tables from migration
psql -U parking -d parking -c "
SELECT table_name 
FROM information_schema.tables 
WHERE table_schema = 'public' 
AND table_name IN ('gates', 'pos', 'cameras', 'printers')
ORDER BY table_name;
"

# Verify foreign keys
psql -U parking -d parking -c "
SELECT
    tc.table_name,
    kcu.column_name,
    ccu.table_name AS foreign_table,
    ccu.column_name AS foreign_column
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name
JOIN information_schema.constraint_column_usage ccu ON ccu.constraint_name = tc.constraint_name
WHERE tc.constraint_type = 'FOREIGN KEY'
AND tc.table_name IN ('gates', 'pos', 'printers', 'parking_transactions')
ORDER BY tc.table_name;
"
```

### Data Migration Verification

```bash
# After running migration, verify data integrity
psql -U parking -d parking -c "
SELECT 
    direction, 
    COUNT(*) as count,
    COUNT(pos_id) as with_pos
FROM gates 
GROUP BY direction;
"

# Verify POS records created for OUT gates
psql -U parking -d parking -c "
SELECT p.code, p.name, g.code as gate_code
FROM pos p
JOIN gates g ON g.pos_id = p.id;
"
```

---

## Level 5: Frontend Tests

**Goal:** Verify frontend builds without errors, type-checks pass, and key pages render.

**Time:** ~2 minutes

### Build Verification

```bash
cd frontend

# Install dependencies
npm install

# Type check
npx nuxt typecheck

# Build for production
npm run build

# Verify output exists
ls -la .output/public/ 2>/dev/null || ls -la .output/server/
```

**Expected:** Build completes with zero errors.

### Page Component Tests

```bash
# Verify critical pages compile
npm run build 2>&1 | grep -E "(error|warn)" | head -20

# Should show no errors
```

### Vue Component Tests (Optional)

```bash
# Run Vitest unit tests for Vue components
npm run test:unit

# Run component tests
npm run test:components
```

---

## Level 6: Integration Tests (E2E)

**Goal:** Test full request flows: auth → API → database → response.

**Time:** ~5 minutes

```bash
# Run full system tests (requires running database)
pytest tests/e2e/ -x -q --tb=short

# Run with live database
pytest tests/e2e/test_full_system.py -v
```

### Test Scenarios

```python
# Example: Full payment flow
def test_cash_payment_flow(client, admin_token):
    # 1. Create a gate-in
    gate_in = client.post("/api/gates", json={...}, cookies={"access_token": admin_token}).json()
    
    # 2. Create a gate-out
    gate_out = client.post("/api/gates", json={...}, cookies={"access_token": admin_token}).json()
    
    # 3. Create a vehicle entry
    entry = client.post("/api/transactions", json={...}, cookies={...}).json()
    
    # 4. Process exit payment
    payment = client.post("/api/payments/cash", json={...}, cookies={...}).json()
    
    # 5. Verify transaction is closed
    tx = client.get(f"/api/transactions/{entry['id']}", cookies={...}).json()
    assert tx["status"] == "COMPLETED"
```

### Gate Orchestration Tests

```bash
# Test gate-in state machine
pytest tests/e2e/test_gate_in_orchestration.py -v

# Test gate-out state machine
pytest tests/e2e/test_gate_out_orchestration.py -v
```

---

## Level 7: Smoke Tests

**Goal:** Fast verification that all critical components are functional. Run this before every deployment.

**Time:** ~1 minute

```bash
# Run all smoke tests
pytest tests/smoke/test_smoke_go_live.py -v
```

### What It Checks

| Test Class | What It Verifies |
|------------|------------------|
| `TestHealthSmoke` | API health endpoint responds |
| `TestAuthSmoke` | Login validation works |
| `TestApiRoutesSmoke` | All routes are mounted (no 404s) |
| `TestSecurityHeadersSmoke` | Security headers present |
| `TestRateLimitSmoke` | Rate limiting active |
| `TestWebSocketSmoke` | WebSocket endpoint available |
| `TestRouteCountSmoke` | Expected number of routes loaded |

### Quick Smoke Check (Fastest)

```bash
# Single-command health check
curl http://localhost:8000/api/health
curl http://localhost:8000/metrics
```

---

## Level 8: Hardware Simulation

**Goal:** Test hardware protocols without physical devices.

**Time:** ~3 minutes

### Controller Simulator

```bash
# Run controller simulator tests
pytest tests/e2e/simulator/test_controller_sim.py -v

# Run PASSTI simulator tests
pytest tests/e2e/simulator/test_passti_sim.py -v
```

### Manual Simulation

```bash
# Start controller simulator (in terminal 1)
python tests/e2e/simulator/controller_sim.py --port 9001

# Test gate daemon against simulator (in terminal 2)
python scripts/controller_test.py compass localhost 9001
```

### Booth Bridge Simulation

```bash
# Start booth bridge with test config
python -m booth_bridge.main --config tests/fixtures/booth_test.json --port 5679

# Test WebSocket connection
python scripts/test_booth_ws.py --port 5679
```

---

## Level 9: Load Tests

**Goal:** Verify system handles expected concurrent load.

**Time:** ~10 minutes

### Prerequisites

```bash
# Ensure full stack is running
docker compose --env-file .env -f docker/docker-compose.prod.yml up -d

# Seed test data
python scripts/seed.py

# Start API
uvicorn api.app.main:app --host 0.0.0.0 --port 8000
```

### Run Load Tests

```bash
# Start Locust
locust -f tests/load/locustfile.py --host http://localhost:8000

# Open browser: http://localhost:8089
# Set: 50 users, spawn rate 5, duration 5 minutes
```

### Expected Results

| Metric | Threshold | Action if Exceeded |
|--------|-----------|-------------------|
| Health check median | < 100ms | Investigate API latency |
| Transaction list median | < 300ms | Check database indexing |
| Error rate at 50 users | 0% | Review logs for failures |
| Memory usage | < 80% | Scale up or optimize |

### Quick Load Test (CLI)

```bash
# Run headless load test (no browser needed)
locust -f tests/load/locustfile.py \
    --host http://localhost:8000 \
    --users 50 \
    --spawn-rate 5 \
    --run-time 5m \
    --headless \
    --html load_test_report.html
```

---

## Pre-Deployment Checklist

Before deploying to production, complete all levels:

### Code & Quality
- [ ] Level 1: `ruff check` passes (0 errors)
- [ ] Level 1: `ruff format --check` passes
- [ ] Level 1: `mypy` passes (0 errors)

### Backend Tests
- [ ] Level 2: Unit tests pass (`pytest tests/unit/`)
- [ ] Level 3: API tests pass (`pytest tests/api/`)
- [ ] Level 4: Migrations apply cleanly (`alembic upgrade head`)
- [ ] Level 4: Schema validation passes

### Frontend Tests
- [ ] Level 5: `npm install` succeeds
- [ ] Level 5: `npm run build` succeeds (0 errors)
- [ ] Level 5: Type check passes (`npx nuxt typecheck`)

### Integration Tests
- [ ] Level 6: E2E tests pass (`pytest tests/e2e/`)
- [ ] Level 7: Smoke tests pass (`pytest tests/smoke/`)

### Hardware & Load
- [ ] Level 8: Simulator tests pass (if hardware unavailable)
- [ ] Level 9: Load tests pass (if production-like environment available)

### Manual Verification
- [ ] Login page loads correctly
- [ ] Device page shows unified gate list
- [ ] POS page auto-detects booth (if configured)
- [ ] Gate-in daemon starts and connects to controller
- [ ] Gate-out daemon starts and connects to controller
- [ ] Booth bridge starts and accepts WebSocket connections

---

## Continuous Integration

### Recommended CI Pipeline

```yaml
# .github/workflows/test.yml (example)
name: Test

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_PASSWORD: postgres
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
      redis:
        image: redis:7
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      
      - name: Install dependencies
        run: |
          python -m venv .venv
          source .venv/bin/activate
          pip install -e ".[dev]"
      
      - name: Run lint
        run: |
          source .venv/bin/activate
          ruff check api/ daemons/ protocols/ shared/ workers/ tests/
      
      - name: Run type check
        run: |
          source .venv/bin/activate
          mypy api/app/models/ api/app/routes/ api/app/schemas/ --ignore-missing-imports
      
      - name: Run unit tests
        run: |
          source .venv/bin/activate
          pytest tests/unit/ -x -q --tb=short
      
      - name: Run API tests
        run: |
          source .venv/bin/activate
          pytest tests/api/ -x -q --tb=short
      
      - name: Run smoke tests
        run: |
          source .venv/bin/activate
          pytest tests/smoke/ -v
      
      - name: Build frontend
        run: |
          cd frontend
          npm install
          npm run build
```

---

## Debugging Failed Tests

### Common Issues

**"relation does not exist" errors:**
```bash
# Database not initialized
alembic upgrade head
python scripts/seed.py
```

**"Module not found" errors:**
```bash
# Dependencies not installed
pip install -e ".[dev]"
```

**"Connection refused" in E2E tests:**
```bash
# Ensure database is running
docker compose --env-file .env -f docker/docker-compose.prod.yml up -d postgres
```

**Frontend build errors:**
```bash
# Clear node_modules and reinstall
cd frontend
rm -rf node_modules package-lock.json
npm install
npm run build
```

### Getting Help

1. Check logs: `pytest -v --tb=long` for full traceback
2. Isolate test: `pytest tests/path/test_file.py::test_function -v`
3. Check fixtures: `pytest --fixtures` to see available test fixtures
4. Run with debugger: `pytest --pdb` to drop into debugger on failure

---

*This guide should be updated when new test suites are added or testing procedures change.*
