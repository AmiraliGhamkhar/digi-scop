# DigiScope

**DigiScope** is a Persian, RTL market-intelligence dashboard for recording and
analysing observable Digikala product rankings and prices. It is a single
FastAPI application with a vanilla-JavaScript frontend, SQLite persistence, a
standalone cron-friendly collector, and a replaceable MCP adapter.

> **Data integrity:** a rank in DigiScope means an observed position in a list at
> a recorded time. It is not a sales quantity. Failed collections are not treated
> as product absences, current ranks are never copied into the past, and missing
> history remains visibly missing.

## What is implemented

- Current global and category ranking observations with 10/20/50 display limits.
- Coverage-aware rolling 7-day and 30-day reports: average/best/latest rank,
  earliest-to-latest improvement, presence rate, and observation counts.
- A documented **ranking-based trend indicator**, explicitly not sales growth.
- Product details with independent ranking and price timelines.
- Nullable price, discount, rating, rating count, availability, URL, and image
  handling; unavailable upstream fields are not fabricated.
- UTF-8 BOM CSV export with Persian headers and spreadsheet-formula protection.
- Collection run health, failures, timing, configured scopes, and stale-data state.
- Authenticated manual collection plus a standalone scheduled collection command.
- Per-scope cross-process file locks and SQLite foreign keys/WAL/busy timeout.
- Structured JSON logs, `/health`, `/ready`, OpenAPI docs, and safe browser headers.
- A deterministic development-only fixture that is visibly labelled in the UI.

## Documentation

- [Documentation index](docs/README.md)
- [Architecture](docs/architecture.md)
- [REST API reference](docs/api.md)
- [Data-integrity and analytics semantics](docs/data-integrity.md)
- [Operations runbook](docs/operations.md)
- [Deployment guide](docs/deployment.md)
- [Testing guide](docs/testing.md)
- [Security policy](SECURITY.md) and [changelog](CHANGELOG.md)
- [Persian guide / راهنمای فارسی](README_FA.md)

Upstream MCP material is explicitly separated in the
[integration report](docs/MCP_INTEGRATION_REPORT.md) and
[tool-contract snapshot](docs/tools.md).

## MCP contract inspection

The upstream `mmdju/digikala-mcp` repository was inspected at commit
`927ab481bb2d1292410b1b3858c691a844102c6d`. It is intentionally a showcase
repository without Worker source. Its docs verify Streamable HTTP, the
`2024-11-05` handshake used by its examples, 19 read-only tools, text JSON in
MCP content, no required session, a 20 POST/minute/IP limit, and transient
Digikala CDN blocks.

The adapter supports direct JSON and SSE responses, textual and structured tool
content, optional MCP session IDs, JSON-RPC/tool/HTTP errors, timeouts, bounded
exponential retries, and `Retry-After`.

The exact inspected findings and relevant tool schemas are in
[`docs/MCP_INTEGRATION_REPORT.md`](docs/MCP_INTEGRATION_REPORT.md); the upstream
parameter reference remains in [`docs/tools.md`](docs/tools.md).

### Important upstream limits

- `best_selling` has a documented maximum `limit` of **30** and no page argument,
  even though its estimated complete list is 50. DigiScope allows a top-50 view
  but honestly returns only the global observations that the tool exposes and
  marks a top-50 collection partial. Category `browse_category` supports paging
  and can collect up to 50.
- `product_price_chart` offers about 30 daily price points per colour/size, with
  seller/warranty where supplied. It is not full product history.
- No inspected tool provides historical bestseller ranks or units sold. Rank
  history starts when DigiScope starts collecting.
- The endpoint could not be reached from this restricted build sandbox. The
  adapter follows the inspected contract and is deterministically tested; run
  the live check below from the deployment host.

## Architecture

```text
Browser (Persian RTL, vanilla JS, Chart.js)
                  │ relative REST/HTML
                  ▼
        Single FastAPI process
         ├── REST + templates/static
         ├── analytics services
         ├── collection service
         └── SQLAlchemy 2 / SQLite
                  ▲
                  │ standalone cron command
                  │
       Digikala MCP adapter (HTTPX)
                  │ Streamable HTTP / JSON-RPC
                  ▼
   digikala-mcp.mmdju.workers.dev
```

The web process does **not** start an in-process scheduler, so multiple worker
starts cannot duplicate scheduled jobs. Cron invokes a separate command; a
per-scope file lock also rejects overlap.

## Requirements

- Python 3.11+
- Writable private directory for SQLite and lock files
- Outbound HTTPS access to the configured MCP endpoint for live collection
- Cron (recommended) or another external scheduler

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

# Set a long random ADMIN_TOKEN in .env if manual collection is needed.
python -c 'import secrets; print(secrets.token_urlsafe(32))'

alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open <http://127.0.0.1:8000>. API docs are at `/docs` and `/redoc`.

The application intentionally reports degraded readiness before migrations are
applied; it does not silently mutate a production schema at startup.

### Optional demo observations

```bash
# APP_ENV must be development or test.
python -m scripts.seed_demo_data
# Recreate only the clearly-labelled demo fixture:
python -m scripts.seed_demo_data --reset
```

