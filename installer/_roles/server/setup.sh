#!/bin/bash
set -euo pipefail

# ═══════════════════════════════════════════════════════════════════════════════
# E-Parking v2 — Server Installation Script
# ═══════════════════════════════════════════════════════════════════════════════
#
# This script installs the full E-Parking v2 server stack:
#   PostgreSQL 16, Redis, nginx, Python 3.12, Node.js, Google Chrome
#   Clones the repo, builds the frontend, installs systemd services.
#
# Usage:
#   sudo ./setup.sh                      # interactive (advanced: wizard follows)
#   sudo ./setup.sh --quick              # technician one-command install
#   sudo ./setup.sh --quick --topology 2in2out --tariff mall \
#        --site-name "Parkir ABC" --admin-user admin
#   sudo ./setup.sh --non-interactive    # infrastructure only (CI); wizard follows
#
# ═══════════════════════════════════════════════════════════════════════════════

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="/opt/parking-system-v2"
# Default to the origin of this checkout (tech cloned the repo to run us), so
# the field tech never has to type/paste the URL or hit the placeholder guard.
REPO_URL="$(git -C "$SCRIPT_DIR" remote get-url origin 2>/dev/null || echo "https://github.com/your-org/parking-system-v2.git")"

source "$SCRIPT_DIR/../common.sh"

NON_INTERACTIVE=false
QUICK=false
QUICK_TOPOLOGY="1in1out"
QUICK_TARIFF="standard"
QUICK_SITE_NAME="E-Parking"
QUICK_ADMIN_USER="admin"
QUICK_ADMIN_PASSWORD=""
QUICK_ADMIN_PASSWORD_FILE=""
QUICK_GATE_BASE_IP="192.168.1.100"
QUICK_NO_DAEMONS=false
QUICK_INCLUDE_LOCAL_SERIAL=false
QUICK_OPTS_USED=false
# Accept both `--flag=value` and `--flag value` (docs use the spaced form).
while [[ $# -gt 0 ]]; do
    case "$1" in
        --non-interactive) NON_INTERACTIVE=true ;;
        --quick) QUICK=true; NON_INTERACTIVE=true ;;
        --topology) QUICK_TOPOLOGY="${2:-}"; QUICK_OPTS_USED=true; shift ;;
        --topology=*) QUICK_TOPOLOGY="${1#*=}"; QUICK_OPTS_USED=true ;;
        --tariff) QUICK_TARIFF="${2:-}"; QUICK_OPTS_USED=true; shift ;;
        --tariff=*) QUICK_TARIFF="${1#*=}"; QUICK_OPTS_USED=true ;;
        --site-name) QUICK_SITE_NAME="${2:-}"; QUICK_OPTS_USED=true; shift ;;
        --site-name=*) QUICK_SITE_NAME="${1#*=}"; QUICK_OPTS_USED=true ;;
        --admin-user) QUICK_ADMIN_USER="${2:-}"; QUICK_OPTS_USED=true; shift ;;
        --admin-user=*) QUICK_ADMIN_USER="${1#*=}"; QUICK_OPTS_USED=true ;;
        --admin-password) QUICK_ADMIN_PASSWORD="${2:-}"; QUICK_OPTS_USED=true; shift ;;
        --admin-password=*) QUICK_ADMIN_PASSWORD="${1#*=}"; QUICK_OPTS_USED=true ;;
        --admin-password-file) QUICK_ADMIN_PASSWORD_FILE="${2:-}"; QUICK_OPTS_USED=true; shift ;;
        --admin-password-file=*) QUICK_ADMIN_PASSWORD_FILE="${1#*=}"; QUICK_OPTS_USED=true ;;
        --gate-base-ip) QUICK_GATE_BASE_IP="${2:-}"; QUICK_OPTS_USED=true; shift ;;
        --gate-base-ip=*) QUICK_GATE_BASE_IP="${1#*=}"; QUICK_OPTS_USED=true ;;
        --no-daemons) QUICK_NO_DAEMONS=true; QUICK_OPTS_USED=true ;;
        --include-local-serial) QUICK_INCLUDE_LOCAL_SERIAL=true; QUICK_OPTS_USED=true ;;
        -h|--help) sed -n '6,30p' "$0"; exit 0 ;;
        *) error "unknown arg: $1"; exit 2 ;;
    esac
    shift
