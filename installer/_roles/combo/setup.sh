#!/bin/bash
set -euo pipefail

# ═══════════════════════════════════════════════════════════════════════════════
# E-Parking v2 — Server + Booth Combo Installation Script
# ═══════════════════════════════════════════════════════════════════════════════
#
# This script installs the full server stack AND configures the local machine
# as Booth 1 (the booth physically connected to this server PC).
#
# Use case: Small parking lots where the server PC is also the operator station
#           for one of the exit gates.
#
# Topology (2 IN + 2 OUT):
#   Server PC (this machine)  → Booth 1 (local) + Gate In 1 + Gate In 2 + Gate Out 1
#   Booth PC 2 (separate)     → Booth 2 (remote) + Gate Out 2
#
# Usage:
#   sudo ./setup.sh
#
# ═══════════════════════════════════════════════════════════════════════════════

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

source "$SCRIPT_DIR/../common.sh"

NON_INTERACTIVE=false
QUICK=false
GATE_CODE_FLAG=""
EMONEY_INIT_KEY_HEX="${EMONEY_INIT_KEY:-}"
SERVER_EXTRA=()
# Accept both `--flag=value` and `--flag value` (docs use the spaced form).
while [[ $# -gt 0 ]]; do
    case "$1" in
        --non-interactive) NON_INTERACTIVE=true ;;
        --quick) QUICK=true; NON_INTERACTIVE=true ;;
        --gate-code) GATE_CODE_FLAG="${2:-}"; shift ;;
        --gate-code=*) GATE_CODE_FLAG="${1#*=}" ;;
        --emoney-init-key) EMONEY_INIT_KEY_HEX="${2:-}"; shift ;;
        --emoney-init-key=*) EMONEY_INIT_KEY_HEX="${1#*=}" ;;
        # Server quick-mode options are passed through to the server installer
        # instead of being rejected here.
        --topology) SERVER_EXTRA+=("--topology=${2:-}"); shift ;;
        --topology=*) SERVER_EXTRA+=("$1") ;;
        --tariff) SERVER_EXTRA+=("--tariff=${2:-}"); shift ;;
        --tariff=*) SERVER_EXTRA+=("$1") ;;
        --site-name) SERVER_EXTRA+=("--site-name=${2:-}"); shift ;;
        --site-name=*) SERVER_EXTRA+=("$1") ;;
        --admin-user) SERVER_EXTRA+=("--admin-user=${2:-}"); shift ;;
        --admin-user=*) SERVER_EXTRA+=("$1") ;;
        --admin-password) SERVER_EXTRA+=("--admin-password=${2:-}"); shift ;;
        --admin-password=*) SERVER_EXTRA+=("$1") ;;
        --admin-password-file) SERVER_EXTRA+=("--admin-password-file=${2:-}"); shift ;;
        --admin-password-file=*) SERVER_EXTRA+=("$1") ;;
        --gate-base-ip) SERVER_EXTRA+=("--gate-base-ip=${2:-}"); shift ;;
        --gate-base-ip=*) SERVER_EXTRA+=("$1") ;;
        --no-daemons) SERVER_EXTRA+=("$1") ;;
        --include-local-serial) SERVER_EXTRA+=("$1") ;;
        -h|--help) sed -n '6,20p' "$0"; exit 0 ;;
        *) error "unknown arg: $1"; exit 2 ;;
    esac
    shift
done

# Quick combo: default local lane is the first exit gate provisioned by the
# server quick preset (1 IN + 1 OUT).
if $QUICK && [[ -z "$GATE_CODE_FLAG" ]]; then
    GATE_CODE_FLAG="GOUT-01"
fi

# ── 0. Preflight ────────────────────────────────────────────────────────────────
step "0/2 — Preflight Checks"

if [[ $EUID -ne 0 ]]; then
    error "This script must be run as root (use sudo)"
    exit 1
fi

SERVER_IP=$(hostname -I | awk '{print $1}')
info "Detected server IP: ${SERVER_IP}"
info "This script will:"
echo "  1. Install the full server stack (PostgreSQL, Redis, API, nginx)"
echo "  2. Configure this PC as Booth 1 with local serial devices"
echo ""
if ! $NON_INTERACTIVE; then
    read -rp "Press Enter to continue or Ctrl+C to abort..."
fi

# ── 1. Run server installer ─────────────────────────────────────────────────────
step "1/2 — Installing Server Stack"

