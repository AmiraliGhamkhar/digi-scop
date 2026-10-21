# DigiScope changelog

All notable changes to DigiScope are recorded here. Dates use UTC and versions
follow semantic versioning. This file describes the DigiScope application, not
the independently hosted Digikala MCP service.

The upstream MCP release history is maintained in the
[`mmdju/digikala-mcp` repository](https://github.com/mmdju/digikala-mcp).

## Unreleased

### Fixed

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
