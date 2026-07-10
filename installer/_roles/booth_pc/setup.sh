#!/bin/bash
set -euo pipefail

# ═══════════════════════════════════════════════════════════════════════════════
# E-Parking v2 — Booth PC Installation Script
# ═══════════════════════════════════════════════════════════════════════════════
#
# Two phases so software can be installed in the workshop and the booth wired
# up on-site later:
#   --install-only    Workshop: packages, timezone, user, udev, venv, deps.
#                     Needs no hardware and asks no field questions.
#   --configure-only  Field: device paths, gate code, server key → booth.json,
#                     systemd service, kiosk shortcut.
#   (no flag)         Run both (single-visit install, original behaviour).
#
# Usage:
#   sudo ./setup.sh                  # install + configure
#   sudo ./setup.sh --install-only   # workshop
#   sudo ./setup.sh --configure-only # on-site
# ═══════════════════════════════════════════════════════════════════════════════

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="/opt/parking-system-v2"
# Default to the origin of this checkout so the tech never types the URL.
REPO_URL="$(git -C "$SCRIPT_DIR" remote get-url origin 2>/dev/null || echo "https://github.com/your-org/parking-system-v2.git")"

source "$SCRIPT_DIR/../common.sh"

DO_INSTALL=true
DO_CONFIGURE=true
for arg in "$@"; do
    case "$arg" in
        --install-only)   DO_CONFIGURE=false ;;
        --configure-only) DO_INSTALL=false ;;
        -h|--help)        sed -n '4,22p' "$0"; exit 0 ;;
        *) error "unknown arg: $arg"; exit 2 ;;
    esac
done

# ── 0. Preflight checks ───────────────────────────────────────────────────────
step "Preflight Checks"

if [[ $EUID -ne 0 ]]; then
    error "This script must be run as root (use sudo)"
    exit 1
fi

if ! grep -q "Ubuntu 24.04" /etc/os-release 2>/dev/null; then
    warn "This script targets Ubuntu 24.04 LTS (ships python3.12 natively). Continuing anyway..."
    warn "On 22.04 the python3.12 packages below are NOT in the default repos and install will fail."
    read -rp "Press Enter to continue or Ctrl+C to abort..."
fi

