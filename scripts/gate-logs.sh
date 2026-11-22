#!/usr/bin/env bash
# Print the gate daemon's journal as JSON lines (technician live log).
#
#   gate-logs.sh <GATE_CODE> [LINES]
#
# Invoked through sudo by the API (see /etc/sudoers.d/parking-setup), so the
# gate code is validated here: the unit name is interpolated into a journalctl
# argument.
set -euo pipefail

code="${1:-}"
lines="${2:-200}"

if [[ ! "$code" =~ ^[A-Za-z0-9_-]+$ ]]; then
    echo "invalid gate code" >&2
    exit 2
fi
if [[ ! "$lines" =~ ^[0-9]+$ ]]; then
    lines=200
fi
if (( lines > 1000 )); then
    lines=1000
fi

exec journalctl -u "parking-daemon-gate-in@${code}" -n "$lines" --no-pager -o json
