# DigiScope operations runbook

This runbook covers a single-host SQLite deployment. Read
[`deployment.md`](deployment.md) before choosing a host and
[`SECURITY.md`](../SECURITY.md) before exposing the application.

## Initial installation

```bash
cd /srv/digiscope
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```

Generate an administrative token if HTTP-triggered collection is required:

```bash
python -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Store the result only as `ADMIN_TOKEN` in the protected `.env`. In production it
must contain at least 24 characters.

Create/migrate the database before starting the web process:

```bash
alembic upgrade head
alembic current
```

Readiness intentionally returns 503 when required tables are absent.

## Start and verify

Development:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Production process (normally behind a TLS reverse proxy):

```bash
APP_ENV=production uvicorn app.main:app \
  --host 127.0.0.1 --port 8000 --workers 1
```

Checks:

```bash
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/ready
curl -fsS http://127.0.0.1:8000/api/collection/status
```

Expected readiness body:

```json
{"status":"ok","database":"ready","version":"0.1.0","timestamp":"..."}
```

## Verify upstream MCP access

Run this from the actual collection host, because firewalls and region-specific
CDN challenges differ from development/CI:

```bash
# Protocol initialization and required tools
python -m scripts.check_mcp

# Also retrieve and normalize three current cards
python -m scripts.check_mcp --call-data
```

Interpretation:

- `MCPHTTPError: MCP network request failed`: DNS, firewall, TLS, or outbound
  access failed before a valid MCP response.
- HTTP 429: the public per-IP budget was exceeded; DigiScope honours
  `Retry-After`, but scope/request volume should be reduced.
- An MCP tool message asking for a retry: Digikala temporarily challenged the
  upstream service region; wait instead of increasing concurrency.
- Missing required tool: upstream contract drift; stop collection and compare
  with `docs/MCP_INTEGRATION_REPORT.md` before adapting code.

The normal test suite never requires live MCP access.

## Collection commands

All enabled scopes using the configured default limit:

```bash
python -m scripts.collect
```

Explicit limit:

```bash
python -m scripts.collect --limit 20
```

One or more known categories, with optional global scope:

```bash
python -m scripts.collect --category-id 2 --limit 20
python -m scripts.collect --category-id 2 --category-id 3 --no-global --limit 20
```

Bounded short price-history import:

```bash
# In .env, for example:
# PRICE_HISTORY_PRODUCTS_PER_RUN=3
python -m scripts.collect --limit 20 --with-price-history
```

A zero history limit intentionally produces a partial warning instead of making
unbounded requests. Ranking rows are committed before optional history
retrieval; history failure cannot erase valid ranks.

The command prints JSON outcomes and exits nonzero if any scope failed. A busy
scope is reported as skipped.

## Manage scheduled scopes

A successful global collection stores categories exposed by `best_selling`.
List known categories and configured scopes:

```bash
python -m scripts.manage_scopes list
```

Enable one known category conservatively:

```bash
python -m scripts.manage_scopes add-category 2 --interval 1440
```

Disable or re-enable a scope by its scope ID:

```bash
python -m scripts.manage_scopes set-enabled 2 false
python -m scripts.manage_scopes set-enabled 2 true
```

Do not recursively enable every category. Estimate daily POST volume first and
stay below the upstream public limit with room for initialization, retries, and
manual diagnostics.

`interval_minutes` is the expected cadence used by coverage calculations. It is
not an in-process timer: with no `--category-id`, `scripts.collect` runs every
enabled scope on every invocation. Give enabled scopes the same real cron
cadence. For a different category cadence, keep that recurring scope disabled
and use an explicit `--category-id ... --no-global` cron entry whose schedule
matches its interval.

## Cron scheduling

One daily run at 02:17 server local time:

```cron
17 2 * * * cd /srv/digiscope && /srv/digiscope/.venv/bin/python -m scripts.collect >> /srv/digiscope/data/collection.log 2>&1
```

Operational rules:

- use one scheduler host;
- ensure cron can read `.env` and write `data/` without broadening permissions;
- configure OS log rotation for `collection.log`;
- alert on nonzero exit status or repeated failed runs;
- align cron cadence with each scope's `interval_minutes`, because that interval
  defines expected historical opportunities;
- leave conservative time between runs rather than batching bursts.

A per-scope Unix file lock prevents overlap on one shared filesystem. It is not a
distributed lock across machines.

## Authenticated manual collection

Prefer cron for normal operation. For an exceptional HTTPS trigger:

```bash
curl --fail-with-body -X POST https://your-host.example/api/collection/run \
  -H 'Content-Type: application/json' \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  -d '{
    "include_global": true,
    "category_ids": [],
    "limit": 10,
    "include_price_history": false
  }'
