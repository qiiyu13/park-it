#!/usr/bin/env bash
# Regenerate the booth enrollment token.
#
# Booth PCs redeem this token at POST /api/setup/enroll to fetch the server's
# INTERNAL_API_KEY + Redis address (replaces hand-copying the key). Unlike the
# setup-wizard token it is reusable: one token enrolls every booth brought
# online during the install window. It expires 24h after mint (mtime-based,
# see api/app/services/setup.py).
#
# Usage:
#   sudo ./scripts/regen-enroll-token.sh

set -euo pipefail

TOKEN_PATH="${ENROLL_TOKEN_PATH:-/etc/parking/enroll-token}"

if [[ $EUID -ne 0 ]]; then
    echo "must run as root (sudo)" >&2
    exit 1
fi

mkdir -p "$(dirname "$TOKEN_PATH")"
# 12 hex chars (48 bits), uppercase, rate-limited at /api/setup/enroll.
TOKEN=$(openssl rand -hex 6 | tr 'a-f' 'A-F')
echo -n "$TOKEN" > "$TOKEN_PATH"
chown root:parking "$TOKEN_PATH" 2>/dev/null || true
chmod 0640 "$TOKEN_PATH"

SERVER_IP=$(hostname -I | awk '{print $1}')
echo "Booth enrollment token regenerated at ${TOKEN_PATH}"
echo
echo "On each booth PC, run the booth installer and paste when prompted:"
echo "  Server IP        : ${SERVER_IP}"
echo "  Enrollment token : ${TOKEN}"
echo
echo "Valid 24h, reusable for every booth in that window."