done

# Quick topology: preset name or NinMout. Exit lanes are booth-driven; this
# only controls how many gate ROWS get created.
QUICK_IN=1
QUICK_OUT=1
case "$QUICK_TOPOLOGY" in
    1in1out|1in1) QUICK_IN=1; QUICK_OUT=1 ;;
    2in2out|2in2) QUICK_IN=2; QUICK_OUT=2 ;;
    1in2out|1in2) QUICK_IN=1; QUICK_OUT=2 ;;
    *in*out)
        if [[ "$QUICK_TOPOLOGY" =~ ^([0-9]+)in([0-9]+)out$ ]]; then
            QUICK_IN="${BASH_REMATCH[1]}"
            QUICK_OUT="${BASH_REMATCH[2]}"
        else
            error "invalid --topology '${QUICK_TOPOLOGY}' (use 1in1out, 2in2out, 1in2out, NinMout)"
            exit 2
        fi
        ;;
    *)
        error "invalid --topology '${QUICK_TOPOLOGY}' (use 1in1out, 2in2out, 1in2out, NinMout)"
        exit 2
        ;;
esac

if [[ "$QUICK_TARIFF" != "standard" && "$QUICK_TARIFF" != "mall" ]]; then
    error "invalid --tariff '${QUICK_TARIFF}' (use standard or mall)"
    exit 2
