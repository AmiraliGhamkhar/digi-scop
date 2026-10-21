# DigiScope testing guide

The normal DigiScope test suite is deterministic and must not depend on live
Digikala or MCP availability.

## Environment

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
```

Run all tests:

```bash
pytest -q
```

Without activating the virtualenv:

```bash
.venv/bin/pytest -q
```

Current baseline:

```text
58 passed, 0 failed
```

The installed FastAPI/Starlette test client may emit one non-failing dependency
deprecation warning. Warnings must not be hidden as failures; review them when
updating dependencies.

## Static checks used during delivery

```bash
python -m compileall -q app scripts tests
node --check app/static/js/api.js
node --check app/static/js/charts.js
node --check app/static/js/app.js
```

If Ruff is installed for contribution checks:

```bash
ruff format --check app scripts tests
ruff check app scripts tests
```

Ruff is intentionally not a runtime dependency.

When Node package-registry access is available, validate maintained Markdown with
the repository configuration:

```bash
npx --yes markdownlint-cli2
```

## Test layout

| File | Coverage |
|---|---|
| `tests/test_mcp_client.py` | Initialization, notifications, discovery, session reuse, JSON/SSE, structured/text content, invalid JSON, JSON-RPC/tool/HTTP errors, timeout, rate limit, retries |
| `tests/test_mcp_adapter.py` | Verified tool mapping, global cap, category pagination/slot offsets, price variants, required tools, numeric IDs |
| `tests/test_database.py` | Clean schema, unique identity, snapshots/ranks, duplicate prevention, rollback, foreign keys, checks, Alembic upgrade/downgrade |
| `tests/test_collection.py` | Normalization/persistence, history preservation, same-run idempotency, failed/partial runs, category scopes, price deduplication, locks |
| `tests/test_analytics.py` | Improvement, worsening, unchanged, missing observations, failed runs, multi-category identity, insufficient history, incomplete coverage, price-only history |
| `tests/test_api.py` | Every REST area, validation, filtering, pagination, empty/404 states, auth, burst guard, CSV BOM/formula safety, RTL/static contracts |
| `tests/test_config.py` | Limit/timezone validation and production token requirements |

`tests/conftest.py` builds temporary SQLite databases and deterministic Persian
fixtures. No test writes to the normal `data/digiscope.db`.

## Required analytical cases

Any analytics refactor must continue to cover:

1. rank 20 improving to rank 5;
2. worsening rank;
3. unchanged rank;
4. missing successful opportunities;
5. failed collection excluded from absence;
6. one product in multiple category scopes;
7. insufficient history;
8. incomplete 7-day/30-day coverage;
9. duplicate collection persistence;
10. price history without ranking history.

See [`data-integrity.md`](data-integrity.md) for expected formulas.

## Migration verification

The automated suite runs Alembic against a clean temporary file and downgrades to
base. A manual release check may also use an isolated database:

```bash
TMP_DIR="$(mktemp -d)"
TMP_DB="$TMP_DIR/digiscope.db"
DATABASE_URL="sqlite:///$TMP_DB" alembic upgrade head
DATABASE_URL="sqlite:///$TMP_DB" alembic current
rm -rf "$TMP_DIR"
```

Do not point migration experiments at production. Back up before every production
migration.

## Collection test strategy

`MockMCPAdapter` returns explicit deterministic payloads and records calls.
Collection tests assert both database state and run diagnostics. Tests do not
mock the database transaction layer, because constraints and rollback behaviour
are part of the contract.

Optional enrichment failures are isolated from ranking facts. Tests must verify
that importing price points never creates or modifies rank observations.

## MCP transport test strategy

HTTPX `MockTransport` simulates:

- direct JSON and Streamable HTTP SSE bodies;
- `Mcp-Session-Id` creation/reuse;
- empty notification responses;
- standard `structuredContent` and JSON text content;
- invalid JSON and mismatched protocol envelopes;
- permanent/transient MCP tool errors;
- HTTP 429 with `Retry-After`;
- 5xx and timeout retry exhaustion.

When changing parsing, add a fixture that proves both accepted and rejected forms.
Never loosen normalization solely to make an unexpected live payload pass without
first documenting and testing its actual contract.

## API and frontend verification

Automated API tests validate Pydantic response serialization, not only status
codes. Frontend contract checks assert:

- `lang="fa"` and `dir="rtl"`;
- category/period controls;
- vendored Chart.js use;
- narrow-screen media rules;
- API-driven JavaScript rather than embedded production mock rows;
- Content Security Policy headers.

Manual browser release checks:

1. open the dashboard at desktop and narrow mobile widths;
2. use current/7-day/30-day controls;
3. switch global/category scope;
4. search, sort, paginate, and export;
5. open a product and compare independent rank/price charts;
6. verify empty, loading, API-error, demo, incomplete, stale, and failed-run labels;
7. navigate controls by keyboard and inspect visible focus;
8. confirm Persian text opens correctly in Excel-compatible CSV.

## Live MCP smoke test

Live access is separate from the deterministic suite:

```bash
python -m scripts.check_mcp
python -m scripts.check_mcp --call-data
```

A successful check verifies the configured host at that moment. It does not make
normal tests network-dependent and does not guarantee future Digikala uptime.
Record live status honestly in release notes.

The retained upstream verifier can provide an independent contract signal:

```bash
node scripts/verify-live.mjs
```

It tests the hosted MCP project, not DigiScope persistence or analytics.

## Release validation checklist

```bash
pytest -q
python -m compileall -q app scripts tests
node --check app/static/js/api.js
node --check app/static/js/charts.js
node --check app/static/js/app.js
alembic current
python -m scripts.backup_db ./data/backups
```

Then:

- review `git diff --check`;
- confirm no `.env`, database, lock, backup, or log is staged;
- update `CHANGELOG.md` and affected focused docs;
- run the live MCP check from a host where outbound access is expected;
- report test failures, warnings, and unverified integration status without
  omission.
