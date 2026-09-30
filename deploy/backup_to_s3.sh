#!/usr/bin/env bash
set -euo pipefail

repo=${PROPOSAL_DEPLOY_DIR:-/opt/proposal-ingest}
env_file=${PROPOSAL_ENV_FILE:-/etc/proposal-ingest/.env.production}
export PROPOSAL_ENV_FILE="$env_file"
backup_uri=${PROPOSAL_BACKUP_S3_URI:?Set PROPOSAL_BACKUP_S3_URI in the root-only backup environment file}
[[ "$backup_uri" == s3://* ]] || { echo "Backup destination must be an s3:// URI" >&2; exit 2; }
[[ -r "$env_file" ]] || { echo "Production Compose environment file is unreadable" >&2; exit 2; }
command -v docker >/dev/null || { echo "Docker is required" >&2; exit 2; }
command -v aws >/dev/null || { echo "AWS CLI is required" >&2; exit 2; }

stage_root=${PROPOSAL_BACKUP_STAGING_ROOT:-/var/lib/proposal-ingest/backup-staging}
install -d -m 0700 "$stage_root"
stage=$(mktemp -d "$stage_root/run.XXXXXX")
chmod 0700 "$stage"
trap 'rm -rf "$stage"' EXIT
compose=(docker compose --env-file "$env_file" -f "$repo/deploy/compose.production.yml")

# This local socket operation runs inside the pinned PostgreSQL 18 service container.
"${compose[@]}" exec -T database sh -c \
  'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --format=custom --no-owner --no-privileges' \
  > "$stage/database.dump"
[[ -s "$stage/database.dump" ]] || { echo "Database dump was empty" >&2; exit 2; }

# The web image shares the immutable object volume; the bundle checks every object hash.
"${compose[@]}" run --rm --no-deps --user 0:0 -v "$stage:/backup:rw" web \
  python /app/scripts/app_recovery.py package \
  --dump-file /backup/database.dump \
  --object-root /var/lib/proposal-ingest/objects \
  --destination /backup/bundle

stamp=$(date -u +%Y%m%dT%H%M%SZ)
aws s3 sync "$stage/bundle" "$backup_uri/$stamp" --sse AES256 --only-show-errors
echo "backup=uploaded timestamp=$stamp"
