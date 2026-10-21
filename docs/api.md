# DigiScope REST API

DigiScope exposes a same-origin JSON API under `/api`, plus health checks and
OpenAPI documentation. The interactive schema at `/docs` is authoritative for
field types; this guide explains semantics that a schema alone cannot express.

Base URL examples use `http://127.0.0.1:8000`. Production traffic must use HTTPS.

## Conventions

- JSON keys are English; product titles and UI labels may be Persian.
- Timestamps are ISO 8601 UTC values.
- Product `id` in REST paths is DigiScope's internal integer primary key.
  `external_id` is the stable upstream/fallback identity.
- Prices are nullable integer Toman values only when the upstream unit is
  verified. Missing values remain `null`.
- `rank_change`/`rank_improvement` is positive when ranking improved because a
  smaller position is better.
- `current` means the latest usable `success`/`partial` observed list with saved
  ranks. `7d` and `30d` use only usable stored observations inside those rolling
  windows.
- Every ranking list returns `data_basis` so clients can distinguish current data
  from stored history.
- In a `current` list, `observation_count` is the number of times the product was
  really observed in that scope and method, and `first_observed` is its earliest
  such observation. Both count stored observations only.
- The maximum API page/export size is 50. The upstream global `best_selling`
  source itself exposes at most 30 products.

## Health endpoints

### `GET /health`

Checks process and database/schema availability. It always returns a structured
health body and uses `status: "degraded"` if the database is unavailable.

### `GET /ready`

Readiness probe. Returns the same schema as `/health`, but responds with HTTP 503
until database connectivity and required tables are available.

```json
{
  "status": "ok",
  "database": "ready",
  "version": "0.1.0",
  "timestamp": "2026-10-21T12:00:00Z"
}
```

## Dashboard

### `GET /api/dashboard`

Returns:

- latest successful collection time and latest run state;
- collection health (`healthy`, `warning`, `stale`, `error`, or `no_data`);
- monitored product/category and rank-observation counts;
- latest ten current observed global bestsellers;
- up to five sufficient-history 7-day improvements;
- complete 7-day and 30-day coverage objects;
- `demo_data`, allowing the UI to label seeded development rows;
- terminology that explicitly rejects sales-volume interpretation.

No query parameters are accepted.

## Categories

### `GET /api/categories`

Returns known categories as a nested parent/child list. Categories become known
when a collection response supplies them or when development fixtures are
seeded. An empty list is valid before category metadata has been observed.

Category IDs used by the REST API are internal DigiScope IDs, not upstream MCP
category IDs. Each object includes `external_id` for the upstream identity.

## Ranking and product lists

### `GET /api/rankings`

| Parameter | Type/default | Rules |
|---|---|---|
| `period` | `current` | `current`, `7d`, or `30d` |
| `scope` | `global` | `global` or `category` |
| `category_id` | null | Required for category scope; invalid for global scope |
| `ranking_method` | `best_selling` | Only the verified method is currently exposed |
| `q` | null | Case-insensitive title substring, max 200 characters |
| `sort` | `rank` | See supported sorts below |
| `limit` | `10` | 1–50 |
| `offset` | `0` | 0–10,000 |

Supported sort values:

```text
rank, -rank
rank_improvement, -rank_improvement
price, -price
rating, -rating
observations, -observations
last_observed, -last_observed
trend, -trend
```

A leading `-` means descending. Null values sort last. Sort values are validated
against this allowlist and never interpolated into SQL.

When the requested sort field cannot separate the rows of the requested period
(for example `rank_improvement` in a current list, where no row has that field),
the list keeps the observed rank order instead of an arbitrary product order.

Example:

```bash
curl 'http://127.0.0.1:8000/api/rankings?period=7d&scope=global&sort=-rank_improvement&limit=20'
```

Response outline:

```json
{
  "items": [
    {
      "id": 12,
      "external_id": "19019009",
      "title": "…",
      "price_toman": 900000,
      "current_rank": 5,
      "start_rank": 20,
      "end_rank": 5,
      "rank_improvement": 15,
      "observation_count": 6,
      "presence_rate": 85.71,
      "sufficient_history": true,
      "trend_score": 72.4,
      "trend_components": {
        "normalized_rank_improvement": 0.75,
        "presence": 0.8571,
        "observation_confidence": 0.8571,
        "recency": 0.99
      }
    }
  ],
  "pagination": {"limit": 20, "offset": 0, "total": 1},
  "period": "7d",
  "scope_key": "global",
  "sort_type": "best_selling",
  "observed_at": "2026-10-21T12:00:00Z",
  "coverage": {"complete": false, "coverage_percent": 42.9},
  "data_basis": "stored_observed_ranking_history"
}
```

The full coverage object includes window boundaries, expected/successful runs,
excluded failures, unique products, sufficient-history products, schedule and
temporal coverage, earliest/latest observations, interval, label, and completion.

