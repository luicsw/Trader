// Mirrors app/api/routers/*.py response shapes. Kept as one file since the backend has no
// OpenAPI-client codegen wired up yet -- hand-written, update alongside backend changes.

export type CoverageTier = 'watchlist' | 'lookup'
export type Verdict = 'buy' | 'hold' | 'sell'
export type AnalysisTrigger = 'scheduled' | 'on_demand' | 'initial'

export interface LatestPrice {
  open: number | null
  high: number | null
  low: number | null
  close: number | null
  ts: string | null
}

export interface PriceSummary {
  last_close: number | null
  change_1d_pct: number | null
  change_1m_pct: number | null
  change_3m_pct: number | null
  change_1y_pct: number | null
  vs_50d_ma_pct: number | null
  vs_200d_ma_pct: number | null
}

export interface SwingLevels {
  high_20d: number | null
  low_20d: number | null
  high_60d: number | null
  low_60d: number | null
}

export interface NewsArticle {
  headline: string
  summary: string | null
  source: string | null
  published_at: string | null
  sentiment: 'positive' | 'neutral' | 'negative' | null
  url: string
}

export interface WikiSection {
  body: string
  generated_at: string
}

export type WikiSectionKey = 'overview' | 'key_metrics' | 'financials_summary' | 'news_digest' | 'risks_notes'

export interface PriceBar {
  ts: string
  open: number | null
  high: number | null
  low: number | null
  close: number | null
}

export interface Holding {
  ticker: string
  name: string | null
  category: string
  shares: number
  cost_basis_per_share: number
  acquired_at: string | null
  notes: string | null
  latest_price: number | null
  market_value: number | null
  cost_basis_total: number
  unrealized_gain: number | null
  unrealized_gain_pct: number | null
}

export interface Wiki {
  ticker: string
  name: string | null
  exchange: string | null
  sector: string | null
  category: string
  description: string | null
  logo_url: string | null
  market_cap: number | null
  coverage_tier: CoverageTier
  holding: Holding | null
  last_updated: string | null
  latest_price: LatestPrice | null
  price_summary: PriceSummary
  recent_swing_levels: SwingLevels
  recent_news: NewsArticle[]
  sections: Partial<Record<WikiSectionKey, WikiSection>>
}

export interface PromoteResult extends Wiki {
  initial_refresh_ok: boolean
  backfilled: boolean
}

export interface WatchlistSummary {
  ticker: string
  name: string | null
  sector: string | null
  category: string
  logo_url: string | null
  last_updated: string | null
  latest_price: { close: number | null; ts: string } | null
  latest_verdict: { verdict: Verdict; confidence: number; generated_at: string } | null
}

export interface SearchResult {
  symbol: string
  name: string | null
  type: string | null
}

export interface TickerSuggestion {
  symbol: string
  name: string | null
  exchange: string | null
  security_type: string | null
}

export interface PriceTargets {
  buy_at_or_below: number | null
  sell_at_or_above: number | null
  stop_loss: number | null
}

export interface HoldPeriod {
  min: number | null
  max: number | null
  note: string | null
}

export interface CitedSource {
  type: 'news' | 'fundamental' | 'price' | 'metric'
  reference: string
}

export interface Critique {
  id: number
  analysis_id: number
  agrees_with_verdict_direction: boolean
  biggest_weakness: string
  revised_price_targets: PriceTargets
  revised_confidence: number | null
  rationale: string
  generated_at: string
}

export interface Analysis {
  id: number
  ticker: string
  verdict: Verdict
  confidence: number
  reasoning: string
  price_targets: PriceTargets
  hold_period_days: HoldPeriod
  cited_sources: CitedSource[]
  trigger: AnalysisTrigger
  generated_at: string
}

export interface AnalysisWithCritiques extends Analysis {
  critiques: Critique[]
}

export interface ApiErrorBody {
  detail: string
}

export interface ChatMessage {
  id: number
  role: 'user' | 'assistant'
  content: string
  created_at: string
}
