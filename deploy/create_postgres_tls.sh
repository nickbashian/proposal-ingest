#!/usr/bin/env bash
set -euo pipefail

root=${1:?Usage: create_postgres_tls.sh /etc/proposal-ingest/tls}
target="$root/postgres"
private="$root/private-ca"
if [[ -e "$target" || -e "$private" ]]; then
  echo "Refusing to overwrite existing TLS material below: $root" >&2
  exit 2
fi
command -v openssl >/dev/null || { echo "openssl is required" >&2; exit 2; }
install -d -m 0700 "$target"
install -d -m 0700 "$root"
install -d -m 0700 "$private"
umask 077
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

openssl genrsa -out "$private/ca.key" 4096
openssl req -x509 -new -key "$private/ca.key" -sha256 -days 3650 \
  -subj "/CN=proposal-ingest-postgres-private-ca" -out "$private/ca.crt"
openssl genrsa -out "$work/server.key" 2048
openssl req -new -key "$work/server.key" -subj "/CN=database" \
  -addext "subjectAltName=DNS:database" -out "$work/server.csr"
printf '%s\n' 'subjectAltName=DNS:database' 'extendedKeyUsage=serverAuth' > "$work/server.ext"
openssl x509 -req -in "$work/server.csr" -CA "$private/ca.crt" -CAkey "$private/ca.key" \
  -CAcreateserial -out "$target/server.crt" -days 397 -sha256 -extfile "$work/server.ext"
install -m 0644 "$private/ca.crt" "$target/ca.crt"
install -m 0640 "$work/server.key" "$target/server.key"
chown 70:70 "$target" "$target/server.key" "$target/server.crt"
chmod 0700 "$target"
chmod 0600 "$private/ca.key"
echo "TLS files created. Keep private-ca/ca.key offline; set PROPOSAL_TLS_DIR=$root."
