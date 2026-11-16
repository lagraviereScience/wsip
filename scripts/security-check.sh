#!/usr/bin/env bash
# Automated security checks (docs/SECURITY_CHECKLIST.md). Exit code != 0 on findings.
#   1. Python dependency vulnerabilities (pip-audit against the locked runtime set)
#   2. JavaScript dependency vulnerabilities (npm audit, production deps, high+)
#   3. Secrets: .env not tracked; the Steam key appears in no tracked file
#   4. Exposure: no published port (production) or 127.0.0.1 only (workstation);
#      database and Redis on the internal network only, never on Traefik's network
#   5. Containers: non-root users, read-only root filesystems
#   6. HTTP: security headers on the API and the web app
set -uo pipefail
cd "$(dirname "$0")/.."
fail=0
ok()  { printf '  \033[32m✓\033[0m %s\n' "$1"; }
bad() { printf '  \033[31m✗\033[0m %s\n' "$1"; fail=1; }

skip() { printf '  \033[33m-\033[0m %s\n' "$1"; }

# 1-2 need uv and npm (developer tools). On a server without them they are skipped:
# run them on a workstation before each release instead.
echo "1. Python dependencies"
if command -v uv > /dev/null; then
  req=$(mktemp)
  (cd backend && uv export --no-dev --frozen --format requirements-txt --no-emit-project > "$req" 2>/dev/null)
  if uvx --quiet pip-audit --strict --disable-pip -r "$req" > /tmp/pip-audit.out 2>&1; then
    ok "pip-audit: no known vulnerabilities ($(grep -c '==' "$req") pinned packages)"
  else
    bad "pip-audit findings:"; cat /tmp/pip-audit.out
  fi
  rm -f "$req"
else
  skip "skipped: uv is not installed (run on a workstation)"
fi

echo "2. JavaScript dependencies"
if command -v npm > /dev/null; then
  if (cd frontend && npm audit --omit=dev --audit-level=high > /tmp/npm-audit.out 2>&1); then
    ok "npm audit: no high or critical vulnerabilities in production dependencies"
  else
    bad "npm audit findings:"; tail -20 /tmp/npm-audit.out
  fi
else
  skip "skipped: npm is not installed (run on a workstation)"
fi

echo "3. Secrets"
if git ls-files --error-unmatch .env > /dev/null 2>&1; then bad ".env is tracked by git"; else ok ".env is not tracked"; fi
perm=$(stat -c %a .env 2>/dev/null || echo "?")
[[ "$perm" == "600" ]] && ok ".env mode 600" || bad ".env mode is $perm (want 600)"
key=$(grep -E '^STEAM_WEB_API_KEY=' .env | cut -d= -f2- | tr -d '"'"'"' ')
if [[ -n "$key" ]] && git grep -qF "$key" 2>/dev/null; then bad "Steam key found in a tracked file"; else ok "Steam key in no tracked file"; fi
if git grep -nE 'BEGIN (RSA|OPENSSH|EC|PRIVATE) KEY' -- ':!*.md' > /dev/null 2>&1; then bad "private key material in the repository"; else ok "no private keys in the repository"; fi

echo "4. Exposure"
cfg=$(docker compose config --format json)
q() { python3 -c "import json,sys; d=json.load(sys.stdin); $1" <<<"$cfg"; }
published=$(q "print(chr(10).join(n + ' ' + str(p.get('host_ip', '0.0.0.0')) + ':' + str(p.get('published')) for n, v in d['services'].items() if 'profiles' not in v for p in v.get('ports', [])))")
[[ -z "$published" ]] && ok "no port is published on the host (traffic only through Traefik)"
while read -r line; do
  [[ -z "$line" ]] && continue
  [[ "$line" == *"127.0.0.1:"* ]] && ok "published only on loopback: $line" || bad "published publicly: $line"
done <<<"$published"
for svc in postgres redis worker scheduler; do
  n=$(q "print(len(d['services']['$svc'].get('ports',[])))")
  [[ "$n" == "0" ]] && ok "$svc publishes no port" || bad "$svc publishes a port"
done
internal=$(q "print(str(d['networks']['internal'].get('internal')).lower())")
[[ "$internal" == "true" ]] && ok "internal network has no outside route" || bad "internal network is routable"
for svc in postgres redis; do
  nets=$(q "print(' '.join(sorted(d['services']['$svc'].get('networks', {}))))")
  [[ "$nets" == "internal" ]] && ok "$svc is only on the internal network" || bad "$svc is on: $nets"
done

echo "5. Containers"
for svc in backend worker frontend scheduler; do
  uid=$(docker compose exec -T "$svc" id -u 2>/dev/null || echo "?")
  [[ "$uid" != "0" && "$uid" != "?" ]] && ok "$svc runs as uid $uid" || bad "$svc runs as root ($uid)"
  ro=$(q "print(str(d['services']['$svc'].get('read_only')).lower())")
  [[ "$ro" == "true" ]] && ok "$svc root filesystem is read-only" || bad "$svc root filesystem is writable"
done

echo "6. HTTP security headers"
# Checked inside the containers, so it works without published ports (production).
api=$(docker compose exec -T backend python -c "import urllib.request as u; r=u.urlopen('http://127.0.0.1:8000/api/health/live'); print(''.join(f'{k}: {v}\\n' for k, v in r.headers.items()))")
for h in x-content-type-options x-frame-options content-security-policy referrer-policy; do
  grep -qi "^$h:" <<<"$api" && ok "API sends $h" || bad "API lacks $h"
done
web=$(docker compose exec -T frontend node -e "fetch('http://127.0.0.1:3000/').then(r => { for (const [k, v] of r.headers) console.log(k + ': ' + v) })")
for h in x-content-type-options x-frame-options referrer-policy; do
  grep -qi "^$h:" <<<"$web" && ok "web app sends $h" || bad "web app lacks $h"
done
grep -qi "^x-powered-by:" <<<"$web" && bad "web app reveals x-powered-by" || ok "web app hides x-powered-by"

echo
[[ $fail == 0 ]] && echo "Security checks passed." || echo "Security checks found problems."
exit $fail
