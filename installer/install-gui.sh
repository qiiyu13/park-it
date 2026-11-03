#!/usr/bin/env bash
# E-Parking v2 click-through installer (flashdisk / double-click).
#
#   ./install-gui.sh                  # GUI: Agree -> pick role -> progress -> setup wizard opens
#   ./install-gui.sh --auto combo     # no GUI (first-boot / ISO autoinstall)
#   ./install-gui.sh --auto booth --server-ip=IP --token=TOKEN [--booth-code=.. --gate-code=..]
#
# Installs from THIS checkout (PARKING_SOURCE_DIR), not git, then runs the
# normal role installer, which ends with the parking-doctor hard gate.
# Needs internet for apt/npm/pip until the offline bundle exists.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG=/var/log/parking-install.log
TITLE="E-Parking Installer"

AUTO=false
ROLE=""
EXTRA=()
if [[ "${1:-}" == "--auto" ]]; then
    AUTO=true
    ROLE="${2:?usage: --auto server|booth|combo [role flags]}"
    shift 2
    EXTRA=("$@")
fi

# ── Root (GUI keeps the user's display) ──────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    exec pkexec env DISPLAY="${DISPLAY:-:0}" XAUTHORITY="${XAUTHORITY:-$HOME/.Xauthority}" \
        INVOKER="${USER}" "$0" "$@"
fi
INVOKER="${INVOKER:-${SUDO_USER:-parking}}"

run_setup() {
    # GUI path is the technician quick install: one command, defaults, no
    # wizard. Advanced installs stay available from the CLI.
    PARKING_SOURCE_DIR="$(dirname "$HERE")" "$HERE/setup.sh" \
        --role "$ROLE" --non-interactive --quick "${EXTRA[@]}"
}

open_wizard() {
    # setup-token is minted by the server installer; booth has none (no wizard).
    [[ "$ROLE" == "booth" || ! -r /etc/parking/setup-token ]] && return 0
    local url="http://localhost/setup?token=$(cat /etc/parking/setup-token)"
    if [[ -n "${DISPLAY:-}" ]]; then
        sudo -u "$INVOKER" -i env DISPLAY="$DISPLAY" XAUTHORITY="${XAUTHORITY:-}" \
            nohup google-chrome --no-first-run "$url" >/dev/null 2>&1 &
    fi
    echo "Setup wizard: $url"
}

if $AUTO; then
    run_setup 2>&1 | tee -a "$LOG"
    open_wizard
    exit 0
fi

# ── GUI ──────────────────────────────────────────────────────────────────────
command -v zenity >/dev/null || { apt-get update -qq && apt-get install -y -qq zenity; }

TERMS="This installer will set up the E-Parking system on THIS computer:

  • install PostgreSQL, Redis, nginx, Python, Node.js and Google Chrome
  • create a 'parking' system user and the /opt/parking-system-v2 folder
  • generate random passwords and keys for this site
  • register system services that start automatically on boot

An internet connection is required. It takes about 10-20 minutes.
Do not turn off the computer while it runs.

At the end, this window shows the Admin URL, username, password and
booth enrollment code. Save them before closing."

zenity --text-info --title="$TITLE" --width=560 --height=380 \
    --checkbox="I agree to the above" --ok-label="Next" --cancel-label="Cancel" \
    <<<"$TERMS" || exit 0

ROLE=$(zenity --list --radiolist --title="$TITLE" --width=560 --height=300 \
    --text="What is this computer for?" --ok-label="Next" \
    --column="" --column="Role" --column="Description" \
    TRUE  combo  "Single PC: server + booth 1 (small parking lot)" \
    FALSE server "Server only (database, API, admin dashboard)" \
    FALSE booth  "Booth PC only (connects to an existing server)") || exit 0

if [[ "$ROLE" == "booth" ]]; then
    IFS='|' read -r SRV TOK < <(zenity --forms --title="$TITLE" --text="Connect to the server" \
        --add-entry="Server IP address" --add-entry="Enrollment token (shown on the server)") || exit 0
    [[ -n "$SRV" && -n "$TOK" ]] || { zenity --error --text="Server IP and token are required."; exit 1; }
    EXTRA=("--server-ip=$SRV" "--token=$TOK")
fi

set +e
{ run_setup 2>&1 | tee -a "$LOG" | sed -u 's/\x1b\[[0-9;]*m//g; s/^/#/'; exit "${PIPESTATUS[0]}"; } \
    | zenity --progress --pulsate --no-cancel --auto-close --width=560 \
        --title="$TITLE" --text="Installing… please wait"
rc=${PIPESTATUS[0]}
set -e

if [[ $rc -ne 0 ]]; then
    zenity --error --width=560 --title="$TITLE" \
        --text="Installation failed.\n\nSend this file to support:\n$LOG\n\nLast lines:\n$(tail -n 8 "$LOG" | sed 's/\x1b\[[0-9;]*m//g')"
    exit "$rc"
fi

if [[ -r /etc/parking/install-notes.txt ]]; then
    zenity --text-info --title="Install complete — save these details" \
        --filename=/etc/parking/install-notes.txt \
        --width=680 --height=560 \
        --checkbox="I have saved the admin credentials and booth code" \
        --ok-label="Finish" || true
fi

if [[ "$ROLE" == "booth" ]]; then
    zenity --info --width=420 --title="$TITLE" --text="Installation complete.\nReboot to start the booth."
else
    zenity --info --width=420 --title="$TITLE" --text="Installation complete.\nOpen the Admin URL and log in. Details are in /etc/parking/install-notes.txt."
fi
