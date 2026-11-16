#!/usr/bin/env bash
# Optional convenience (tutorial.md, section C): create .env from .env.example with
# the four secrets already filled in with random values. Same result as copying
# the file and generating each secret with `openssl rand -hex 24`.
# Refuses to overwrite an existing .env. Never prints the secrets.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -e .env ]]; then
  echo ".env already exists; not overwriting." >&2
  exit 1
fi

umask 077
secrets='^(POSTGRES_SUPERUSER_PASSWORD|DB_MIGRATION_PASSWORD|DB_PASSWORD|REDIS_PASSWORD)=$'
while IFS= read -r line; do
  if [[ "$line" =~ $secrets ]]; then
    printf '%s%s\n' "$line" "$(openssl rand -hex 24)"
  else
    printf '%s\n' "$line"
  fi
done < .env.example > .env

echo "Created .env with generated secrets (mode 600). Now fill in the REQUIRED values."
