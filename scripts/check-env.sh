#!/usr/bin/env bash
# Optional diagnostic (tutorial.md, "Troubleshooting"): explains what is wrong with
# .env in plain words. Not a deployment step: `docker compose up -d` checks the
# required values itself, and the migrate service validates the full configuration
# on every start. Never prints secret values.
#
#   ./scripts/check-env.sh
#
# Exit code 0: looks ready (warnings may still be printed). 1: something to fix.
set -uo pipefail
cd "$(dirname "$0")/.."
fail=0
ok()   { printf '  \033[32mOK\033[0m    %s\n' "$1"; }
warn() { printf '  \033[33mWARN\033[0m  %s\n' "$1"; }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; fail=1; }

if [[ ! -f .env ]]; then
  echo "No .env file. Create it first: cp .env.example .env (tutorial.md, section C)."
  exit 1
fi

# Read KEY=VALUE lines without executing anything (the last occurrence wins, as in
# Docker Compose). Surrounding quotes are removed.
declare -A env
while IFS= read -r line || [[ -n "$line" ]]; do
  [[ "$line" =~ ^[[:space:]]*# || ! "$line" =~ = ]] && continue
  key="${line%%=*}"; key="${key//[[:space:]]/}"
  val="${line#*=}"; val="${val%%[[:space:]]#*}"
  val="${val#"${val%%[![:space:]]*}"}"; val="${val%"${val##*[![:space:]]}"}"
  val="${val%\"}"; val="${val#\"}"; val="${val%\'}"; val="${val#\'}"
  [[ "$key" =~ ^[A-Z_][A-Z0-9_]*$ ]] && env[$key]="$val"
done < .env
get() { printf '%s' "${env[$1]:-}"; }

echo "File"
perm=$(stat -c %a .env 2>/dev/null || echo "?")
[[ "$perm" == "600" ]] && ok ".env is private (mode 600)" || bad ".env mode is $perm; run: chmod 600 .env"

app_env=$(get APP_ENV); app_env=${app_env:-production}
if [[ -n "$(get COMPOSE_FILE)" ]]; then
  bad "COMPOSE_FILE is set in .env: docker compose would load other files than docker-compose.yml; remove that line"
fi

echo "Domain and Traefik"
host=$(get PUBLIC_HOSTNAME); url=$(get PUBLIC_BASE_URL)
[[ -n "$host" ]] && ok "PUBLIC_HOSTNAME is set ($host)" || bad "PUBLIC_HOSTNAME is empty"
if [[ -z "$url" ]]; then
  bad "PUBLIC_BASE_URL is empty"
elif [[ "$app_env" == "production" && ! "$url" =~ ^https://${host//./\\.}(:[0-9]+)?$ ]]; then
  bad "PUBLIC_BASE_URL must be exactly https://$host in production (is $url)"
else
  ok "PUBLIC_BASE_URL is $url"
fi
[[ "$host" == *example.* ]] && bad "PUBLIC_HOSTNAME is still an example domain"
for k in TRAEFIK_NETWORK TRAEFIK_CERT_RESOLVER FORWARDED_ALLOW_IPS; do
  [[ -n "$(get $k)" ]] && ok "$k is set ($(get $k))" || bad "$k is empty"
done
net=$(get TRAEFIK_NETWORK)
if [[ -n "$net" ]] && command -v docker > /dev/null; then
  if docker network inspect "$net" > /dev/null 2>&1; then
    ok "Docker network '$net' exists"
  else
    bad "Docker network '$net' does not exist (docker network ls); it must be Traefik's network"
  fi
fi

echo "Secrets"
for k in POSTGRES_SUPERUSER_PASSWORD DB_MIGRATION_PASSWORD DB_PASSWORD REDIS_PASSWORD; do
  v=$(get $k); lower=${v,,}
  if [[ -z "$v" ]]; then bad "$k is empty"
  elif [[ "$lower" == "change-me" || "$lower" == "changeme" || "$lower" == "password" || "$lower" == "postgres" ]]; then
    bad "$k is still a placeholder; set a random value (openssl rand -hex 24)"
  elif [[ ${#v} -lt 16 ]]; then bad "$k is shorter than 16 characters"
  elif [[ ! "$v" =~ ^[A-Za-z0-9]+$ ]]; then bad "$k must contain letters and digits only"
  else ok "$k is set (${#v} characters)"
  fi
done
db=$(get DB_PASSWORD); mig=$(get DB_MIGRATION_PASSWORD); su=$(get POSTGRES_SUPERUSER_PASSWORD)
[[ -n "$db" && ( "$db" == "$mig" || "$db" == "$su" ) ]] && bad "database passwords must all be different"

echo "Steam"
key=$(get STEAM_WEB_API_KEY)
if [[ -z "$key" ]]; then
  warn "STEAM_WEB_API_KEY is empty: libraries cannot be imported automatically (manual mode)"
elif [[ "$key" =~ ^[0-9A-Fa-f]{32}$ ]]; then
  ok "STEAM_WEB_API_KEY has the expected format (32 hex characters)"
else
  bad "STEAM_WEB_API_KEY does not look like a Steam Web API key (32 hex characters)"
fi

echo "Application"
grade=$(get AI_GRADE)
case "${grade,,}" in
  ""|true) ok "AI_GRADE=${grade:-TRUE (default)}: machine-learning scoring" ;;
  false) ok "AI_GRADE=$grade: classic scoring (no machine learning, no training)" ;;
  *) bad "AI_GRADE must be TRUE or FALSE (is '$grade')" ;;
esac
case "$app_env" in
  production) ok "APP_ENV=production" ;;
  development) warn "APP_ENV=development: for workstations only; use production on a server" ;;
  *) bad "APP_ENV must be production (or development on a workstation)" ;;
esac
if [[ "$(get IGDB_ENABLED)" == "true" ]]; then
  [[ -n "$(get IGDB_CLIENT_ID)" && -n "$(get IGDB_CLIENT_SECRET)" ]] \
    && ok "IGDB enabled with credentials" || bad "IGDB_ENABLED=true needs IGDB_CLIENT_ID and IGDB_CLIENT_SECRET"
else
  ok "IGDB disabled (optional)"
fi

echo "Docker Compose"
if ! command -v docker > /dev/null; then
  bad "docker is not installed"
elif errors=$(docker compose config --quiet 2>&1); then
  ok "docker compose config is valid"
else
  bad "docker compose config failed:"; printf '        %s\n' "$errors"
fi

echo
if [[ $fail == 0 ]]; then echo "Configuration looks ready."; else echo "Fix the FAIL items above, then run this again."; fi
exit $fail