SERVER_SETUP="${SCRIPT_DIR}/../server/setup.sh"
if [[ ! -f "$SERVER_SETUP" ]]; then
    error "Server installer not found at: ${SERVER_SETUP}"
    exit 1
fi

# Pass through (e.g. --non-interactive/--quick) so both halves behave identically,
# plus any server quick-mode options (--topology/--tariff/--site-name/...).
SERVER_ARGS=()
$NON_INTERACTIVE && SERVER_ARGS+=(--non-interactive)
$QUICK && SERVER_ARGS+=(--quick)
SERVER_ARGS+=("${SERVER_EXTRA[@]}")
bash "$SERVER_SETUP" "${SERVER_ARGS[@]}"
ok "Server installation complete"

# ── 2. Run local booth installer ────────────────────────────────────────────────
step "2/2 — Configuring Local Booth (Booth 1)"

info "Now configuring this PC as Booth 1..."
echo ""

# Gather booth-specific config
if $NON_INTERACTIVE; then
    BOOTH_NAME="Booth 1"
    BOOTH_CODE="BOOTH_01"
    GATE_CODE="$GATE_CODE_FLAG"
    if [[ -z "$GATE_CODE" ]]; then
        error "--non-interactive requires --gate-code=GOUT-01 (default gate for Booth 1)"
        exit 1
    fi
else
    read -rp "Booth 1 name [Booth 1]: " BOOTH_NAME
    BOOTH_NAME=${BOOTH_NAME:-Booth 1}

    read -rp "Booth 1 code [BOOTH_01]: " BOOTH_CODE
    BOOTH_CODE=${BOOTH_CODE:-BOOTH_01}

    read -rp "Default gate for Booth 1 (e.g. GOUT-01): " GATE_CODE
    if [[ -z "$GATE_CODE" ]]; then
        error "Default gate code is required"
        exit 1
    fi
fi

# Codes feed a systemd unit filename and a JSON heredoc — reject anything
# that would break either (quotes, spaces, slashes).
validate_code() {
    if [[ ! "$2" =~ ^[A-Za-z0-9_-]+$ ]]; then
        error "$1 must be alphanumeric/dash/underscore only (got: '$2')"
        exit 1
    fi
}
validate_code "Booth code" "$BOOTH_CODE"
validate_code "Gate code" "$GATE_CODE"

# ── Stable serial device detection ────────────────────────────────────────────
# Pin /dev/parking-{emoney,printer,scanner,gate} symlinks by serial#/USB-port
# instead of guessing /dev/ttyUSB0/1/2 (which renumber on reboot).
step "Detecting serial devices"
DETECT="/opt/parking-system-v2/scripts/detect-serial-devices.sh"
if [[ -f "$DETECT" ]]; then
    if $NON_INTERACTIVE; then
        CANDIDATES=$(bash "$DETECT" --json 2>/dev/null || echo '{"candidates":[]}')
        ASSIGNMENTS=$(printf '%s' "$CANDIDATES" | python3 -c 'import sys,json; [print(c.get("suggested_role","")+"|"+c.get("port","")) for c in json.load(sys.stdin).get("candidates",[]) if c.get("suggested_role")]' 2>/dev/null || true)
        while IFS='|' read -r role port; do
            [[ -z "$role" || -z "$port" ]] && continue
            bash "$DETECT" --write-udev "$role" "$port" >/dev/null 2>&1 \
                && ok "Stable symlink /dev/parking-${role} → ${port}" \
                || warn "Could not create /dev/parking-${role} for ${port} — using manual path."
        done <<< "$ASSIGNMENTS"
    else
        bash "$DETECT" || warn "Detection exited non-zero — falling back to manual paths where symlinks are missing."
    fi
else
    warn "detect-serial-devices.sh not found — using manual device paths."
fi

# resolve_dev <role> <label> <default-ttyUSB>: prefer stable symlink, else ask.
resolve_dev() {
    local role="$1" label="$2" fallback="$3" link="/dev/parking-$1"
    # Status lines go to stderr; only the resolved path goes to stdout so
    # command substitution captures the path alone.
    if [[ -e "$link" ]]; then
        ok "${label}: ${link} (stable symlink)" >&2
        printf '%s' "$link"
        return
    fi
    if $NON_INTERACTIVE; then
        warn "${label}: no ${link} symlink — using ${fallback} (configure later)." >&2
        printf '%s' "$fallback"
        return
    fi
    warn "${label}: no ${link} symlink — enter the device path manually." >&2
    local ans
    read -rp "    ${label} serial device [${fallback}]: " ans </dev/tty
    printf '%s' "${ans:-$fallback}"
}

