#!/usr/bin/env bash
# E-Parking v2 — technician one-command installer (v1-compatible muscle memory).
#
#   sudo ./install.sh                       # server, quick mode (defaults)
#   sudo ./install.sh --topology 2in2out --tariff mall --site-name "Parkir ABC"
#   sudo ./install.sh --combo --gate-code GOUT-01
#   sudo ./install.sh --booth --server-ip 192.168.1.10 --token ABCDEF123456
#   sudo ./install.sh --advanced            # old interactive installer + wizard
#
# Quick mode provisions admin/site/tariff/area/topology, marks setup complete,
# enables gate daemons and prints a hand-over summary. No wizard step.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Running from a flash-disk copy (no .git): install from this tree instead of
# requiring a repository URL. Developers with a git checkout keep the normal
# clone/pull-update path.
if [[ -z "${PARKING_SOURCE_DIR:-}" && ! -d "$HERE/.git" ]]; then
    export PARKING_SOURCE_DIR="$HERE"
fi

ROLE="server"
ADVANCED=false
PASSTHROUGH=()

for arg in "$@"; do
    case "$arg" in
        --booth)    ROLE="booth" ;;
        --server)   ROLE="server" ;;
        --combo)    ROLE="combo" ;;
        --advanced) ADVANCED=true ;;
        *)          PASSTHROUGH+=("$arg") ;;
    esac
done

ARGS=(--role "$ROLE")
if ! $ADVANCED; then
    ARGS+=(--quick)
fi
ARGS+=("${PASSTHROUGH[@]}")

exec "$HERE/installer/setup.sh" "${ARGS[@]}"