Demo products use `identity_source=demo_fixture`, snapshots use `demo:*` sources,
and runs carry `source_metadata.demo=true`. The dashboard displays a warning.
No production view embeds mock rows.

## Live MCP verification

```bash
# Handshake + tools/list and required-tool validation
python -m scripts.check_mcp

# Also fetch three current observed bestseller cards
python -m scripts.check_mcp --call-data

# The upstream repository's independent verifier is retained too:
node scripts/verify-live.mjs
```

A failure before an HTTP status usually means DNS/firewall/outbound-HTTPS access.
An MCP `isError` asking for a retry can mean Digikala temporarily challenged the
server region; bounded retries are automatic during collection.

## Collect data

```bash
# All enabled scopes, default limit
python -m scripts.collect

# Explicit current top 20
python -m scripts.collect --limit 20

# Import verified short price charts for a bounded number of ranked products.
# Set PRICE_HISTORY_PRODUCTS_PER_RUN (for example 3) before using this option.
python -m scripts.collect --limit 20 --with-price-history

# Collect a known category now (internal id from GET /api/categories)
python -m scripts.collect --category-id 2 --limit 20

# Skip the global scope (honoured with and without --category-id)
python -m scripts.collect --no-global
```

The first successful global collection stores category IDs returned by MCP.
Enable conservative recurring category scopes with:

```bash
python -m scripts.manage_scopes list
python -m scripts.manage_scopes add-category 2 --interval 1440
python -m scripts.manage_scopes set-enabled 2 false
```

DigiScope does not recursively enable every category because doing so would
create unmeasured request volume against a rate-limited public service.

### Cron example

Run once daily (server local time) and use an OS-level log rotation policy:

```cron
17 2 * * * cd /srv/digiscope && /srv/digiscope/.venv/bin/python -m scripts.collect >> /srv/digiscope/data/collection.log 2>&1
```

Do not start the same scope from several cron hosts. The local file lock protects
one host; it cannot coordinate unrelated machines sharing no filesystem.

### Manual REST collection

Set `ADMIN_TOKEN` and send it only over HTTPS:

```bash
curl -X POST https://your-host.example/api/collection/run \
  -H 'content-type: application/json' \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  -d '{"include_global":true,"category_ids":[],"limit":10,"include_price_history":false}'
```

The endpoint rejects missing/incorrect tokens, applies a small burst guard, and
uses the same per-scope lock as cron. The token is never returned by status APIs.

## Analytics definitions

For each product in a rolling window:

```text
rank_improvement = earliest_observed_rank - latest_observed_rank
presence_rate = observed_successful_runs / eligible_successful_runs × 100
```

A positive improvement is better because rank 1 is best. “Eligible” includes
only successful or usable partial runs for the same scope and ranking method;
failed runs never count as absences.

The ranking trend indicator is:

```text
100 × (0.55 × normalized rank improvement
     + 0.25 × presence
     + 0.10 × observation confidence
     + 0.10 × recency)
```

Its range is -100..100 and all components are returned by the API. It is not a
sales-growth score. At least two valid observations are required for a product
to be described as improving.

Coverage reports include the exact window, expected and successful runs,
excluded failures, unique products, sufficient-history count, temporal and
schedule percentages, and earliest/latest observations. Overall coverage is the
lower of temporal and schedule coverage; a period is “complete” only at 95%+ and
with the expected successful opportunities.

## REST API

| Method | Path | Purpose |
|---|---|---|
| GET | `/health`, `/ready` | Process health and DB/schema readiness |
| GET | `/api/dashboard` | Metrics, current list, improvements, 7d/30d coverage |
| GET | `/api/categories` | Known parent/child categories |
| GET | `/api/products` | Search/filter/sort/paginate rankings |
| GET | `/api/products/{id}` | Metadata, price/rank timelines, coverage |
| GET | `/api/rankings` | Current, 7d, or 30d observed rankings |
| GET | `/api/market/trends` | Sufficient-history ranking improvements |
| GET | `/api/collection/status` | Runs, errors, timestamps, configured scopes |
| POST | `/api/collection/run` | Authenticated manual collection |
| GET | `/api/export.csv` | Filtered Excel-compatible Persian CSV |

Examples:

```bash
curl 'http://127.0.0.1:8000/api/rankings?period=7d&scope=global&limit=10'
curl 'http://127.0.0.1:8000/api/rankings?period=30d&scope=category&category_id=2&limit=20'
curl -OJ 'http://127.0.0.1:8000/api/export.csv?period=7d&scope=global&limit=50'
```

## Tests

```bash
pytest -q
# or, without activating the environment:
.venv/bin/pytest -q
```

The deterministic suite covers MCP initialization/discovery/sessions, JSON/SSE,
structured/text content, invalid payloads, retries/rate limits/timeouts/tool
errors; migrations and DB constraints/rollback/FKs; collection idempotency and
locks; all requested analytics edge cases; every REST area, auth, CSV BOM and
formula protection; and static RTL/responsive frontend contracts.

