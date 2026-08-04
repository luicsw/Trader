# Personal Investment Research App — Spec & Task Breakdown

**Status:** Phase 0 through Phase 5 functionally complete, plus "Post-Phase-5 Addition #1"
(categories, holdings, live chart, chat) complete. "Post-Phase-5 Addition #2" (portfolio income
projections, second-LLM forecasts, ticker autocomplete) and "Post-Phase-5 Addition #3"
(observability, data retention, alerts, backtest vs. benchmark, fundamentals ingestion) both
specced but not started. Phase 6 not started · **Last updated:** 2026-08-04
(Phase 5's UI has not been visually/interactively verified in a real browser — see its section below.)
**Two FR-21 routes are still unbuilt:** `/compare` (scheduled, Phase 6 T6.3) and `/settings`
(never in any task list until Addition #3 — see that section).

**Relationship to `plan.md`:** `plan.md` is the narrative design doc — architecture rationale,
rejected alternatives, tradeoffs. This file is the structured, testable specification and task
list derived from it — the source of truth for *what's done* and *what's left*. When they
conflict, `plan.md` explains why; this file says what to build next.

---

## 1. Overview & Scope

A personal, single-user tool for deciding which stocks to buy/hold/sell, backed by always-fresh
data and an AI that reasons over a browsable, wiki-style company page rather than raw numbers.
Python/FastAPI backend, React PWA frontend, fully free-tier stack (Neon, Render, GitHub Actions,
Gemini free tier), single shared-credential auth, no native app.

**In scope:** any-company lookup + watchlist tracking, AI buy/hold/sell verdicts with concrete
price targets and hold periods, an on-demand adversarial "second opinion" critique pass, a
full fintech-style chart set, installable mobile-first PWA, free-tier-safe reliability
mechanics (fallback/retry/circuit-breaker/rate-limiting).

**Out of scope:** multi-user accounts, real brokerage/trade execution, paid data feeds, native
mobile apps, portfolio tax/accounting features.

---

## 2. Goals & Non-Goals

| Goal | Why it's a goal |
|---|---|
| Never silently fail or corrupt data | Personal reliability requirement — see `plan.md` reliability mechanics |
| AI gives a real, actionable verdict (not a refusal/hedge) | Validated in Phase 0 — see §9 |
| Every AI conclusion traceable to visible wiki data | `wiki_service.assemble()` single-source-of-truth pattern |
| Zero paid services | Hosting/data/AI budget is $0 by requirement |
| Works well installed on a phone | Primary daily-use device is assumed to be a phone |

| Non-goal | Why not |
|---|---|
| Sub-second freshness | Free-tier cron cadence (15-30 min) is an accepted tradeoff |
| Perfect price-target precision | LLM synthesis is heuristic, not a technical-analysis engine — see `prompts/verdict_prompt_v1.md` design notes |
| High-availability (no cold starts) | Render free tier cold-starts after idle; accepted tradeoff |

---

## 3. Functional Requirements

Grouped by area. IDs are referenced from the task breakdown in §9.

### 3.1 Data ingestion & reliability
- **FR-1**: WHEN a scheduled refresh triggers for a watchlist ticker, THE SYSTEM SHALL fetch
  profile/price/news via the primary provider (Finnhub) and fall back to the secondary
  (Alpha Vantage) on failure or rate-limit.
- **FR-2**: WHEN a provider call fails with a transient error (timeout/5xx/429), THE SYSTEM
  SHALL retry with jittered exponential backoff before falling back to the other provider.
- **FR-3**: WHEN a provider call fails with a permanent error (bad ticker, auth error), THE
  SYSTEM SHALL NOT retry, SHALL log it (structured log + Sentry), and SHALL record it in
  `job_runs`.
- **FR-4**: THE SYSTEM SHALL persist every external write via idempotent upsert (`INSERT ...
  ON CONFLICT DO UPDATE`) so a mid-refresh crash cannot corrupt data.
- **FR-5**: WHEN a provider's circuit breaker is open, THE SYSTEM SHALL skip calls to that
  provider until cooldown/half-open probe succeeds.
- **FR-6**: THE SYSTEM SHALL NOT block any request path on a live external call — all reads
  come from Postgres; only background jobs write external data in.
- **FR-7**: Every API response carrying externally-sourced data SHALL include a `last_updated`
  timestamp so staleness is visible, never hidden.

### 3.2 Wiki / company data
- **FR-8**: THE SYSTEM SHALL expose `GET /companies/{ticker}/wiki` returning the assembled wiki
  dict for any valid ticker, watchlisted or not.
- **FR-9**: WHEN a requested ticker is absent from `companies` or stale, THE SYSTEM SHALL
  perform exactly one fetch-with-fallback pass, upsert, regenerate `wiki_sections`
  (template-based, no AI call), and return the page (lookup tier) — without adding it to
  `watchlist`.
- **FR-10**: `wiki_service.assemble(ticker)` SHALL be the single function used by both the wiki
  API route and the AI prompt builder — the AI must never see data the user can't also see.

### 3.3 Watchlist
- **FR-11**: `POST /watchlist/{ticker}/promote` SHALL insert into `watchlist` and immediately
  trigger a refresh + an `initial`-trigger AI analysis.
- **FR-12**: THE SYSTEM SHALL support removing a ticker from `watchlist` without deleting its
  historical `ai_analyses`/`ai_critiques` rows.
- **FR-13**: Only `watchlist` tickers with `active = true` SHALL receive recurring scheduled
  refresh/analysis; lookup-tier tickers get none.

### 3.4 AI verdict
- **FR-14**: WHEN an analysis is requested (scheduled or on-demand), THE SYSTEM SHALL render
  `prompts/verdict_prompt_v1.md` against `wiki_service.assemble(ticker)` and call Gemini with
  schema-forced JSON output (`response_schema`).
- **FR-15**: THE SYSTEM SHALL persist every generated verdict as a new `ai_analyses` row
  (append-only, never overwritten), including `price_targets` and `hold_period_days`.
- **FR-16**: WHEN Gemini's quota is exhausted: a scheduled analysis SHALL skip the cycle
  (logged in `job_runs`, retried next cycle); an on-demand request SHALL return a clear "AI
  quota reached, try later" response — never a silent failure or generic 500.
- **FR-17**: Scheduled watchlist analyses SHALL take priority over on-demand analyses when the
  daily Gemini budget is constrained.

### 3.5 Second opinion (adversarial critique)
- **FR-18**: `POST /companies/{ticker}/critique?analysis_id={id}` SHALL render
  `prompts/verdict_critique_prompt_v1.md` against the same wiki data plus the target
  `ai_analyses` row, and persist the result as a new `ai_critiques` row.
- **FR-19**: The critique pass SHALL only ever run on-demand (explicit user action) — never as
  part of a scheduled job, since it doubles the Gemini call cost of the analysis it critiques.
- **FR-20**: The critique pass SHALL be the *lowest*-priority consumer of the daily Gemini
  budget — below scheduled analyses and below on-demand first-pass verdicts.

### 3.6 Frontend
- **FR-21**: THE SYSTEM SHALL provide routes: `/login`, `/` (dashboard), `/search`,
  `/company/:ticker`, `/portfolio`, `/chat`, `/compare`, `/settings`. *(Built as of Addition #1:
  all but `/compare` — deferred to Phase 6 T6.3 — and `/settings`, which no phase ever
  scheduled; it is now a task under Addition #3's budget dashboard, because that feature,
  Phase 7's install prompt (T7.2), and the auth-credential UI all assume it exists.)*
- **FR-22**: The company wiki page SHALL render, in order: infobox header → AI verdict banner
  (badge, rationale, confidence, price-target strip, hold period, cited sources, "Get Second
  Opinion" button) → price chart panel → overview → key metrics → financials → recent news →
  AI analysis history → risks/notes.
- **FR-23**: Each wiki-page section SHALL fetch/load independently (own React Query key, own
  skeleton) so one slow section never blocks the rest of the page.
- **FR-24**: Every data-bearing view SHALL show a `FreshnessIndicator` ("Live" / "Updated Xm
  ago" / "Cached (offline)" / "Stale") derived from `last_updated` + React Query cache state.
- **FR-25**: THE SYSTEM SHALL be installable as a PWA (`display: standalone`) with an offline
  fallback for cached data and a clear "offline, will retry" toast for mutations — never a
  silent no-op.

### 3.7 Auth
- **FR-26**: All non-trivial endpoints SHALL require a single shared bearer/basic-auth
  credential (env var/secret) — no per-user accounts.

### 3.8 Portfolio income projection *(planned — Post-Phase-5 Addition #2)*
- **FR-27**: WHEN the user requests projected income for a horizon (30/60/90 days) — for the
  whole portfolio, a single holding, or an arbitrary selected subset — THE SYSTEM SHALL compute
  expected profit per eligible holding as `(latest ai_analyses.price_targets.sell_at_or_above -
  holdings.cost_basis_per_share) * holdings.shares`, and SHALL sum across the selected set for
  the aggregate figure.
- **FR-28**: A holding is only eligible for horizon *H*'s projection if its latest analysis has
  a non-null `sell_at_or_above` target AND `hold_period_days.min <= H`. WHEN a holding is
  ineligible (no analysis, no target, or the AI's own suggested minimum hold period exceeds
  *H*), THE SYSTEM SHALL report that holding's projection as `null` with an explicit reason
  string, never silently omitted or defaulted to zero.
- **FR-29**: `GET /portfolio/projected-income` SHALL return all three horizons (30/60/90)
  together by default, so one endpoint serves whole-portfolio, single-stock, and arbitrary-subset
  views without extra round trips. It SHALL accept two optional filters: `tickers` (restrict the
  holdings included) and `horizon` (restrict the response to a single horizon). Both are
  narrowing filters only — omitting them returns every holding at every horizon.

### 3.9 Multi-horizon forecast (second LLM) *(planned — Post-Phase-5 Addition #2)*
- **FR-30**: WHEN a forecast is requested for a watchlist ticker, THE SYSTEM SHALL render
  `prompts/forecast_prompt_v1.md` against `wiki_service.assemble(ticker)` (the same data the
  user can see — same traceability guarantee as FR-10) and call **Groq** with schema-forced JSON
  output covering horizons 30/60/90/180/360 days, each with an expected low, expected high,
  **its own per-horizon confidence**, and rationale, in a single call. Confidence is per-horizon
  rather than one value for the whole set, both because `price_forecasts` stores one row per
  horizon (a single top-level value would just be copied into all five) and because confidence
  genuinely should decay from 30d to 360d — that decay is useful signal, not noise.
- **FR-31**: THE SYSTEM SHALL persist every forecast generation as new `price_forecasts` rows
  (append-only, one row per horizon per generation, never overwritten), analogous to
  `ai_analyses`.
- **FR-32**: The forecast pass SHALL be on-demand only and restricted to watchlist tickers —
  never run as part of a scheduled job, and rejected for lookup-tier tickers — mirroring the
  critique pass's gating (FR-19, and the "watchlist-only" resolution in §11).
- **FR-33**: Groq calls SHALL be retried/rate-limited/circuit-broken exactly like every other
  provider (FR-1 through FR-5 pattern), on a budget entirely independent of Gemini's — Groq
  quota exhaustion SHALL degrade the same way as Gemini's (FR-16: a clear "try later" response,
  never a silent failure or generic 500). Because that machinery logs to
  `provider_call_log.provider`, `groq` MUST be added to **both** the `ProviderName` Python enum
  and the Postgres `providername` type before any Groq call can succeed — see the migration task
  in Addition #2.

### 3.10 Ticker directory / autocomplete *(planned — Post-Phase-5 Addition #2)*
- **FR-34**: THE SYSTEM SHALL expose `GET /tickers/search?q=` backed by a locally cached
  `ticker_directory` table — no live provider call per request — refreshed periodically (weekly)
  by a dedicated job, so it's safe to call on every keystroke of a type-ahead dropdown. The bulk
  source endpoint SHALL be confirmed free-tier accessible before ingestion code is written (see
  the derisk task in Addition #2); if trigram matching is used rather than plain `ILIKE`, the
  `pg_trgm` extension SHALL be created by migration, not assumed present.
- **FR-35**: WHEN adding or editing a holding, THE SYSTEM SHALL offer a type-ahead dropdown
  backed by FR-34, but SHALL still allow manual ticker entry for symbols absent from the local
  directory (e.g. newly listed or OTC tickers) — never a hard block on manual entry.

### 3.11 Observability *(planned — Post-Phase-5 Addition #3)*
- **FR-36**: THE SYSTEM SHALL expose current-day usage vs. configured budget for every
  rate-limited provider (Finnhub, Alpha Vantage, Gemini, Groq) via `GET /status/budget`, so
  quota exhaustion is visible before a request is rejected, not only after.
- **FR-37**: WHEN a company has more than one `ai_analyses` row, THE SYSTEM SHALL include a
  diff of the latest row against the immediately preceding one (verdict changed, confidence
  delta, price-target deltas, hold-period change) in the `GET /companies/{ticker}/analyses`
  response. This diff SHALL be computed by a single shared function that FR-41's
  `verdict_change` alert trigger also calls — both features need exactly "did the verdict change
  versus the previous analysis for this company", and it is implemented once, not twice.

### 3.12 Data retention *(planned — Post-Phase-5 Addition #3)*
- **FR-38**: THE SYSTEM SHALL prune `"5m"`-interval `price_bars` rows older than a configured
  `price_bars_retention_days`, while never pruning `"1d"`-interval rows, via the same
  dual-trigger (cron + APScheduler) pattern as every other job (NFR-1).

### 3.13 Fundamentals ingestion *(planned — Post-Phase-5 Addition #3)*
- **FR-39**: WHEN a ticker is promoted to the watchlist, and thereafter on a low-frequency
  scheduled refresh (not the 15-30 min price/news cycle), THE SYSTEM SHALL fetch fundamentals
  (revenue, net income, EPS, margins, FCF) via Alpha Vantage and upsert into the `fundamentals`
  table (already in §6, never implemented), subject to the same rate-limiter/circuit-breaker
  treatment as every other Alpha Vantage call.
- **FR-40**: Fundamentals refresh SHALL run at most monthly per company, never on the main
  refresh cadence, to protect Alpha Vantage's small daily budget already relied on for price
  fallback, news fallback, and historical backfill.

### 3.14 Alerts *(planned — Post-Phase-5 Addition #3)*
- **FR-41**: Immediately after each scheduled refresh/analysis cycle completes, THE SYSTEM
  SHALL evaluate alert conditions and persist any newly triggered condition as a new `alerts`
  row. Two condition families:
  - `verdict_change` — verdict direction changed since the prior analysis, detected via FR-37's
    shared diff function.
  - `sell_target_hit` / `stop_loss_hit` — price crossed a stored `sell_at_or_above` or
    `stop_loss` target. Crossing SHALL be tested against the **latest `"1d"` bar's `high` and
    `low`**, not its `close`: scheduled refresh only ever writes a `"1d"` bar truncated to
    midnight UTC, and `"5m"` bars exist only while a company page is open in a browser
    (Addition #1's live-quote poll), so `close` alone would silently miss any target crossed and
    then retraced within the same session. High/low costs nothing extra — it is data already in
    the row being written.
- **FR-41a**: Alert evaluation SHALL skip `watchlist` rows with `is_benchmark = true` (FR-45) —
  a benchmark is tracked for price history only and has no verdicts or targets to alert on.
- **FR-42**: THE SYSTEM SHALL NOT create a new alert for a condition that already has an
  unacknowledged open alert of the same `alert_type` for the same company.
- **FR-43**: THE SYSTEM SHALL expose `GET /alerts` (unacknowledged + recent) and `POST
  /alerts/{id}/acknowledge`.
- **FR-44** *(stretch, sequenced after Phase 7)*: WHEN the user has granted browser push
  permission, THE SYSTEM SHALL additionally deliver new alerts as a Web Push notification
  (VAPID, free) — best-effort only, never the sole delivery channel (NFR-7).

### 3.15 Backtest vs. benchmark *(planned — Post-Phase-5 Addition #3)*
- **FR-45**: THE SYSTEM SHALL designate one or more benchmark tickers (default `SPY`) that
  receive watchlist-level continuous *price* tracking regardless of whether the user holds them,
  solely to support benchmark comparison. Benchmarks SHALL be marked with a new
  `watchlist.is_benchmark` flag and SHALL be excluded from every other consequence of watchlist
  membership. "On the watchlist" has accreted five consequences across the phases; a benchmark
  must inherit exactly one of them. **Excluded:**
  - no `initial`-trigger AI analysis on promote (FR-11) and no recurring scheduled analysis
    (FR-13) — a benchmark burns zero Gemini quota, ever;
  - not returned by `GET /watchlist`, so it never appears as a dashboard card;
  - not included in `chat_service`'s grounding set (which today grounds on *every* tracked
    company), so chat replies aren't diluted by an index the user doesn't hold;
  - not evaluated for alerts (FR-41a).

  **Retained:** scheduled price refresh and the one-time historical backfill — that is the entire
  point of tracking it.
- **FR-46**: `GET /verdicts/backtest?benchmark=` SHALL compute the hypothetical aggregate
  return of following every historical `buy` verdict (enter at verdict-time price, exit at
  horizon or at its sell target if hit first — "hit" tested against daily bar `high`/`low` for
  the same reason FR-41 does) versus holding the benchmark ticker over the same
  window, broken down by confidence bucket like the existing track-record endpoint. This is a
  simplified historical simulation (no fees/slippage, single historical path) — see NFR-8.
- **FR-46a**: The backtest SHALL report the window it actually covered, and SHALL exclude
  verdicts predating the benchmark's own `price_bars` history rather than silently comparing
  against nothing. The benchmark's history starts at whatever the one-time Alpha Vantage backfill
  provides (`outputsize=compact`, ~100 trading days — `full` is premium-gated, confirmed live in
  the post-Phase-4 backfill addition) counted from the day it is first tracked, so early on the
  comparable window is short and the aggregate is correspondingly noisy. Stating the window is
  the mitigation; deepening it is not possible on the free tier.

---

## 4. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-1 | Reliability mechanics (FR-1 to FR-7) apply uniformly regardless of trigger source (cron vs. warm process) — refresh/analyze logic lives once in `services/`, called identically by `api/routers/refresh.py` and `jobs/tasks.py`. |
| NFR-2 | Entire stack must run at $0/month: Neon free Postgres, Render free web service, GitHub Actions free cron, Vercel/Netlify free static hosting, Gemini free tier. |
| NFR-3 | Mobile-first responsive: bottom tab bar on phone / nav rail on desktop, ≥44px touch targets, RSI/MACD panes collapse to accordion on narrow screens. |
| NFR-4 | No silent failures anywhere — every failure path (provider, AI, job) is logged to `job_runs` and/or Sentry and surfaced to the user in some form. |
| NFR-5 | Reproducibility: every `ai_analyses` row stores the exact `context_snapshot` sent to Gemini; prompt changes are versioned by filename (`_v2.md`, etc.), never edited in place. **Known gap:** `ai_critiques` has no `context_snapshot` column of its own (see §6) — a critique is only reproducible via the `ai_analyses` row it points to, which is *not* the same thing, since a critique run days later reads freshly-refreshed wiki data. Either add the column (migration) or accept that critiques are less reproducible than verdicts; do not claim otherwise. |
| NFR-6 | Accepted cold-start tradeoff: first request after Render idle may take 10-30s — never treated as a bug. |
| NFR-7 *(planned)* | Web Push alert delivery (FR-44) is best-effort — browser/OS support varies (notably iOS Safari) — the in-app alerts feed (FR-43) SHALL remain the reliable channel regardless of push delivery success. |
| NFR-8 *(planned)* | The backtest (FR-46) SHALL be presented as a simplified historical simulation, not a validated trading strategy — no fees/slippage modeling, single historical path, no claim about future performance. |

---

## 5. Architecture Summary

```
 GitHub Actions (cron) ──POST /internal/refresh──────▶ FastAPI (Render) ──▶ Postgres (Neon)
 GitHub Actions (cron) ──POST /internal/analyze-scheduled──▶  │                    │
                                                               ├─▶ Finnhub (primary)
                                                               ├─▶ Alpha Vantage (fallback)
                                                               ├─▶ Gemini (verdict + critique + chat)
                                                               └─▶ Groq (forecast, separate quota,
                                                                    on-demand only) *(planned)*

 React PWA ──HTTPS/JSON──▶ FastAPI ──reads only──▶ Postgres
```

Postgres is always the source of truth the API/frontend reads from. Full rationale for this
topology (why hosted, why these specific free tiers, why APScheduler over Celery) is in
`plan.md` → "Deployment Decision".

---

## 6. Data Model

All tables live in Postgres, managed via Alembic migrations under `app/db/migrations/`.

| Table | Key columns | Constraints / indexes |
|---|---|---|
| `companies` | name, exchange, sector, description, logo, market_cap, `coverage_tier` (watchlist\|lookup), `last_profile_refresh_at` | PK on ticker/id |
| `watchlist` | company_id, refresh_interval_minutes, last_scheduled_refresh_at, last_scheduled_analysis_at, active, `is_benchmark` *(planned — Post-Phase-5 Addition #3)* | FK → companies; `is_benchmark = true` means price-tracking only — no AI analysis, no dashboard card, no chat grounding, no alerts (FR-45) |
| `price_bars` | company_id, ts, interval, open/high/low/close/volume | UNIQUE `(company_id, ts, interval)`; INDEX `(company_id, interval, ts DESC)` |
| `news_articles` | company_id, headline, summary, url, source, published_at, sentiment | UNIQUE `(company_id, url)` |
| `fundamentals` *(speced since Phase 1, still unimplemented — see Post-Phase-5 Addition #3)* | company_id, period, fiscal_period, revenue, net_income, eps, margins, fcf... | UNIQUE `(company_id, period, fiscal_period)` |
| `wiki_sections` | company_id, section_key (overview\|financials_summary\|news_digest\|key_metrics\|risks_notes), body, generated_at | UNIQUE `(company_id, section_key)` |
| `ai_analyses` | company_id, verdict, confidence, reasoning_text, **price_targets** (JSONB: buy_at_or_below/sell_at_or_above/stop_loss), **hold_period_days** (JSONB: min/max/note), cited_sources (JSONB), context_snapshot (JSONB), trigger (scheduled\|on_demand\|initial), generated_at | Append-only; INDEX `(company_id, generated_at DESC)` |
| `ai_critiques` | analysis_id (FK → ai_analyses), agrees_with_verdict_direction (bool), biggest_weakness (text), revised_price_targets (JSONB, nullable per field), revised_confidence (nullable float), rationale (text), generated_at | Append-only; always on-demand-triggered. **No `context_snapshot` column** — see NFR-5's known gap; a critique reads wiki data as of *its own* run time, which may differ from the analysis it critiques |
| `provider_call_log` | provider, status, called_at | Backs rate limiter + circuit breaker; audit trail |
| `job_runs` | job_name, status, error_message, attempt | Never-silent-failure observability |
| `verdict_outcomes` *(post-Phase-4 addition)* | analysis_id (FK → ai_analyses), horizon_days, price_at_verdict, price_at_horizon, price_change_pct, directionally_correct, evaluated_at | Append-only; UNIQUE `(analysis_id)` (single fixed horizon) — checks verdict/confidence calibration against actual price, see §9 "Post-Phase-4 Addition" |
| `holdings` *(post-Phase-5 addition)* | company_id, shares, cost_basis_per_share, acquired_at, notes, created_at, updated_at | UNIQUE `(company_id)` — one row per company, not tax lots (explicit scope decision) |
| `chat_messages` *(post-Phase-5 addition)* | role (user\|assistant), content, created_at | Append-only, linear, single-user — no multi-conversation concept |
| `price_bars` interval `"5m"` *(post-Phase-5 addition)* | same columns as the `"1d"` rows above, one bucket per 5 minutes | Aggregated server-side from repeated `/quote` polls (Finnhub's free tier has no intraday candle endpoint) — not a new table, just a new `interval` value in the existing `price_bars` table |
| `price_forecasts` *(planned — Post-Phase-5 Addition #2)* | company_id, horizon_days, expected_low, expected_high, confidence, rationale, model, trigger, generated_at | Append-only, one row per horizon per generation; INDEX `(company_id, horizon_days, generated_at DESC)`. `confidence` is **per-horizon**, sourced from the prompt's per-horizon field (FR-30) — not one value copied across five rows |
| `ticker_directory` *(planned — Post-Phase-5 Addition #2)* | symbol, name, exchange, security_type, updated_at | UNIQUE `(symbol)`; bulk-refreshed weekly, backs local autocomplete (FR-34). Bulk source endpoint to be confirmed free-tier accessible first — Finnhub's symbol listing if free, Alpha Vantage `LISTING_STATUS` otherwise |
| `alerts` *(planned — Post-Phase-5 Addition #3)* | company_id, alert_type (verdict_change\|sell_target_hit\|stop_loss_hit), message, triggered_at, acknowledged, acknowledged_at | Not append-only — `acknowledged` is a real state transition; "one open alert per `(company_id, alert_type)`" enforced in `alert_service`, not a DB constraint (FR-41–43) |
| `push_subscriptions` *(planned, stretch — Post-Phase-5 Addition #3)* | endpoint, p256dh_key, auth_key, created_at | UNIQUE `(endpoint)`; only needed if the Web Push extension (FR-44) is built |

---

## 7. API Contract

| Method & Path | Purpose | Auth | Notes |
|---|---|---|---|
| `GET /health` | Liveness probe | none | For Render health checks |
| `GET /status` | Recent `job_runs` + provider health summary | shared credential | Post-deploy verification target |
| `GET /status/budget` *(planned — Post-Phase-5 Addition #3)* | Current-day usage vs. configured budget per rate-limited provider (FR-36) | shared credential | Reuses `rate_limiter`'s existing sliding-window computation, no new tracking |
| `GET /companies/search?q=` | Ticker/name search — proxies Finnhub's `/search` (Phase 5, built alongside the frontend that needed it) | shared credential | Backs `/search` route; Finnhub-only, no Alpha Vantage fallback (not worth the fallback-only budget for a discovery feature) |
| `GET /companies/{ticker}/wiki` | Full assembled wiki page (FR-8, FR-9) | shared credential | `last_updated` on every field group |
| `GET /watchlist` *(Phase 5)* | Summary list of active watchlist companies (ticker/name/latest price/latest verdict) | shared credential | Backs the dashboard grid; deliberately thin, not a full wiki assembly per ticker |
| `POST /watchlist/{ticker}/promote` | Add to watchlist + trigger initial refresh/analysis (FR-11) | shared credential | Idempotent |
| `DELETE /watchlist/{ticker}` | Remove from watchlist (FR-12) | shared credential | Does not delete history |
| `POST /companies/{ticker}/analyze` | On-demand AI verdict (FR-14) | shared credential | 429-style clear response on quota exhaustion (FR-16) |
| `GET /companies/{ticker}/analyses` *(Phase 5; response extended — Post-Phase-5 Addition #3)* | Full verdict history with nested critiques, latest row includes a diff against the prior one (FR-37) | shared credential | Backs the verdict banner (latest) + "AI Analysis History" section (FR-22); no separate "latest analysis" endpoint |
| `POST /companies/{ticker}/critique?analysis_id=` | On-demand second opinion (FR-18) | shared credential | Lowest budget priority (FR-20) |
| `POST /internal/refresh` | Cron-triggered refresh for all active watchlist tickers | shared credential | Idempotent, safe no-op if too soon |
| `POST /internal/analyze-scheduled` | Cron-triggered daily scheduled analyses | shared credential | Budget-priority applies (FR-17) |
| `GET /compare?tickers=A,B,C` | Normalized overlay + peer fundamentals data for 2-5 tickers | shared credential | Backs `/compare` route |
| `POST /internal/evaluate-outcomes` *(post-Phase-4)* | Cron-triggered evaluation of verdicts past the 30-day horizon | shared credential | Never fails on missing price data, just retries next cycle |
| `GET /verdicts/track-record` *(post-Phase-4)* | Aggregate accuracy/return by verdict type and by confidence bucket | shared credential | See §9 "Post-Phase-4 Addition" — the calibration check |
| `GET /holdings` *(post-Phase-5)* | List tracked positions with computed gain/loss | shared credential | Backs `/portfolio` |
| `POST /holdings/{ticker}` *(post-Phase-5)* | Upsert a position (shares, cost_basis_per_share, acquired_at, notes) | shared credential | Auto-promotes to watchlist the first time only |
| `DELETE /holdings/{ticker}` *(post-Phase-5)* | Remove a tracked position | shared credential | Idempotent; leaves the watchlist entry untouched |
| `GET /companies/{ticker}/price-history?interval=&limit=` *(post-Phase-5)* | Historical bars for chart context | shared credential | Read-only, no provider calls |
| `POST /companies/{ticker}/live-quote` *(post-Phase-5)* | One near-live price poll, aggregated into a `"5m"` bar | shared credential | Called by the frontend only while a company page is open, ~every 20s |
| `GET /chat/messages` *(post-Phase-5)* | Full chat history | shared credential | Backs `/chat` |
| `POST /chat` *(post-Phase-5)* | Send a chat message, get a grounded AI reply | shared credential | Grounded to tracked companies only (user decision); lowest Gemini budget priority |
| `GET /portfolio/projected-income?tickers=&horizon=` *(planned — Post-Phase-5 Addition #2)* | Expected profit at 30/60/90-day horizons, whole portfolio / single stock / selected subset (FR-27–29) | shared credential | Pure computation over existing `holdings` + latest `ai_analyses`; no new AI call. Both params are optional narrowing filters — bare call returns all holdings × all three horizons (FR-29) |
| `POST /companies/{ticker}/forecast` *(planned — Post-Phase-5 Addition #2)* | On-demand multi-horizon (30/60/90/180/360d) high/low forecast via Groq (FR-30–32) | shared credential | Watchlist-only, on-demand-only, mirrors `/critique`'s gating; own independent Groq budget |
| `GET /companies/{ticker}/forecasts` *(planned — Post-Phase-5 Addition #2)* | Latest + historical forecast rows | shared credential | Backs a new wiki-page forecast panel |
| `GET /tickers/search?q=&limit=` *(planned — Post-Phase-5 Addition #2)* | Local-only ticker/name autocomplete for the Add Holding form (FR-34–35) | shared credential | No live provider call; distinct from `/companies/search` (which proxies Finnhub live) |
| `POST /internal/refresh-ticker-directory` *(planned — Post-Phase-5 Addition #2)* | Cron-triggered weekly bulk refresh of `ticker_directory` | shared credential | Same dual-trigger pattern as every other job (NFR-1); source endpoint pending the derisk check in §9 |
| `POST /internal/prune-price-bars` *(planned — Post-Phase-5 Addition #3)* | Cron-triggered deletion of `"5m"` bars older than `price_bars_retention_days` (FR-38) | shared credential | Never touches `"1d"` rows; same dual-trigger pattern (NFR-1) |
| `POST /internal/refresh-fundamentals` *(planned — Post-Phase-5 Addition #3)* | Cron-triggered monthly fundamentals refresh for watchlist companies (FR-39, FR-40) | shared credential | Alpha Vantage-sourced; deliberately low-frequency to protect its small daily budget |
| `GET /alerts` *(planned — Post-Phase-5 Addition #3)* | Unacknowledged + recent alerts (FR-43) | shared credential | Backs the nav bell-icon feed |
| `POST /alerts/{id}/acknowledge` *(planned — Post-Phase-5 Addition #3)* | Acknowledge an alert (FR-43) | shared credential | Clears the "open alert" state for that `(company, alert_type)` |
| `GET /verdicts/backtest?benchmark=` *(planned — Post-Phase-5 Addition #3)* | Hypothetical strategy return vs. a benchmark ticker, by confidence bucket (FR-45, FR-46) | shared credential | Simplified historical simulation — see NFR-8 |
| `POST /push/subscribe` / `DELETE /push/subscribe` *(planned, stretch — Post-Phase-5 Addition #3)* | Register/remove a Web Push subscription (FR-44) | shared credential | Only needed if the Web Push extension is built; sequenced after Phase 7's service worker |

---

## 8. AI Prompt Contracts

Both prompt files are versioned by filename, never edited in place (NFR-5), and were validated
standalone in Phase 0 before any backend code was written (see §9).

| File | Purpose | Input | Output schema |
|---|---|---|---|
| `prompts/verdict_prompt_v1.md` | First-pass buy/hold/sell verdict (superseded by v2 as the live default — kept for reproducibility of old `ai_analyses` rows) | `wiki_service.assemble(ticker)` dict | `{verdict, confidence, reasoning, price_targets{buy_at_or_below, sell_at_or_above, stop_loss}, hold_period_days{min, max, note}, cited_sources[]}` |
| `prompts/verdict_prompt_v2.md` *(post-Phase-5, current default)* | Same as v1 plus a "Your Position" section (holdings-aware, honest "no position" when none exists) | same wiki dict, now including a `holding` key | Same schema as v1 |
| `prompts/verdict_critique_prompt_v1.md` | Adversarial second opinion on an existing verdict | same wiki dict + the `ai_analyses` row being critiqued | `{agrees_with_verdict_direction, biggest_weakness, revised_price_targets{...}, revised_confidence, rationale}` |
| `prompts/chat_prompt_v1.md` *(post-Phase-5)* | Grounded chat reply — restricted to tracked companies only | list of every tracked company's wiki dict + chat history + the new user message | `{reply}` |
| `prompts/forecast_prompt_v1.md` *(planned — Post-Phase-5 Addition #2)* | Multi-horizon (30/60/90/180/360d) expected low/high forecast, second independent model (Groq) | `wiki_service.assemble(ticker)` dict | `{forecasts: [{horizon_days, expected_low, expected_high, confidence, rationale}]}` — confidence is per-horizon (FR-30), not one value for the set |

Every Gemini-backed prompt above is schema-forced via `response_schema` (not instruction-only
parsing); the Groq-backed forecast prompt uses Groq's own JSON/schema mode for the same reason.
Standalone
test harness: `scripts/test_gemini_prompt.py` (`--fixture`, `--model`, `--repeat`, `--critique`
flags) against fixtures in `scripts/fixtures/` (`sample_wiki_data.json` — synthetic normal case,
`sample_wiki_thin.json` — synthetic thin/contradictory case, `aapl_live.json` — real researched
data, snapshot dated 2026-08-02).

---

## 9. Task Breakdown

Checkboxes track implementation status. Each phase's "Verify" line is its exit criterion —
don't start the next phase until it passes.

### Phase 0 — Derisk the AI prompt ✅ DONE
- [x] T0.1 Draft `verdict_prompt_v1.md` (private single-user framing, grounding constraint, schema-forced JSON)
- [x] T0.2 Build standalone `scripts/test_gemini_prompt.py` (zero dependency on backend/DB)
- [x] T0.3 Validate against normal + thin synthetic fixtures — verdict varies, thin case produces honest low-confidence hold
- [x] T0.4 Extend schema with `price_targets` + `hold_period_days` (FR-15)
- [x] T0.5 Build `verdict_critique_prompt_v1.md` adversarial second-opinion pass + wire `--critique` flag
- [x] T0.6 Validate both prompts against real researched data (AAPL, 2026-08-02 snapshot) — verdict, targets, and critique all judged sound on independent review
- [x] T0.7 Secure API key handling: `.env` + `.gitignore` + `.env.example`, no secrets in git history
- **Verified:** consistent buy/hold/sell verdicts (not always "hold"), internally-consistent price targets anchored to real swing levels, honest nulls on thin data, adversarial critique produces genuine (not rubber-stamped) pushback.

### Phase 1 — Backend skeleton ✅ DONE
- [x] T1.1 Initialize Python project structure per `plan.md` → "Backend (FastAPI) Structure" (`app/`, `tests/`)
- [x] T1.2 `docker-compose.yml` for local Postgres
- [x] T1.3 SQLAlchemy models + first Alembic migration: `companies`, `price_bars` (minimal columns to start)
- [x] T1.4 FastAPI app boot + `api/routers/health.py` (`GET /health`)
- [x] T1.5 `providers/finnhub_client.py` implementing `providers/base.py` interface (no fallback yet), unit-tested against recorded fixtures with `respx` (no live network)
- [x] T1.6 `GET /companies/{ticker}/wiki` returning real price/profile data for a real ticker (AAPL), upserted via `ON CONFLICT DO UPDATE` (FR-4)
- **Verified:** `/health` → 200; `alembic upgrade head` creates `companies`/`price_bars` cleanly; `/companies/AAPL/wiki` → 200 with real Finnhub data, correctly persisted (confirmed via direct query).

**Local dev environment note:** on this machine, Docker Desktop's host↔container port-forwarding
proxy (and, separately, Podman's) both failed to deliver TCP traffic correctly from Windows host
to a containerized Postgres — proven to be host-level interference (likely the corporate-managed
endpoint security agent — Windows Defender NIS was active), not a bug in either container
runtime, since Postgres itself and its password auth worked flawlessly from *inside* both
Docker's and Podman's containers, and identically failed from the host with both backends.
Workaround: PostgreSQL installed natively inside the `Ubuntu` WSL distro (`apt install
postgresql`), with a matching `.venv-wsl` Python virtualenv also inside WSL — both the app and the
database now run in the same Linux VM, so nothing crosses the Windows host boundary where the
interference occurs. `docker-compose.yml` is kept as-is for anyone (or any future machine) where
Docker's port-forwarding works normally; this is a per-machine workaround, not a project-wide
architecture change. Flagged as a question for IT if Docker Desktop itself needs to work on this
machine specifically.

### Phase 2 — Wiki assembly + lookup tier ✅ DONE
- [x] T2.1 `services/wiki_service.py::assemble(ticker)` (FR-10)
- [x] T2.2 `services/lookup_service.py::get_or_fetch(ticker)` (FR-9)
- [x] T2.3 `wiki_sections` generation, template-based, no AI yet
- **Verify:** look up several arbitrary (non-watchlisted) tickers end-to-end.
- **Verified:** looked up AAPL/MSFT/NVDA live against real Finnhub data — each persisted as
  `coverage_tier=lookup` (never added to `watchlist`), all five `wiki_sections` rows generated
  (`overview`/`key_metrics` from real data, honest "not yet ingested" placeholders for
  `financials_summary`/`news_digest`/`risks_notes` since those source tables don't exist until
  later phases), and a repeat request served from Postgres in ~6ms with no new Finnhub call.
  16/16 tests pass (unit: section-template rendering; integration: real Postgres,
  transaction-rolled-back, covering `assemble()` and `get_or_fetch()` freshness/staleness
  behavior).

### Phase 3 — Watchlist + scheduler + reliability ✅ DONE
- [x] T3.1 `watchlist` table/CRUD + `api/routers/watchlist.py` (FR-11, FR-12, FR-13)
- [x] T3.2 `jobs/scheduler.py` (APScheduler) + `api/routers/refresh.py` (`POST /internal/refresh`) calling shared `refresh_service` functions (NFR-1)
- [x] T3.3 `providers/alpha_vantage_client.py` + `fetch_with_fallback()` orchestrator (FR-1)
- [x] T3.4 `services/rate_limiter.py` — sliding window per provider, computed directly from `provider_call_log`
- [x] T3.5 `services/circuit_breaker.py` (FR-5)
- [x] T3.6 `provider_call_log` + `job_runs` tables and writers (FR-3, FR-4)
- [x] T3.7 Retry/backoff via `tenacity` (FR-2)
- **Verify:** reliability drill — point Finnhub client at an invalid key/URL, confirm circuit breaker trips, Alpha Vantage fallback kicks in, `job_runs`/Sentry surface the failure, no crashed refresh cycle.
- **Verified:** live drill against the real running app + real Postgres — pointed a fresh
  process at an invalid `FINNHUB_API_KEY`, promoted IBM (with valid credentials first), forced
  its watchlist entry due, then hit `POST /internal/refresh` repeatedly with the broken key.
  Real Finnhub 401s were logged to `provider_call_log`/`job_runs` with clear messages on each
  of the first 3 attempts; the 4th attempt's `job_runs` row read `"finnhub: circuit open"`,
  confirming the breaker tripped after `circuit_breaker_failure_threshold` (3) consecutive
  failures — and the server never crashed across any attempt. Drill artifacts (IBM watchlist
  entry, `provider_call_log`/`job_runs` rows) were cleaned up afterward. "Alpha Vantage takes
  over" itself was verified via mocked integration tests
  (`tests/integration/test_provider_orchestrator.py`), not a live drill, since no real
  `ALPHA_VANTAGE_API_KEY` is configured yet — get a free key from
  alphavantage.co/support/#api-key if you want that leg live-verified too.
  54 unit+integration tests pass (up from 20 at the end of Phase 2), including new coverage
  for `finnhub_client`/`alpha_vantage_client` normalization, `rate_limiter`, `circuit_breaker`,
  `provider_orchestrator`, `refresh_service`, and `watchlist_service`.
- **Post-phase hardening (before starting Phase 4):** a coverage audit found the `watchlist`/
  `wiki` routers had HTTP-layer tests missing (only tested at the service layer), the
  APScheduler wiring in `jobs/scheduler.py` had zero coverage, and no migration's `downgrade()`
  had ever actually been executed. Closed all three: 9 new tests (54 → 63 passing) plus a live
  `alembic upgrade head` → `downgrade base` → `upgrade head` round-trip against a disposable
  throwaway database (all three migrations' downgrades run cleanly). Full detail in
  [`tests/phase-3.md`](tests/phase-3.md#post-phase-hardening-requested-before-starting-phase-4).
- **Design decisions beyond the literal task list:**
  - `providers/*` clients now return a **normalized** shape (`name/exchange/sector/logo_url/
    market_cap`, `open/high/low/close/previous_close`) instead of provider-specific keys, so
    `fetch_with_fallback()` can hand callers the same shape regardless of which provider
    answered. `providers/base.py` also gained `TransientProviderError`/`PermanentProviderError`
    subclasses so the orchestrator knows retry-then-fallback vs. immediate-fallback.
  - `fetch_with_fallback()` lives in `services/provider_orchestrator.py`, not `providers/`,
    because it depends on the DB-backed rate limiter/circuit breaker — `providers/` stays pure
    API clients with no DB dependency.
  - Rate limiter and circuit breaker are both **stateless, computed directly from
    `provider_call_log`** on every check (sliding-window count / last-N-calls scan) rather than
    in-memory token buckets or state machines — this is what "seeded from `provider_call_log`"
    in `plan.md` reduces to in practice, and it means state survives Render's frequent cold
    starts for free, with nothing to lose or re-seed.
  - A shared `services/ingest_service.py::upsert_profile_and_quote()` factors the upsert logic
    that both `lookup_service` and `refresh_service` need, keeping refresh mechanics genuinely
    single-sourced (NFR-1) rather than duplicated between the two call paths.
  - Sentry (mentioned in `plan.md`) is not wired yet — it needs a real DSN, which is a
    deploy-time concern; structured failure visibility for now comes entirely from `job_runs`
    (satisfies FR-3/NFR-4 in spirit). Revisit alongside Phase 8 deploy prep.
  - `watchlist_service.promote()` implements the refresh half of FR-11 only — the
    "`initial`-trigger AI analysis" half is deferred to Phase 4 since `ai_service` doesn't
    exist yet (documented in the module docstring so it isn't mistaken for an oversight).
  - Backend auth (FR-26) is still not wired on any endpoint, including the new
    `/watchlist/*` and `/internal/refresh` routes — this matches the existing task breakdown,
    which only wires the shared credential at Phase 8 deploy time (`T8.2`/`T8.3`), since
    everything today runs local-only.
  - **Test-isolation fix:** `rate_limiter`/`circuit_breaker` read every already-committed row
    in `provider_call_log`, not just rows a given test writes. The reliability drill above left
    real failure rows in the shared dev database, which then made every circuit-breaker-
    dependent test see a tripped breaker and fail. Fixed by having
    `tests/integration/conftest.py`'s `db_session` fixture delete existing `provider_call_log`
    rows inside the test's (rolled-back) transaction before yielding, so manual live testing
    against this same dev DB can never poison the suite again.

### Phase 4 — AI pipeline (verdict + second opinion) ✅ DONE
- [x] T4.1 `providers/gemini_client.py` wrapping `google-genai` with retry/backoff + rate-limit bucket
- [x] T4.2 `services/ai_service.py::build_prompt(ticker)` rendering `verdict_prompt_v1.md` against `wiki_service.assemble()` (FR-14)
- [x] T4.3 `ai_analyses` table + write path + budget/priority logic (FR-15, FR-16, FR-17)
- [x] T4.4 `api/routers/analysis.py`: `POST /companies/{ticker}/analyze`, `POST /internal/analyze-scheduled`
- [x] T4.5 `ai_critiques` table + `build_critique_prompt()` + `POST /companies/{ticker}/critique` (FR-18, FR-19, FR-20)
- **Verify:** trigger on-demand analysis on a few tickers, confirm `context_snapshot` matches the wiki page shown; trigger critique on one of them and confirm it lands below scheduled/on-demand analyses in budget priority under simulated quota pressure.
- **Verified:** live, real Gemini calls (not mocked) against NVDA — `POST /companies/NVDA/analyze`
  returned an honest low-confidence `hold` (0.25) with null price targets and reasoning explicitly
  citing the missing financials/news, exactly matching Phase 0's validated thin-data behavior.
  `context_snapshot` in the DB confirmed to match the wiki page's `last_close` exactly. Critique
  on that same analysis came back genuinely adversarial (agreed with the `hold` direction but
  flagged the missing stop-loss as the weakest point, proposing one anchored to the real 20-day
  low) — not a rubber-stamp. Watchlist-only restriction confirmed live (AAPL, lookup-tier →
  `400`). Budget-priority ordering (scheduled > on-demand > critique) verified via mocked
  integration tests simulating quota pressure, not live (didn't want to actually burn real daily
  quota to prove it) — see `tests/phase-4.md`.
- **Open decision resolved:** `/critique` restricted to **watchlist tickers only** (extra quota
  protection beyond budget-priority ordering, since critique is a nice-to-have refinement) —
  user decision, made before this phase started.
- **Scope decision beyond the literal task list:** the verdict prompt (Phase 0) was validated
  against rich fixtures (real fundamentals, news, computed technicals) that the pipeline didn't
  actually collect through Phase 3 (no `fundamentals`/`news_articles` tables existed). Closed
  the gap for news and technicals, not fundamentals: added `news_articles` (real Finnhub/Alpha
  Vantage news, best-effort, never blocks the primary refresh) and `services/technicals_service.py`
  (swing levels + price-change %, computed from `price_bars` history already being collected --
  no new provider calls needed). Fundamentals (P/E, revenue growth, margins) are still not
  ingested -- Gemini handles the resulting empty `financials_summary_last_4_periods` array
  honestly (already proven by Phase 0's own thin fixture, and reconfirmed by the live NVDA
  verification above). User decision, made before this phase started.
- **Bugs found and fixed while building this phase:**
  - `ingest_service.upsert_profile_and_quote` truncated `price_bars.ts` to the **hour**, not
    the day, so a `"1d"`-interval bar fragmented into one row per hour instead of one per
    trading day -- would have silently broken every swing-level/price-history computation this
    phase needed. Fixed to truncate to midnight UTC before writing any Phase 4 code.
  - Added `ProviderName.gemini` to the Python enum but forgot the matching Postgres migration
    -- `ALTER TYPE providername ADD VALUE 'gemini'` was missing, so the very first rate-limiter
    check against Gemini failed with `invalid input value for enum providername`. Caught
    immediately by the test suite; fixed with migration `0006`.
  - Same test-isolation class of bug as Phase 3's `provider_call_log` incident, this time on
    `ai_analyses`: the live NVDA verification (above) committed real rows to the shared dev DB,
    which then broke two tests asserting a *global* `AiAnalysis` table count. Unlike Phase 3's
    fix (clearing `provider_call_log` in the test fixture, since rate limiting is inherently
    provider-wide), this was a bug in the tests themselves -- they should have scoped the count
    to the company they seeded from the start. Fixed by scoping both assertions to their own
    `company_id`(s) rather than broadening the fixture to blindly clear a business-data table.

### Post-Phase-4 Addition — Verdict Track Record ✅ DONE
Not part of the original phase numbering — added in response to a direct question about
whether the verdicts should actually be trusted. The honest answer at the end of Phase 4 was
"the engineering is sound, the judgment quality is unproven" (see §12 discussion below); this
closes part of that gap by making calibration checkable instead of assumed.

- [x] `verdict_outcomes` table + migration `0007` — append-only, one row per analysis at a
  single fixed 30-day horizon (`settings.verdict_outcome_horizon_days`)
- [x] `services/outcome_service.py::evaluate_pending_outcomes(db)` — reuses the exact
  `last_close` already stamped into `ai_analyses.context_snapshot` at verdict time (no
  re-query needed, and guarantees the comparison is against precisely what the AI saw), looks
  up the nearest `price_bars` row at/after the horizon, computes `price_change_pct` and
  `directionally_correct` (`buy`>0%, `sell`<0%, `hold` within ±`verdict_outcome_hold_band_pct`
  = 5%). Skips (never fails) analyses with no horizon price data yet — retried next cycle.
- [x] Wired the same dual-trigger pattern as everything else (NFR-1): APScheduler daily job +
  `POST /internal/evaluate-outcomes`, identical underlying function.
- [x] `GET /verdicts/track-record` — count/avg-return/%-directionally-correct grouped by
  verdict type, plus a confidence-bucket breakdown (`>=0.6` vs `<0.6`) — this second breakdown
  is the actual calibration check: whether verdicts the AI was more confident about really did
  better than the ones it wasn't, not just whether it sounded sure.
- **Verify:** unit tests for the correctness logic, integration tests for the evaluation batch
  (skip-too-recent, skip-missing-data, no-duplicate-evaluation), HTTP-level tests for both
  routes.
- **Verified:** 132/132 tests pass (17 new). Full detail, including a real scheduler bug found
  and fixed while testing this (`BackgroundScheduler` can't be restarted after `shutdown()` —
  latent since Phase 3, never surfaced until a second job needed adding), in
  [`tests/outcome-tracking.md`](tests/outcome-tracking.md).
- **Honest limitation:** this data won't be meaningful for weeks — it needs real elapsed time
  and real accumulated `price_bars` history before there's a large enough sample to say
  anything about calibration. Built now because it's small and self-contained, not because
  it's urgent.

### Post-Phase-4 Addition — Historical Price Backfill ✅ DONE
Not part of the original phase numbering — user-proposed after getting a real Alpha Vantage
key, to fix the *other* half of the "verdicts are thin" problem: swing-level/moving-average
technicals were `null` until real time accumulated one bar per day. A one-time historical
backfill on watchlist promote closes most of that gap immediately.

- [x] **Verified live before building** (per the project's established derisking habit):
  `TIME_SERIES_DAILY` with `outputsize=full` (full multi-year history) is **premium-gated on
  the free tier** — confirmed via a real call returning a clean upsell message, not data. Only
  `outputsize=compact` (~100 most recent trading days) is free. This changed the plan: covers
  20d/60d swing levels, 1d/1m/3m price change, and the 50-day moving average immediately; the
  200-day moving average still needs real elapsed time (~8-9 months), same as before, just
  starting from a much stronger base.
- [x] `AlphaVantageClient.get_daily_history(ticker)` — not part of the `DataProvider` ABC
  (Finnhub has no free-tier historical-candles endpoint, so this has no fallback partner and
  is only ever called directly on the Alpha Vantage client).
- [x] `ingest_service.bulk_upsert_bars()` — one multi-row `ON CONFLICT` statement for the
  whole batch, each conflicting row updating via `EXCLUDED` rather than a shared literal.
- [x] `provider_orchestrator.backfill_price_history()` — same rate-limiter/circuit-breaker
  checks as every other Alpha Vantage call (no bypass for this one case), best-effort like
  `fetch_news_best_effort` (never raises; backfill is enrichment, not a hard requirement for
  promote to succeed).
- [x] Wired into `watchlist_service.promote()` only, **not** `lookup_service.get_or_fetch()` —
  deliberate scope decision: Alpha Vantage's daily budget is small and reserved as an
  emergency fallback (plan.md), never a load-shared partner; backfilling on every casual
  lookup would risk draining that budget on low-stakes browsing instead of the deliberate,
  low-frequency act of promoting a ticker.
- [x] Idempotent: skipped if the company already has ≥`backfill_min_bars_threshold` (50) bars,
  so re-promoting a previously-tracked ticker doesn't spend budget for nothing.
- **Verify:** unit tests for parsing/normalization, integration tests for the bulk upsert,
  the orchestration function (rate-limited, circuit-broken, never raises), and `promote()`
  wiring (backfills new tickers, skips already-sufficient ones); live verification with a
  real ticker.
- **Verified live:** promoted AMD (previously untracked) with a real Alpha Vantage key —
  `backfilled: true`, 101 real historical bars landed (2026-03-10 to 2026-08-03, matching
  compact's ~100-day window exactly), and `price_summary`/`recent_swing_levels` came back with
  real numbers (`change_1m_pct: -8.15`, `vs_50d_ma_pct: -7.24`, real 20d/60d ranges) instead of
  the all-`null` result the NVDA verification showed back in Phase 4 — direct, visible proof
  the feature does what it was built for. Also reconfirmed, on a second real ticker, that
  Finnhub's free tier rejects `/company-news` — the fallback to Alpha Vantage's
  `NEWS_SENTIMENT` kicked in correctly and returned real sentiment-classified articles.
  146/146 tests pass (14 new), stable across repeated runs; no test-isolation regressions
  from this round of live testing (the Phase 3 `provider_call_log`-clearing fixture held up
  under a new real-data write).

### Phase 5 — Frontend core ✅ DONE (functionally verified; visual/interactive check still needed from you)
- [x] T5.1 Vite + React + TypeScript scaffold, Tailwind, React Router, React Query provider
- [x] T5.2 `/login` auth gate (shared bearer credential, stored client-side)
- [x] T5.3 Dashboard route — static sections first, no charts (FR-21)
- [x] T5.4 Company wiki page route — static sections first, AI verdict banner incl. "Get Second Opinion" button (FR-22)
- [x] T5.5 `/search` route
- [x] T5.6 Per-section independent query keys + skeletons (FR-23), `FreshnessIndicator` (FR-24)
- **Verify:** exercise all routes against the running local backend.
- **Verified:** TypeScript compiles clean (`tsc -b --noEmit`), `oxlint` passes (0 errors, 2
  harmless fast-refresh style warnings), both dev servers run, and every API path the
  frontend calls was confirmed reaching the real backend with real data through Vite's dev
  proxy (`/api/watchlist`, `/api/companies/AAPL/wiki`, `/api/companies/search?q=`,
  `/api/companies/AAPL/analyses`).
- **Not verified — genuinely could not be, be honest about this:** actual rendered
  appearance, client-side routing/auth-redirect behavior, interactive elements (buttons,
  forms), responsive layout. This session has no interactive Chrome attached
  (`claude-in-chrome` unavailable in this background job), so HTTP-level/proxy checks are the
  ceiling of what could be confirmed here — they prove the data plumbing works, not that the
  UI renders or behaves correctly. **Open `http://localhost:5173` yourself before trusting
  this beyond "the code compiles and the API calls resolve."**
- **Backend prerequisites discovered missing while starting this phase** (built first, see
  §7's now-current API contract): `GET /watchlist` (dashboard needed a way to list tracked
  tickers — didn't exist), `GET /companies/search` (speced in this file's API contract table
  since the beginning but never implemented in any prior phase), `GET
  /companies/{ticker}/analyses` (the verdict banner and "AI Analysis History" section both
  need the analysis history, and no endpoint returned it — `POST /analyze` only ever returned
  the single new verdict it had just created).
- **Scope note on FR-23:** "each section fetches independently" is interpreted at the
  granularity the backend actually offers — wiki data (overview/key_metrics/financials/risks)
  is assembled server-side in one call and is one query key; AI analysis history is a
  separate endpoint and a separate query key. A slow AI-history fetch never blocks the wiki
  sections from rendering, and vice versa, which is the actual intent of FR-23 — there's no
  per-wiki-section backend endpoint to fetch even more granularly than that.
- **FR-21 routes not delivered by this phase:** `/compare` (deliberate — it's Phase 6 T6.3, since
  it needs the chart components) and `/settings` (**not deliberate — it was simply never in any
  phase's task list**, despite FR-21 requiring it since the first draft and Phase 7's install
  prompt assuming it). Now scheduled as the first task of Addition #3's budget dashboard, which is
  the next feature that needs somewhere to render. Phase 5 stays ✅ for what T5.1–T5.6 actually
  listed; this is a spec-level gap being recorded, not retroactively failing the phase.
- **Known environment friction:** Vite's dependency pre-bundling step logged one `EACCES`
  permission error on a rename inside `node_modules/.vite/deps` on first run, then recovered
  and served correctly — almost certainly OneDrive's file-sync locking interfering with a
  Windows/WSL-crossing path, the same category of issue as Phase 1's Docker/Podman
  networking note. Not blocking, but worth knowing about if the dev server ever seems stuck
  on first start.

### Post-Phase-5 Addition — Categories, Holdings, Live Chart, Chat ✅ DONE
Four features the user asked for before the planned visual design pass, sized (by the
assistant's own assessment) as comparable to Phases 3+4 combined. Built in the user's
explicitly chosen order — cheapest/lowest-risk first, each unlocking context the next one
could use:

- [x] **Categories** — sector-to-category taxonomy (`app/services/sector_taxonomy.py`,
  keyword-matched, falls back to `"Other"`), wired additively into `wiki_service.assemble()`
  and `watchlist_service.list_watchlist()` as a `category` field (the granular `sector` field
  is untouched). Frontend: category filter chips on the dashboard, a category badge on the
  wiki page infobox.
- [x] **Holdings** — personal position tracking, explicitly scoped to shares + cost basis per
  share only (user decision: not tax lots, not realized-gains accounting, not cross-brokerage
  import). New `Holding` model/migration `0008`, `holdings_service` (upsert auto-promotes to
  watchlist once, not per edit), `GET/POST/DELETE /holdings`. AI position-awareness: a new
  `verdict_prompt_v2.md` adds a "Your Position" section (honest "no position" when none
  exists) and became the default prompt for every verdict, not just held tickers. Frontend:
  `/portfolio` route, "Your Position" panel on the wiki page.
- [x] **Live Chart** — confirmed live before writing code that Finnhub's free tier does *not*
  grant `/stock/candle` access, so "near-live" means aggregating repeated `/quote` polls into a
  new `"5m"` `price_bars` interval server-side. New `GET /companies/{ticker}/price-history`
  (historical daily bars) and `POST /companies/{ticker}/live-quote` (one poll, called by the
  frontend every ~20s only while a company page is open — never a background scheduler, to
  respect the free-tier quote budget). Frontend: `lightweight-charts` v5, a `PriceChart`
  component on the wiki page. This covers the candlestick-chart half of what was originally
  scoped as Phase 6/T6.1 below — the SMA/EMA/Bollinger/RSI/MACD overlays and benchmark-compare
  toggle remain unbuilt.
- [x] **Chat** — grounded AI chat (user decision: "grounded to tracked stocks only," never
  Gemini's general knowledge, never a live market-wide scan). New `chat_messages` table
  (migration `0009`, linear single-user history), `chat_prompt_v1.md`, `chat_service` grounds
  every reply in every currently-tracked company's `wiki_service.assemble()` data, its own
  lowest-priority `gemini_chat_budget_fraction` (0.2) so chat can never starve
  scheduled/on-demand/critique. Frontend: `/chat` route.
- **Verified:** 210/210 pytest (+49 from Phase 5's 161), stable across repeated full-suite
  runs. Live-verified against the real running backend: the live-quote poll produced a real
  `5m` bar from NVDA's real quote; the chat correctly answered a question about NVDA (a real
  tracked ticker) using its real live price/technicals/position data, and correctly *refused*
  to discuss Tesla (a real company, not tracked), naming real tracked alternatives instead —
  confirming the grounding guarantee actually holds, not just that it compiles.
- **Found and fixed two more instances of this project's recurring test-isolation bug class**
  (real committed data leaking into tests expecting an empty/isolated state) — full detail in
  [`documentations/tests/post-phase-5-additions.md`](tests/post-phase-5-additions.md#incident-the-same-test-isolation-bug-pattern-twice-more-different-shapes).
- **Not verified — same honest limitation as Phase 5:** no interactive browser was available
  this session, so the new frontend pieces (category chips, portfolio page, price chart, chat
  page) are verified via clean `tsc -b && vite build` and real `curl` checks against the
  running backend, not actual rendering/interactivity.

### Post-Phase-5 Addition #2 — Portfolio Income Projections, Multi-Horizon Forecasts (Second LLM), Ticker Autocomplete
Three features requested directly by the user before starting Phase 6 (charts). Sized and
sequenced by the same habit as every prior multi-feature addition in this project: cheapest and
lowest-risk first, each step not depending on the next.

- [ ] **Ticker directory / autocomplete** (build first — no AI, no quota risk)
  - [ ] **Derisk the bulk symbol endpoint live, before writing ingestion code.** This project's
    established habit, applied here because it was initially missed: Finnhub's free tier has
    already rejected two endpoints this plan assumed it had (`/stock/candle` in Addition #1,
    `/company-news` in Phase 4) and Alpha Vantage gated a third (`outputsize=full`,
    post-Phase-4). One `curl` against `/stock/symbol?exchange=US` with the real key confirms
    whether it returns a symbol array or an upsell message. **Fallback if gated:** Alpha
    Vantage's `LISTING_STATUS` (CSV of all active US symbols) — a once-weekly bulk pull is well
    within even AV's small daily budget, unlike anything on the refresh cadence.
  - [ ] `ticker_directory` table + migration; `CREATE EXTENSION IF NOT EXISTS pg_trgm` in the
    same migration if trigram search is used (Neon supports it, but it is not enabled by default)
  - [ ] `services/ticker_directory_service.py::refresh_directory()` — bulk upsert from whichever
    endpoint the derisk step confirmed
  - [ ] `GET /tickers/search?q=&limit=` — ILIKE/trigram search against the local table only,
    zero live provider calls (FR-34)
  - [ ] `POST /internal/refresh-ticker-directory` + weekly APScheduler job, same dual-trigger
    pattern as every other job (NFR-1)
  - [ ] Frontend: type-ahead combobox on the "Add Holding" form; manual-entry fallback
    preserved for symbols not yet in the directory (FR-35)
  - **Verify:** directory populates from a real bulk pull; typing a partial name/ticker
    in Add Holding returns matches with zero new provider rows in `provider_call_log`; an
    obscure/newly-listed ticker absent from the directory can still be typed manually and
    resolves via the existing lookup/promote path.

- [ ] **Portfolio income projection** (build second — pure computation, no new provider)
  - [ ] `services/portfolio_projection_service.py::compute_projected_income(holdings,
    horizon_days)` — eligibility + expected-profit math (FR-27, FR-28)
  - [ ] `GET /portfolio/projected-income?horizon=&tickers=` (FR-29)
  - [ ] Frontend: `/portfolio` gets a 30/60/90-day projection panel — toggle between all
    holdings, one stock, or a multi-select subset; ineligible projections rendered with their
    reason string (never hidden or zeroed), matching the existing honest-null convention used
    for price targets elsewhere
  - **Verify:** unit tests for the eligibility/bucketing logic (hold-period-vs-horizon, missing
    target, missing analysis, each producing the correct reason string); integration test
    against seeded holdings + analyses; live check against real holdings, hand-computing
    expected values to compare.

- [ ] **Multi-horizon forecast — second LLM (Groq)** (build third — new provider, new prompt,
  highest complexity)
  - [ ] Derisk standalone first, same habit as Phase 0: a small script calling Groq against a
    real wiki fixture, confirming it returns real, sensibly-varying high/low numbers per
    horizon (not a refusal/hedge) before any backend code is built assuming it works
  - [ ] **`ProviderName.groq` + `ALTER TYPE providername ADD VALUE 'groq'` migration — do this
    before the client.** Called out as its own task because Phase 4 hit precisely this bug with
    `gemini`: the Python enum member was added, the Postgres `ALTER TYPE` was forgotten, and the
    very first rate-limiter check died on `invalid input value for enum providername` (fixed by
    migration `0006` — see Phase 4's bug list). The rate limiter, circuit breaker, and
    `provider_call_log` writer all key off this enum, so *no* Groq call can succeed until both
    halves exist. Copy `0006`'s pattern verbatim: `ALTER TYPE providername ADD VALUE IF NOT
    EXISTS 'groq'` on upgrade, documented no-op on downgrade (Postgres has no `DROP VALUE`).
  - [ ] `providers/groq_client.py` — own retry/backoff + rate-limit bucket + circuit breaker,
    entirely independent of Gemini's budget (FR-33)
  - [ ] `prompts/forecast_prompt_v1.md` — schema-forced JSON, all five horizons in one call to
    conserve quota, per-horizon `confidence` (FR-30)
  - [ ] `price_forecasts` table + migration (FR-31)
  - [ ] `services/forecast_service.py::build_forecast_prompt()` / `generate_forecast()`
  - [ ] `POST /companies/{ticker}/forecast` — watchlist-only, on-demand-only, mirroring
    `/critique`'s gating exactly (FR-30, FR-32)
  - [ ] `GET /companies/{ticker}/forecasts`
  - [ ] Frontend: forecast panel on the wiki page (per-horizon low/high — consult the
    `dataviz` skill for how to render a range-band across 5 horizons before finalizing),
    "Generate Forecast" button gated the same way "Get Second Opinion" is for lookup-tier
    tickers
  - **Verify:** live Groq call against a real watchlist ticker — confirm `price_forecasts` rows
    land for all 5 horizons and the low/high band widens sensibly with horizon length; confirm
    a lookup-tier ticker is rejected (400) exactly like `/critique`; confirm Groq quota
    exhaustion returns the same style of clear "try later" message as Gemini's, never a silent
    failure or generic 500.
  - **Deferred, not required for this addition:** blending Groq's horizon-matched high/low into
    the income projection above (instead of relying solely on Gemini's single price target) —
    ship the two independently first; revisit once both have real usage.

- **Verify (whole addition):** each sub-feature's own verify step above passes; full test suite
  still green; all three UI additions visually/interactively confirmed in a real browser
  (carrying forward the same "open it yourself" caveat Phase 5 and its post-phase addition
  both flagged as outstanding).

### Post-Phase-5 Addition #3 — Observability, Data Retention, Alerts, Backtest vs. Benchmark, Fundamentals
Six sub-features requested directly by the user after reviewing the app's own flagged gaps
(§12 risks, the unimplemented `fundamentals` table, the never-built `price_bars` retention
policy). Sequenced cheapest/lowest-risk-first, same habit as every prior addition:

- [ ] **Budget dashboard** (build first — trivial, reuses existing `rate_limiter` computation)
  - [ ] **Build the `/settings` route** — FR-21 has listed it since the beginning but no phase
    ever scheduled it, and `frontend/src/App.tsx` currently registers only `/login`, `/`,
    `/search`, `/portfolio`, `/chat`, `/company/:ticker`. It is the container this feature's
    usage bars, Phase 7's install prompt (T7.2), and the shared-credential UI all assume exists,
    so it gets built here rather than being assumed a fourth time. `SettingsPage.tsx` + nav entry
    in `Layout.tsx`.
  - [ ] `GET /status/budget` (FR-36)
  - [ ] Frontend: per-provider usage bars on `/settings`
  - **Verify:** matches hand-counted `provider_call_log` rows for the current day, per provider;
    `/settings` reachable from the nav on both desktop rail and mobile tab bar.

- [ ] **Verdict-change diff** (build second — trivial, pure computation over existing `ai_analyses`)
  - [ ] **Shared** diff function comparing the latest `ai_analyses` row to the immediately
    preceding one for the same company (FR-37) — built here as the single implementation that the
    alerts step below also calls for its `verdict_change` trigger (FR-41), rather than each
    feature growing its own copy of "did the verdict change". Return the full diff (verdict flip,
    confidence delta, target deltas, hold-period change); the alert path just reads the
    verdict-flip field off it.
  - [ ] Extend `GET /companies/{ticker}/analyses` response with the diff on the latest entry
  - [ ] Frontend: "changed since last analysis" callout on the verdict banner
  - **Verify:** unit tests covering verdict-flip, confidence-delta, price-target-delta, and
    first-ever-analysis (no prior to diff against, diff is null) cases.

- [ ] **`price_bars` retention/pruning** (build third — small, no new provider)
  - [ ] `services/retention_service.py::prune_price_bars()` — deletes `"5m"` rows older than
    `price_bars_retention_days`, never touches `"1d"` rows (FR-38)
  - [ ] `POST /internal/prune-price-bars` + weekly APScheduler job (NFR-1 pattern)
  - **Verify:** integration test seeding old + recent `"5m"` and `"1d"` rows, confirming only
    old `"5m"` rows are deleted.

- [ ] **Alerts — in-app feed** (build fourth — small-medium, no new provider)
  - [ ] `alerts` table + migration
  - [ ] `services/alert_service.py::evaluate_alerts()` — called right after each scheduled
    refresh/analysis cycle completes (FR-41), with dedup against existing open alerts (FR-42)
  - [ ] Price-crossing checks read the latest `"1d"` bar's **`high`/`low`, not `close`** (FR-41):
    scheduled refresh writes one midnight-UTC-truncated daily bar, and `"5m"` bars only exist
    while a company page happens to be open in a browser, so a `close`-only check silently misses
    any stop-loss or sell target that was crossed and then retraced the same session. Reuse the
    verdict-change half from the shared diff function above, not a second implementation.
  - [ ] Skip `is_benchmark` watchlist rows (FR-41a) — nothing to alert on
  - [ ] `GET /alerts`, `POST /alerts/{id}/acknowledge` (FR-43)
  - [ ] Frontend: bell icon + unacknowledged count in nav, alerts feed
  - **Verify:** integration tests for each trigger condition (verdict flip, sell-target
    crossed, stop-loss crossed) and for the no-duplicate-open-alert rule; **explicitly test the
    intraday-retrace case** — a daily bar whose `low` breached the stop-loss but whose `close`
    recovered above it must still fire; live check triggering a real condition against a real
    watchlist ticker.
  - **Deferred to its own step below:** Web Push delivery — ship the in-app feed alone first.

- [ ] **Backtest vs. benchmark** (build fifth — medium, extends existing `verdict_outcomes`)
  - [ ] `watchlist.is_benchmark` column + migration, and the **five exclusions** it implies
    (FR-45) — this is the substance of the task, not a footnote to it. Today "on the watchlist"
    means: an `initial` Gemini analysis on promote (`watchlist_service.promote()`), recurring
    scheduled analysis (`ai_service.analyze_scheduled()`), a dashboard card
    (`watchlist_service.list_watchlist()`), inclusion in chat grounding (`chat_service` grounds on
    *every* tracked company), and alert evaluation. A benchmark must inherit none of those — only
    price refresh and one-time backfill. Left unhandled, SPY would spend real Gemini quota daily
    and dilute every chat reply with an index the user doesn't hold.
  - [ ] Designate default benchmark ticker(s) (`SPY`) via config, tracked regardless of holdings
  - [ ] `services/backtest_service.py::simulate_follow_all_verdicts(benchmark)` (FR-46)
  - [ ] Report the covered window and exclude verdicts predating the benchmark's own
    `price_bars` history (FR-46a) — the benchmark starts with ~100 trading days from the
    Alpha Vantage compact backfill, so early results cover a short, noisy window
  - [ ] `GET /verdicts/backtest?benchmark=`
  - [ ] Frontend: extend the track-record page with a strategy-vs-benchmark comparison
  - **Verify:** unit tests for the entry/exit simulation logic against seeded verdicts +
    price_bars; integration test comparing against a hand-computed expected return; **a test
    asserting a benchmark ticker gets zero `ai_analyses` rows, never appears in `GET /watchlist`,
    and is absent from chat grounding**; UI clearly labels this as a simplified simulation over a
    stated window (NFR-8, FR-46a), not investment advice.

- [ ] **Fundamentals ingestion** (build last — medium complexity, real Alpha Vantage budget risk)
  - [ ] **Derisk live first**, same habit as the historical-backfill addition: confirm
    `OVERVIEW`/`INCOME_STATEMENT`/`BALANCE_SHEET`/`CASH_FLOW` are actually free-tier accessible
    (not premium-gated like `outputsize=full` turned out to be) before writing ingestion code
  - [ ] `AlphaVantageClient` methods for the above endpoints
  - [ ] Ingestion wired into `watchlist_service.promote()` (one-time) plus a **monthly**
    scheduled refresh — deliberately not the 15-30 min cadence (FR-39, FR-40)
  - [ ] `POST /internal/refresh-fundamentals` + monthly APScheduler job
  - [ ] Upsert into the existing (never-implemented) `fundamentals` table
  - [ ] Confirm `ai_service`'s `financials_summary_last_4_periods` actually populates from real
    data once this lands, instead of the honest empty array it's produced since Phase 4
  - **Verify:** live check against a real ticker confirming real fundamentals land in the
    table and flow into a subsequent verdict's `context_snapshot`; confirm Alpha Vantage's
    daily budget isn't measurably more strained by adding this (check `provider_call_log`
    volume before/after over a few days).

- [ ] **Web Push extension for alerts** *(stretch, sequenced after Phase 7's service worker exists)*
  - [ ] `push_subscriptions` table + migration
  - [ ] Service worker push event handler (added alongside Phase 7's `vite-plugin-pwa` setup)
  - [ ] `push_service.py` sends a Web Push (VAPID) notification on new alert creation (FR-44)
  - [ ] `POST /push/subscribe`, `DELETE /push/subscribe`
  - **Verify:** real push notification received on a real device; confirm the in-app feed
    still works identically with push permission denied (NFR-7 — push is never the only channel).

- **Verify (whole addition):** each sub-feature's own verify step passes; full test suite still
  green; new `/settings` route, budget dashboard, alerts feed, and backtest page visually
  confirmed in a real browser.

### Phase 6 — Charts
- [ ] T6.1 `lightweight-charts` price panel: ~~candlestick~~ (done, see Post-Phase-5 Addition
  above) + volume, SMA/EMA/Bollinger overlays, RSI/MACD sub-panes, benchmark-compare toggle,
  verdict markers
- [ ] T6.2 Recharts: quarterly revenue/earnings bars, EPS/P-E trend, news-sentiment-over-time, allocation donut, peer comparison bars
- [ ] T6.3 `/compare` route (2-5 tickers)
- [ ] T6.4 Consult `dataviz` skill for palette/series-color assignment before finalizing
- **Verify:** visual check against real data for several tickers.

### Phase 7 — PWA + mobile polish
- [ ] T7.1 `vite-plugin-pwa` manifest + Workbox service worker (shell SWR, API NetworkFirst+offline fallback, static CacheFirst, mutations excluded) (FR-25)
- [ ] T7.2 Custom install prompt (`beforeinstallprompt`) + iOS "Add to Home Screen" card
- [ ] T7.3 Mobile responsive layout (NFR-3)
- **Verify:** install on an actual phone browser, test offline behavior.

### Phase 8 — Deploy
- [ ] T8.1 Neon Postgres provisioning
- [ ] T8.2 Render backend deploy + secrets (API keys, shared auth credential)
- [ ] T8.3 GitHub Actions cron workflows (`/internal/refresh` every 15-30 min, `/internal/analyze-scheduled` daily)
- [ ] T8.4 Static host frontend deploy (Vercel/Netlify)
- **Verify:** kill your laptop, wait through a couple of cron cycles, confirm `GET /status` shows recent successful `job_runs`, then open the PWA from a phone on cellular data.

---

## 10. Verification & Testing Plan

- **Unit tests** (`pytest`): provider response parsers against recorded fixtures (no live
  network), prompt-assembly/verdict-parsing with mocked Gemini responses, rate-limiter/circuit-
  breaker state machines.
- **Integration tests**: real Postgres (local Docker / CI) — upsert idempotency (refresh run
  twice → no duplicate rows), `wiki_service.assemble()` against seeded fixtures, watchlist
  promote/demote transitions.
- **CI**: both suites run on every push; nothing depends on live third-party APIs being
  reachable.
- **Local end-to-end**: `docker compose up` + frontend dev server — search a ticker → wiki page
  renders → add to watchlist → on-demand analysis → verdict banner + history appear and match
  `context_snapshot`.
- **Reliability drill**: see Phase 3 verify step.
- **Post-deploy check**: see Phase 8 verify step.

---

## 11. Open Decisions

| # | Question | Status |
|---|---|---|
| 1 | Should `POST /companies/{ticker}/critique` be available for lookup-tier (non-watchlisted) tickers, or restricted to watchlist tickers only, as an extra layer of quota protection beyond the existing budget-priority ordering? | **Resolved** — watchlist-only, enforced in `api/routers/analysis.py::critique()` and verified both by mocked tests and live against a real lookup-tier ticker (AAPL → 400). |
| 2 | Gemini model id drifts as Google deprecates versions (`gemini-2.0-flash` and `gemini-2.5-flash` both already dead ends as of 2026-08-02). Current default is the `gemini-flash-latest` alias. | **Addressed, not fully closed** — `settings.gemini_model` is now a config knob (default still the `gemini-flash-latest` alias) rather than hardcoded, and the exact model used per call is stamped into `ai_analyses.context_snapshot` for reproducibility (NFR-5). Still worth pinning to an explicit version before Phase 8 deploy if alias drift becomes a real problem. |

## 12. Key Risks (carried from `plan.md`, condensed)

- Gemini may refuse/hedge instead of giving a verdict — mitigated by framing, derisked in Phase 0.
- Render free-tier cold start (10-30s) — accepted (NFR-6).
- Alpha Vantage free daily cap is small — fallback-only, never load-shared.
- Gemini free-tier limits mean heavy on-demand + critique usage in one day could hit "try again
  later" — budget-priority ordering (FR-17, FR-20) mitigates.
- Neon/Supabase free storage caps unlikely to bind soon, but a `price_bars` retention/pruning
  policy is still cheap insurance worth building — not done in Phase 3 (wasn't in its task
  list); revisit before Phase 8 deploy if it hasn't been picked up by then.
- **The AI's actual investment judgment is unproven, separate from the engineering around it
  being sound.** Raised directly after Phase 4's live verification: today's verdicts reason
  over a real price snapshot plus little else (no fundamentals ingested at all; news is often
  unavailable depending on provider free-tier access; computed technicals need weeks of real
  `price_bars` history to mean anything and today have almost none) — a single non-deterministic
  LLM call with no backtesting or track record. The low confidence scores the model returns on
  thin data are honest, not a flaw, but that doesn't make the underlying judgment reliable yet.
  Partially addressed by the verdict-outcomes tracking below (calibration becomes checkable
  instead of assumed); not addressed by it: still no fundamentals, still one AI call, still no
  validated edge. Treat current verdicts as a research starting point, not a trusted answer,
  until real track-record data accumulates over weeks/months.
- **Groq's free-tier model lineup drifts/deprecates over time** — the same class of risk
  already seen with Gemini model aliasing (§11 #2). Mitigated the same way: a config knob, not
  a hardcoded model id, and the exact model stamped into each `price_forecasts` row (NFR-5
  pattern).
- **The multi-horizon forecast is a second independently-reasoned opinion, not a validated
  forecasting model** — same caveat as the verdict risk above, arguably sharper at the 180/360-
  day horizons where there's no realistic way to backtest yet. Treat it as a research input
  alongside the verdict, not a trusted number, until real elapsed time lets it be checked
  against actual prices (the same mechanism `verdict_outcomes` already applies to verdicts
  could extend to forecasts later, but doesn't yet).
- **Fundamentals ingestion competes for Alpha Vantage's already-small daily budget** (also
  relied on for price fallback, news fallback, and historical backfill) — mitigated by making
  it deliberately low-frequency (promote-time + monthly, never the main refresh cadence, FR-40),
  but worth watching if AV's free cap ever tightens further.
- **The backtest vs. benchmark is a simplified historical simulation, not a validated trading
  strategy** (NFR-8) — no fees/slippage, single historical path, no claim about future
  performance. Same "research input, not a trusted number" framing as the verdict/forecast
  risks above, applied to an aggregate instead of a single call.
- **Web Push alert delivery is best-effort** — browser/OS support (notably iOS Safari) varies
  and isn't guaranteed (NFR-7); the in-app alerts feed is the reliable channel regardless of
  whether push succeeds.
- **Price-target alerts are day-resolution, not intraday.** The only price data a scheduled cycle
  can rely on is one `"1d"` bar per company per day (`"5m"` bars exist only while a page is open
  in a browser — Addition #1's live-quote poll is frontend-driven by design, to respect the free
  quote budget). Testing crossings against that bar's `high`/`low` rather than `close` (FR-41)
  recovers same-day breaches that retraced, which is most of the gap for free — but an alert still
  can't fire *while* a target is being crossed, only after the day's bar reflects it. Acceptable
  for a research tool that is explicitly not day-trading (same framing as NFR-6's cold start); a
  hard blocker only if this ever became an execution tool, which it is not (§1 Out of scope).
- **New-provider integrations must touch two enums, not one.** Adding Groq means both
  `ProviderName` in Python and the Postgres `providername` type; Phase 4 shipped the first without
  the second and the first Gemini rate-limiter check failed outright. Recorded as a standing risk
  rather than a one-off bug because it will recur for every future provider — the mitigation is
  the explicit migration task now written into Addition #2's checklist.

---

## Appendix: Repository Map (current state)

```
plan.md                              — narrative design doc (architecture rationale, tradeoffs)
spec.md                              — this file (requirements + task breakdown)
.env / .env.example / .gitignore     — Gemini/Finnhub API key + DB URL handling (never committed)
prompts/
  verdict_prompt_v1.md               — first-pass verdict prompt (Phase 0, done; superseded
                                        by v2 as the live default, kept for reproducibility)
  verdict_prompt_v2.md               — adds a "Your Position" section (post-Phase-5, current default)
  verdict_critique_prompt_v1.md      — adversarial second-opinion prompt (Phase 0, done)
  chat_prompt_v1.md                  — grounded chat reply prompt (post-Phase-5)
scripts/
  test_gemini_prompt.py              — standalone prompt test harness (Phase 0, done)
  fixtures/
    sample_wiki_data.json            — synthetic "normal" test case
    sample_wiki_thin.json            — synthetic thin/contradictory test case
    aapl_live.json                   — real researched data, snapshot 2026-08-02
app/
  main.py, config.py                 — FastAPI app (lifespan starts/stops the scheduler), settings
  db/
    session.py, models.py            — Company, PriceBar, WikiSection (Phase 1-2); Watchlist,
                                        ProviderCallLog, JobRun (Phase 3); NewsArticle, AiAnalysis,
                                        AiCritique (Phase 4); VerdictOutcome (post-Phase-4);
                                        Holding, ChatMessage (post-Phase-5)
    migrations/versions/
      0001_initial.py                — companies, price_bars (Phase 1)
      0002_wiki_sections.py          — wiki_sections (Phase 2)
      0003_watchlist_reliability.py  — watchlist, provider_call_log, job_runs (Phase 3)
      0004_news_articles.py          — news_articles (Phase 4)
      0005_ai_analyses_and_critiques.py — ai_analyses, ai_critiques (Phase 4)
      0006_add_gemini_provider.py    — adds 'gemini' to the providername enum (Phase 4)
      0007_verdict_outcomes.py       — verdict_outcomes (post-Phase-4)
      0008_holdings.py               — holdings (post-Phase-5)
      0009_chat_messages.py          — chat_messages (post-Phase-5)
  api/routers/
    health.py                        — GET /health (Phase 1)
    wiki.py                          — GET /companies/{ticker}/wiki, delegates to lookup_service (Phase 2)
    search.py                        — GET /companies/search?q=, proxies Finnhub's /search (Phase 5)
    watchlist.py                     — POST /watchlist/{ticker}/promote, DELETE /watchlist/{ticker} (Phase 3)
    refresh.py                       — POST /internal/refresh (Phase 3)
    analysis.py                      — POST /companies/{ticker}/analyze, /internal/analyze-scheduled,
                                        /companies/{ticker}/critique (watchlist-only) (Phase 4)
    outcomes.py                      — POST /internal/evaluate-outcomes, GET /verdicts/track-record
                                        (post-Phase-4)
    holdings.py                      — GET/POST/DELETE /holdings (post-Phase-5)
    price_history.py                 — GET /companies/{ticker}/price-history,
                                        POST /companies/{ticker}/live-quote (post-Phase-5)
    chat.py                          — GET /chat/messages, POST /chat (post-Phase-5)
  jobs/
    scheduler.py                     — APScheduler wiring; calls the same refresh_service/
                                        outcome_service functions as their cron-facing routes
                                        (NFR-1) (Phase 3, extended post-Phase-4)
  services/
    wiki_service.py                  — assemble(ticker), now also surfaces recent_news/
                                        price_summary/recent_swing_levels (Phase 2, extended Phase 4),
                                        category (post-Phase-5), holding (post-Phase-5)
    sector_taxonomy.py               — categorize(sector) -> broad category, keyword-matched (post-Phase-5)
    holdings_service.py              — upsert()/list_holdings()/remove()/get_for_company();
                                        lazy-imports lookup_service/watchlist_service inside
                                        upsert() to avoid a circular import with wiki_service (post-Phase-5)
    live_price_service.py            — poll_and_record(): one /quote poll -> a "5m" price_bars
                                        row (post-Phase-5)
    chat_service.py                  — send_message()/list_messages(); grounds every reply in
                                        every tracked company's wiki_service.assemble() data (post-Phase-5)
    lookup_service.py                — get_or_fetch(ticker) (Phase 2, T2.2)
    wiki_sections_service.py         — template-based section generation, real news_digest +
                                        technicals in key_metrics (Phase 2, extended Phase 4)
    ingest_service.py                — shared profile+quote+news upsert logic, recent_bars()/
                                        recent_news() readers (Phase 3, extended Phase 4),
                                        bar_count()/bulk_upsert_bars() for backfill (post-Phase-4),
                                        bars_for_interval()/record_live_quote() for the near-live
                                        chart's "5m" bars (post-Phase-5)
    provider_orchestrator.py         — fetch_with_fallback(), fetch_news_best_effort() (Phase 3, T3.3;
                                        news added Phase 4), backfill_price_history() (post-Phase-4),
                                        fetch_quote_best_effort() for the live-quote poll (post-Phase-5)
    rate_limiter.py                 — per-provider sliding window over provider_call_log, with a
                                        budget_fraction param for priority tiers (Phase 3, T3.4;
                                        extended Phase 4 for Gemini budget priority)
    circuit_breaker.py               — per-provider circuit state over provider_call_log (Phase 3, T3.5)
    refresh_service.py               — refresh_watchlist()/refresh_entry() (Phase 3, T3.2)
    watchlist_service.py             — promote()/remove(), one-time historical backfill on
                                        promote (Phase 3, T3.1; backfill added post-Phase-4)
    technicals_service.py            — compute_swing_levels()/compute_price_summary() from
                                        price_bars history, no new provider calls (Phase 4)
    ai_service.py                    — build_prompt()/build_critique_prompt(), generate_verdict(),
                                        analyze_scheduled(), generate_critique(), QuotaExhaustedError
                                        (Phase 4, T4.2-T4.5); build_prompt() now defaults to
                                        verdict_prompt_v2.md with position-awareness (post-Phase-5)
    outcome_service.py                — evaluate_pending_outcomes(): verdict vs actual price at a
                                        fixed horizon, reuses context_snapshot's snapshotted price
                                        (post-Phase-4)
  providers/
    base.py                          — DataProvider interface (get_profile/get_quote/get_news),
                                        Transient/PermanentProviderError
    finnhub_client.py                — primary provider, normalized output, get_news() via
                                        /company-news (Phase 1, updated Phase 3 and Phase 4)
    alpha_vantage_client.py          — fallback provider, normalized output, get_news() via
                                        NEWS_SENTIMENT with real sentiment labels (Phase 3, T3.3;
                                        news added Phase 4), get_daily_history() for one-time
                                        backfill -- outputsize=compact only, full is
                                        premium-gated (post-Phase-4)
    gemini_client.py                 — wraps google-genai, schema-forced JSON, Transient/
                                        PermanentProviderError mapping (Phase 4, T4.1)
tests/
  unit/                              — provider parsers, section-template rendering, technicals
                                        computation, prompt-mapping, Gemini client (respx/mocks,
                                        no live network)
  integration/                       — real Postgres, conftest.py rolls back per test, clears
                                        provider_call_log (protects rate_limiter/circuit_breaker
                                        assertions from manual live testing), also deactivates
                                        pre-existing watchlist rows the same way (post-Phase-5 —
                                        see that addition's test report for why), and provides a
                                        `client` fixture (TestClient wired to the same rolled-back
                                        session) for HTTP-level router tests
frontend/                            — Vite + React + TypeScript + Tailwind v4 (Phase 5)
  vite.config.ts                     — dev proxy: /api/* -> http://127.0.0.1:8000 (avoids
                                        needing CORS for local dev; Phase 8 deploy will need
                                        real CORS config once frontend/backend are separate domains)
  src/
    App.tsx                          — QueryClientProvider + AuthProvider + router wiring
    api/
      client.ts                      — fetch wrapper, attaches the stored bearer credential,
                                        typed ApiError; holdings/price-history/live-quote/chat
                                        calls added post-Phase-5
      types.ts                       — hand-written TS types mirroring backend response shapes
      hooks.ts                       — React Query hooks, one query key per resource (FR-23)
    auth/AuthContext.tsx             — shared credential in localStorage, ProtectedRoute (T5.2)
    components/
      Layout.tsx                     — nav rail (desktop) / bottom tabs (mobile); Portfolio/Chat
                                        nav items added post-Phase-5
      FreshnessIndicator.tsx         — FR-24
      VerdictBadge.tsx, VerdictBanner.tsx, Skeleton.tsx
      PriceChart.tsx                 — lightweight-charts candlestick + live-poll updates (post-Phase-5)
    routes/
      LoginPage.tsx, DashboardPage.tsx, SearchPage.tsx, CompanyPage.tsx
      PortfolioPage.tsx, ChatPage.tsx (post-Phase-5)
```

A `fundamentals` table still does not exist — Phase 4 deliberately did not add one (see that
phase's scope-decision note above); the prompt's `financials_summary_last_4_periods` stays an
honest empty array until a future phase adds real fundamentals ingestion.
