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
#   3. installs the systemd units (API, three workers, update-check timer)
#   4. runs the database migrations
#   5. enables and starts everything, then verifies the API answers
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/cyberstratum/app}"
STATE_DIR="${STATE_DIR:-/var/lib/cyberstratum}"
LOG_DIR="${LOG_DIR:-/var/log/cyberstratum}"
ENV_FILE="${ENV_FILE:-/etc/cyberstratum/app.env}"
SERVICE_USER="cyberstratum"
PYTHON_VERSION="${PYTHON_VERSION:-3.12}"
# Set INSTALL_CADDY=0 to skip the reverse-proxy step.
INSTALL_CADDY="${INSTALL_CADDY:-1}"

log() { printf '\n=== %s ===\n' "$1"; }

if [ "$(id -u)" -ne 0 ]; then
  echo "This script must be run as root: sudo $0" >&2
  exit 1
fi

log "1. system user"
if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --home-dir "$STATE_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
fi
mkdir -p "$STATE_DIR" "$STATE_DIR/artifacts" "$LOG_DIR" "$(dirname "$ENV_FILE")"
chown -R "$SERVICE_USER":"$SERVICE_USER" "$STATE_DIR" "$LOG_DIR"

if [ ! -f "$ENV_FILE" ]; then
  echo
  echo "ERROR: $ENV_FILE does not exist."
  echo "Create it from the template, then fill in the real values:"
  echo "  sudo cp deploy/vps/app.env.example $ENV_FILE"
  echo "  sudo chown root:$SERVICE_USER $ENV_FILE && sudo chmod 640 $ENV_FILE"
  echo
  echo "At minimum these must be set:"
  echo "  APP_ENV=production"
  echo "  DATABASE_URL=postgresql+psycopg://USER:PASS@HOST:5432/cyberstratum"
  echo "  REDIS_URL=redis://HOST:6379"
  echo "  API_KEY=<a long random secret>"
  echo "  AUTH_SECRET=<a long random secret>"
  echo "  API_BASE_URL=https://api.example.com"
  echo "  WEB_BASE_URL=https://cyberstratum.netlify.app"
  echo "  CORS_EXTRA_ORIGINS=https://cyberstratum.netlify.app"
  echo "  OBJECT_STORAGE_ROOT=$STATE_DIR/artifacts"
  exit 1
fi
chown root:"$SERVICE_USER" "$ENV_FILE"
chmod 640 "$ENV_FILE"

log "2. python environment"
cd "$APP_DIR"
# Every project distribution is installed EDITABLE, and the extras are
# attached to the editable root install. Installing the extras separately
# would replace the editable root package with a copied one, and the
# application would then run against a stale snapshot of the code.
if command -v uv >/dev/null 2>&1; then
  uv venv --python "$PYTHON_VERSION" .venv
  uv pip install --python .venv/bin/python \
    -e ".[dev,ml]" \
    -e packages/evm_analysis \
    -e packages/ml_baseline \
    -e packages/dataset_ingest
else
  python3 -m venv .venv
  .venv/bin/pip install --upgrade pip
  .venv/bin/pip install \
    -e ".[dev,ml]" \
    -e packages/evm_analysis \
    -e packages/ml_baseline \
    -e packages/dataset_ingest
fi
# ReportLab is pinned exactly: the PDF renderer must be byte-reproducible,
# and a different ReportLab version can change the bytes it emits.
.venv/bin/pip install "reportlab==5.1.0"
chown -R "$SERVICE_USER":"$SERVICE_USER" "$APP_DIR"

# Prove the running application imports the working tree, not a copied
# snapshot. This is the same class of failure that once made the API and
# the workers disagree about where artifacts were stored.
"$APP_DIR/.venv/bin/python" - <<'PY'
import pathlib
import app
import evm_analysis
import evm_dataset
import evm_ml
for module in (app, evm_analysis, evm_dataset, evm_ml):
    path = pathlib.Path(module.__file__).resolve()
    if "site-packages" in path.parts:
        raise SystemExit(f"FAIL: {module.__name__} resolves to a copied install: {path}")
    print(f"ok: {module.__name__} -> {path}")