EMONEY_DEV=$(resolve_dev emoney "E-Money reader" /dev/ttyUSB0)
PRINTER_DEV=$(resolve_dev printer "Receipt printer" /dev/ttyUSB1)
SCANNER_DEV=$(resolve_dev scanner "Barcode scanner" /dev/ttyUSB2)

EMONEY_BAUD=38400
PRINTER_BAUD=9600
SCANNER_BAUD=9600
GATE_TYPE="tcp"
GATE_DEV=""
GATE_BAUD=9600
AUTO_LOGIN="n"

if ! $NON_INTERACTIVE; then
    read -rp "E-Money reader baudrate [38400]: " EMONEY_BAUD_IN
    EMONEY_BAUD=${EMONEY_BAUD_IN:-38400}
    read -rp "Receipt printer baudrate [9600]: " PRINTER_BAUD_IN
    PRINTER_BAUD=${PRINTER_BAUD_IN:-9600}
    read -rp "Barcode scanner baudrate [9600]: " SCANNER_BAUD_IN
    SCANNER_BAUD=${SCANNER_BAUD_IN:-9600}

    read -rp "Barrier gate connection type (tcp/serial) [tcp]: " GATE_TYPE_IN
    GATE_TYPE=${GATE_TYPE_IN:-tcp}
    if [[ "$GATE_TYPE" == "serial" ]]; then
        GATE_DEV=$(resolve_dev gate "Barrier gate" /dev/ttyUSB3)
        read -rp "Barrier gate baudrate [9600]: " GATE_BAUD_INPUT
        GATE_BAUD=${GATE_BAUD_INPUT:-9600}
    fi

    read -rp "Enable auto-login for operator? [y/N]: " AUTO_LOGIN_IN
    AUTO_LOGIN=${AUTO_LOGIN_IN:-n}
fi

PROJECT_ROOT="/opt/parking-system-v2"

# server/setup.sh generated INTERNAL_API_KEY in its own shell and wrote it to
# .env. Read it back so booth.json's api_key matches what the API expects.
INTERNAL_API_KEY=$(grep -m1 '^INTERNAL_API_KEY=' "$PROJECT_ROOT/.env" | cut -d= -f2-)
if [[ -z "$INTERNAL_API_KEY" ]]; then
    error "INTERNAL_API_KEY not found in ${PROJECT_ROOT}/.env — server install incomplete."
    exit 1
fi

# Base udev rules — Omnikey RFID (input) + serial relay/readers (dialout).
# Per-device symlinks are added later by the wizard's detect-serial step.
cat > /etc/udev/rules.d/99-parking.rules <<'EOF'
KERNEL=="event*", SUBSYSTEM=="input", ATTRS{idVendor}=="076b", ATTRS{idProduct}=="5427", MODE="0660", OWNER="parking", GROUP="input"
KERNEL=="event*", SUBSYSTEM=="input", ATTRS{idVendor}=="076b", ATTRS{idProduct}=="5428", MODE="0660", OWNER="parking", GROUP="input"
SUBSYSTEM=="tty", ATTRS{idVendor}=="1a86", MODE="0660", OWNER="parking", GROUP="dialout"
SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", MODE="0660", OWNER="parking", GROUP="dialout"
SUBSYSTEM=="tty", ATTRS{idVendor}=="067b", MODE="0660", OWNER="parking", GROUP="dialout"
EOF
udevadm control --reload-rules
udevadm trigger --subsystem-match=input --subsystem-match=tty
ok "udev rules installed (/etc/udev/rules.d/99-parking.rules)"

# Write booth config
mkdir -p /etc/parking
chown parking:parking /etc/parking

