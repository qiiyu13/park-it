#!/bin/bash
set -euo pipefail

# E-Parking System v2 Deployment Script
# Usage: ./scripts/deploy.sh

APP_DIR="/opt/parking-system-v2"
USER="parking"

echo "=== E-Parking v2 Deployment ==="

# 1. Build frontend
echo "[1/6] Building frontend..."
cd "$APP_DIR/frontend"
npm install
npm run build

# 2. Frontend: Nuxt/Nitro output is built in place and served by
# parking-frontend.service. (The old copy to /var/www was a leftover from a
# static-nginx deployment and diverged from the systemd host layout.)
echo "[2/6] Frontend build is in place (served by parking-frontend.service)..."

# 3. Update Python dependencies (production deps only)
echo "[3/6] Updating Python dependencies..."
cd "$APP_DIR"
source .venv/bin/activate
pip install -e .

# 4. Run database migrations (alembic.ini lives at the repo root)
echo "[4/6] Running database migrations..."
cd "$APP_DIR"
alembic upgrade head

# 5. Validate nginx. The host config is owned by the installer; never copy
# docker/nginx.conf here — its upstreams are compose service names and would
# break every /api request on a systemd host.
echo "[5/6] Validating nginx configuration..."
if [ -f /etc/nginx/sites-available/parking ]; then
    sudo nginx -t && sudo systemctl reload nginx
else
    echo "  (no /etc/nginx/sites-available/parking — skipping nginx reload)"
fi

# 6. Restart services
echo "[6/6] Restarting services..."
sudo systemctl daemon-reload
sudo systemctl restart parking-api
sudo systemctl restart parking-events
sudo systemctl restart parking-worker-critical
sudo systemctl restart parking-worker-bg
sudo systemctl restart parking-frontend

# Restart gate-in daemons (exit lanes are driven by booth_bridge, not a unit)
for service in $(systemctl list-units --plain --no-legend 'parking-daemon-gate-in@*' | awk '{print $1}'); do
    sudo systemctl restart "$service"
done

# Health check
echo "=== Health Check ==="
sleep 2
curl -sf http://localhost/api/health && echo "API OK" || echo "API FAIL"

echo "=== Deployment Complete ==="