PY

log "3. systemd units"
for unit in cyberstratum-api cyberstratum-worker cyberstratum-worker-mythril \
            cyberstratum-worker-correspondence cyberstratum-update-check; do
  install -m 644 "$APP_DIR/deploy/systemd/${unit}.service" /etc/systemd/system/
done
install -m 644 "$APP_DIR/deploy/systemd/cyberstratum-update-check.timer" /etc/systemd/system/
systemctl daemon-reload

log "4. database migrations"
# Migrations run as the service user so they use the same credentials and
# produce the same schema as the running application. The environment file
# is sourced rather than parsed with grep/xargs, so a value containing a
# space or a quote cannot silently truncate the configuration.
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a
sudo -u "$SERVICE_USER" \
  env DATABASE_URL="$DATABASE_URL" \
      REDIS_URL="$REDIS_URL" \
      OBJECT_STORAGE_ROOT="${OBJECT_STORAGE_ROOT:-$STATE_DIR/artifacts}" \
  "$APP_DIR/.venv/bin/python" -m alembic -c "$APP_DIR/alembic.ini" upgrade head

log "5. start services"
# The Mythril and correspondence workers are separate units: a symbolic
# execution run and a recompilation both need a budget of their own, so
# neither may delay an ordinary scan.
systemctl enable cyberstratum-api cyberstratum-worker \
  cyberstratum-worker-mythril cyberstratum-worker-correspondence \
  cyberstratum-update-check.timer
systemctl restart cyberstratum-api cyberstratum-worker \
  cyberstratum-worker-mythril cyberstratum-worker-correspondence
systemctl enable --now cyberstratum-update-check.timer
sleep 3

log "6. verify"
FAILED=0
for unit in cyberstratum-api cyberstratum-worker cyberstratum-worker-mythril \
            cyberstratum-worker-correspondence; do
  if systemctl is-active --quiet "$unit"; then
    echo "active: $unit"
  else
    echo "FAILED:  $unit"
    systemctl --no-pager --lines=20 status "$unit" || true
    FAILED=1
  fi
done
# The API must actually answer, not merely be running.
if curl -fsS --max-time 10 http://127.0.0.1:8000/api/v1/health >/dev/null; then
  echo "active: API health endpoint answered"
else
  echo "FAILED:  API health endpoint did not answer"
  FAILED=1
fi

if [ "$INSTALL_CADDY" = "1" ]; then
  log "7. reverse proxy"
  if command -v caddy >/dev/null 2>&1; then
    install -m 644 "$APP_DIR/deploy/vps/Caddyfile" /etc/caddy/Caddyfile
    caddy validate --config /etc/caddy/Caddyfile
    systemctl reload caddy || systemctl restart caddy
    echo "Caddy installed. The hostname in the Caddyfile must match API_BASE_URL."
  else
    echo "Caddy is not installed. Install it (apt-get install caddy) and copy"
    echo "deploy/vps/Caddyfile to /etc/caddy/Caddyfile, or put your own"
    echo "TLS-terminating proxy in front of 127.0.0.1:8000."
  fi
fi

if [ "$FAILED" -ne 0 ]; then
  echo
  echo "=== DEPLOY FINISHED WITH FAILURES ===" >&2
  exit 1
fi

echo
echo "=== DEPLOY DONE ==="
echo "The API listens on 127.0.0.1:8000 and answers /api/v1/health."
echo "Put a TLS-terminating reverse proxy in front of it and set API_BASE_URL"
echo "to the public https URL. Then set CORS_EXTRA_ORIGINS to the deployed"
echo "frontend origin and deploy the frontend to Netlify."
