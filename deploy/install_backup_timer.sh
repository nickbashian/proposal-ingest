#!/usr/bin/env bash
set -euo pipefail

repo=${1:-/opt/proposal-ingest}
if [[ ! -f "$repo/deploy/backup_to_s3.sh" ]]; then
  echo "Expected deployment repository at $repo" >&2
  exit 2
fi
install -d -m 0700 /etc/proposal-ingest
if [[ ! -f /etc/proposal-ingest/backup.env ]]; then
  cat > /etc/proposal-ingest/backup.env <<'EOF'
PROPOSAL_DEPLOY_DIR=/opt/proposal-ingest
PROPOSAL_ENV_FILE=/etc/proposal-ingest/.env.production
PROPOSAL_BACKUP_S3_URI=s3://REPLACE_WITH_PRIVATE_BUCKET/backups
EOF
  chmod 0600 /etc/proposal-ingest/backup.env
  echo "Created /etc/proposal-ingest/backup.env; set the S3 URI before enabling the timer." >&2
  exit 2
fi
install -m 0644 "$repo/deploy/systemd/proposal-ingest-backup.service" /etc/systemd/system/
install -m 0644 "$repo/deploy/systemd/proposal-ingest-backup.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now proposal-ingest-backup.timer
echo "Daily backup timer enabled. Run systemctl start proposal-ingest-backup.service for an immediate drill."
