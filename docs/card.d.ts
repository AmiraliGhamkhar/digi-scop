// Inspected upstream Digikala MCP card envelope.
// Snapshot: mmdju/digikala-mcp@927ab481 (2026-10-21).
// This is reference material, not a DigiScope REST response type. Keep it in
// sync with docs/tools.md only after contract inspection and adapter tests.
export interface UpstreamDigikalaCardShape {
  id: number;
  title: string;
  price_toman: number | null;
  price_rial: number | null;
  price_before_toman: number | null;
  discount_percent: number;
  rating_stars: number | null;
  rating_count: number;
  in_stock: boolean;
  seller: string | null;
  badges: string[];
  url: string | null;
  /** Deal countdown, only while a deal runs. */
  ends_in_seconds?: number | null;
  /** Deal deadline when the payload carries one; absent on ordinary cards. */
  ends_at?: string | null;
  /** Percentage sold, only when Digikala publishes it. */
  sold_percent?: number | null;
  /** Fewer than ten reviews: the score is observed but its sample is thin. */
  rating_low_sample?: true;
}