### `GET /api/products`

Convenience product-list endpoint over the same ranking read model.

| Parameter | Type/default | Rules |
|---|---|---|
| `q` | null | Title substring, max 200 characters |
| `category_id` | null | If supplied, uses that category ranking scope |
| `period` | `current` | `current`, `7d`, or `30d` |
| `sort` | `rank` | Same allowlist as `/api/rankings` |
| `limit` | `20` | 1–50 |
| `offset` | `0` | 0–10,000 |

It returns the same `RankingListResponse` structure.

## Product detail

### `GET /api/products/{id}`

Returns stable product metadata, first/last seen times, latest snapshot, up to 500
stored non-null price snapshots, up to 500 ranking observations from usable
`success`/`partial` runs across scopes, and per-scope 7-day/30-day coverage.

The history windows hold the **newest** 500 rows, not the oldest ones, and
`latest_snapshot` is the newest known observation of the product. A product with
more than 500 stored points therefore shows its most recent price and rank.

Price and ranking histories are separate arrays. A price point at a timestamp does
not imply that the product had a ranking observation then.

HTTP 404 means the internal product ID is unknown.

```bash
curl 'http://127.0.0.1:8000/api/products/12'
```

## Trends

### `GET /api/market/trends`

| Parameter | Type/default | Rules |
|---|---|---|
| `period` | `7d` | `7d` or `30d` |
| `scope` | `global` | `global` or `category` |
| `category_id` | null | Required for category scope |
| `ranking_method` | `best_selling` | Current verified method |
| `limit` | `10` | 1–50 |

Only products with at least two observations and positive earliest-to-latest rank
improvement are returned. The response names the metric
`ranking_based_trend_indicator`, sets `not_sales_growth: true`, and includes the
formula and components.

## Collection status

### `GET /api/collection/status`

Returns the latest 20 collection runs and all configured scopes. Run diagnostics
include status, timestamps, scope/method, fetched/saved counts, duration,
truncated safe error message, and source metadata. Environment variables and the
administrative token are never included.

Statuses are:

- `running`: created, not finished;
- `success`: ranking saved without warnings;
- `partial`: the call completed with validation/enrichment warnings; any saved
  ranks remain usable;
- `failed`: ranking could not be saved.

A manual request can additionally report `skipped` when a scope lock is already
held; no collection run is created for that skipped attempt.

## Manual collection

### `POST /api/collection/run`

Requires:

```http
X-Admin-Token: <ADMIN_TOKEN>
Content-Type: application/json
```

Request body:

```json
{
  "include_global": true,
  "category_ids": [2],
  "limit": 20,
  "include_price_history": false
}
```

Rules:

- `ADMIN_TOKEN` must be configured; otherwise HTTP 503.
- A missing or incorrect token returns HTTP 401.
- Category IDs must be unique; at most ten are accepted.
- At least global or one category must be selected.
- `limit` is 1–50 and must not exceed `MAX_RANKING_LIMIT` (50, the same cap the
  verified adapter enforces).
- Unknown categories return HTTP 404.
- A process-local two-second trigger guard returns HTTP 429 with `Retry-After`.
- Per-scope filesystem locks prevent overlapping cron/web collections.
- Price-history enrichment is further bounded by
  `PRICE_HISTORY_PRODUCTS_PER_RUN`.

The endpoint waits for selected scopes to finish and returns one outcome per
scope. Prefer local cron for normal scheduling.

## CSV export

### `GET /api/export.csv`

Parameters: `period`, `scope`, `category_id`, `q`, `sort`, and `limit` with the
same validation as ranking endpoints. `limit` defaults to 50, so the export is
not narrowed by the page size of the table. The response:

- contains a UTF-8 BOM for Persian Excel compatibility;
- uses Persian column headings;
- exports nullable values as empty cells;
- escapes strings that could be interpreted as spreadsheet formulas;
- includes `X-DigiScope-Data-Basis` and, for historical reports,
  `X-DigiScope-Coverage-Percent` headers.

```bash
curl -OJ 'http://127.0.0.1:8000/api/export.csv?period=30d&scope=global&limit=50'
```

## Error responses

FastAPI validation failures use HTTP 422. Application errors use a small safe
message without upstream payloads or secrets.

| Status | Meaning |
|---|---|
| 401 | Missing/incorrect administrative token |
| 404 | Unknown category or product |
| 422 | Invalid period, scope, sort, pagination, or body |
| 429 | Manual collection triggered too quickly |
| 503 | Database unavailable or manual collection disabled |

HTTP 200 with an empty `items` list is not an error. It means no qualifying
stored observation exists for the requested filters.

## OpenAPI

- Swagger UI: `/docs`
- ReDoc: `/redoc`
- Schema: `/openapi.json`

Clients should generate against the running deployment's schema and still apply
the data-basis and coverage semantics documented here.