# ═══════════════════════════════════════════════════════════════════════════════
# WORKSHOP PHASE — software only, no hardware, no field questions
# ═══════════════════════════════════════════════════════════════════════════════
phase_install() {
    step "Install 1/4 — System Packages"

    read -rp "Git repository URL [${REPO_URL}]: " INPUT_REPO
    REPO_URL=${INPUT_REPO:-$REPO_URL}
    if [[ "$REPO_URL" == *your-org* ]]; then
        error "REPO_URL is still the placeholder (your-org). Enter the real repository URL."
        exit 1
    fi

    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get upgrade -y -qq

    # Pin timezone (WIB) so booth-stamped events line up with the server's
    # settlement cut.
    APP_TIMEZONE="${APP_TIMEZONE:-Asia/Jakarta}"
    if [[ "$(timedatectl show -p Timezone --value 2>/dev/null || echo "")" != "$APP_TIMEZONE" ]]; then
        timedatectl set-timezone "$APP_TIMEZONE" \
            && ok "Timezone set to ${APP_TIMEZONE}" \
            || warn "Failed to set timezone — set ${APP_TIMEZONE} manually."
    fi

    apt-get install -y -qq \
        python3.12 python3.12-venv python3.12-dev python3-pip \
        curl wget git unzip

    if ! command -v google-chrome &>/dev/null; then
        wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb -O /tmp/chrome.deb
        apt-get install -y -qq /tmp/chrome.deb || apt-get install -fy -qq
        rm -f /tmp/chrome.deb
    fi
    ok "Google Chrome installed"

    step "Install 2/4 — System User"
    if ! id parking &>/dev/null; then
        useradd -r -s /bin/bash -m -d /home/parking parking
    fi
    usermod -aG dialout,input parking
    ok "User 'parking' created (groups: $(groups parking))"

    step "Install 3/4 — udev Rules"
    # Stable group/mode so the parking user can read the Omnikey (input) and
    # write serial relays/readers (dialout) without root. Per-device symlinks
    # are added later by the setup wizard's detect-serial step.
    cat > /etc/udev/rules.d/99-parking.rules <<'EOF'
# Omnikey 5427 CK — HID keyboard mode (0x5427)
KERNEL=="event*", SUBSYSTEM=="input", ATTRS{idVendor}=="076b", ATTRS{idProduct}=="5427", MODE="0660", OWNER="parking", GROUP="input"
# Omnikey 5427 CK — CCID admin mode (0x5428) — diagnostics only
KERNEL=="event*", SUBSYSTEM=="input", ATTRS{idVendor}=="076b", ATTRS{idProduct}=="5428", MODE="0660", OWNER="parking", GROUP="input"
# USB-serial relay / barrier / reader (CH340, FTDI, PL2303)
SUBSYSTEM=="tty", ATTRS{idVendor}=="1a86", MODE="0660", OWNER="parking", GROUP="dialout"
SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", MODE="0660", OWNER="parking", GROUP="dialout"
SUBSYSTEM=="tty", ATTRS{idVendor}=="067b", MODE="0660", OWNER="parking", GROUP="dialout"
EOF
    udevadm control --reload-rules
    udevadm trigger --subsystem-match=input --subsystem-match=tty
    ok "udev rules installed (/etc/udev/rules.d/99-parking.rules)"

    step "Install 4/4 — Application"
    if [[ -d "$PROJECT_ROOT/.git" ]]; then
        warn "Repository already exists. Pulling latest..."
        cd "$PROJECT_ROOT"
        sudo -u parking git pull origin main
    else
        rm -rf "$PROJECT_ROOT"
        git clone "$REPO_URL" "$PROJECT_ROOT"
        chown -R parking:parking "$PROJECT_ROOT"
    fi

    cd "$PROJECT_ROOT"
    if [[ ! -d ".venv" ]]; then
        sudo -u parking python3.12 -m venv .venv
    fi
    sudo -u parking .venv/bin/pip install --quiet --upgrade pip
    # Always full install: booth_bridge's omnikey_poller needs evdev, and the
    # exit-relay path needs protocols/shared.
    sudo -u parking .venv/bin/pip install --quiet -e "$PROJECT_ROOT/"
    ok "Application dependencies installed (booth bridge + Omnikey poller)"

    if ! $DO_CONFIGURE; then
        echo ""
        ok "Workshop install complete. On-site, run: sudo ./setup.sh --configure-only"
    fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# FIELD PHASE — gather site config, write booth.json, install service
# ═══════════════════════════════════════════════════════════════════════════════
phase_configure() {
    if [[ ! -d "$PROJECT_ROOT/.venv" ]]; then
        error "App not installed at ${PROJECT_ROOT} — run sudo ./setup.sh --install-only first."
        exit 1
    fi

    step "Configure 1/4 — Site Configuration"

    read -rp "Server IP address (e.g. 192.168.1.100): " SERVER_IP
    if [[ -z "$SERVER_IP" ]]; then
        error "Server IP is required"
        exit 1
    fi

    # Enroll over the network: the server prints an enrollment token at the end
    # of its install. We redeem it for the INTERNAL_API_KEY + Redis address
    # instead of hand-copying the key (typos there = silent 401 at runtime).
    read -rp "Server enrollment token (printed by the server installer): " ENROLL_TOKEN
    if [[ -z "$ENROLL_TOKEN" ]]; then
        error "Enrollment token is required — get it from the server install summary or run scripts/regen-enroll-token.sh on the server."
        exit 1
    fi

    ENROLL_URL="http://${SERVER_IP}:8000/api/setup/enroll"
    info "Enrolling with ${ENROLL_URL} ..."
    ENROLL_JSON=$(curl -fsS -X POST "$ENROLL_URL" \
        -H "Content-Type: application/json" \
        -d "{\"token\":\"${ENROLL_TOKEN}\"}" 2>/dev/null) || {
        error "Enrollment failed — server unreachable or token invalid (HTTP error from ${ENROLL_URL})."
        error "Check the server IP, that parking-api is up, and the token is current (24h)."
        exit 1
    }

    # Parse the JSON response (no jq dependency).
    INTERNAL_API_KEY=$(python3 -c 'import sys,json; print(json.load(sys.stdin)["internal_api_key"])' <<<"$ENROLL_JSON" 2>/dev/null || true)
    REDIS_HOST_FROM_ENROLL=$(python3 -c 'import sys,json; print(json.load(sys.stdin).get("redis_host",""))' <<<"$ENROLL_JSON" 2>/dev/null || true)
    API_BASE_URL=$(python3 -c 'import sys,json; print(json.load(sys.stdin).get("api_base_url",""))' <<<"$ENROLL_JSON" 2>/dev/null || true)
    if [[ -z "$INTERNAL_API_KEY" ]]; then
        error "Enrollment response had no internal_api_key. Raw response: ${ENROLL_JSON}"
        exit 1
    fi
    ok "Enrolled — received API key + Redis address from server"

    read -rp "Booth name (e.g. Booth 2): " BOOTH_NAME
    BOOTH_NAME=${BOOTH_NAME:-Booth}

    read -rp "Booth code (e.g. BOOTH_02): " BOOTH_CODE
    BOOTH_CODE=${BOOTH_CODE:-BOOTH}

    read -rp "Booth PC IP address (for auto-detection): " BOOTH_IP
    if [[ -z "$BOOTH_IP" ]]; then
        BOOTH_IP=$(hostname -I | awk '{print $1}')
        warn "Auto-detected booth IP: ${BOOTH_IP}"
    fi

    read -rp "Default gate code for this booth (e.g. GOUT-02): " GATE_CODE
    GATE_CODE=${GATE_CODE:-}

    # ── Stable serial device detection ────────────────────────────────────────
    # Instead of guessing /dev/ttyUSB0/1/2 (which renumber on reboot/replug),
    # run the detector: it shows each USB device by chipset, the tech confirms
    # roles, and it writes /dev/parking-{emoney,printer,scanner,gate} symlinks
    # pinned by serial#/USB-port. We then reference those stable names.
    step "Configure 1b/4 — Serial Device Detection"
    DETECT="$PROJECT_ROOT/scripts/detect-serial-devices.sh"
    if [[ -x "$DETECT" ]] || [[ -f "$DETECT" ]]; then
        bash "$DETECT" || warn "Detection exited non-zero — falling back to manual paths where symlinks are missing."
    else
        warn "detect-serial-devices.sh not found — using manual device paths."
    fi

    # resolve_dev <role> <prompt-label> <default-ttyUSB>
    # Prefer the stable symlink the detector created; only ask if it's absent.
    resolve_dev() {
        local role="$1" label="$2" fallback="$3" link="/dev/parking-$1"
        # Status lines go to stderr; only the resolved path goes to stdout so
        # command substitution captures the path alone.
        if [[ -e "$link" ]]; then
            ok "${label}: ${link} (stable symlink)" >&2
            printf '%s' "$link"
            return
        fi
        warn "${label}: no ${link} symlink — enter the device path manually." >&2
        local ans
        read -rp "    ${label} serial device [${fallback}]: " ans </dev/tty
        printf '%s' "${ans:-$fallback}"
    }

    EMONEY_DEV=$(resolve_dev emoney "E-Money reader" /dev/ttyUSB0)
    read -rp "E-Money reader baudrate [38400]: " EMONEY_BAUD
    EMONEY_BAUD=${EMONEY_BAUD:-38400}

    PRINTER_DEV=$(resolve_dev printer "Receipt printer" /dev/ttyUSB1)
    read -rp "Receipt printer baudrate [9600]: " PRINTER_BAUD
    PRINTER_BAUD=${PRINTER_BAUD:-9600}

    SCANNER_DEV=$(resolve_dev scanner "Barcode scanner" /dev/ttyUSB2)
    read -rp "Barcode scanner baudrate [9600]: " SCANNER_BAUD
    SCANNER_BAUD=${SCANNER_BAUD:-9600}

    read -rp "Enable auto-login for operator? [y/N]: " AUTO_LOGIN
    AUTO_LOGIN=${AUTO_LOGIN:-n}

    read -rp "Does this booth PC have a RS232/USB barrier gate (Interface Barrier Gate)? [y/N]: " HAS_SERIAL_GATE
    HAS_SERIAL_GATE=${HAS_SERIAL_GATE:-n}

    SERIAL_GATE_CODE=""
    GATE_DEV="/dev/parking-gate"
    GATE_BAUD=9600
    if [[ "$HAS_SERIAL_GATE" =~ ^[Yy]$ ]]; then
        read -rp "Gate code in DB (e.g. GOUT-02 — must match gate configured with protocol=serial): " SERIAL_GATE_CODE
        if [[ -z "$SERIAL_GATE_CODE" ]]; then
            error "Gate code is required for RS232/USB gate"
            exit 1
        fi
        GATE_DEV=$(resolve_dev gate "Barrier gate" /dev/ttyUSB3)
        read -rp "Barrier gate baudrate [9600]: " GATE_BAUD_INPUT
        GATE_BAUD=${GATE_BAUD_INPUT:-9600}
    fi

    step "Configure 2/4 — Booth Configuration"
    mkdir -p /etc/parking
    chown parking:parking /etc/parking

    cat > /etc/parking/booth.json <<EOF
{
  "name": "${BOOTH_NAME}",
  "code": "${BOOTH_CODE}",
  "ip_address": "${BOOTH_IP}",
  "default_gate_code": "${GATE_CODE}",
  "api_base_url": "${API_BASE_URL:-http://${SERVER_IP}:8000}",
  "api_key": "${INTERNAL_API_KEY}",
  "peripherals": {
    "emoney_reader": {
      "enabled": true,
      "device": "${EMONEY_DEV}",
      "baudrate": ${EMONEY_BAUD}
    },
    "receipt_printer": {
      "enabled": true,
      "device": "${PRINTER_DEV}",
      "baudrate": ${PRINTER_BAUD}
    },
    "barcode_scanner": {
      "enabled": true,
      "device": "${SCANNER_DEV}",
      "baudrate": ${SCANNER_BAUD}
    },
    "running_text": {
      "enabled": false
    }
  }
}
EOF
    chown parking:parking /etc/parking/booth.json
    ok "Booth config written to /etc/parking/booth.json"

    # booth_bridge gate_opener + omnikey_poller reach the server's Redis.
    # Prefer the Redis address the server told us during enrollment.
    REDIS_HOST_EFFECTIVE=${REDIS_HOST_FROM_ENROLL:-$SERVER_IP}
    ENV_FILE="$PROJECT_ROOT/.env"
    if [[ ! -f "$ENV_FILE" ]]; then
        cat > "$ENV_FILE" <<EOF
REDIS_HOST=${REDIS_HOST_EFFECTIVE}
REDIS_PORT=6379
APP_ENV=production
INTERNAL_API_KEY=${INTERNAL_API_KEY}
EOF
        chown parking:parking "$ENV_FILE"
    else
        grep -q "^REDIS_HOST=" "$ENV_FILE" \
            && sed -i "s|^REDIS_HOST=.*|REDIS_HOST=${REDIS_HOST_EFFECTIVE}|" "$ENV_FILE" \
            || echo "REDIS_HOST=${REDIS_HOST_EFFECTIVE}" >> "$ENV_FILE"
        grep -q "^INTERNAL_API_KEY=" "$ENV_FILE" \
            && sed -i "s|^INTERNAL_API_KEY=.*|INTERNAL_API_KEY=${INTERNAL_API_KEY}|" "$ENV_FILE" \
            || echo "INTERNAL_API_KEY=${INTERNAL_API_KEY}" >> "$ENV_FILE"
    fi
    ok "REDIS_HOST set to ${REDIS_HOST_EFFECTIVE} in ${ENV_FILE}"

    NOTES_FILE="/etc/parking/install-notes.txt"
    cat > "$NOTES_FILE" <<EOF
E-Parking v2 — Installation Notes
Generated: $(date)
════════════════════════════════════════

BOOTH: ${BOOTH_NAME} (${BOOTH_CODE})
  Default gate : ${GATE_CODE}
  Server IP    : ${SERVER_IP}
  Booth IP     : ${BOOTH_IP}

PERIPHERALS:
  E-Money reader : ${EMONEY_DEV}  (${EMONEY_BAUD} baud)
  Receipt printer: ${PRINTER_DEV}  (${PRINTER_BAUD} baud)
  Barcode scanner: ${SCANNER_DEV}  (${SCANNER_BAUD} baud)
EOF
    if [[ "$HAS_SERIAL_GATE" =~ ^[Yy]$ && -n "$SERIAL_GATE_CODE" ]]; then
        cat >> "$NOTES_FILE" <<EOF

BARRIER GATE (${SERIAL_GATE_CODE}):
  Connection type  : serial (RS232/USB)
  Serial device    : ${GATE_DEV}  (${GATE_BAUD} baud)

  ↳ In admin UI → Device → Gates → ${SERIAL_GATE_CODE}, set:
      protocol           = serial
      controller_device  = ${GATE_DEV}
      controller_baudrate= ${GATE_BAUD}
EOF
    fi
    cat >> "$NOTES_FILE" <<EOF

════════════════════════════════════════
View anytime: cat ${NOTES_FILE}
EOF
    chown parking:parking "$NOTES_FILE"
    ok "Install notes written to ${NOTES_FILE}"

    step "Configure 3/4 — Booth Bridge Service"
    SERVICE_FILE="/etc/systemd/system/booth-bridge-${BOOTH_CODE,,}.service"
    cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Parking Booth Bridge — ${BOOTH_NAME}
After=network.target

[Service]
Type=simple
User=parking
Group=parking
SupplementaryGroups=dialout input
WorkingDirectory=${PROJECT_ROOT}
Environment=PYTHONPATH=${PROJECT_ROOT}
Environment=APP_ENV=production
ExecStart=${PROJECT_ROOT}/.venv/bin/python -m booth_bridge.main --config /etc/parking/booth.json --port 5678
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=booth-bridge-${BOOTH_CODE,,}

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable "$(basename "$SERVICE_FILE")"
    systemctl start "$(basename "$SERVICE_FILE")"
    ok "Booth bridge service installed and started"

    # Exit lanes have NO daemon (gate_out removed in f4a3eb0). booth_bridge's
    # gate_opener drives the local relay directly.
    if [[ "$HAS_SERIAL_GATE" =~ ^[Yy]$ && -n "$SERIAL_GATE_CODE" ]]; then
        ok "Exit gate ${SERIAL_GATE_CODE} on ${GATE_DEV} — driven by booth-bridge (no daemon)."
        info "Set this gate's controller_device=${GATE_DEV} in the DB / setup wizard."
    fi

    step "Configure 4/4 — Kiosk Shortcut + Auto-Login"
    DESKTOP_FILE="/home/parking/Desktop/Parking-POS.desktop"
    mkdir -p "$(dirname "$DESKTOP_FILE")"
    cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Name=Parking POS
Comment=E-Parking POS System
Exec=/usr/bin/google-chrome --app=http://${SERVER_IP}/pos --start-fullscreen --no-first-run --no-default-browser-check --kiosk --disable-infobars
Icon=/usr/share/icons/hicolor/256x256/apps/google-chrome.png
Type=Application
Terminal=false
Categories=Application;
StartupNotify=true
EOF
    chmod +x "$DESKTOP_FILE"
    chown -R parking:parking "$(dirname "$DESKTOP_FILE")"
    ok "Desktop shortcut created for user 'parking'"

    for user_dir in /home/*; do
        [[ -d "$user_dir" ]] || continue
        username=$(basename "$user_dir")
        [[ "$username" == "parking" ]] && continue
        mkdir -p "$user_dir/Desktop"
        cp "$DESKTOP_FILE" "$user_dir/Desktop/Parking-POS.desktop"
        chown "$username:$username" "$user_dir/Desktop/Parking-POS.desktop"
        ok "Desktop shortcut copied for user '$username'"
    done

    if [[ "$AUTO_LOGIN" =~ ^[Yy]$ ]]; then
        if [[ -f /etc/gdm3/custom.conf ]]; then
            sed -i 's/^#*AutomaticLoginEnable=.*/AutomaticLoginEnable=true/' /etc/gdm3/custom.conf
            sed -i 's/^#*AutomaticLogin=.*/AutomaticLogin=parking/' /etc/gdm3/custom.conf
            ok "GDM auto-login configured for user 'parking'"
        elif [[ -d /etc/lightdm ]]; then
            mkdir -p /etc/lightdm/lightdm.conf.d
            cat > /etc/lightdm/lightdm.conf.d/50-autologin.conf <<EOF
[Seat:*]
autologin-user=parking
autologin-user-timeout=0
EOF
            ok "LightDM auto-login configured for user 'parking'"
        else
            warn "Unknown display manager. Auto-login not configured."
        fi
    else
        info "Auto-login skipped"
    fi

    # ── Summary ──────────────────────────────────────────────────────────────
    echo ""
    echo -e "${GREEN}═══════════════════════════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  Booth PC configuration complete!${NC}"
    echo -e "${GREEN}═══════════════════════════════════════════════════════════════════════════════${NC}"
    echo ""
    info "Booth:      ${BOOTH_NAME} (${BOOTH_CODE})"
    info "Server:     http://${SERVER_IP}"
    info "Local WS:   ws://localhost:5678"
    info "Serial dev: ${EMONEY_DEV}, ${PRINTER_DEV}, ${SCANNER_DEV}"
    if [[ "$HAS_SERIAL_GATE" =~ ^[Yy]$ ]]; then
        info "Gate dev:   ${GATE_DEV} (baudrate: ${GATE_BAUD}) → gate ${SERIAL_GATE_CODE}"
    fi
    echo ""
    warn "Next steps:"
    echo "  1. Verify booth bridge: sudo journalctl -u $(basename "$SERVICE_FILE") -f"
    echo "  2. Verify serial devices: ls -la /dev/parking-*"
    if [[ "$HAS_SERIAL_GATE" =~ ^[Yy]$ && -n "$SERIAL_GATE_CODE" ]]; then
        echo "  3. Verify exit relay via booth-bridge: sudo journalctl -u $(basename "$SERVICE_FILE") -f"
        echo "     ↳ Gate must be configured in DB with protocol=serial, controller_device=${GATE_DEV}"
    else
        echo "  3. On the SERVER, ensure TCP gate daemons are running:"
        echo "       cd /opt/parking-system-v2 && ./scripts/enable-gate-daemons.sh --run"
    fi
    echo "  4. On the SERVER admin page, ensure POS record exists:"
    echo "       Name: ${BOOTH_NAME} | Code: ${BOOTH_CODE} | IP: ${BOOTH_IP} | Default Gate: ${GATE_CODE}"
    echo "  5. Open Chrome shortcut — POS should auto-detect this booth"
    echo "  6. Test e-money reader tap and receipt printer"
    echo ""

    # ── Post-install diagnostic ────────────────────────────────────────────────
    step "Post-install — parking-doctor (booth checks)"
    info "Verifying serial symlinks + server reachability (non-fatal)..."
    sudo -u parking "$PROJECT_ROOT/.venv/bin/python" "$PROJECT_ROOT/scripts/parking_doctor.py" --booth \
        || warn "parking-doctor flagged issues above — fix before handing the booth over."
    echo ""
}

if $DO_INSTALL; then phase_install; fi
if $DO_CONFIGURE; then phase_configure; fi
