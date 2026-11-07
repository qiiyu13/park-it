# E-Parking v2 — Server Installation Guide

> Install the complete server stack: PostgreSQL, Redis, API, Frontend, nginx, and workers.

---

## Prerequisites

| Requirement | Minimum |
|------------|---------|
| OS | Ubuntu 24.04 LTS |
| CPU | 4 cores |
| RAM | 8 GB |
| Disk | 50 GB SSD |
| Network | Static IP or mDNS hostname |

---

## Quick Start

```bash
# 1. Clone the repository
git clone <repo-url> /tmp/parking-system-v2
cd /tmp/parking-system-v2/installer/server

# 2. Run the installer (requires root)
sudo ./setup.sh
```

The script will interactively prompt you for:
- **Server IP** — used for CORS and booth shortcuts
- **PostgreSQL password** — for the `parking` DB user
- **JWT secret** — used for token signing (auto-generated if blank)
- **Git repository URL** — source code location

---

## What Gets Installed

### System Packages
- `postgresql-16` — Main database
- `redis-server` — Cache, pub/sub, streams
- `nginx` — Reverse proxy
- `python3.12` + venv — Runtime
- `nodejs` 22 + npm — Frontend build
- `google-chrome-stable` — For kiosk mode on server-as-booth setups

### Application
- Cloned to `/opt/parking-system-v2`
- Python venv at `/opt/parking-system-v2/.venv`
- Frontend built at `/opt/parking-system-v2/frontend/.output/`

### Database
- Database: `parking`
- User: `parking`
- Migrations applied automatically
- Seeding is **not** done automatically. `scripts/seed.py` is development-only
  and refuses to run when `APP_ENV=production` (demo users/gates with default passwords)

### Systemd Services
| Service | Purpose |
|---------|---------|
| `parking-api` | FastAPI via Gunicorn (port 8000) |
| `parking-worker-critical` | ARQ critical queue worker |
| `parking-worker-bg` | ARQ background queue worker |
| `nginx` | Reverse proxy (port 80) |

### Directories
| Path | Purpose |
|------|---------|
| `/var/lib/parking/snapshots` | Camera snapshots |
| `/var/lib/parking/settlements` | Settlement files |
| `/var/lib/parking/logs` | Application logs |

---

## Post-Installation

### 1. Verify Services

```bash
sudo systemctl status parking-api
sudo systemctl status parking-worker-critical
sudo systemctl status parking-worker-bg
sudo systemctl status nginx
```

### 2. Configure Gates

Log in to the web UI at `http://<server-ip>`:

1. **Admin login** — default from `seed.py`: `admin` / `admin123`
2. Go to **Device → Gates**
3. Add your gates:

| Field | Gate In 1 | Gate In 2 | Gate Out 1 | Gate Out 2 |
|-------|-----------|-----------|------------|------------|
| Name | Gate Masuk 1 | Gate Masuk 2 | Gate Keluar 1 | Gate Keluar 2 |
| Code | `GIN-01` | `GIN-02` | `GOUT-01` | `GOUT-02` |
| Direction | `IN` | `IN` | `OUT` | `OUT` |
| Controller Host | `192.168.1.101` | `192.168.1.102` | `192.168.1.201` | `192.168.1.202` |
| Controller Port | `5000` | `5000` | `5000` | `5000` |

4. Go to **Device → Booth POS**
5. Add booth records:

| Field | Booth 1 (on server) | Booth 2 (separate PC) |
|-------|---------------------|-----------------------|
| Name | Booth 1 | Booth 2 |
| Code | `BOOTH_01` | `BOOTH_02` |
| IP Address | `192.168.1.100` | `192.168.1.101` |
| Gate Default | `GOUT-01` | `GOUT-02` |

6. Link gates to booths by editing each gate and setting its **POS** field.

### 3. Start Gate Daemons (After Configuring Gates in Web UI)

**Important:** Gate daemons read their config from the database. You must add gates in the web UI **before** starting daemons, or they will fail with "Gate not found in database".

#### Quick Auto-Enable (Recommended)
```bash
cd /opt/parking-system-v2
./scripts/enable-gate-daemons.sh --run
```

This script reads all gates from the database and runs the correct `systemctl enable --now` commands for each one. Gates auto-start on future reboots.

#### Manual Enable (if you prefer)
```bash
# Entry gates only — exit lanes have no daemon (booth-bridge drives the relay)
sudo systemctl enable --now parking-daemon-gate-in@GIN-01
sudo systemctl enable --now parking-daemon-gate-in@GIN-02
```

> `enable --now` means: (1) enable auto-start on boot, and (2) start immediately. You only need to run this once per gate.

### 4. Verify API

```bash
curl http://localhost/api/health
# Expected: {"status":"ok"}
```

### 5. Change Default Passwords

```bash
# Log in via web UI and change admin password immediately
# Create additional operators as needed
```

---

## Troubleshooting

### API won't start
```bash
sudo journalctl -u parking-api -n 50
# Check .env variables and DB connectivity
```

### Database connection failed
```bash
# Test from command line
sudo -u parking psql -U parking -d parking -c "SELECT 1"
```

### nginx 502 Bad Gateway
```bash
sudo nginx -t
sudo systemctl restart nginx
sudo systemctl status parking-api
```

### Port 80 already in use
```bash
sudo lsof -i :80
sudo systemctl stop apache2  # or whatever is using it
```

---

## Maintenance

### Update Application
```bash
cd /opt/parking-system-v2
sudo -u parking git pull origin main
sudo -u parking .venv/bin/pip install -e .
sudo -u parking .venv/bin/alembic upgrade head
cd frontend && sudo -u parking npm ci && NUXT_PUBLIC_API_BASE_URL="" npm run build
sudo systemctl restart parking-api parking-worker-critical parking-worker-bg
```

### Backup Database
```bash
DATE=$(date +%Y%m%d_%H%M%S)
sudo -u postgres pg_dump parking | gzip > /backup/parking_${DATE}.sql.gz
```

### Restore Database
```bash
gunzip < /backup/parking_YYYYMMDD_HHMMSS.sql.gz | sudo -u postgres psql -d parking
```

---

*Last updated: April 2026*