Current documented baseline: **79 passed, 0 failed**. The normal suite performs
no live Digikala requests. See [`docs/testing.md`](docs/testing.md) for the test
matrix, static checks, browser verification, and live-smoke separation.

Continuous integration (`.github/workflows/verify.yml`) runs `ruff check .`,
`ruff format --check .` and `pytest -q` on every push and pull request, and the
live MCP contract check on the hourly schedule.

## Database migrations, backup, and restore

```bash
alembic current
alembic upgrade head

# Consistent online SQLite backup + integrity check (mode 0600)
python -m scripts.backup_db ./data/backups
```

Restore procedure:

1. Stop web and collection processes.
2. Back up the damaged/current file separately.
3. Copy the selected backup over the path in `DATABASE_URL`.
4. Remove stale `-wal`/`-shm` files only while every process is stopped.
5. Run `alembic current`, `alembic upgrade head`, and `GET /ready`.

Always make a backup before applying future migrations. Keep the database,
backups, `.env`, and lock directory outside any public document root.

## Production deployment

A small VPS with one Uvicorn worker and system cron is the predictable target:

```bash
APP_ENV=production uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Put Nginx/Caddy in front for TLS and proxy requests to that local port. Keep one
worker for SQLite write simplicity; scale vertically or move to a server DB
before adding workers. Run cron separately as shown above.

For cPanel/shared hosting, verify **before deployment**:

1. Python 3.11+, ASGI support (not only Passenger WSGI), and process longevity.
2. Outbound HTTPS to `digikala-mcp.mmdju.workers.dev`.
3. A writable private path outside `public_html` for SQLite/locks/backups.
4. Cron support with the virtualenv Python executable.
5. Whether host restarts or worker multiplicity can conflict with SQLite.

If ASGI, outbound access, or reliable cron is unavailable, use a small VPS or an
external scheduler that securely invokes the authenticated endpoint. No claim is
made that this repository has been externally deployed.

## Configuration

See [`.env.example`](.env.example). Key values:

- `DATABASE_URL`: file-backed SQLite URL.
- `DIGIKALA_MCP_URL`: replaceable fixed upstream endpoint (never user-supplied).
- `MCP_REQUEST_TIMEOUT`, `MCP_MAX_RETRIES`, retry delays.
- `COLLECTION_INTERVAL_MINUTES`: expected-opportunity/cron cadence; it does not
  schedule or suppress runs.
- `COLLECTION_ENABLED`: production token-validation policy in `0.1.x`, not a
  runtime collector kill switch; disable cron and omit the token for read-only use.
- `DEFAULT_RANKING_LIMIT`, `MAX_RANKING_LIMIT`.
- `PRICE_HISTORY_PRODUCTS_PER_RUN`: conservative history enrichment bound.
- `ADMIN_TOKEN`: required for manual collection; mandatory in production when
  collection is enabled.
- `APP_TIMEZONE`: validated IANA deployment setting reserved for scheduling/local
  policy. Stored timestamps remain UTC; the current browser formats them in the
  viewer's locale/timezone.

## Troubleshooting

- **`/ready` is 503:** run `alembic upgrade head`; verify file permissions.
- **`database is locked`:** confirm only one web worker/cron host, keep the DB on
  a local filesystem, and inspect stale collection processes. A 30-second busy
  timeout and WAL are already enabled.
- **HTTP 429 from MCP:** lower scope frequency; DigiScope honours `Retry-After`.
- **Transient Digikala/CDN tool error:** wait and retry; do not increase retries
  aggressively.
- **No 7d/30d comparison:** at least two actual rank observations are required.
- **Global top 50 shows fewer rows:** this is the documented `best_selling`
  maximum of 30, not missing rows filled from another method.
- **No price chart:** set a positive `PRICE_HISTORY_PRODUCTS_PER_RUN`, collect
  with `--with-price-history`, and remember that not every product has points.

## Project layout

```text
app/
  api/              REST routers
  mcp/              Streamable HTTP client, adapter, normalizers
  models/           SQLAlchemy observed-fact schema
  schemas/          Pydantic REST contracts
  services/         collection, persistence, coverage, analytics
  static/           RTL CSS, vanilla JS, vendored Chart.js/Vazirmatn
  templates/        Persian dashboard
migrations/          Alembic revisions
scripts/             collect, check MCP, scopes, demo seed, backup
tests/               deterministic MCP/DB/analytics/API/frontend tests
docs/               architecture, API, integrity, operations, deployment, MCP
data/               ignored runtime DB, locks, backups, logs
```

## Attribution and license

Digikala MCP and retained upstream contract material are by `mmdju`. The existing
[`LICENSE`](LICENSE) originated with that showcase repository and explicitly
controls its inherited documentation/examples; it does **not** clearly grant a
license for the newly added DigiScope application source. Do not assume rights
beyond that text until the repository owner adds an explicit DigiScope license.
Chart.js and Vazirmatn notices are vendored beside their assets and remain
unchanged.

DigiScope is not affiliated with or endorsed by Digikala. Digikala's public web
API is undocumented and may change without notice.
