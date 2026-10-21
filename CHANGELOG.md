# DigiScope changelog

All notable changes to DigiScope are recorded here. Dates use UTC and versions
follow semantic versioning. This file describes the DigiScope application, not
the independently hosted Digikala MCP service.

The upstream MCP release history is maintained in the
[`mmdju/digikala-mcp` repository](https://github.com/mmdju/digikala-mcp).

## Unreleased

### Fixed

- The product detail view returned the *oldest* 500 stored price points and
  reported a `latest_snapshot` taken from the oldest row that fitted the
  window. It now returns the newest 500 rows and the newest known observation.
- The current observed ranking reported `observation_count: 1` and a
  placeholder `first_observed` for every product. Both are now the real
  observed values for that scope and ranking method.
- A sort field that could not separate the rows of the requested period (for
  example `rank_improvement` in a current list) fell back to an arbitrary
  product order. The list now keeps the observed rank order instead.
- The category foreign keys promised `ON DELETE SET NULL` while the scope check
  constraints required a category scope to keep its category, so deleting a
  category produced rows that could not satisfy their own check. The foreign
  keys now refuse the delete, and a new Alembic revision
  (`b7c8d9e0f1a2`) migrates existing databases while keeping every row,
  check, and index.
- A malformed upstream number (a price sent as a formatted or Persian string)
  dropped the whole product card. Only the unusable field is now dropped; the
  product keeps its observation, and a card is only skipped when it has no
  usable identity.
- The collection CLI ignored `--no-global` when no category was requested, and
  a locked scope ended the run with a raw traceback. The flag is honoured for
  every scope selection, and a locked scope is reported as `skipped`.
- The configured ranking limit could promise 100 rows while the verified
  adapter accepts at most 50. One shared cap (`MAX_RANKING_LIMIT = 50`) now
  bounds the settings, the API, and the adapter.
- The CSV export link reused the page size of the table, so an export could
  contain only the visible rows. It now requests the export maximum.
- The live verification compared the hosted MCP service version with this
  repository's `CHANGELOG.md`, which tracks DigiScope application releases and
  can never match an upstream service version. It now compares the live
  version against the oldest release whose contract DigiScope verified.
- Continuous integration now runs the test suite and Ruff on every push and
  pull request instead of only the hourly live check, and the repository
  passes `ruff check .` and `ruff format --check .`.
- Alembic now creates a missing SQLite parent directory before connecting, so
  `alembic upgrade head` succeeds on a fresh clone where `data/` does not exist
  instead of failing with `unable to open database file`.
- Documented `COLLECTION_ENABLED` and `COLLECTION_INTERVAL_MINUTES` accurately:
  the first is a production token-validation policy, the second only defines the
  expected analytics cadence. Cron owns scheduling and every collector run
  processes its selected enabled scopes.
- Corrected `APP_HOST`/`APP_PORT`/`APP_TIMEZONE` descriptions: the first two are
  validated settings not consumed by the launch commands, and the timezone is a
  deployment/policy setting while timestamps stay UTC.

### Documentation

- Replaced the inherited upstream-service changelog and security policy with
  DigiScope-specific documents.
- Added a documentation index, REST API reference, data-integrity specification,
  operational runbook, deployment guide, testing guide, and application
  architecture guide.
- Reframed the retained MCP tool reference and examples as inspected upstream
  contract material rather than DigiScope application endpoints.
- Expanded Persian setup and operating guidance.
- Added a status notice ahead of the preserved inherited license so its original
  “documentation only” statement is not misapplied to new DigiScope source.
- Marked the inherited `assets/` illustration as upstream material rather than a
  DigiScope screenshot.

## 0.1.0 - 2026-10-21

### Added

- A single-process FastAPI application serving the REST API and Persian RTL
  dashboard.
- SQLAlchemy 2 models for products, categories, snapshots, rank observations,
  collection runs, and collection scopes.
- An initial Alembic migration with foreign keys, uniqueness constraints, check
  constraints, and indexes suitable for the SQLite MVP.
- A replaceable Digikala MCP adapter supporting Streamable HTTP initialization,
  JSON and SSE responses, textual and structured tool content, optional session
  IDs, bounded retries, `Retry-After`, timeouts, and sanitized errors.
- Global `best_selling` and category `browse_category` collection workflows with
  stable product identity, per-scope file locks, controlled transactions, and
  idempotent historical price imports.
- Coverage-aware current, 7-day, and 30-day analytics with observed-rank
  improvement, presence rate, sufficient-history checks, and an exposed
  ranking-based trend indicator.
- Dashboard, category, product, ranking, trend, collection-status, authenticated
  collection, health, readiness, and CSV export endpoints.
- A responsive Persian dashboard using vanilla JavaScript, vendored Chart.js,
  and vendored Vazirmatn fonts.
- CLI commands for collection, live MCP checks, scope management, deterministic
  development data, and consistent SQLite backups.
- Deterministic MCP, database, migration, collection, analytics, API, CSV,
  security, and frontend-contract tests.

### Data-integrity guarantees

- Current rankings are never copied into earlier dates.
- Failed runs never count as product absences.
- Historical price points never create rank observations.
- Missing optional values remain null.
- No sales quantities or historical ranks are inferred.
- The documented 30-item limit of the global MCP `best_selling` tool is exposed
  instead of silently combining it with a different ranking method.

### Known limitations

- Upstream historical ranking and units-sold data are unavailable.
- `product_price_chart` supplies only a short, approximately 30-day,
  variant-specific window where available.
- SQLite and filesystem locks target a single-host deployment.
- The live MCP endpoint could not be reached from the restricted build sandbox;
  deployment hosts must run `python -m scripts.check_mcp --call-data`.
