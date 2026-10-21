# Data integrity and analytics semantics

DigiScope is an observation system, not a sales-estimation system. This document
is normative: API, UI, exports, tests, and future changes must preserve these
semantics.

## Fact and derivation boundary

### Observed facts

A value is observed only when it was present in a successful upstream response
or supplied by an explicitly labelled development fixture:

- stable product/category identity and metadata;
- a product's position in a specific ranking list;
- observation timestamp, scope, and ranking method;
- nullable price, discount, rating, rating count, stock state, seller, and URL;
- variant-specific historical price-chart points;
- collection success, partial success, failure, duration, and counts.

### Derived indicators

The following are deterministic calculations over stored observed facts:

- average and best observed rank;
- earliest-to-latest rank improvement;
- presence rate;
- schedule and temporal coverage;
- ranking-based trend score;
- stale/current health labels.

Derived values must expose enough inputs to reproduce them. They must never be
labelled as observed sales or sales growth.

### Prohibited representations

DigiScope must not:

- copy a current ranking into earlier dates;
- invent a rank for an unobserved product/run;
- infer units sold from rank, rating, review count, price, discount, or stock;
- convert price history into ranking history;
- treat an HTTP/tool/validation failure as a product absence;
- turn a missing stock field into `out_of_stock`;
- silently combine differently defined ranking methods to fill a list;
- label a partially covered 7-day/30-day window as complete;
- claim that first appearance after a gap proves demand or sales growth.

## Identity

The preferred product identity is the numeric ID returned by Digikala MCP. If it
is absent, a fallback is accepted only from a verified canonical Digikala URL
containing a `dkp-<number>` identity. A title is never an identity.

Products are deduplicated globally while rank observations retain every global
or category scope. `products.category_id` is only a primary/first verified
category; category analytics use `rank_observations.scope_id`, not that product
column.

## Ranking observations

Every rank row records:

```text
product + observed_at + scope + ranking_method + rank_position + collection_run
```

A global rank has no category scope ID. A category rank has a category scope ID.
Database checks enforce this distinction. Per-run uniqueness prevents the same
product or position being inserted twice for one scope/method.

The current list is the latest run with status `success` or usable `partial` and
at least one saved rank. The phrase **current observed ranking** should be used in
user-facing text.

## Historical window selection

Seven-day and thirty-day reports use rolling UTC windows ending at request time.
For each product:

- start rank = earliest valid observation inside the window;
- end/latest rank = latest valid observation inside the window;
- observation count = valid rank rows inside the window;
- average rank = arithmetic mean of observed positions;
- best rank = minimum observed position;
- sufficient history = at least two valid observations.

There is no interpolation between points and no forward/backward fill.

## Rank improvement

```text
rank_improvement = start_rank - end_rank
```

- positive: observed position improved;
- zero: earliest and latest observed positions are equal;
- negative: observed position worsened.

This does not prove a change in units sold. For the current list, `rank_change`
compares the latest position with the immediately preceding valid stored
observation for the same scope and method.

## Presence rate

```text
presence_rate = observed_successful_runs / eligible_successful_runs × 100
```

An eligible opportunity is a collection run for the same scope/method/window
with:

- status `success` or `partial`; and
- `items_saved > 0`.

Failed and still-running runs are excluded from the denominator. If a successful
list does not contain a product, that opportunity counts as a non-appearance.
This distinguishes an observed absence from a collection failure.

## Ranking-based trend indicator

The indicator is intentionally named a ranking trend—not sales growth.

Components are normalized as follows:

```text
normalized_rank_improvement = clamp(
    (start_rank - end_rank) / max(start_rank, end_rank, 1),
    -1,
    1
)

presence = presence_rate / 100

observation_confidence = min(
    observation_count / max(2, eligible_successful_runs),
    1
)

recency = max(
    0,
    1 - age_of_latest_observation / window_duration
)
```

Score:

```text
trend_score = clamp(
    100 × (
        0.55 × normalized_rank_improvement
      + 0.25 × presence
      + 0.10 × observation_confidence
      + 0.10 × recency
    ),
    -100,
    100
)
```

The API returns all four components and the formula. The trends endpoint includes
only products with sufficient history and positive rank improvement. Ties are
resolved deterministically by improvement, score, current rank, then product ID.

## Coverage

For a configured interval in minutes:

```text
expected_runs = ceil(window_minutes / interval_minutes)
schedule_completion = min(successful_runs / expected_runs × 100, 100)
```

Temporal coverage uses the actual rank-observation span and gives one interval of
credit for each boundary observation:

```text
observed_span = max(
    interval,
    latest_observation - earliest_observation + interval
)

temporal_coverage = min(observed_span / window_duration × 100, 100)
overall_coverage = min(schedule_completion, temporal_coverage)
```

A period is complete only when:

```text
overall_coverage >= 95% AND successful_runs >= expected_runs
```

Coverage output also includes failed-run count (disclosed but excluded), unique
products, sufficient-history products, exact UTC boundaries, and earliest/latest
observations.

If ten daily runs exist, a 30-day report reports roughly one-third coverage; the
missing twenty days are not synthesized.

## Price history

The inspected `product_price_chart` contract describes approximately 30 daily
points per colour/size series. Each point may have a seller and warranty. These
are stored as snapshots with:

- source `mcp:product_price_chart`;
- a stable variant key;
- `is_historical_import=true`;
- verified `TOMAN` unit metadata;
- an optional collection run showing when it was imported.

Repeated imports use a product/time/source/variant uniqueness check. Different
variants at the same timestamp remain distinct. Price coverage does not increase
ranking coverage.

## Missing and stale data

- `null` means the upstream response did not provide a usable value.
- No rank row means there was no valid ranking observation for that product/run.
- A failed run means the opportunity is unknown, not that every product vanished.
- `no_data` means no usable current `success`/`partial` run with saved ranks
  exists.
- Global data is stale when the latest usable run is older than twice the
  configured interval (with a minimum one-hour threshold).
- UI tables show neutral unavailable values and the last observation timestamp.

## Demo data

Development fixtures are permitted only when `APP_ENV` is `development` or
`test`. They use:

- external IDs prefixed `demo-`;
- `identity_source=demo_fixture`;
- snapshot sources prefixed `demo:`;
- collection metadata with `demo: true`.

The dashboard must display its demo warning whenever such rows exist. Demo data
must never be described as live Digikala data.

## Review checklist for analytical changes

Before merging an analytics change, verify:

1. failed runs remain excluded from absence denominators;
2. scope and ranking method are included in every query;
3. earliest/latest selection is deterministic;
4. insufficient-history products are labelled, not scored as growth;
5. no price-only row gains a rank;
6. incomplete windows remain incomplete;
7. components and formula remain exposed in API responses;
8. deterministic tests cover improvement, worsening, unchanged, missing, failed,
   multi-category, insufficient, incomplete, duplicate, and price-only cases.