fi
if [[ -n "$QUICK_ADMIN_PASSWORD" && ${#QUICK_ADMIN_PASSWORD} -lt 8 ]]; then
    error "--admin-password must be at least 8 characters"
    exit 2
fi
# Quick-only options mean nothing without quick provisioning. Silently ignoring
# them in --advanced mode is how a site ends up with the wrong name/topology.
if ! $QUICK && $QUICK_OPTS_USED; then
    error "options like --topology/--tariff/--site-name/--admin-*/--gate-base-ip/--no-daemons only apply to quick mode."
    error "Remove --advanced, or configure these values in the setup wizard instead."
    exit 2
fi

TMP_ADMIN_PASSWORD_FILE=""
trap 'rm -f "${TMP_ADMIN_PASSWORD_FILE:-}"' EXIT

# ── 0. Preflight checks ───────────────────────────────────────────────────────
step "0/12 — Preflight Checks"

if [[ $EUID -ne 0 ]]; then
    error "This script must be run as root (use sudo)"
    exit 1
fi

if ! grep -q "Ubuntu 24.04" /etc/os-release 2>/dev/null; then
    warn "This script targets Ubuntu 24.04 LTS (ships python3.12 natively). Continuing anyway..."
    warn "On 22.04 the python3.12 packages below are NOT in the default repos and install will fail."
    if ! $NON_INTERACTIVE; then
        read -rp "Press Enter to continue or Ctrl+C to abort..."
    fi
fi

# ── 1. Gather configuration ───────────────────────────────────────────────────
step "1/12 — Configuration"

SERVER_IP=$(hostname -I | awk '{print $1}')
if ! $NON_INTERACTIVE; then
    read -rp "Server IP address [${SERVER_IP}]: " INPUT_IP
    SERVER_IP=${INPUT_IP:-$SERVER_IP}
fi

# DB password: reuse an existing non-placeholder value (re-run must not
# rotate), otherwise prompt with NO default — parking_secret is rejected by
# the app's production validator, so offering it as a default meant
# "press Enter" produced a server that could never boot.
DB_PASS=""
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    existing_db=$(grep -m1 '^DB_PASSWORD=' "$PROJECT_ROOT/.env" | cut -d= -f2- || true)
    if [[ -n "$existing_db" && "$existing_db" != "parking_secret" && "$existing_db" != *"change-me"* ]]; then
        DB_PASS="$existing_db"
        info "Reusing DB_PASSWORD from existing .env (no rotation)"
    fi
fi
if [[ -z "$DB_PASS" ]]; then
    if $NON_INTERACTIVE; then
        DB_PASS=$(openssl rand -hex 12)
        info "Generated random DB password (stored in .env)"
    else
        read -rsp "PostgreSQL password for 'parking' (empty = generate random): " DB_PASS
        echo
        if [[ -z "$DB_PASS" || "$DB_PASS" == "parking_secret" ]]; then
            DB_PASS=$(openssl rand -hex 12)
            warn "parking_secret/empty rejected by the app in production — generated a random password"
        fi
    fi
fi
# Password lands in SQL (CREATE/ALTER) — restrict to safe characters.
if [[ ! "$DB_PASS" =~ ^[A-Za-z0-9@#%^+=._-]+$ ]]; then
    error "DB password may only contain [A-Za-z0-9@#%^+=._-] (got quotes/spaces/semicolons)."
    exit 1
fi

if $NON_INTERACTIVE; then
    JWT_SECRET=$(openssl rand -hex 32)
else
    read -rsp "JWT secret (empty = generate random): " JWT_SECRET
    echo
    if [[ -z "$JWT_SECRET" ]]; then
        JWT_SECRET=$(openssl rand -hex 32)
        warn "Generated random JWT secret"
    fi
fi

# Booth bridge machine-to-machine auth. config.py refuses to start when
# APP_ENV=production and this is unset, so always generate one.
INTERNAL_API_KEY=$(openssl rand -hex 32)

# PARKING_SOURCE_DIR (set by installer/install-gui.sh): install from the
# flashdisk copy instead of cloning, so no repo URL is needed.
if ! $NON_INTERACTIVE && [[ -z "${PARKING_SOURCE_DIR:-}" ]]; then
    read -rp "Git repository URL [${REPO_URL}]: " INPUT_REPO
    REPO_URL=${INPUT_REPO:-$REPO_URL}
fi
if [[ -z "${PARKING_SOURCE_DIR:-}" && "$REPO_URL" == *your-org* ]]; then
    error "REPO_URL is still the placeholder (your-org). Enter the real repository URL."
    exit 1
fi

# ── 1b. System timezone ───────────────────────────────────────────────────────
# Settlement files + transaction timestamps are operational-local (WIB). A
# mismatched clock corrupts the daily Multibank cut, so pin the zone.
APP_TIMEZONE="${APP_TIMEZONE:-Asia/Jakarta}"
current_tz="$(timedatectl show -p Timezone --value 2>/dev/null || echo "")"
if [[ "$current_tz" != "$APP_TIMEZONE" ]]; then
    timedatectl set-timezone "$APP_TIMEZONE" \
        && ok "Timezone set to ${APP_TIMEZONE} (was: ${current_tz:-unknown})" \
        || warn "Failed to set timezone — set ${APP_TIMEZONE} manually before go-live."
else
    ok "Timezone already ${APP_TIMEZONE}"
fi

# ── 2. Update system ──────────────────────────────────────────────────────────
step "2/12 — Updating System Packages"

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get upgrade -y -qq

# ── 3. Install dependencies ───────────────────────────────────────────────────
step "3/12 — Installing Dependencies"

apt-get install -y -qq \
    postgresql-16 postgresql-client-16 postgresql-contrib-16 \
    redis-server \
    nginx \
    python3.12 python3.12-venv python3.12-dev python3-pip \
    curl wget git unzip rsync \
    ffmpeg

# Node.js 22 (matches CI and the frontend Docker image)
if ! command -v node &>/dev/null; then
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
    apt-get install -y -qq nodejs
fi
ok "Node.js $(node -v) installed"

# Google Chrome
if ! command -v google-chrome &>/dev/null; then
    wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb -O /tmp/chrome.deb
    apt-get install -y -qq /tmp/chrome.deb || apt-get install -fy -qq
    rm -f /tmp/chrome.deb
fi
ok "Google Chrome installed"

# ── 4. Create parking user ────────────────────────────────────────────────────
step "4/12 — Creating System User"

if ! id parking &>/dev/null; then
    useradd -r -s /bin/bash -m -d /home/parking parking
fi
usermod -aG dialout,input parking
ok "User 'parking' created (groups: $(groups parking))"

# ── 5. Configure PostgreSQL ───────────────────────────────────────────────────
step "5/12 — Configuring PostgreSQL"

# CREATE if absent, then ALWAYS ALTER: a re-run with a different password
# used to leave the old one in place (CREATE silently skipped) while .env
# got the new one — API could never connect again.
sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname='parking'" | grep -q 1 \
    || sudo -u postgres psql -c "CREATE USER parking WITH PASSWORD '${DB_PASS}';"
sudo -u postgres psql -c "ALTER USER parking WITH PASSWORD '${DB_PASS}';"
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='parking'" | grep -q 1 \
    || sudo -u postgres psql -c "CREATE DATABASE parking OWNER parking;"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE parking TO parking;"
ok "PostgreSQL user/database ensured (password matches .env)"

# Allow local connections with md5
PG_HBA="/etc/postgresql/16/main/pg_hba.conf"
if ! grep -q "parking" "$PG_HBA"; then
    echo "local   parking   parking   md5" >> "$PG_HBA"
    systemctl restart postgresql
fi
ok "PostgreSQL configured"

# ── 6. Configure Redis ────────────────────────────────────────────────────────
step "6/12 — Configuring Redis"

systemctl enable redis-server
systemctl start redis-server
ok "Redis enabled and started"

# ── 7. Clone and install application ──────────────────────────────────────────
step "7/12 — Installing Application"

if [[ -d "$PROJECT_ROOT/.git" ]]; then
    warn "Repository already exists at ${PROJECT_ROOT}. Pulling latest..."
    cd "$PROJECT_ROOT"
    # Branch-aware: `git pull origin main` clobbered checkouts on fix/* or a
    # tag with main. Pull the branch we're actually on, ff-only.
    current_branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo HEAD)
    if [[ "$current_branch" == "HEAD" ]]; then
        warn "Detached HEAD — skipping pull, installing this exact checkout."
    else
        sudo -u parking git pull --ff-only origin "$current_branch" \
            || warn "git pull failed (diverged/local changes) — continuing with existing checkout."
    fi
elif [[ -n "${PARKING_SOURCE_DIR:-}" ]]; then
    # ponytail: plain copy, no updates via git. Re-run from a newer stick to upgrade.
    mkdir -p "$PROJECT_ROOT"
    rsync -a --exclude=.git --exclude=node_modules --exclude=.venv --exclude=.nuxt \
        --exclude=.output --exclude=graphify-out --exclude=__pycache__ \
        "${PARKING_SOURCE_DIR}/" "$PROJECT_ROOT/"
    chown -R parking:parking "$PROJECT_ROOT"
else
    rm -rf "$PROJECT_ROOT"
    git clone "$REPO_URL" "$PROJECT_ROOT"
    chown -R parking:parking "$PROJECT_ROOT"
fi

cd "$PROJECT_ROOT"

# Create virtual environment
if [[ ! -d ".venv" ]]; then
    sudo -u parking python3.12 -m venv .venv
fi

# Install Python dependencies
sudo -u parking .venv/bin/pip install --quiet --upgrade pip
sudo -u parking .venv/bin/pip install --quiet -e .
ok "Python dependencies installed"

# ── 8. Environment file ───────────────────────────────────────────────────────
step "8/12 — Writing Environment Configuration"

# Re-running the installer must NOT rotate secrets: a fresh JWT_SECRET logs
# every operator out, and a fresh INTERNAL_API_KEY 401s every already-enrolled
# booth. Preserve the existing values when an .env is present.
EXISTING_ENV="$PROJECT_ROOT/.env"
if [[ -f "$EXISTING_ENV" ]]; then
    existing_jwt=$(grep -m1 '^JWT_SECRET=' "$EXISTING_ENV" | cut -d= -f2-)
    existing_key=$(grep -m1 '^INTERNAL_API_KEY=' "$EXISTING_ENV" | cut -d= -f2-)
    if [[ -n "$existing_jwt" || -n "$existing_key" ]]; then
        JWT_SECRET=${existing_jwt:-$JWT_SECRET}
        INTERNAL_API_KEY=${existing_key:-$INTERNAL_API_KEY}
        warn "Existing .env found — reusing its JWT_SECRET / INTERNAL_API_KEY (no rotation)."
    fi
fi

ENV_TMP=$(mktemp)
cat > "$ENV_TMP" <<EOF
# Auto-generated by installer/_roles/server/setup.sh on $(date -Iseconds)
# Keys NOT listed as managed below are carried over from the old file.
APP_ENV=production
SERVICE_ROLE=server
DEBUG=false

# Database
DB_HOST=localhost
DB_PORT=5432
DB_NAME=parking
DB_USER=parking
DB_PASSWORD=${DB_PASS}

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0

# Security
JWT_SECRET=${JWT_SECRET}
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30
JWT_REFRESH_TOKEN_EXPIRE_DAYS=7
INTERNAL_API_KEY=${INTERNAL_API_KEY}

# CORS (server + booth PCs on local network)
CORS_ORIGINS=http://localhost:3000,http://${SERVER_IP}:3000
EOF

# Managed keys we regenerate ourselves + legacy keys to DROP (old installs
# wrote DB_POOL_SIZE=20/10 which overrides the safe app defaults 8/4 and can
# exceed Postgres max_connections=100 across gunicorn/ARQ processes).
read -r -a MANAGED_KEYS <<'EOF'
APP_ENV SERVICE_ROLE DEBUG DB_HOST DB_PORT DB_NAME DB_USER DB_PASSWORD REDIS_HOST REDIS_PORT REDIS_DB JWT_SECRET JWT_ALGORITHM JWT_ACCESS_TOKEN_EXPIRE_MINUTES JWT_REFRESH_TOKEN_EXPIRE_DAYS INTERNAL_API_KEY CORS_ORIGINS DB_POOL_SIZE DB_MAX_OVERFLOW
EOF

if [[ -f "$EXISTING_ENV" ]]; then
    preserved=0
    while IFS= read -r line; do
        if [[ "$line" =~ ^([A-Za-z_][A-Za-z0-9_]*)= ]]; then
            key="${BASH_REMATCH[1]}"
            skip=false
            for k in "${MANAGED_KEYS[@]}"; do
                [[ "$key" == "$k" ]] && { skip=true; break; }
            done
            $skip && continue
        fi
        printf '%s\n' "$line" >> "$ENV_TMP"
        preserved=$((preserved + 1))
    done < "$EXISTING_ENV"
    info "Preserved ${preserved} lines from existing .env (TELEGRAM_*, SETTLEMENT_*, tuning, ...)"
fi

mv "$ENV_TMP" "$EXISTING_ENV"
chown parking:parking "$EXISTING_ENV"
chmod 600 "$EXISTING_ENV"
ok ".env written to ${PROJECT_ROOT} (DB pool uses app defaults 8+4)"

# ── 9. Database migrations ──────────────────────────────────────────────────────
step "9/12 — Running Database Migrations"

cd "$PROJECT_ROOT"
sudo -u parking .venv/bin/alembic upgrade head
ok "Alembic migrations applied"

# ── 10. Build frontend ──────────────────────────────────────────────────────────
step "10/12 — Building Frontend"

cd "$PROJECT_ROOT/frontend"
# Always reinstall from the lockfile: a stale node_modules silently keeps old
# dependencies after an upgrade, and a global NODE_ENV=production would omit
# devDependencies (postinstall runs patch-package).
sudo -u parking env -u NODE_ENV npm ci

# Build with empty apiBaseUrl so relative /api/ works through nginx
sudo -u parking bash -c 'NUXT_PUBLIC_API_BASE_URL="" npm run build'
ok "Frontend built"

# ── 11. Install systemd services ────────────────────────────────────────────────
step "11/12 — Installing Systemd Services"

services=(
    "parking-api.service"
    "parking-events.service"
    "parking-frontend.service"
    "parking-worker-critical.service"
    "parking-worker-bg.service"
)

for svc in "${services[@]}"; do
    cp "$PROJECT_ROOT/systemd/$svc" /etc/systemd/system/
    systemctl daemon-reload
    systemctl enable "$svc"
    systemctl start "$svc"
    ok "${svc} installed and started"
done

# Template unit for entry-gate daemons. Instances are enabled per gate by
# scripts/enable-gate-daemons.sh once the gates exist in the database.
cp "$PROJECT_ROOT/systemd/parking-daemon-gate-in@.service" /etc/systemd/system/
ok "Gate daemon template installed"

# Nightly PostgreSQL backup (oneshot service triggered by the timer). The unit
# uses StateDirectory= so the backup directory is created with the right owner.
cp "$PROJECT_ROOT/systemd/parking-backup.service" /etc/systemd/system/
cp "$PROJECT_ROOT/systemd/parking-backup.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now parking-backup.timer
ok "Nightly backup timer installed and started"

# Create app data directories
mkdir -p /var/lib/parking/{snapshots,settlements,logs}
chown -R parking:parking /var/lib/parking

# Short command used throughout the docs. Without this wrapper every doc that
# says `parking-doctor` fails with "command not found".
cat > /usr/local/bin/parking-doctor <<EOF
#!/usr/bin/env bash
set -euo pipefail
cd ${PROJECT_ROOT}
exec ${PROJECT_ROOT}/.venv/bin/python ${PROJECT_ROOT}/scripts/parking_doctor.py "\$@"
EOF
chmod 0755 /usr/local/bin/parking-doctor
ok "parking-doctor command installed (/usr/local/bin/parking-doctor)"

# Admin dashboard shortcut (single shortcut for the server role). Harmless on a
# headless box — it's just a .desktop file the admin double-clicks if a GUI exists.
DESKTOP_DIR="/home/parking/Desktop"
mkdir -p "$DESKTOP_DIR"
cat > "$DESKTOP_DIR/Parking-Admin.desktop" <<EOF
[Desktop Entry]
Name=Parking Admin
Comment=E-Parking Admin Dashboard
Exec=/usr/bin/google-chrome --app=http://localhost/ --no-first-run --no-default-browser-check --disable-infobars
Icon=/usr/share/icons/hicolor/256x256/apps/google-chrome.png
Type=Application
Terminal=false
Categories=Application;
StartupNotify=true
EOF
chmod +x "$DESKTOP_DIR/Parking-Admin.desktop"
chown -R parking:parking "$DESKTOP_DIR"
ok "Admin dashboard shortcut created"

# ── 11b. Drop sudoers rule for setup wizard ────────────────────────────────────
step "11b/12 — Sudoers Drop for Wizard"

cat > /etc/sudoers.d/parking-setup <<EOF
# Allow the parking user to invoke setup wizard helpers without a password.
# Audited by /etc/audit/rules.d if enabled.
parking ALL=(root) NOPASSWD: ${PROJECT_ROOT}/scripts/detect-serial-devices.sh
parking ALL=(root) NOPASSWD: ${PROJECT_ROOT}/scripts/enable-gate-daemons.sh
parking ALL=(root) NOPASSWD: /usr/bin/systemctl start parking-daemon-gate-*
parking ALL=(root) NOPASSWD: /usr/bin/systemctl enable parking-daemon-gate-*
parking ALL=(root) NOPASSWD: /usr/bin/systemctl restart parking-daemon-gate-*
parking ALL=(root) NOPASSWD: /usr/bin/udevadm control --reload-rules
parking ALL=(root) NOPASSWD: /usr/bin/udevadm trigger *
parking ALL=(root) NOPASSWD: /usr/bin/udevadm settle *
EOF
chmod 0440 /etc/sudoers.d/parking-setup
if ! visudo -cf /etc/sudoers.d/parking-setup >/dev/null; then
    error "sudoers drop failed validation; aborting."
    rm -f /etc/sudoers.d/parking-setup
    exit 1
fi
ok "Sudoers drop installed at /etc/sudoers.d/parking-setup"

# ── 11c. Generate one-time setup token ─────────────────────────────────────────
step "11c/12 — Setup Wizard Token"

mkdir -p /etc/parking
# parking-api (User=parking) must be able to unlink the token on redeem
# (unlink checks write on the dir, not the file). Own the dir by parking.
chown parking:parking /etc/parking
chmod 0750 /etc/parking
# Quick mode skips the wizard, so it must not leave a token that implies one.
if ! $QUICK; then
    SETUP_TOKEN=$(openssl rand -hex 32)
    echo -n "$SETUP_TOKEN" > /etc/parking/setup-token
    chown root:parking /etc/parking/setup-token
    chmod 0640 /etc/parking/setup-token
    ok "Token written to /etc/parking/setup-token"
else
    rm -f /etc/parking/setup-token
    ok "Quick mode — no setup wizard token (wizard skipped)"
fi

# Booth enrollment token — booths redeem this at POST /api/setup/enroll to
# fetch INTERNAL_API_KEY + Redis address (no hand-copying). Reusable for 24h.
# 12 hex chars (~48 bits) — short enough to type on a booth PC, protected by
# the 10/min rate limit on /api/setup/enroll.
ENROLL_TOKEN=$(openssl rand -hex 6 | tr 'a-f' 'A-F')
echo -n "$ENROLL_TOKEN" > /etc/parking/enroll-token
chown root:parking /etc/parking/enroll-token
chmod 0640 /etc/parking/enroll-token
ok "Booth enrollment token written to /etc/parking/enroll-token"

# ── 12. Configure nginx ─────────────────────────────────────────────────────────
step "12/12 — Configuring Nginx"

cat > /etc/nginx/sites-available/parking <<'EOF'
server {
    listen 80;
    server_name _;

    # Frontend (Nuxt SSR / static)
    location / {
        proxy_pass http://localhost:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
    }

    # API
    location /api/ {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # WebSocket
    location /ws {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    # Metrics (internal only)
    location /metrics {
        proxy_pass http://localhost:8000;
        allow 127.0.0.1;
        allow 192.168.0.0/16;
        allow 10.0.0.0/8;
        deny all;
    }
}
EOF

rm -f /etc/nginx/sites-enabled/default
ln -sf /etc/nginx/sites-available/parking /etc/nginx/sites-enabled/parking
nginx -t && systemctl restart nginx
ok "Nginx configured and restarted"

# ── Quick provisioning (v1-style one-command setup) ──────────────────────────
if $QUICK; then
    step "Quick provisioning — admin, site, tariff, area, gates"

    QUICK_ARGS=(
        --admin-username "$QUICK_ADMIN_USER"
        --site-name "$QUICK_SITE_NAME"
        --tariff "$QUICK_TARIFF"
        --in-count "$QUICK_IN"
        --out-count "$QUICK_OUT"
        --gate-base-ip "$QUICK_GATE_BASE_IP"
    )

    if [[ -n "$QUICK_ADMIN_PASSWORD_FILE" ]]; then
        TMP_ADMIN_PASSWORD_FILE=$(mktemp /tmp/parking-admin.XXXXXX)
        install -m 600 -o parking -g parking "$QUICK_ADMIN_PASSWORD_FILE" "$TMP_ADMIN_PASSWORD_FILE"
        QUICK_ARGS+=(--admin-password-file "$TMP_ADMIN_PASSWORD_FILE")
    elif [[ -n "$QUICK_ADMIN_PASSWORD" ]]; then
        TMP_ADMIN_PASSWORD_FILE=$(mktemp /tmp/parking-admin.XXXXXX)
        printf '%s' "$QUICK_ADMIN_PASSWORD" > "$TMP_ADMIN_PASSWORD_FILE"
        chown parking:parking "$TMP_ADMIN_PASSWORD_FILE"
        chmod 600 "$TMP_ADMIN_PASSWORD_FILE"
        QUICK_ARGS+=(--admin-password-file "$TMP_ADMIN_PASSWORD_FILE")
    fi

    if sudo -u parking "$PROJECT_ROOT/.venv/bin/python" \
        "$PROJECT_ROOT/scripts/quickstart_provision.py" "${QUICK_ARGS[@]}"; then
        ok "Quick provisioning complete — setup wizard bypassed."
    else
        error "Quick provisioning failed. Site is installed but setup_complete is not set."
        error "Re-run: cd $PROJECT_ROOT && sudo -u parking .venv/bin/python scripts/quickstart_provision.py ${QUICK_ARGS[*]}"
        exit 1
    fi

    if ! $QUICK_NO_DAEMONS; then
        if $QUICK_INCLUDE_LOCAL_SERIAL; then
            bash "$PROJECT_ROOT/scripts/enable-gate-daemons.sh" --run --include-local-serial \
                || warn "Some gate daemons failed to enable — check: systemctl status 'parking-daemon-gate-*'"
        else
            bash "$PROJECT_ROOT/scripts/enable-gate-daemons.sh" --run \
                || warn "Some gate daemons failed to enable — check: systemctl status 'parking-daemon-gate-*'"
        fi
    fi

fi

# ── Post-install verification (HARD GATE) ────────────────────────────────────
# Runs LAST: the banner below never prints unless provisioning succeeded and the
# infrastructure checks pass.
step "Post-install — parking-doctor (infrastructure gate)"
info "Verifying infrastructure: services, DB, Redis, migrations, events consumer, ARQ..."
cd "$PROJECT_ROOT"
if sudo -u parking "$PROJECT_ROOT/.venv/bin/python" "$PROJECT_ROOT/scripts/parking_doctor.py" --infra-only; then
    ok "INSTALL VERIFIED — all infrastructure checks green."
else
    error "INSTALL FAILED VERIFICATION — see the FAIL rows above."
    error "Fix them, then re-run: sudo parking-doctor --infra-only"
    exit 1
fi

# ── Summary (after provisioning — nothing is announced before it ran) ─────────
echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Server installation complete!${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════════════════════════════${NC}"
echo ""
info "Open in a browser:  http://${SERVER_IP}/        (operator/admin page)"
info "API health check:   http://${SERVER_IP}/api/health"
echo ""
if $QUICK; then
    echo "  Username  : ${QUICK_ADMIN_USER}"
    echo "  Password  : sudo cat /etc/parking/install-notes.txt  (mode 0600)"
    echo "  Gates     : ${QUICK_IN} IN + ${QUICK_OUT} OUT (default controller IPs 192.168.1.100+)"
    echo "  Tariff    : ${QUICK_TARIFF}"
    echo "  ↳ Set each gate's real controller IP/port in Device → Gates."
    echo "    Gate daemons already run; they connect once the IPs are correct."
else
    SETUP_URL="http://${SERVER_IP}/setup?token=${SETUP_TOKEN}"
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}  OPEN THIS LINK ON THE INSTALLER LAPTOP TO FINISH CONFIGURATION${NC}"
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo "  ${SETUP_URL}"
    echo ""
    echo "  Token expires when redeemed or after 24h, whichever comes first."
    echo "  Regenerate by re-running this script if you lose it."
fi
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  BOOTH ENROLLMENT (use on each booth PC installer)${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo "  Server IP        : ${SERVER_IP}"
echo "  Enrollment token : ${ENROLL_TOKEN}"
echo ""
echo "  Booths redeem this instead of copying INTERNAL_API_KEY by hand."
echo "  Valid 24h, reusable for every booth. Regenerate: scripts/regen-enroll-token.sh"
echo ""
info "For technicians — service status:"
info "  systemctl status parking-api parking-worker-critical parking-worker-bg"
info "  systemctl status parking-frontend parking-events nginx"
info "Full health report: sudo parking-doctor"

# Auto-launch the wizard in a browser if a desktop session is present.
if ! $QUICK && [[ -n "${DISPLAY:-}" || -n "${WAYLAND_DISPLAY:-}" ]]; then
    BROWSER_CMD=""
    for cand in google-chrome google-chrome-stable chromium chromium-browser firefox xdg-open; do
        if command -v "$cand" &>/dev/null; then
            BROWSER_CMD="$cand"
            break
        fi
    done
    if [[ -n "$BROWSER_CMD" ]]; then
        sudo -u "${SUDO_USER:-parking}" "$BROWSER_CMD" "$SETUP_URL" >/dev/null 2>&1 &
        ok "Launched ${BROWSER_CMD} at ${SETUP_URL}"
    else
        warn "No browser found — open the link above manually on the installer laptop."
    fi
fi
echo ""
