# E-Parking v2 — Development Tools & Operations Guide

> **Version:** 1.0.0  
> **Date:** 26 April 2026  
> **Scope:** Development scripts, desktop shortcuts, system tray, deployment installer, site config, and reporting

---

## Table of Contents

1. [Development Environment Scripts](#1-development-environment-scripts)
2. [Desktop Shortcuts](#2-desktop-shortcuts)
3. [System Tray Indicator](#3-system-tray-indicator)
4. [Hybrid Guided Installer](#4-hybrid-guided-installer)
5. [Site Configuration](#5-site-configuration)
6. [Reporting Enhancements](#6-reporting-enhancements)
7. [Troubleshooting](#7-troubleshooting)

---

## 1. Development Environment Scripts

### Quick Start

```bash
# Start everything (PostgreSQL, Redis, API, frontend)
./scripts/dev-start.sh

# Start only infrastructure (useful before running daemons manually)
./scripts/dev-start.sh --infra-only

# Stop all services
./scripts/dev-stop.sh

# Stop services AND Docker containers
./scripts/dev-stop.sh --infra

# Start with tmux (all logs in one window)
./scripts/dev-tmux.sh
```

### What Each Script Does

#### `dev-start.sh`

| Step | Action | Output |
|------|--------|--------|
| 1 | Start Docker containers (postgres, redis, pgbouncer) | Terminal output |
| 2 | Wait for PostgreSQL to be ready | `PostgreSQL is ready!` |
| 3 | Run Alembic migrations | Migration status |
| 4 | Seed database (if empty) | `Seed complete!` |
| 5 | Start API server (background) | `logs/api.log` |
| 6 | Start frontend dev server (background) | `logs/frontend.log` |

After running, access:
- **API:** http://localhost:8000
- **Frontend:** http://localhost:3000
- **API Docs:** http://localhost:8000/docs

#### `dev-stop.sh`

Kills processes by reading PID files from `pids/`:
- `api.pid` → Uvicorn server
- `frontend.pid` → Nuxt dev server
- `daemon-*.pid` → Gate daemons

#### `dev-tmux.sh`

Creates a tmux session `eparking-dev` with 4 panes:

```
+------------------+------------------+
|  PostgreSQL/     |  API Server      |
|  Redis logs      |  (uvicorn)       |
+------------------+------------------+
|  Frontend        |  Daemon shell    |
|  (npm run dev)   |  (manual daemons)|
+------------------+------------------+
```

**Tmux controls:**
- `Ctrl+B D` — Detach (leave running in background)
- `tmux attach -t eparking-dev` — Re-attach
- `tmux kill-session -t eparking-dev` — Kill session

### Logs Directory

All logs are written to `logs/`:

```
logs/
├── api.log           # FastAPI access + error logs
├── frontend.log      # Nuxt build + dev server logs
└── daemon-*.log      # Gate daemon logs (when running)
```

---

## 2. Desktop Shortcuts

### Creating Shortcuts

```bash
./scripts/create-shortcuts.sh
```

This creates:
- `~/Desktop/E-Parking Start.desktop`
- `~/Desktop/E-Parking Stop.desktop`
- `~/.local/share/applications/eparking-*.desktop`

### Icons

- **Start icon:** Green car with "START" text (`assets/icons/eparking-start.svg`)
- **Stop icon:** Red car with "STOP" text (`assets/icons/eparking-stop.svg`)

### First Run — Trust Prompt

Ubuntu shows a trust dialog on first double-click. The script marks files as trusted automatically, but if you see:

> "Untrusted application launcher"

Right-click → **Allow Launching**.

### What Happens on Double-Click

**E-Parking Start:**
1. Opens terminal showing startup progress
2. Runs `./scripts/dev-start.sh`
3. Opens browser to http://localhost:3000

**E-Parking Stop:**
1. Opens terminal
2. Runs `./scripts/dev-stop.sh`
3. Shows confirmation when done

---

## 3. System Tray Indicator

### Installation

```bash
# Install system dependencies
sudo apt install libappindicator3-1 gir1.2-appindicator3-0.1

# Install Python dependencies
pip install -r scripts/tray-indicator-requirements.txt
```

### Running

```bash
# Foreground
python scripts/tray-indicator.py

# Background (add to startup)
nohup python scripts/tray-indicator.py &
```

### Auto-Start on Login

Add to `~/.config/autostart/eparking-tray.desktop`:

```ini
[Desktop Entry]
Name=E-Parking Tray
Exec=python /path/to/parking-system-v2/scripts/tray-indicator.py
Icon=/path/to/parking-system-v2/assets/icons/eparking-start.svg
Type=Application
```

### Tray Menu Options

| Menu Item | Action |
|-----------|--------|
| **Status** | Shows current system state (read-only) |
| **Start E-Parking** | Runs `dev-start.sh` in new terminal |
| **Stop E-Parking** | Runs `dev-stop.sh` in new terminal |
| **Open POS** | Opens browser to http://localhost:3000 |
| **View Logs** | Opens file manager to `logs/` directory |
| **View API Docs** | Opens browser to http://localhost:8000/docs |
| **Exit** | Closes tray indicator (does NOT stop services) |

### Icon Colors

| Color | Meaning |
|-------|---------|
| 🟢 Green | All services running (API, frontend, PostgreSQL, Redis) |
| 🟡 Yellow | Some services running |
| 🔴 Red | Nothing running |

The indicator polls every 5 seconds and updates automatically.

---

## 4. Guided Installer

### Purpose

Install E-Parking v2 on a fresh Ubuntu server with role selection
(server / booth / combo).

### Requirements

- Ubuntu 22.04 / 24.04 LTS (fresh install preferred)
- Internet connection
- Run as root: `sudo installer/setup.sh` (interactive role prompt) or
  `sudo installer/setup.sh --role server|booth|combo`

### Installation Phases

| Phase | Description | Typical Duration |
|-------|-------------|------------------|
| 1 | System check (Ubuntu version, disk, memory) | < 1s |
| 2 | Install packages (PostgreSQL 16, Redis 7, nginx, Node.js 20) | 3–5 min |
| 3 | Create `parking` user + `dialout` group | < 1s |
| 4 | Copy application to `/opt/parking-system-v2`, create venv | 1–2 min |
| 5 | Create PostgreSQL database, run migrations | 10–30s |
| 6 | Seed initial data (users, vehicle types, shifts) | 5s |
| 7 | Build Nuxt frontend | 1–2 min |
| 8 | Install systemd services | < 1s |
| 9 | Interactive site config (name, address, phone) | Manual |
| 10 | Interactive hardware config (controller IPs, serial port) | Manual |
| 11 | Enable and start core services | 5s |
| 12 | Health check via API | 5s |

### Post-Installation

After completion, the installer prints:

```
  API:       http://localhost/api
  Frontend:  http://localhost
  API Docs:  http://localhost/api/docs

  Login:     admin / admin123
             operator / operator123
```

### Configuration Files

| File | Purpose |
|------|---------|
| `/opt/parking-system-v2/.env` | Environment variables |
| `/opt/parking-system-v2/.install-config.json` | Installation metadata |
| `/etc/systemd/system/parking-*.service` | systemd service units |

### Managing Services

```bash
# Check status
sudo systemctl status parking-api
sudo systemctl status parking-worker-critical
sudo systemctl status parking-worker-bg

# View logs
sudo journalctl -u parking-api -f
sudo journalctl -u parking-daemon-gate-in@<gate_id> -f

# Restart
sudo systemctl restart parking-api
```

---

## 5. Site Configuration

### Purpose

Store parking site information (name, address, contact) for use in:
- Receipt / ticket headers
- Report footers
- Admin display

### Accessing Site Config

1. Log in to the admin panel
2. Go to **Settings** → **Site Info** tab

### Fields

| Field | Used In | Example |
|-------|---------|---------|
| **Site Name** | Receipt header, report title | "Parking Mall ABC" |
| **Address** | Receipt footer | "Jl. Sudirman No. 1" |
| **City** | Receipt footer | "Jakarta" |
| **Phone** | Contact info | "021-1234567" |
| **Email** | Contact info | "admin@parking.local" |
| **Tax ID (NPWP)** | Official reports | "09.123.456.7-123.000" |

### Receipt Preview

The Settings page shows a live preview of how the site name and address will appear on printed receipts.

### API Endpoints

```bash
# Get current config
curl http://localhost:8000/api/site-config

# Update config (admin only)
curl -X PUT http://localhost:8000/api/site-config \
  -H "Content-Type: application/json" \
  -H "Cookie: access_token=<token>" \
  -d '{
    "name": "Parking Mall ABC",
    "address": "Jl. Sudirman No. 1",
    "city": "Jakarta",
    "phone": "021-1234567"
  }'
```

### Database

Stored in `site_config` table (singleton — only one row allowed).

---

## 6. Reporting Enhancements

### Report Types

#### Summary Report
Overall parking statistics for a date range.

**Fields:**
- Total transactions
- Total revenue
- Revenue by method (Cash, E-Money, RFID)
- Active vs completed transactions
- Average fee

#### E-Money Report
E-Money transaction details.

**Fields:**
- Total e-money transactions
- Total deducted amount
- Success / failed / lost contact counts
- Settled vs unsettled counts

#### Shift Report (NEW)
Breakdown by work shift and operator.

**Fields per shift:**
- Shift name and date
- Operator name
- Total transactions and revenue
- Revenue by payment method
- Active vs completed

### Quick Preset Buttons (NEW)

On the Reports page, click for instant date ranges:

| Button | Date Range |
|--------|-----------|
| **Hari Ini** | Today only |
| **Minggu Ini** | Current week (Mon–Sun) |
| **Bulan Ini** | Current month |
| **Bulan Lalu** | Previous month |

### Report Export (NEW)

Each report tab has export buttons:

| Format | File Extension | Best For |
|--------|---------------|----------|
| **CSV** | `.csv` | Spreadsheet analysis, data import |
| **Excel** | `.xlsx` | Formatted tables, sharing |
| **PDF** | `.pdf` | Printing, official records |

**File naming:** `EParking_Report_Summary_2026-04-01_2026-04-27.pdf`

**PDF includes:**
- Site name from Site Config as header
- Report period
- Summary statistics table

### API Endpoints

```bash
# Summary report (date range)
GET /api/reports/summary?date_from=2026-04-01&date_to=2026-04-27

# E-Money report
GET /api/reports/emoney?date_from=2026-04-01&date_to=2026-04-27

# Shift report
GET /api/reports/shift?date_from=2026-04-01&date_to=2026-04-27

# Daily preset
GET /api/reports/summary/daily?date=2026-04-26

# Weekly preset
GET /api/reports/summary/weekly?year=2026&week=17

# Monthly preset
GET /api/reports/summary/monthly?year=2026&month=4

# Export
GET /api/reports/summary/export?format=csv&date_from=2026-04-01&date_to=2026-04-27
GET /api/reports/summary/export?format=xlsx&date_from=2026-04-01&date_to=2026-04-27
GET /api/reports/summary/export?format=pdf&date_from=2026-04-01&date_to=2026-04-27
```

---

## 7. Troubleshooting

### Development Scripts

**Issue:** `dev-start.sh` hangs on "Waiting for PostgreSQL..."

**Fix:**
```bash
# Check Docker status
docker compose --env-file .env -f docker/docker-compose.prod.yml ps

# Restart containers manually
docker compose --env-file .env -f docker/docker-compose.prod.yml down
docker compose --env-file .env -f docker/docker-compose.prod.yml up -d postgres redis

# Check PostgreSQL logs
docker compose --env-file .env -f docker/docker-compose.prod.yml logs postgres
```

**Issue:** Port 8000 or 3000 already in use

**Fix:**
```bash
# Find what's using the port
lsof -i :8000
lsof -i :3000

# Kill the process or change ports in dev-start.sh
```

### Desktop Shortcuts

**Issue:** Double-click does nothing

**Fix:**
```bash
# Check if trusted
ls -la ~/Desktop/E-Parking\ Start.desktop
# Should show executable permissions (x)

# Re-run shortcut creation
./scripts/create-shortcuts.sh

# Or manually mark trusted
gio set ~/Desktop/E-Parking\ Start.desktop metadata::trusted true
chmod +x ~/Desktop/E-Parking\ Start.desktop
```

### System Tray

**Issue:** `ModuleNotFoundError: No module named 'gi'`

**Fix:**
```bash
# Install system GTK bindings
sudo apt install libgirepository1.0-dev libcairo2-dev

# Reinstall PyGObject
pip install --force-reinstall PyGObject
```

**Issue:** Tray icon shows red even though services are running

**Fix:** Check if health endpoint is accessible:
```bash
curl http://localhost:8000/api/health
```

### Installer

**Issue:** PostgreSQL authentication fails

**Fix:**
```bash
# Reset PostgreSQL password
sudo -u postgres psql -c "ALTER USER parking WITH PASSWORD 'parking_secret';"

# Check pg_hba.conf
sudo nano /etc/postgresql/16/main/pg_hba.conf
# Ensure local connections use 'md5' or 'trust'
```

**Issue:** `permission denied` when starting services

**Fix:**
```bash
# Fix ownership
sudo chown -R parking:parking /opt/parking-system-v2

# Fix systemd file permissions
sudo chmod 644 /etc/systemd/system/parking-*.service
sudo systemctl daemon-reload
```

### Site Config

**Issue:** Site config not appearing in settings

**Fix:**
```bash
# Check if migration ran (run from repo root)
alembic current

# Apply migration if needed
alembic upgrade head

# Or create manually via API
curl -X PUT http://localhost:8000/api/site-config \
  -H "Content-Type: application/json" \
  -d '{"name": "My Parking"}'
```

### Reports

**Issue:** Export fails with 500 error

**Fix:**
```bash
# Check if openpyxl and reportlab are installed
pip list | grep -E "openpyxl|reportlab"

# Install if missing
pip install openpyxl reportlab
```

**Issue:** Shift report shows no data

**Fix:** Ensure transactions have `shift_id` assigned. Check in database:
```sql
SELECT shift_id, COUNT(*) FROM parking_transactions GROUP BY shift_id;
```

---

*For more help, check the operations runbook at `docs/OPERATIONS_RUNBOOK.md`.*
