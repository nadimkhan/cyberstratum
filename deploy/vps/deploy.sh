#!/usr/bin/env bash
# Deploy the CyberStratum backend to a Linux VPS.
#
# This script is meant to be RUN ON THE VPS (it needs root for the system
# user, the service files and the directories). It is checked into the repo
# so the deployment is reproducible rather than a sequence of remembered
# commands.
#
#   sudo ./deploy/vps/deploy.sh
#
# It assumes:
#   - Ubuntu 22.04 or newer
#   - PostgreSQL and Redis reachable (managed instances or local services)
#   - The repository already cloned to /opt/cyberstratum/app
#
# What it does:
#   1. creates the `cyberstratum` system user
#   2. installs Python dependencies into /opt/cyberstratum/app/.venv
#   3. installs the systemd units
#   4. runs the database migrations
#   5. enables and starts the API and the worker
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/cyberstratum/app}"
STATE_DIR="${STATE_DIR:-/var/lib/cyberstratum}"
LOG_DIR="${LOG_DIR:-/var/log/cyberstratum}"
ENV_FILE="${ENV_FILE:-/etc/cyberstratum/app.env}"
SERVICE_USER="cyberstratum"
PYTHON_VERSION="${PYTHON_VERSION:-3.12}"

log() { printf '\n=== %s ===\n' "$1"; }

if [ "$(id -u)" -ne 0 ]; then
  echo "This script must be run as root: sudo $0" >&2
  exit 1
fi

log "1. system user"
if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --home-dir "$STATE_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
fi
mkdir -p "$STATE_DIR" "$LOG_DIR" "$(dirname "$ENV_FILE")"
chown -R "$SERVICE_USER":"$SERVICE_USER" "$STATE_DIR" "$LOG_DIR"

if [ ! -f "$ENV_FILE" ]; then
  echo
  echo "ERROR: $ENV_FILE does not exist."
  echo "Create it first, from .env.example, with at minimum:"
  echo "  APP_ENV=production"
  echo "  DATABASE_URL=postgresql+psycopg://USER:PASS@HOST:5432/cyberstratum"
  echo "  REDIS_URL=redis://HOST:6379"
  echo "  API_KEY=<a long random secret>"
  echo "  AUTH_SECRET=<a long random secret>"
  echo "  API_BASE_URL=https://api.example.com"
  echo "  WEB_BASE_URL=https://cyberstratum.netlify.app"
  echo "  CORS_EXTRA_ORIGINS=https://cyberstratum.netlify.app,https://app.example.com"
  exit 1
fi
chown root:"$SERVICE_USER" "$ENV_FILE"
chmod 640 "$ENV_FILE"

log "2. python environment"
cd "$APP_DIR"
if command -v uv >/dev/null 2>&1; then
  uv venv --python "$PYTHON_VERSION" .venv
  uv pip install --python .venv/bin/python -e . -e packages/evm_analysis -e packages/ml_baseline
  uv pip install --python .venv/bin/python ".[dev,ml]"
  uv pip install --python .venv/bin/python "reportlab==5.1.0"
else
  python3 -m venv .venv
  .venv/bin/pip install --upgrade pip
  .venv/bin/pip install -e . -e packages/evm_analysis -e packages/ml_baseline
  .venv/bin/pip install ".[dev,ml]" "reportlab==5.1.0"
fi
chown -R "$SERVICE_USER":"$SERVICE_USER" "$APP_DIR"

log "3. systemd units"
install -m 644 "$APP_DIR/deploy/systemd/cyberstratum-api.service" /etc/systemd/system/
install -m 644 "$APP_DIR/deploy/systemd/cyberstratum-worker.service" /etc/systemd/system/
systemctl daemon-reload

log "4. database migrations"
# Migrations run as the service user so they use the same credentials and
# produce the same schema as the running application.
sudo -u "$SERVICE_USER" env $(grep -v '^#' "$ENV_FILE" | grep -v '^$' | xargs) \
  "$APP_DIR/.venv/bin/python" -m alembic -c "$APP_DIR/alembic.ini" upgrade head

log "5. start services"
systemctl enable cyberstratum-api cyberstratum-worker
systemctl restart cyberstratum-api cyberstratum-worker
sleep 3
systemctl --no-pager --lines=20 status cyberstratum-api cyberstratum-worker || true

echo
echo "=== DEPLOY DONE ==="
echo "The API listens on 127.0.0.1:8000. Put a TLS-terminating reverse"
echo "proxy in front of it and set API_BASE_URL to the public https URL."
