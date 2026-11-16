# Installation and deployment tutorial

This guide installs **What Do You Want to Play?** on a Linux server, behind a
Traefik reverse proxy you already run. The whole deployment is three steps:

1. configure `.env`;
2. run `./build.sh`;
3. run `docker compose up -d`.

The same two commands also update an existing installation. Everything else is
automatic:

- creating the database on the first start, and reusing it afterwards;
- database migrations;
- configuration checks;
- start order.

Conventions: `bash` blocks are commands to run. Lines like `PUBLIC_HOSTNAME=...` are
values to put in `.env`. `<ANGLE_BRACKETS>` are values only you know; replace them,
brackets included. ⚠️ marks destructive operations.

---

## A. Prerequisites

- **Server:** 64-bit Linux, for example Ubuntu Server 24.04 LTS or Debian 12/13.
  At least 4 CPU cores, 8 GB RAM and 20 GB free disk. 2 cores and 4 GB are enough
  for a small private site.
- **Docker Engine with the Compose plugin** (`docker compose version` shows v2.24 or
  newer). Install them with Docker's official guide:
  <https://docs.docker.com/engine/install/>. Then let your user run Docker, and log
  out and back in:

  ```bash
  sudo usermod -aG docker "$USER"
  ```

  > ⚠️ Members of the `docker` group effectively have root access. Add only trusted
  > administrators.

