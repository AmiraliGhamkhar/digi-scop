# DigiScope deployment guide

DigiScope is designed first for one Linux host, one FastAPI web process, one
SQLite database, and cron. It has not been deployed by this repository and no
hosting compatibility should be assumed without the checks below.

## Recommended topology

```text
Internet
   │ HTTPS
Reverse proxy (Nginx/Caddy)
   │ HTTP on 127.0.0.1
One Uvicorn worker
   │
Private SQLite + locks + logs + backups
   ▲
One local cron scheduler
   │ outbound HTTPS
Configured Digikala MCP endpoint
```

Why one worker:

- SQLite permits concurrent reads but serializes writes;
- collection can also be triggered by the web process;
- the supplied lock coordinates processes on one filesystem, not multiple hosts;
- the expected MVP load does not require horizontal scale.

Move to a server database and distributed job coordination before adding hosts or
workers that can write concurrently.

## Host prerequisites

Verify all of these on the target:

- Python 3.11 or newer;
- ASGI process support and a way to keep Uvicorn running;
- outbound HTTPS/DNS access to `DIGIKALA_MCP_URL`;
- private writable local storage for SQLite and lock files;
- cron or an equivalent reliable external scheduler;
- TLS termination and configurable reverse proxy timeouts;
- sufficient disk for DB, WAL, logs, and retained backups;
- an unprivileged service account and file permission control.

## Filesystem layout

Example:

```text
/srv/digiscope/                 application checkout, not public
/srv/digiscope/.venv/           virtual environment
/srv/digiscope/.env             mode 0600
/var/lib/digiscope/digiscope.db private SQLite database
/var/lib/digiscope/locks/       collection locks
/var/backups/digiscope/         mode-restricted backups
/var/log/digiscope/             rotated logs if not using journald
```

Corresponding settings:

```dotenv
APP_ENV=production
DATABASE_URL=sqlite:////var/lib/digiscope/digiscope.db
COLLECTION_LOCK_DIR=/var/lib/digiscope/locks
ADMIN_TOKEN=<random value of at least 24 characters>
```

Do not place `.env`, `data`, locks, database, logs, or backups under `public_html`
or `app/static`.

## Install and migrate

```bash
cd /srv/digiscope
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
# edit .env and protect it
chmod 600 .env
alembic upgrade head
pytest -q
python -m scripts.check_mcp --call-data
```

The live MCP check is a deployment gate. A green upstream GitHub workflow is not
a substitute for testing outbound access from the real host.

## Process manager example

A minimal systemd service can run Uvicorn as an unprivileged account:

```ini
[Unit]
Description=DigiScope web application
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=digiscope
Group=digiscope
WorkingDirectory=/srv/digiscope
EnvironmentFile=/srv/digiscope/.env
ExecStart=/srv/digiscope/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

Host hardening options vary. Test database/lock/backup permissions before adding
filesystem sandbox directives.

After installation:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now digiscope
sudo systemctl status digiscope
curl -fsS http://127.0.0.1:8000/ready
```

## Reverse proxy example

Nginx outline:

```nginx
server {
    listen 443 ssl http2;
    server_name digiscope.example.com;

    # Configure maintained certificate/key paths and modern TLS policy here.

    client_max_body_size 1m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 120s;
    }
}
```

Collection can wait on upstream timeouts/retries, so an authenticated manual
request may need a longer proxy read timeout. Cron remains the preferred path.
Do not add permissive CORS headers at the proxy.

## Scheduler

Example daily cron under the same service account:

```cron
17 2 * * * cd /srv/digiscope && /srv/digiscope/.venv/bin/python -m scripts.collect >> /var/log/digiscope/collection.log 2>&1
```

Use one scheduler host. Configure log rotation and monitor exit status. See the
[operations runbook](operations.md) for scope management and collection volume.

## cPanel/shared hosting assessment

Do not promise cPanel compatibility until all answers are known:

