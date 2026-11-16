# Backup and recovery guide

What to back up, how, and how to recover from each kind of failure. Commands assume
the repository directory on the server (for example `/srv/wdywtp`).

## What holds data

| Volume / place | Contents | Back up? |
|---|---|---|
| `postgres-data` | Everything durable: accounts, libraries, playtime history, feedback, events, recommendations, model registry and reports | **Yes, daily** |
| `models` | Model artifacts and Markdown evaluation reports | Optional: rebuilt by the next training run; reports are also in the database |
| `redis-data` | Queues, rate-limit counters, cooldowns | No: nothing durable |
| `.env` | Secrets and configuration | **Yes**, separately and encrypted (password manager or vault) |

## Daily database backup

```cron
15 3 * * *  cd /srv/wdywtp && ./scripts/backup-db.sh >> backups/backup.log 2>&1
```

- Writes `backups/<db>-<UTC timestamp>.dump` (custom format, compressed, mode 600) and
  keeps the newest 14 (`BACKUP_KEEP`).
- **Copy `backups/` off the server** (another disk or host). A backup next to the
  database doesn't survive the loss of that disk.
- Backups contain personal data: keep them encrypted at rest off the server, and
  state their retention in the privacy policy. Account deletions reach backups only
  when old dumps rotate out (14 days by default).

## Rehearse a restore (monthly, and after schema changes)

```bash
./scripts/restore-db.sh backups/<file>.dump --drop-after
```

This restores into a scratch database `<db>_restore_check`, recreated with the normal
owner and runtime roles and grants. It then prints the schema revision and row counts
next to the live database, checks that the runtime role can read the data, and drops
the scratch database. The live database and the running app are untouched.

Last rehearsal: see [TESTING.md](TESTING.md) ("Backup and restore").

## Recovery procedures

### Database lost or corrupted

```bash
./scripts/restore-db.sh backups/<file>.dump --overwrite-live
```

This stops the frontend, backend, worker and scheduler, then drops and recreates the
live database with its roles and grants. It restores the dump, prints row counts,
restarts everything and waits until `/api/health/ready` is healthy. Data since the
dump is lost. Players' libraries come back on their next sync; feedback given since
the dump does not.

### A bad deployment (new code)

Step by step: [tutorial.md](../tutorial.md), section I ("Go back to the previous version"). In short:

```bash
docker compose run --rm --no-deps migrate alembic downgrade <revision>   # only if the update migrated
git checkout <previous tag>
./build.sh
docker compose up -d
```

Run the downgrade while the new code is still checked out (it holds the downgrade
steps), after taking a fresh backup. The alternative is restoring the pre-update
backup. Downgrade 0008 → 0007 and the re-upgrade were rehearsed on a test deployment
(2026-11-15).

### A bad model

```bash
docker compose exec worker python -m app.cli models                 # list versions
docker compose exec worker python -m app.cli rollback <version>     # redeploy a kept one
```

Lists rebuild with the restored model on each player's next refresh.

There is no "undeploy" command. To stop using a model when no good earlier version is
kept, move its artifact file out of the `models` volume. Serving then falls back to
content-based Match, and recommendations keep working (tested behaviour). The next
training run that passes its gates deploys a new model.

### Redis lost

`docker compose up -d redis`. Nothing durable is lost. Queued jobs disappear. Player
lists rebuild on their next visit, sync or the next scheduled job; training and
monitoring run again at their next schedule (or run `app.cli train`).

### Worker stuck or crashed

`docker compose restart worker`. Tasks are acknowledged late, so a task interrupted
mid-run is redelivered. A library sync stuck in `queued` (lost message) blocks new
syncs for that user (OPEN_QUESTIONS #17). Clear it with:

```bash
docker compose exec -T postgres psql -U postgres -d wdywtp \
  -c "UPDATE library_sync_runs SET status='failed', error_code='manual_reset' WHERE status IN ('queued','running') AND queued_at < now() - interval '1 hour'"
```

### Steam unavailable

Nothing to do. Sign-in, imports and metadata fail with clear messages. Calls are cut
short for 2 minutes after a failure (circuit breaker). Existing recommendations keep
being served. Trend scores pause if player counts are older than 26 hours, and resume
by themselves.

### Server lost

On a new host, follow [tutorial.md](../tutorial.md) sections A to E (a new `.env` with
new secrets is fine), copy the latest dump into `backups/`, then run
`./scripts/restore-db.sh backups/<latest dump> --overwrite-live` and
`docker compose exec worker python -m app.cli train` to rebuild models (tutorial.md, section H).
Rehearsed on 2026-11-15: a dump from one test deployment restored into a second one
with different secrets; the runtime role read the data and the app reported ready.
