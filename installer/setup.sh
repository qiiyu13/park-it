#!/usr/bin/env bash
# E-Parking v2 unified installer dispatcher.
#
# One entry point for field techs. Picks the correct role-specific installer
# under _roles/ based on the flag (or asks interactively).
#
# Usage:
#   sudo ./setup.sh                  # interactive role prompt
#   sudo ./setup.sh --role server    # full server stack (DB+API+frontend+nginx)
#   sudo ./setup.sh --role booth     # booth PC only (Chrome kiosk + booth_bridge)
#   sudo ./setup.sh --role combo     # server + on-box booth (single-PC site)

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROLES_DIR="$HERE/_roles"

ROLE=""
PASSTHROUGH=()
NON_INTERACTIVE=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --role) ROLE="$2"; shift ;;
    --role=*) ROLE="${1#*=}" ;;
    --non-interactive) NON_INTERACTIVE=true; PASSTHROUGH+=("$1") ;;
    -h|--help)
      sed -n '1,15p' "$0"
      exit 0
      ;;
    *) PASSTHROUGH+=("$1") ;;
  esac
  shift
done

if [[ $EUID -ne 0 ]]; then
  echo "must run as root (sudo)" >&2
  exit 1
fi

if [[ -z "$ROLE" ]]; then
  if $NON_INTERACTIVE; then
    echo "--non-interactive requires --role server|booth|combo" >&2
    exit 2
  fi
  echo
  echo "==== E-Parking v2 Installer ===="
  echo "  1) server   — full backend (DB, API, frontend, workers, nginx)"
  echo "  2) booth    — booth PC only (Chrome kiosk + booth_bridge)"
  echo "  3) combo    — server + booth on same machine (single-PC site)"
  echo
  read -r -p "Pick role [1-3]: " choice
  case "$choice" in
    1) ROLE="server" ;;
    2) ROLE="booth" ;;
    3) ROLE="combo" ;;
    *) echo "invalid choice" >&2; exit 2 ;;
  esac
fi

declare -A ROLE_DIR=(
  [server]="$ROLES_DIR/server"
  [booth]="$ROLES_DIR/booth_pc"
  [combo]="$ROLES_DIR/combo"
)

target="${ROLE_DIR[$ROLE]:-}"
if [[ -z "$target" || ! -d "$target" ]]; then
  echo "unknown role: $ROLE (expected server|booth|combo)" >&2
  exit 2
fi

target_script="$target/setup.sh"
if [[ ! -x "$target_script" ]]; then
  echo "role installer not executable: $target_script" >&2
  exit 2
fi

echo
echo "→ dispatching to $target_script ${PASSTHROUGH[*]:-}"
exec "$target_script" "${PASSTHROUGH[@]}"