- **Git** and **OpenSSL**: `sudo apt-get install -y git openssl`.
- **Traefik, already running** on this server, with:
  - its Docker provider enabled (it reads container labels);
  - an HTTPS entrypoint;
  - a certificate resolver (for example Let's Encrypt).

  This application does not install Traefik.
- **Network:** the server reaches the internet over HTTPS (Steam). The application
  opens **no ports** on the server; visitors only arrive through Traefik (ports 80
  and 443, which Traefik already uses).
- **Domain and DNS:** a domain or subdomain (for example `play.example.org`) whose
  DNS record points to this server. Let's Encrypt needs it before the first start.

## B. Obtain the project

```bash
sudo mkdir -p /srv/wdywtp && sudo chown "$USER": /srv/wdywtp
git clone <REPOSITORY_URL> /srv/wdywtp
cd /srv/wdywtp
```

If you received a zip file instead: `unzip <FILE>.zip -d /srv`, then
`cd /srv/wdywtp`.

All commands below run in this directory: it holds `build.sh`, `docker-compose.yml`
and, once created, `.env`.

## C. Configure `.env`

`.env`, next to `docker-compose.yml`, is the only configuration file. Create it from
the template, make it private, and fill in the four passwords with random values:

```bash
cp .env.example .env
chmod 600 .env
for k in POSTGRES_SUPERUSER_PASSWORD DB_MIGRATION_PASSWORD DB_PASSWORD REDIS_PASSWORD; do sed -i "s/^$k=\$/$k=$(openssl rand -hex 24)/" .env; done
nano .env
```

Every variable is explained inside the file. `docker compose up -d` refuses to start
while a required value is empty.

> ⚠️ Set the passwords **before the first start**. PostgreSQL stores them when it
> creates the database, so changing them later takes a few extra commands (section I,
> "Rotate a password").

### Required values

| Variable | What to put |
|---|---|
| `PUBLIC_HOSTNAME` | Your domain, without `https://`: `play.example.org` |
| `PUBLIC_BASE_URL` | The same with `https://`: `https://play.example.org`. Steam sign-in returns here. |
| `TRAEFIK_NETWORK` | The Docker network your Traefik container is on (see below) |
| `TRAEFIK_CERT_RESOLVER` | The name of the certificate resolver in your Traefik configuration |
| `FORWARDED_ALLOW_IPS` | The subnet of that network (see below), so the app sees visitors' real IPs |
| `POSTGRES_SUPERUSER_PASSWORD`, `DB_MIGRATION_PASSWORD`, `DB_PASSWORD`, `REDIS_PASSWORD` | Already filled in by the command above |
| `STEAM_WEB_API_KEY` | Needed for automatic library import (see below) |

### Traefik settings

Find the network Traefik uses and its subnet:

```bash
docker ps --format '{{.Names}}' | grep -i traefik
docker inspect <TRAEFIK_CONTAINER> --format '{{range $n, $_ := .NetworkSettings.Networks}}{{$n}} {{end}}'
docker network inspect <TRAEFIK_NETWORK> --format '{{(index .IPAM.Config 0).Subnet}}'
```

Put the network name in `TRAEFIK_NETWORK` and the subnet (for example
`172.18.0.0/16`) in `FORWARDED_ALLOW_IPS`. `TRAEFIK_ENTRYPOINT` (default
`websecure`) and `TRAEFIK_CERT_RESOLVER` come from Traefik's own static
configuration: its `entryPoints` and `certificatesResolvers` sections.

The routing is already defined in `docker-compose.yml`:

- `https://<domain>/api` goes to the `backend` container;
- everything else goes to the `frontend` container;
- HSTS and security headers are added.

To adapt it, look for the blocks marked `TRAEFIK ROUTING ... (edit here ...)`. You
can add your own middlewares, or remove the `certresolver` lines if Traefik already
has a certificate for the domain. Only `frontend` and `backend` join Traefik's
network; the database and Redis never do.

### Steam Web API key

1. Sign in at <https://steamcommunity.com/dev/apikey> with the Steam account that
   will own the key.
2. Enter your domain, accept Valve's terms and register.
3. Copy the 32-character key into `STEAM_WEB_API_KEY`.

Keep it secret: only the backend and worker use it, and it is never sent to
browsers. Without a key, people can sign in, but they must add their games by hand.

### Optional values

- **`AI_GRADE`** (default `TRUE`): selects how recommendations are scored.
  - `TRUE`: machine-learning ranking. Models are trained nightly and used once
    they have enough data and pass their quality checks.
  - `FALSE`: classic, deterministic scoring only, and no model training.

  Only `TRUE` or `FALSE` is accepted.
- **IGDB** (completion times): keep `IGDB_ENABLED=false` unless you have accepted
  IGDB's terms. Then set it to `true` and fill in `IGDB_CLIENT_ID` and
  `IGDB_CLIENT_SECRET` from a Twitch developer application.
- **The other settings** (capacity, recommendation weights, sessions, rate limits,
  retention) have tested defaults.

## D. Build the images

```bash
./build.sh
```

It builds three local images, all with the fixed tag `1.0`:

| Image | From | Used by |
|---|---|---|
| `wdywtp-backend:1.0` | `./backend` | `migrate`, `backend`, `worker`, `scheduler` |
| `wdywtp-frontend:1.0` | `./frontend` | `frontend` |
| `wdywtp-postgres:1.0` | `./docker/postgres` | `postgres` (official PostgreSQL 18 + database setup scripts) |

The first build takes several minutes. It ends with `BUILD SUCCEEDED` and the image
list. It does not start anything and does not read `.env`.

## E. Deploy

```bash
docker compose up -d
```

This is the only deployment command. Docker Compose then:

1. downloads the official Redis image if it is missing;
2. creates the persistent volumes on the first run, and reuses them afterwards;
3. starts PostgreSQL:
   - **first installation** (empty volume): it creates the database and its users;
   - **existing installation**: it reuses the data as is and skips that step;
4. runs `migrate`. It checks the configuration, applies any database updates that
   are still pending, and exits. If it fails, the application does not start (see
   section I);
5. starts the backend, worker and scheduler, then the frontend once the backend is
   healthy.

After a minute, open `https://<your-domain>/`. You should see the home page with a
**Sign in through Steam** button.

**First use:**

1. Sign in through Steam.
2. In Steam, set **Game details** to Public (Profile → Edit Profile → Privacy
   Settings).
3. The library imports automatically, and recommendations appear a few minutes later.

"Trending Games" stays empty for about six weeks while player-count history builds
up; a "Popular right now" list is shown meanwhile.

## F. Check application status (optional)

These are diagnostics, not deployment steps:

```bash
docker compose ps
docker compose logs --tail 100
docker compose logs --tail 100 backend
docker compose exec backend python -c "import urllib.request as u; print(u.urlopen('http://127.0.0.1:8000/api/health/ready').read().decode())"
```

What healthy looks like:

- `docker compose ps` shows `postgres`, `redis`, `backend`, `worker` and `frontend`
  as `(healthy)`, and `scheduler` as `Up`;
- `migrate` has finished, so it is not listed;
- the last command prints `"status":"ok"` and the active `"scoring_mode"`.

For more detail:

```bash
docker compose exec worker python -m app.cli status
```

It shows the queues, workers, Steam calls, training and database size.

## G. Updating the application

Exactly the same two commands:

```bash
git pull
./build.sh
docker compose up -d
```

`./build.sh` replaces the `1.0` images. `docker compose up -d` then recreates only
the containers whose image or configuration changed, and runs `migrate`, which
applies only the new database updates. **The database and other volumes are kept:**
existing data is never deleted, copied or reinitialised by an update.

To change a setting in `.env` (for example `AI_GRADE`), edit the file and run
`docker compose up -d` again.

> ⚠️ **Never** use `docker compose down -v`, `docker volume rm` or
> `docker volume prune` as part of a deployment: they **delete the database**.
> `docker compose down`, `stop` and `restart` (without `-v`) are safe.

## H. Backup and restore (administration)

These are maintenance tools. A normal deployment never needs them.

**Back up** the database to `backups/<name>-<date>.dump`. The file is private
(mode 600), and the newest 14 are kept:

```bash
./scripts/backup-db.sh
```

To back up every night at 03:15, add this line with `crontab -e`:

```
15 3 * * * cd /srv/wdywtp && ./scripts/backup-db.sh >> backups/backup.log 2>&1
```

Copy `backups/` to another machine too; that part is not automated.

**Test a backup** without touching the live site. This restores it into a separate
test database, compares row counts, then deletes the test database:

```bash
./scripts/restore-db.sh backups/<FILE>.dump --drop-after
```

**Restore over the live database:**

> ⚠️ Destructive: this replaces the current database with the backup. Everything
> written since the backup is lost.

```bash
./scripts/restore-db.sh backups/<FILE>.dump --overwrite-live
```

It stops the application, recreates the database with its users, restores the data
and starts everything again.

**On a new server:**

1. Install it with sections A to E. A new `.env` with new passwords is fine.
2. Copy the dump into `backups/`.
3. Run the `--overwrite-live` command above.

## I. Troubleshooting

Start with `docker compose ps -a` and the logs of the failing service:
`docker compose logs --tail 100 <service>`. The services are `postgres`, `redis`,
`migrate`, `backend`, `worker`, `scheduler` and `frontend`.

For a plain-language check of `.env` (never prints secrets), run
`./scripts/check-env.sh`.

**Image build fails** (`BUILD FAILED`):

- Read the lines above the message.
- `cannot reach the Docker daemon`: start Docker, and check your user is in the
  `docker` group (A).
- A download error during the build is usually a network or DNS problem on the
  server.

**`required variable ... is missing a value`:** that variable is empty in `.env`
(section C).

**`No such image: wdywtp-...:1.0`:** run `./build.sh` first.

**`network ... declared as external, but could not be found`:** `TRAEFIK_NETWORK`
does not match an existing network. Check it with `docker network ls`.

**Other Compose errors:** `docker compose config --quiet` names the problem in
`docker-compose.yml` or `.env`.

**PostgreSQL does not become healthy:** `docker compose logs postgres`.

- `password authentication failed`: a database password in `.env` was changed after
  the first start. Restore the old value, or change it properly (below).
- Also check free disk space with `df -h`.

**`migrate` failed, so backend, worker and scheduler did not start:**
`docker compose logs migrate`.

- `Configuration INVALID` names the setting: for example `AI_GRADE`, a placeholder
  password, or a `PUBLIC_BASE_URL` that is not `https` in production. Fix `.env`,
  then run `docker compose up -d`.
- A migration error leaves that update unapplied and the data untouched. Keep the
  log and report it.

**Redis problems:** `docker compose logs redis`. An authentication error after
changing `REDIS_PASSWORD` is fixed by `docker compose up -d`, which recreates every
service with the new value.

**Traefik routing:**

- `docker logs <TRAEFIK_CONTAINER> 2>&1 | grep -i wdywtp`
- A 404 from Traefik means:
  - `PUBLIC_HOSTNAME` doesn't match the domain you opened;
  - or the Docker provider is off;
  - or `frontend`/`backend` are not on `TRAEFIK_NETWORK`. Check with
    `docker network inspect <TRAEFIK_NETWORK> --format '{{range .Containers}}{{.Name}} {{end}}'`.
- A 502 means the container isn't healthy yet (check `docker compose ps`).

**HTTPS certificate** (the browser warns; issuer `TRAEFIK DEFAULT CERT`):

- `Router uses a nonexistent certificate resolver` in Traefik's log:
  `TRAEFIK_CERT_RESOLVER` is wrong.
- ACME or challenge errors: the DNS record, or ports 80/443, are not reachable from
  the internet.

**Steam:**

- Sign-in fails or returns to a different address: `PUBLIC_BASE_URL` must be exactly
  `https://<domain in the browser>`.
- "Game details are private": change the Steam privacy setting, then click
  **Try again**.
- Imports fail with `provider_auth_error`: the Steam key was rejected. Check it at
  the Steam page, update `.env`, then run `docker compose up -d`.

**AI models not used** (`AI_GRADE=TRUE`): this is normal until enough players and
ratings exist. The site uses classic scoring meanwhile. See why:

```bash
docker compose exec worker python -m app.cli report
```

**Rotate a password:** Redis only needs a new value in `.env` and
`docker compose up -d`. A database password must also change inside PostgreSQL
first. For `DB_PASSWORD` (role `wdywtp_app`):

```bash
NEW=$(openssl rand -hex 24)
printf "ALTER ROLE wdywtp_app PASSWORD '%s';\n" "$NEW" | docker compose exec -T postgres psql -U postgres -d postgres -q
sed -i "s/^DB_PASSWORD=.*/DB_PASSWORD=$NEW/" .env && unset NEW
docker compose up -d
```

Use role `wdywtp_owner` for `DB_MIGRATION_PASSWORD`, and `postgres` for
`POSTGRES_SUPERUSER_PASSWORD`.

**Go back to the previous version** if an update misbehaves:

```bash
git checkout <PREVIOUS_COMMIT>
./build.sh
docker compose up -d
```

If that update included a database change, the older version reports "not ready".
Restore the backup taken before the update (section H), and ask the developers.
