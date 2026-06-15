#!/bin/bash
# sync_prod_db.sh - Clones the PRODUCTION database into a local Postgres copy.
#
# Source: production RDS reached through an AWS SSM port-forwarding tunnel that
#         must already be running on localhost:${TUNNEL_PORT} (default 5433).
# Target: local Docker Postgres container (default work_postgres), database
#         ${LOCAL_DB} (default experteliq_prod_local) — dropped and recreated.
#
# Source credentials are read from .env.production (DB_USERNAME / DB_PASSWORD /
# DB_NAME); the host is always forced to the tunnel, never taken from the file.
#
# Usage:
#   ./scripts/sync_prod_db.sh
#
# Overridable via environment variables:
#   TUNNEL_PORT=5433 LOCAL_CONTAINER=work_postgres LOCAL_DB=experteliq_prod_local ./scripts/sync_prod_db.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env.production"

TUNNEL_HOST="${TUNNEL_HOST:-localhost}"
TUNNEL_PORT="${TUNNEL_PORT:-5433}"
LOCAL_CONTAINER="${LOCAL_CONTAINER:-work_postgres}"
LOCAL_DB="${LOCAL_DB:-experteliq_prod_local}"
BACKUP_FILE="$REPO_ROOT/backup_prod_$(date +%d_%b_%Y_%H%M).sql"

SSM_TUNNEL_CMD="aws ssm start-session --region us-east-2 --target i-0eacde3222f6e676a --document-name AWS-StartPortForwardingSession --parameters portNumber=5432,localPortNumber=${TUNNEL_PORT}"

# --- Preconditions -----------------------------------------------------------

if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: $ENV_FILE not found. Create it as a copy of the production .env first." >&2
    exit 1
fi

if ! nc -z "$TUNNEL_HOST" "$TUNNEL_PORT" 2>/dev/null; then
    echo "ERROR: SSM tunnel is not running on ${TUNNEL_HOST}:${TUNNEL_PORT}." >&2
    echo "Start it in another terminal with:" >&2
    echo "  $SSM_TUNNEL_CMD" >&2
    exit 1
fi

if ! docker ps --format '{{.Names}}' | grep -qx "$LOCAL_CONTAINER"; then
    echo "ERROR: local Postgres container '$LOCAL_CONTAINER' is not running." >&2
    exit 1
fi

# Source credentials from .env.production (values never echoed).
get_env() { grep -E "^$1=" "$ENV_FILE" | head -1 | cut -d= -f2-; }
REMOTE_USER="$(get_env DB_USERNAME)"
REMOTE_PASS="$(get_env DB_PASSWORD)"
REMOTE_DB="$(get_env DB_NAME)"

if [ -z "$REMOTE_USER" ] || [ -z "$REMOTE_PASS" ] || [ -z "$REMOTE_DB" ]; then
    echo "ERROR: DB_USERNAME / DB_PASSWORD / DB_NAME missing in $ENV_FILE." >&2
    exit 1
fi

LOCAL_USER="$(docker inspect "$LOCAL_CONTAINER" --format '{{range .Config.Env}}{{println .}}{{end}}' | grep '^POSTGRES_USER=' | cut -d= -f2-)"

# --- Dump --------------------------------------------------------------------

echo "==> [1/4] Dumping production DB '$REMOTE_DB' through the tunnel (this can take a while)..."
# host.docker.internal lets the container reach the tunnel listening on the Mac host.
docker exec -e PGPASSWORD="$REMOTE_PASS" "$LOCAL_CONTAINER" \
    pg_dump -h host.docker.internal -p "$TUNNEL_PORT" -U "$REMOTE_USER" -d "$REMOTE_DB" \
    --no-owner --no-privileges > "$BACKUP_FILE"
echo "    Backup saved to: $BACKUP_FILE ($(du -h "$BACKUP_FILE" | cut -f1))"

# --- Restore -----------------------------------------------------------------

echo "==> [2/4] Dropping local database '$LOCAL_DB'..."
docker exec "$LOCAL_CONTAINER" \
    psql -U "$LOCAL_USER" -d postgres -c "DROP DATABASE IF EXISTS $LOCAL_DB;"

echo "==> [3/4] Creating fresh local database '$LOCAL_DB'..."
docker exec "$LOCAL_CONTAINER" \
    psql -U "$LOCAL_USER" -d postgres -c "CREATE DATABASE $LOCAL_DB OWNER $LOCAL_USER;"

echo "==> [4/4] Restoring backup into '$LOCAL_DB'..."
docker exec -i "$LOCAL_CONTAINER" \
    psql -U "$LOCAL_USER" -d "$LOCAL_DB" -q < "$BACKUP_FILE"

# --- Verify ------------------------------------------------------------------

echo ""
echo "Verifying restore..."
docker exec "$LOCAL_CONTAINER" \
    psql -U "$LOCAL_USER" -d "$LOCAL_DB" \
    -c "SELECT COUNT(*) AS scraper_jobs FROM scraper_jobs;"

echo ""
echo "Sync complete. Point .env.local at DB_NAME=$LOCAL_DB and run with .env = .env.local."
echo "Backup file kept at: $BACKUP_FILE (delete it when no longer needed)."
