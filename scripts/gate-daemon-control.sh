#!/usr/bin/env bash
# Control a gate daemon unit from the API (runs as root via NOPASSWD sudo).
#
#   gate-daemon-control.sh <GATE_CODE> enable|disable|restart|status
#
# The gate code is interpolated into a unit name, so validate it strictly.
set -euo pipefail

code="${1:-}"
action="${2:-status}"

if [[ ! "$code" =~ ^[A-Za-z0-9_-]+$ ]]; then
    echo "invalid gate code" >&2
    exit 2
fi

case "$action" in
    enable|disable|restart|status) ;;
    *) echo "invalid action: $action" >&2; exit 2 ;;
esac

unit="parking-daemon-gate-in@${code}.service"

case "$action" in
    status)
        exec systemctl is-active "$unit"
        ;;
    enable)
        systemctl enable --now "$unit"
        systemctl is-active "$unit"
        ;;
    *)
        systemctl "$action" "$unit"
        systemctl is-active "$unit"
        ;;
esac
