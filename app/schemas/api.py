"""Public REST request and response contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Period = Literal["current", "7d", "30d"]
ScopeName = Literal["global", "category"]


class CoverageResponse(BaseModel):
    window_start: datetime
    window_end: datetime
    window_days: int
    expected_runs: int
    successful_runs: int
    failed_runs_excluded: int
    unique_products: int
    products_with_sufficient_history: int
    coverage_percent: float
    schedule_completion_percent: float
    temporal_coverage_percent: float
    earliest_observation: datetime | None
    latest_observation: datetime | None
    complete: bool
    label: str
    interval_minutes: int


class TrendComponents(BaseModel):
    normalized_rank_improvement: float
    presence: float
    observation_confidence: float
    recency: float


class ProductListItem(BaseModel):
    id: int
    external_id: str
    title: str
    url: str | None
    image_url: str | None
    category_id: int | None
    price_toman: int | None
    discount_percent: float | None
    rating_stars: float | None
    rating_count: int | None
    availability_status: str | None
    last_snapshot_at: datetime | None
    current_rank: int
    rank_change: int | None = None
    observation_count: int
    first_observed: datetime | None
    last_observed: datetime | None
    average_rank: float
    best_rank: int
    presence_rate: float
    sufficient_history: bool
    start_rank: int | None = None
    end_rank: int | None = None
    rank_improvement: int | None = None
    trend_score: float | None = None
    trend_components: TrendComponents | None = None
    trend_formula: str | None = None


class PaginationResponse(BaseModel):
    limit: int
    offset: int
    total: int


class RankingListResponse(BaseModel):
    items: list[ProductListItem]
    pagination: PaginationResponse
    period: Period
    scope_key: str
    sort_type: str
    observed_at: datetime | None
    coverage: CoverageResponse | None
    data_basis: str


class TrendResponse(BaseModel):
    items: list[ProductListItem]
    coverage: CoverageResponse
    indicator_name: str
    not_sales_growth: bool
    formula: str


class CategoryResponse(BaseModel):
    id: int
    external_id: str
    title: str
    parent_id: int | None
    url: str | None
    last_seen_at: datetime
    children: list[CategoryResponse] = Field(default_factory=list)


class SnapshotResponse(BaseModel):
    observed_at: datetime
    price_toman: int | None
    discount_percent: float | None
    rating_stars: float | None
    rating_count: int | None
    availability_status: str | None
    currency_unit: str | None
    source: str
    variant_key: str
    seller: str | None
    warranty: str | None
    is_historical_import: bool


class RankHistoryResponse(BaseModel):
    observed_at: datetime
    scope_type: str
    scope_id: int | None
    scope_key: str
    sort_type: str
    rank_position: int
    collection_run_id: int


class ProductDetailResponse(BaseModel):
    id: int
    external_id: str
    identity_source: str
    title: str
    url: str | None
    image_url: str | None
    category_id: int | None
    first_seen_at: datetime
    last_seen_at: datetime
    latest_snapshot: SnapshotResponse | None
    price_history: list[SnapshotResponse]
    ranking_history: list[RankHistoryResponse]
    coverage: dict[str, dict[str, CoverageResponse]]
    history_limits: dict[str, str]


class DashboardResponse(BaseModel):
    latest_successful_collection_at: datetime | None
    latest_collection_status: str | None
    collection_health: str
    data_stale: bool
    monitored_products: int
    known_categories: int
    monitored_categories: int
    ranking_observations: int
    latest_current_best_sellers: list[ProductListItem]
    top_ranking_improvements: list[ProductListItem]
    coverage: dict[str, CoverageResponse]
    demo_data: bool
    terminology: dict[str, str]


class CollectionRunResponse(BaseModel):
    id: int
    started_at: datetime
    finished_at: datetime | None
    status: str
    scope_type: str
    scope_key: str
    category_id: int | None
    sort_type: str
    items_fetched: int
    items_saved: int
    duration_ms: int | None
    error_message: str | None
    source_metadata: dict[str, Any] | None


class CollectionScopeResponse(BaseModel):
    id: int
    scope_type: str
    scope_key: str
    category_id: int | None
    sort_type: str
    enabled: bool
    interval_minutes: int
    last_success_at: datetime | None
    last_error_at: datetime | None


class CollectionStatusResponse(BaseModel):
    runs: list[CollectionRunResponse]
    scopes: list[CollectionScopeResponse]


class ManualCollectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include_global: bool = True
    category_ids: list[int] = Field(default_factory=list, max_length=10)
    limit: int | None = Field(default=None, ge=1, le=50)
    include_price_history: bool = False

    @field_validator("category_ids")
    @classmethod
    def category_ids_are_unique(cls, value: list[int]) -> list[int]:
        if len(value) != len(set(value)):
            raise ValueError("category_ids must not contain duplicates")
        return value


class CollectionOutcomeResponse(BaseModel):
    run_id: int
    scope_key: str
    status: str
    items_fetched: int
    items_saved: int
    warnings: list[str]
    error: str | None


class ManualCollectionResponse(BaseModel):
    outcomes: list[CollectionOutcomeResponse]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    database: Literal["ready", "unavailable"]
    version: str
    timestamp: datetime
