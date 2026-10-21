# Digikala MCP integration report

- **Document status:** inspected contract snapshot for DigiScope `0.1.x`
- **Upstream live status from this sandbox:** unverified (network blocked before HTTP)
- **Related docs:** [documentation index](README.md) · [tool snapshot](tools.md) ·
  [architecture](architecture.md) · [data integrity](data-integrity.md)

Inspected on **2026-10-21** at upstream commit
`927ab481bb2d1292410b1b3858c691a844102c6d` (`mmdju/digikala-mcp`). The upstream
repository is intentionally a showcase repository: it contains documentation,
examples, and a live verifier, but **not the Worker source code**.

## Verified contract from repository files

- Endpoint: `https://digikala-mcp.mmdju.workers.dev/mcp`.
- Transport: stateless MCP Streamable HTTP over `POST`; requests advertise
  `application/json, text/event-stream`. Responses may be JSON or SSE whose last
  `data:` payload is JSON. `GET /mcp` normally returns 405.
- Example handshake uses MCP protocol `2024-11-05`, followed by
  `notifications/initialized`. The service documentation explicitly says there
  are no resumable sessions or accounts. The verified endpoint is a small,
  stateless one-POST contract, so DigiScope uses maintained HTTPX rather than
  adding the full SDK dependency; JSON-RPC and Streamable HTTP behaviours are
  covered by adapter tests. DigiScope still preserves and reuses an
  `Mcp-Session-Id` header if a compatible deployment supplies one.
- Tool calls return an MCP result envelope. The hosted examples read
  `result.content[0].text` and JSON-decode that text; a JSON-looking text value is
  therefore **not** treated as structured data until decoding succeeds.
  DigiScope also supports standard `structuredContent` for forward compatibility.
- Nineteen read-only tools are documented: `digikala_suggest`,
  `search_digikala`, `browse_category`, `browse_tag`, `product_details`,
  `product_price_chart`, `product_questions`, `get_products_batch`, `product_url`,
  `product_variants`, `product_sellers`, `brand_lookup`, `search_filters`,
  `product_reviews`, `compare_products`, `find_best_value`, `incredible_offers`,
  `best_selling`, and `similar_products`. Their complete documented parameter
  tables remain in [`docs/tools.md`](tools.md).

## Tools used by DigiScope

### `best_selling`

Arguments: optional `limit` (default 10, documented maximum **30**),
`min_price_toman`, `max_price_toman`, `min_rating`, and `only_marketable`.
It returns a site-wide ordered `items` card list plus category IDs,
`total_items_estimate` (documented as 50), `total_items_scope`, `fetched`, and
`returned`. There is no documented page argument. Consequently DigiScope never
claims it collected the inaccessible final 20 items: a requested top-50 global
view may contain only the 30 observations the tool can return.

### `browse_category`

Required `category_id`; optional `sort`, `page`, `limit` (max 30), price/rating/
marketability/discount filters, up to five brand IDs, up to three colour IDs,
seller type, and four delivery switches. It returns `items`, category metadata,
subcategories, pagination/estimated totals, breadcrumb, and flags including
`items_from_search`. DigiScope uses `sort: "best_selling"` and documented paging
for category scopes and records that ranking method explicitly.

### `search_digikala`

Optional `query`, `category_id`, one of nine documented sorts (including
`best_selling`), 1-based `page`, `limit` (max 30), and documented price, rating,
marketability, discount, brand, colour, seller, and delivery filters. It returns
compact cards and paging/honesty metadata (`low_confidence`, `unmatched_terms`,
`items_with_all_terms`, and clamping flags where applicable). DigiScope does not
currently use search results as historical rankings.

### `product_price_chart`

Required numeric `id`, with no other documented argument. It returns
`current_price_toman`, `window_days`, and one series per colour/size. A series has
`cheapest_in_window_toman` and daily `points` containing `day`, `price_toman`,
`seller`, and `warranty`. The range is a rolling window of **about 30 daily
points**, not full history. Values are seller/variant-specific. DigiScope stores
these as price snapshots with a variant key and never turns them into rank data.

Cards are documented with stable numeric product `id`, title, Toman and Rial
prices, prior price, discount, nullable rating, rating count, stock, seller,
badges, and product URL. Optional fields stay null/absent; no sales quantity is
provided.

## Reliability constraints

- Public edge limit: **20 POST requests/minute/IP**, HTTP 429 with
  `Retry-After`; DigiScope applies bounded retries and honours that header.
- Upstream Digikala calls are globally paced by the service (maximum two in
  flight, about 500 ms apart). CDN blocks can produce an MCP tool error asking
  for a retry in 15–30 seconds.
- The service uses short-lived response caching (minutes for volatile prices,
  hours for slower reads); Digikala's API is undocumented and can change.
- Request attempts have bounded upstream budgets/timeouts. DigiScope adds its
  own configurable timeout and does not retry validation or permanent tool
  errors.

## Historical-data conclusion

No tool or repository data source supplies historical bestseller rank or units
sold. Exact sales quantities are not available. Only the short product price
chart is historical. DigiScope therefore starts rank history at collection time,
reports actual coverage, excludes failed runs from absence denominators, and
never backfills ranks from a current list.

## Live verification status

Two local live smoke paths were attempted on 2026-10-21. The retained Node
verifier failed before HTTP with `fetch failed`; DigiScope's adapter check failed
with `MCPHTTPError: MCP network request failed`. This sandbox permits outbound
traffic only to approved hosts, so no live payload was used to infer a schema.

The upstream project's public GitHub verification runs were successful on the
same date, but that is not a substitute for DigiScope testing from its deployment
host. Run both commands there:

```bash
python -m scripts.check_mcp
python -m scripts.check_mcp --call-data
```

If they succeed, record the host, time, server version, negotiated protocol, tool
count, and a redacted normalized-card result in deployment/release evidence. Do
not rewrite historical observations solely because a later contract changes.