1. **Python:** Is Python 3.11+ available in an isolated environment?
2. **ASGI:** Can the host run Uvicorn persistently, or does it support only WSGI?
3. **Proxy:** Can the domain proxy HTTPS requests to the ASGI process?
4. **Outbound network:** Can Python reach the configured Workers endpoint over
   HTTPS without a restrictive allowlist?
5. **Private storage:** Is there a writable path outside `public_html` with stable
   ownership and enough space?
6. **Cron:** Can cron activate the virtualenv, load `.env`, and run long enough?
7. **Processes:** Can the panel unexpectedly create multiple app workers or
   restart jobs during collection?
8. **Backups:** Can private SQLite backups be retained and copied off-host?
9. **Timeouts:** Can proxy/application timeouts accommodate bounded upstream
   calls?

If the platform only offers Passenger WSGI, blocks outbound HTTPS, has ephemeral
files, or cannot run cron reliably, use a small VPS instead. An external
scheduler may call the authenticated endpoint over HTTPS, but it introduces token
management and should not replace missing persistent storage.

## Environment configuration

Start from `.env.example`. Production-sensitive points:

- `APP_ENV=production` enables production token validation.
- `APP_HOST`/`APP_PORT` are validated application settings but the supplied
  launch commands do not consume them; Uvicorn CLI flags are the actual bind
  configuration.
- `APP_TIMEZONE` must be a valid IANA name. Stored timestamps remain UTC.
- `DATABASE_URL` must point to private persistent storage.
- `DIGIKALA_MCP_URL` should remain a fixed trusted endpoint.
- MCP timeout/retry settings should stay conservative; retries consume the public
  request budget.
- `COLLECTION_INTERVAL_MINUTES` must match the real scheduler cadence for honest
  expected-run coverage; it does not start or throttle a scheduler.
- In `0.1.x`, `COLLECTION_ENABLED` controls production startup token validation,
  not collector execution. For a read-only deployment, set it to `false`, omit
  `ADMIN_TOKEN`, and disable cron; changing this flag alone is not a runtime kill
  switch.
- `PRICE_HISTORY_PRODUCTS_PER_RUN=0` disables history enrichment by default.
- `ADMIN_TOKEN` must be random, private, and at least 24 characters in production.

## Upgrade procedure

1. Disable cron and stop HTTP-triggered collection.
2. Create and verify a database backup.
3. Fetch/review the intended application revision.
4. Install updated dependencies in the virtualenv.
5. Run the test suite.
6. Stop the web service if the migration is not known to be online-safe.
7. Run `alembic upgrade head`.
8. Start/restart the web service.
9. Verify `/ready`, dashboard/API reads, and one conservative MCP check.
10. Re-enable cron and monitor the first run.

Never run a downgrade against the only production copy without a tested backup.

## Scaling boundary

The current design should be changed before:

- multiple web workers can trigger writes;
- multiple scheduler hosts collect the same scopes;
- the DB is placed on network/shared storage;
- write volume regularly creates SQLite contention;
- availability requires more than one application host.

A future scaled architecture would require a server database, distributed locking
or a job queue, migration/backup changes, and explicit scheduler ownership. Those
components are intentionally outside the MVP.

## Go-live checklist

- [ ] Production `.env` is private and contains no placeholder token.
- [ ] Database, locks, logs, and backups are outside the public root.
- [ ] `alembic current` reports the expected head.
- [ ] `pytest -q` passes on the deployed revision.
- [ ] `python -m scripts.check_mcp --call-data` succeeds from the host.
- [ ] `/ready` returns HTTP 200 through the reverse proxy.
- [ ] TLS and additional access controls are configured as required.
- [ ] One cron schedule and one Uvicorn worker are active.
- [ ] Backup, restore, retention, and alert procedures were exercised.
- [ ] Dashboard labels demo/incomplete/stale/error states correctly.
- [ ] Operators understand the global top-30 upstream limit and lack of
      historical rank backfill.