cat > /etc/parking/booth.json <<EOF
{
  "name": "${BOOTH_NAME}",
  "code": "${BOOTH_CODE}",
  "ip_address": "${SERVER_IP}",
  "default_gate_code": "${GATE_CODE}",
  "api_base_url": "${API_BASE_URL:-http://localhost:8000}",
  "api_key": "${INTERNAL_API_KEY}",
  "peripherals": {
    "emoney_reader": {
      "enabled": true,
      "device": "${EMONEY_DEV}",
      "baudrate": ${EMONEY_BAUD},
      "init_key": "${EMONEY_INIT_KEY_HEX}"
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
ok "Booth config written"

# Self-register the POS row (idempotent) so heartbeat works immediately.
info "Registering booth '${BOOTH_CODE}' with the local server..."
REGISTER_BODY=$(printf '{"booth_code":"%s","name":"%s","ip_address":"%s","default_gate_code":"%s"}' \
    "$BOOTH_CODE" "$BOOTH_NAME" "$SERVER_IP" "$GATE_CODE")
if REGISTER_JSON=$(curl -fsS -X POST "http://localhost/api/pos/register" \
    -H "Content-Type: application/json" \
    -H "X-API-Key: ${INTERNAL_API_KEY}" \
    -d "$REGISTER_BODY" 2>/dev/null); then
    ok "Booth registered with the server"
    REGISTERED_GATE=$(python3 -c 'import sys,json; print(json.load(sys.stdin).get("default_gate_id") or "")' <<<"$REGISTER_JSON" 2>/dev/null || true)
    [[ -z "$REGISTERED_GATE" ]] && warn "Gate '${GATE_CODE}' not found on server — assign it in Device → POS."
else
    warn "Booth self-registration failed — add the POS row manually in the admin UI."
fi

# Write install notes for technician reference. On a combo install the server
# quick-provision step already wrote admin credentials here — append, never
# overwrite them.
NOTES_FILE="/etc/parking/install-notes.txt"
if [[ -f "$NOTES_FILE" ]]; then
    printf '\n\n══ Booth configuration ══\n' >> "$NOTES_FILE"
else
    cat > "$NOTES_FILE" <<EOF
E-Parking v2 — Installation Notes
Generated: $(date)
════════════════════════════════════════
EOF
fi
cat >> "$NOTES_FILE" <<EOF

BOOTH: ${BOOTH_NAME} (${BOOTH_CODE})
  Default gate : ${GATE_CODE}
  POS IP       : ${SERVER_IP}

PERIPHERALS:
  E-Money reader : ${EMONEY_DEV}  (${EMONEY_BAUD} baud)
  Receipt printer: ${PRINTER_DEV}  (${PRINTER_BAUD} baud)
  Barcode scanner: ${SCANNER_DEV}  (${SCANNER_BAUD} baud)

BARRIER GATE (${GATE_CODE}):
  Connection type: ${GATE_TYPE}
EOF

if [[ "$GATE_TYPE" == "serial" ]]; then
    cat >> "$NOTES_FILE" <<EOF
  Serial device  : ${GATE_DEV}  (${GATE_BAUD} baud)

  ↳ In admin UI → Device → Gates → ${GATE_CODE}, set:
      protocol         = serial
      controller_device= ${GATE_DEV}
      controller_baudrate= ${GATE_BAUD}
EOF
    if [[ -n "$(ls /dev/parking-rfid 2>/dev/null || true)" ]]; then
        cat >> "$NOTES_FILE" <<EOF

  RFID (serial gate — Wiegand not available):
    Since this gate has no Wiegand port, RFID requires a direct serial reader.
    In admin UI → Device → Gates → ${GATE_CODE} → hardware_config:
      rfid.enabled          = true
      rfid.connection       = direct_serial
      rfid.device           = /dev/parking-rfid
EOF
    fi
else
    cat >> "$NOTES_FILE" <<EOF
  TCP controller IP and port configured during server install.
EOF
fi

cat >> "$NOTES_FILE" <<EOF

════════════════════════════════════════
View anytime: cat ${NOTES_FILE}
EOF

chown parking:parking "$NOTES_FILE"
ok "Install notes written to ${NOTES_FILE}"

# Install booth bridge service
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

# Entry-gate daemons were enabled by the server quick install for TCP gates.
# A serial barrier gate lives on THIS machine, so include local serial now.
if [[ "$GATE_TYPE" == "serial" ]]; then
    info "Enabling the local serial gate daemon (${GATE_CODE})..."
    bash /opt/parking-system-v2/scripts/enable-gate-daemons.sh --run --include-local-serial \
        || warn "Serial gate daemon not enabled — run: sudo /opt/parking-system-v2/scripts/enable-gate-daemons.sh --run --include-local-serial"
fi

# Combo gets TWO shortcuts: an admin dashboard (normal window, admin logs in)
# and a booth POS (kiosk, auto-entry). Both target this PC's local server.
DESKTOP_DIR="/home/parking/Desktop"
mkdir -p "$DESKTOP_DIR"

# 1) Admin dashboard — normal window so admin can log in and navigate.
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

# 2) Booth POS — kiosk, deep-linked to /pos for auto-entry.
cat > "$DESKTOP_DIR/Parking-POS.desktop" <<EOF
[Desktop Entry]
Name=Parking POS
Comment=E-Parking POS (Booth)
Exec=/usr/bin/google-chrome --app=http://localhost/pos --start-fullscreen --no-first-run --no-default-browser-check --kiosk --disable-infobars
Icon=/usr/share/icons/hicolor/256x256/apps/google-chrome.png
Type=Application
Terminal=false
Categories=Application;
StartupNotify=true
EOF

chmod +x "$DESKTOP_DIR/Parking-Admin.desktop" "$DESKTOP_DIR/Parking-POS.desktop"
chown -R parking:parking "$DESKTOP_DIR"
ok "Desktop shortcuts created (Parking-Admin + Parking-POS)"

# Auto-login (optional)
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
    fi
fi

# ── Summary ─────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Server + Booth 1 installation complete!${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════════════════════════════${NC}"
echo ""
info "Server:     http://${SERVER_IP}"
info "Local POS:  http://localhost (kiosk mode)"
info "API:        http://${SERVER_IP}/api"
info "Booth:      ${BOOTH_NAME} (${BOOTH_CODE}) → ${GATE_CODE}"
echo ""
info "All services:"
info "  systemctl status parking-api"
info "  systemctl status parking-worker-critical"
info "  systemctl status parking-worker-bg"
info "  systemctl status $(basename "$SERVICE_FILE")"
info "  systemctl status nginx"
echo ""
info "Install notes: cat /etc/parking/install-notes.txt"
echo ""
warn "Next steps:"
echo "  1. Log in as admin at http://${SERVER_IP}/  (password: cat /etc/parking/install-notes.txt)"
if $QUICK; then
    echo "  2. Gate rows already exist — Device → Gates: set each controller IP/port"
    echo "  3. POS ${BOOTH_CODE} already registered and linked to ${GATE_CODE}"
else
    echo "  2. Device → Gates: add gate rows (codes such as GIN-01 / GOUT-01)"
    echo "  3. Device → POS: add ${BOOTH_CODE} (IP ${SERVER_IP}) and link it to ${GATE_CODE}"
fi
if [[ "$GATE_TYPE" == "serial" ]]; then
    echo "     ↳ RS232/USB gate ${GATE_CODE}: protocol=serial, controller_device=${GATE_DEV}"
else
    echo "     ↳ TCP controllers: protocol=compass, controller IP/port per gate"
fi
echo "  4. Open the Parking POS shortcut on this PC to test Booth 1"
echo "  5. Booth PC 2: sudo ./install.sh --booth --server-ip ${SERVER_IP} \\"
echo "       --token $(cat /etc/parking/enroll-token 2>/dev/null || echo '<enroll-token>')"
if $QUICK; then
    echo "  Gate daemons: already enabled by the server install —"
    echo "       systemctl status 'parking-daemon-gate-*'"
    echo "     (re-enable anytime: sudo /opt/parking-system-v2/scripts/enable-gate-daemons.sh --run)"
else
    echo "  6. Start gate daemons (reads gate config from the database):"
    if [[ "$GATE_TYPE" == "serial" ]]; then
        echo "       sudo /opt/parking-system-v2/scripts/enable-gate-daemons.sh --run --include-local-serial"
        echo "     ↳ --include-local-serial also enables the RS232/USB gate on this machine"
    else
        echo "       sudo /opt/parking-system-v2/scripts/enable-gate-daemons.sh --run"
    fi
fi
echo ""

# ── Post-install verification (HARD GATE) ────────────────────────────────────
step "Post-install — parking-doctor (infrastructure gate)"
cd "$PROJECT_ROOT"
if sudo -u parking "${PROJECT_ROOT}/.venv/bin/python" "${PROJECT_ROOT}/scripts/parking_doctor.py" --infra-only; then
    ok "INSTALL VERIFIED — infrastructure checks green (gates/POS configured in the wizard, steps above)."
else
    error "INSTALL FAILED VERIFICATION — see the FAIL rows above."
    error "Fix them, then re-run: cd $PROJECT_ROOT && sudo -u parking .venv/bin/python scripts/parking_doctor.py --infra-only"
    exit 1
fi
echo ""
