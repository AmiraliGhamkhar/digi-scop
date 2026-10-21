# DigiScope API and operator examples

These examples target the DigiScope application, not the upstream MCP endpoint.
They assume DigiScope runs at `http://127.0.0.1:8000` and already contains real
observations or explicitly labelled development data.

For direct MCP diagnostics, see [`examples/README.md`](README.md) and
[`mcp.json`](mcp.json).

## 1. Current observed global ranking

Question:

> الان چه محصولاتی در فهرست پرفروش مشاهده شده‌اند؟

```bash
curl --get 'http://127.0.0.1:8000/api/rankings' \
  --data-urlencode 'period=current' \
  --data-urlencode 'scope=global' \
  --data-urlencode 'limit=10'
```

Read `data_basis: current_observed_ranking` and `observed_at`. Do not describe the
positions as units sold.

## 2. Seven-day rank improvement

Question:

> کدام کالاها در هفت روز اخیر جایگاه بهتری پیدا کرده‌اند؟

```bash
curl --get 'http://127.0.0.1:8000/api/rankings' \
  --data-urlencode 'period=7d' \
  --data-urlencode 'scope=global' \
  --data-urlencode 'sort=-rank_improvement' \
  --data-urlencode 'limit=20'
```

Check `coverage.complete`, `coverage.coverage_percent`, and each product's
`sufficient_history` before making a comparison.

## 3. Ranking-based trends

Question:

> قوی‌ترین روندهای رتبه‌ای این ماه کدام‌اند؟

```bash
curl --get 'http://127.0.0.1:8000/api/market/trends' \
  --data-urlencode 'period=30d' \
  --data-urlencode 'scope=global' \
  --data-urlencode 'limit=10'
```

The response deliberately sets `not_sales_growth: true` and exposes formula
components. Call it a ranking-based trend indicator.

## 4. Browse a category scope

First obtain internal category IDs:

```bash
curl -sS 'http://127.0.0.1:8000/api/categories' | python -m json.tool
```

Then request that category's stored observations:

```bash
curl --get 'http://127.0.0.1:8000/api/rankings' \
  --data-urlencode 'period=7d' \
  --data-urlencode 'scope=category' \
  --data-urlencode 'category_id=2' \
  --data-urlencode 'limit=20'
```

The REST `category_id` is DigiScope's internal ID. The response `scope_key`
confirms which category history was queried.

## 5. Search and paginate products

```bash
curl --get 'http://127.0.0.1:8000/api/products' \
  --data-urlencode 'q=هدفون بی‌سیم' \
  --data-urlencode 'period=30d' \
  --data-urlencode 'sort=-observations' \
  --data-urlencode 'limit=20' \
  --data-urlencode 'offset=0'
```

Title search applies to stored products. An empty list means no qualifying stored
observation, not that Digikala has no such product.

## 6. Inspect independent price and rank histories

Use the internal product ID from a list response:

```bash
curl -sS 'http://127.0.0.1:8000/api/products/12' | python -m json.tool
```

Relevant arrays:

- `price_history`: nullable observed card prices and imported variant-specific
  price chart points;
- `ranking_history`: actual scope/method positions;
- `coverage`: per-scope 7-day and 30-day completeness.

A point in one history does not imply a point in the other.

## 7. Export Persian CSV for Excel

```bash
curl -OJ --get 'http://127.0.0.1:8000/api/export.csv' \
  --data-urlencode 'period=7d' \
  --data-urlencode 'scope=global' \
  --data-urlencode 'sort=-rank_improvement' \
  --data-urlencode 'limit=50'
```

The file starts with a UTF-8 BOM, escapes spreadsheet formulas, and includes a
header indicating current versus historical data basis.

## 8. Check collection health

```bash
curl -sS 'http://127.0.0.1:8000/api/collection/status' | python -m json.tool
curl -sS 'http://127.0.0.1:8000/ready' | python -m json.tool
```

A failed run remains visible but is excluded from product-presence denominators.
Investigate repeated errors before trusting freshness.

## 9. Trigger an exceptional manual collection

Prefer cron for normal operation. With a configured token:

```bash
curl --fail-with-body -X POST \
  'https://your-host.example/api/collection/run' \
  -H 'Content-Type: application/json' \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  -d '{
    "include_global": true,
    "category_ids": [],
    "limit": 10,
    "include_price_history": false
  }'
```

Never put the token in a URL. HTTP 429 means the trigger guard is active; a scope
outcome of `skipped` means another process holds its collection lock.

## 10. Scheduled collection and bounded price enrichment

```bash
# Current rankings for all enabled scopes
python -m scripts.collect --limit 20

# At most PRICE_HISTORY_PRODUCTS_PER_RUN price charts per scope
python -m scripts.collect --limit 20 --with-price-history
```

The global upstream tool can expose only 30 products. A request for 50 does not
silently switch to a different tool; the run records a partial warning.

## 11. Explicitly labelled development fixture

```bash
APP_ENV=development python -m scripts.seed_demo_data
```

The dashboard then displays a demo warning. Never cite those fixture values as
live marketplace observations.

## Interpretation checklist

Before presenting a result:

1. State the scope and ranking method.
2. State the last observation time.
3. For historical reports, state coverage and whether it is complete.
4. Require at least two observations for improvement claims.
5. Call trend values ranking indicators, not sales growth.
6. Preserve null price/rating/stock values as unavailable.
7. Do not treat failed runs as absences.
8. Link the product only when a verified canonical Digikala URL exists.