```

The endpoint is synchronous, applies a two-second process-local burst guard, and
uses the same scope lock as cron. Never place the token in a URL.

## Collection health

Inspect:

```bash
curl -fsS http://127.0.0.1:8000/api/collection/status | python -m json.tool
```

Review:

- latest status and finish timestamp;
- `items_fetched` versus `items_saved`;
- duration changes;
- partial warnings in `source_metadata`;
- repeated safe error type/message;
- scope `last_success_at` and `last_error_at`;
- dashboard stale state and 7-day/30-day coverage.

Failed runs remain in diagnostics and do not count as product absences.

## Database maintenance

### Migrations

Before a new migration:

```bash
python -m scripts.backup_db ./data/backups
alembic current
alembic upgrade head
curl -fsS http://127.0.0.1:8000/ready
```

For risky upgrades, stop web and cron first. Test downgrade behaviour in a copy;
do not assume every future data migration is safely reversible.

### Backup

Create a transactionally consistent online backup with SQLite's backup API:

```bash
python -m scripts.backup_db ./data/backups
```

The command:

- resolves the file from `DATABASE_URL`;
- writes a timestamped file;
- performs `PRAGMA integrity_check`;
- sets mode `0600`.

Copy verified backups to encrypted off-host storage and define retention. Do not
serve `data/backups` from a web document root.

### Restore

1. Stop web and collection processes.
2. Make a forensic copy of the current DB and its `-wal`/`-shm` files.
3. Copy the selected backup to the exact file path in `DATABASE_URL`.
4. Remove stale `-wal` and `-shm` files only while all processes are stopped.
5. Run:

   ```bash
   alembic current
   alembic upgrade head
   python - <<'PY'
   import sqlite3
   from app.config import Settings
   from sqlalchemy.engine import make_url
   path = make_url(Settings().database_url).database
   with sqlite3.connect(path) as db:
       print(db.execute('PRAGMA integrity_check').fetchone()[0])
   PY
   ```

6. Start the web process and verify `/ready`, dashboard counts, and recent runs.
7. Re-enable cron after the read path is correct.

## Development/demo data

Only in `APP_ENV=development` or `test`:

```bash
python -m scripts.seed_demo_data
python -m scripts.seed_demo_data --reset
```

The reset removes/replaces labelled demo rows, not arbitrary live products.
Confirm the UI displays the demo warning. Never seed production.

## Logs

DigiScope writes structured JSON logs to standard output. Collection logs include
start/finish/failure, tool method, HTTP status, duration, and counts without tool
arguments or complete payloads.

Production should provide:

- service-manager capture (systemd, container runtime, or hosting panel);
- size/time rotation;
- retention appropriate to operational needs;
- alerts for repeated `collection_failure`, `database_error`, HTTP 503, or stale
  coverage;
- access restrictions because product IDs and safe upstream diagnostics are still
  operational data.

## Troubleshooting

### `/ready` returns 503

- Run `alembic current` and `alembic upgrade head`.
- Verify `DATABASE_URL`, directory ownership, and free disk space.
- Ensure the DB is not inside a read-only application package.

### `database is locked`

- Confirm one web worker and one scheduler host.
- Inspect overlapping manual/cron processes.
- Keep SQLite on a local filesystem, not NFS/shared object storage.
- Check long-running backup or migration operations.

DigiScope already enables WAL and a 30-second busy timeout; repeated lock errors
indicate an unsupported concurrency/topology issue.

### Current rankings are empty

- Check for a successful run with `items_saved > 0`.
- Run the live MCP check from the same host.
- Verify the selected scope/method and category ID.
- Do not fill an empty result with earlier/current data manually.

### 7-day/30-day comparison is unavailable

- A product needs at least two real observations in the selected window.
- Review successful versus expected runs and earliest/latest timestamps.
- Wait for scheduled history; do not backdate current rows.

### Global top 50 contains at most 30 rows

This is the documented maximum of the upstream global `best_selling` tool, which
has no page parameter. It is an upstream contract limit, not a database failure.
Category lists can use verified pagination.

### Price chart is empty

- Set a positive `PRICE_HISTORY_PRODUCTS_PER_RUN`.
- Collect with `--with-price-history`.
- Confirm the product has a numeric upstream ID.
- Some products legitimately have no chart points.

## Routine checklist

Daily/automated:

- cron exit status;
- latest successful timestamp;
- failed/partial run count;
- disk space and DB/backup growth;
- stale dashboard state.

Weekly:

- backup restore test in a temporary location;
- 7-day/30-day coverage progression;
- MCP live check and schema warnings;
- dependency/security advisories;
- log and backup retention.
