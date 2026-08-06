# Personal Investment Research App — Spec & Task Breakdown

**Status:** Phase 0 through Phase 5 functionally complete, plus "Post-Phase-5 Addition #1"
(categories, holdings, live chart, chat) complete and the token-efficiency pass complete.
**"Post-Phase-5 Addition #2" is ✅ COMPLETE: all three sub-features — ticker directory /
autocomplete, portfolio income projection (both 2026-08-05), and the second-LLM Groq forecast
(2026-08-06, shipped **dormant**) — are built.** The Groq forecast's infrastructure is merged
and switched off behind a missing `GROQ_API_KEY`; its **activation checklist is outstanding**
(see "Groq activation" in §9) but does not hold this addition open or block Phase 6.
"Post-Phase-5 Addition #3" (observability, data retention, alerts, backtest vs. benchmark,
fundamentals ingestion) and "Post-Phase-5 Addition #4" (chat source citations) specced but not
started. Phase 6 not started · **Suite: 268/268 green with `GROQ_API_KEY` unset, all 12
migrations round-trip** (migration `0010` = `ticker_directory`, `0011` = `groq` enum, `0012` =
`price_forecasts`) · **Last updated:** 2026-08-06
(Phase 5's UI, the Add-Holding combobox, and the new forecast panel's dormant/standby state
have not been visually/interactively verified in a real browser — see the relevant sections
below.)
**Two FR-21 routes are still unbuilt:** `/compare` (scheduled, Phase 6 T6.3) and `/settings`
(never in any task list until Addition #3 — see that section).

> **⚠ Groq is on standby (2026-08-05).** The user cannot currently sign in to Groq to get an API
> key. Addition #2's multi-horizon forecast is therefore re-scoped to **dormant infrastructure**:
> everything buildable without a live key ships (client, migration, prompt, service, routes, UI,
> mocked tests, derisk script), the feature stays switched off while `GROQ_API_KEY` is unset, and
> **a missing Groq key SHALL NOT affect the app's startup, existing endpoints, scheduled jobs, test
> suite, or migrations in any way** (NFR-9, FR-33a). Activation is a separate, clearly-marked
> checklist — see "Groq activation (blocked on API key)" in §9. Addition #2 can be declared
> complete with Groq dormant; Phase 6 is not blocked by it.

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
grounded chat that cites the articles behind each answer, a
full fintech-style chart set, installable mobile-first PWA, free-tier-safe reliability
mechanics (fallback/retry/circuit-breaker/rate-limiting).

**Optional (key-gated) capability:** the Groq-backed multi-horizon forecast (§3.9) is an
*additive* capability, not a dependency. Its infrastructure is in scope now; its live operation
is gated on a `GROQ_API_KEY` that does not exist yet. The app is fully usable — every requirement
outside §3.9 satisfied — with Groq permanently switched off.

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

### 3.9 Multi-horizon forecast (second LLM) *(planned — Post-Phase-5 Addition #2; **dormant, key-gated**)*

> Every requirement in this subsection is **conditional on a configured `GROQ_API_KEY`**. With no
> key — the state as of 2026-08-05 — FR-33a governs instead, and none of FR-30 through FR-33 can
> be exercised. This is the only optional-capability block in the spec; nothing outside it may depend
> on Groq (NFR-9).

- **FR-30**: WHEN a forecast is requested for a watchlist ticker **and a Groq API key is
  configured**, THE SYSTEM SHALL render
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
- **FR-33a** *(standby behavior — the governing requirement while no key exists)*: WHEN
  `settings.groq_api_key` is unset, THE SYSTEM SHALL treat the forecast capability as
  **unavailable, not broken**. Specifically it SHALL:
  - start up, run every scheduled job, and serve every non-forecast endpoint **exactly as it does
    today** — no import-time or startup-time failure, no degraded behavior, no extra `job_runs` or
    `provider_call_log` rows (NFR-9);
  - report the capability as off in `GET /status` via a `features` map (e.g.
    `{"forecast": false}`), so the frontend renders the "Generate Forecast" button **disabled with
    a "Groq API key not configured" tooltip** — visibly on standby, never hidden and never a
    button that fails when pressed;
  - return `503` with that same clear message if `POST /companies/{ticker}/forecast` is called
    anyway — same never-silent-failure posture as FR-16's quota response, different cause, and
    distinct from the `400` a lookup-tier ticker gets (FR-32) so the two causes are never confused;
  - keep `GET /companies/{ticker}/forecasts` working normally, returning an empty list — reading
    history needs no provider;
  - still ship the `groq` enum value and `price_forecasts` migration, which are inert without a key
    (deferring them is exactly how Phase 4's `gemini` enum bug happened — see §12);
  - pass the **entire test suite with no Groq key present**, including one explicit test asserting
    the `503`-and-no-side-effects path.
- **FR-33b** *(activation gate)*: THE SYSTEM SHALL NOT be described or treated as having a working
  forecast feature until the deferred standalone derisk run (§9, "Groq activation") has executed
  against a real key and its output been reviewed. Until then `prompts/forecast_prompt_v1.md` and
  its response parsing are **unvalidated** — written without the live check every other provider
  integration in this project received first (Phase 0's Gemini prompt, `/stock/candle`,
  `outputsize=full`, `/company-news`).

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
  quota exhaustion is visible before a request is rejected, not only after. A provider with no API
  key configured (Groq, as of 2026-08-05) SHALL report an explicit **`not_configured`** state
  rather than a 0-of-N usage bar — "0 used" reads as spare quota when the truth is "cannot be
  called at all", precisely the kind of misleading display NFR-4 forbids.
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

### 3.16 Chat source citations *(planned — Post-Phase-5 Addition #4)*
- **FR-47**: WHEN the chat produces a reply, THE SYSTEM SHALL return, alongside the reply text, the
  list of sources that reply drew on — **primarily the news articles**, each with its headline,
  source, `published_at`, and a working `url` the user can open — so every answer is checkable
  against the same articles visible on the companies' wiki pages. Citations SHALL be typed
  (`news|price|verdict|metric|position`), mirroring `ai_analyses.cited_sources`, because prices,
  computed technicals, verdicts, and the user's own position are also legitimate grounding data;
  only `news` entries carry a URL.
- **FR-48**: Citation URLs and headlines SHALL NOT come from the model. Each article placed in the
  prompt SHALL be stamped with a short reference id (`[N1]`, `[N2]`, …); the model SHALL cite those
  ids; and `chat_service` SHALL resolve each id back to the real `news_articles` row it assigned,
  populating headline/source/url/published_at server-side. An id the model returns that was not in
  the prompt's map SHALL be **dropped** (and logged), never rendered. Rationale: a model-authored
  URL is a plausible-looking fabrication risk, and resolving ids server-side makes a fabricated
  citation structurally impossible rather than merely discouraged.
- **FR-49**: THE SYSTEM SHALL persist each assistant reply's citations in a nullable
  `chat_messages.cited_sources` JSONB column (assistant rows only) and return them from both
  `POST /chat` and `GET /chat/messages`, so reopening `/chat` shows the same citations the reply was
  originally delivered with rather than losing them on reload.
- **FR-50**: An **empty** citation list SHALL be a valid, correctly-rendered outcome — never an
  error and never filled in with a guess. Two legitimate cases: the grounding-refusal reply ("I can
  only discuss companies tracked here") has nothing to cite, and free-tier news coverage is patchy
  (Finnhub withholds `/company-news`; the Alpha Vantage `NEWS_SENTIMENT` fallback doesn't cover
  every ticker), so some tracked companies have zero articles. WHEN a reply is grounded in
  non-article data only, THE SYSTEM SHALL say so explicitly in the UI ("based on price and verdict
  data — no articles available") rather than showing an empty chip row, and the model SHALL NOT
  attribute a price/position fact to an unrelated headline to fill the list.
- **FR-51**: Citations SHALL cost no additional AI call — they are one extra output field on the
  existing single chat call (`chat_prompt_v2.md`), leaving the chat budget slice
  (`gemini_chat_budget_fraction`) unchanged.

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
| NFR-9 | **Optional providers degrade to absent, never to broken.** An unset provider API key SHALL leave every unrelated capability untouched: the app boots, the scheduler runs, migrations round-trip, and the full test suite passes with the key missing. Key-gated features SHALL announce their unavailability through a capability flag (FR-33a's `GET /status` `features` map) and refuse with a clear `503`, never a silent no-op or a generic 500. Keys already follow this shape in `app/config.py` (`str \| None = None` for Finnhub/Alpha Vantage/Gemini); `groq_api_key` is the first one whose *whole feature* is gated this way, and today the only one actually unset. |
| NFR-10 | **Prompt payload discipline — every AI call site sends a purpose-built subset, never a whole page dict.** `wiki_service.assemble()` is shaped for the wiki *page* (logos, article URLs, rendered `wiki_sections` prose) and is the shared single-source-of-truth read path (FR-10), so trimming happens at each *call site*, never in `assemble()` itself. Three rules: (a) **no field may restate another in the same payload** — the rendered `overview`/`key_metrics`/`news_digest` sections duplicate structured fields that are already present, and sending both costs tokens to say the same thing twice; (b) free-text fields (company `description`, article `summary`) are **length-capped**, and any payload that scales with tracked-company count is capped and tunable via config (`settings.chat_*`), never unbounded; (c) prompt JSON uses **compact separators**, not `indent=2` — the model parses both identically. Rationale is budget, not elegance: `rate_limiter.allow()` counts **every** `provider_call_log` row regardless of status, so a call rejected for exceeding a token limit still consumes a slot from the same daily Gemini budget the user's own on-demand analyses draw on. An oversized prompt costs quota *and* returns nothing. |

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
                                                                    ⚠ DORMANT — no API key yet;
                                                                    everything above works without it

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
| `chat_messages` *(post-Phase-5 addition; `cited_sources` planned — Addition #4)* | role (user\|assistant), content, created_at, **cited_sources** (JSONB, nullable) | Append-only, linear, single-user — no multi-conversation concept. `cited_sources` is populated on assistant rows only, same shape as `ai_analyses.cited_sources`, resolved server-side from prompt reference ids (FR-48) so a stored URL is always a real `news_articles` URL |
| `price_bars` interval `"5m"` *(post-Phase-5 addition)* | same columns as the `"1d"` rows above, one bucket per 5 minutes | Aggregated server-side from repeated `/quote` polls (Finnhub's free tier has no intraday candle endpoint) — not a new table, just a new `interval` value in the existing `price_bars` table |
| `price_forecasts` *(built dormant — Post-Phase-5 Addition #2, migration `0012`)* | company_id, horizon_days, expected_low, expected_high, confidence, rationale, model, trigger, generated_at | Append-only, one row per horizon per generation; INDEX `(company_id, generated_at DESC)`. `confidence` is **per-horizon**, sourced from the prompt's per-horizon field (FR-30) — not one value copied across five rows. **Created even with no Groq key** (FR-33a): an empty table is inert, and deferring the migration is how Phase 4's `gemini` enum bug happened. Stays empty until activation |
| `ticker_directory` *(built — Post-Phase-5 Addition #2, migration `0010`)* | symbol, name, exchange, security_type, updated_at | UNIQUE `(symbol)`; bulk-refreshed weekly, backs local autocomplete (FR-34). Source confirmed free-tier: Finnhub `/stock/symbol?exchange=US` (302-redirects to a downloadable JSON of ~31k US symbols) — no Alpha Vantage fallback needed. Plain `ILIKE` search, no `pg_trgm` |
| `alerts` *(planned — Post-Phase-5 Addition #3)* | company_id, alert_type (verdict_change\|sell_target_hit\|stop_loss_hit), message, triggered_at, acknowledged, acknowledged_at | Not append-only — `acknowledged` is a real state transition; "one open alert per `(company_id, alert_type)`" enforced in `alert_service`, not a DB constraint (FR-41–43) |
| `push_subscriptions` *(planned, stretch — Post-Phase-5 Addition #3)* | endpoint, p256dh_key, auth_key, created_at | UNIQUE `(endpoint)`; only needed if the Web Push extension (FR-44) is built |

---

## 7. API Contract

| Method & Path | Purpose | Auth | Notes |
|---|---|---|---|
| `GET /health` | Liveness probe | none | For Render health checks |
| `GET /status` *(response extended — Addition #2)* | Recent `job_runs` + provider health summary + a `features` capability map (FR-33a) | shared credential | Post-deploy verification target. `features.forecast` is `false` whenever no Groq key is configured — this is what lets the frontend disable the "Generate Forecast" button instead of offering an action that cannot work |
| `GET /status/budget` *(planned — Post-Phase-5 Addition #3)* | Current-day usage vs. configured budget per rate-limited provider (FR-36) | shared credential | Reuses `rate_limiter`'s existing sliding-window computation, no new tracking. Key-less providers report `not_configured`, not a 0-of-N bar (FR-36) |
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
| `GET /chat/messages` *(post-Phase-5; response extended — Addition #4)* | Full chat history, each assistant message carrying its `cited_sources` (FR-49) | shared credential | Backs `/chat`; citations are read from the stored column, not recomputed |
| `POST /chat` *(post-Phase-5; response extended — Addition #4)* | Send a chat message, get a grounded AI reply **plus the sources it drew on** (FR-47) | shared credential | Grounded to tracked companies only (user decision); lowest Gemini budget priority; citations add no extra AI call (FR-51) |
| `GET /portfolio/projected-income?tickers=&horizon=` *(built — Post-Phase-5 Addition #2)* | Expected profit at 30/60/90-day horizons, whole portfolio / single stock / selected subset (FR-27–29) | shared credential | Pure computation over existing `holdings` + latest `ai_analyses`; no new AI call. Both params are optional narrowing filters — bare call returns all holdings × all three horizons (FR-29) |
| `POST /companies/{ticker}/forecast` *(built dormant — Post-Phase-5 Addition #2)* | On-demand multi-horizon (30/60/90/180/360d) high/low forecast via Groq (FR-30–32) | shared credential | Watchlist-only, on-demand-only, mirrors `/critique`'s gating; own independent Groq budget. **With no Groq key: `503` "Groq API key not configured"**, checked *before* the watchlist tier check (FR-33a) — deliberately distinct from the `400` a lookup-tier ticker gets and from the `429` quota-exhaustion response, so the three causes are never conflated |
| `GET /companies/{ticker}/forecasts` *(built dormant — Post-Phase-5 Addition #2)* | Latest + historical forecast rows, grouped by generation | shared credential | Backs the wiki-page forecast panel. Works with no Groq key — returns `{ticker, latest: null, history: []}`, since reading history needs no provider (FR-33a) |
| `GET /tickers/search?q=&limit=` *(built — Post-Phase-5 Addition #2)* | Local-only ticker/name autocomplete for the Add Holding form (FR-34–35) | shared credential | No live provider call; distinct from `/companies/search` (which proxies Finnhub live) |
| `POST /internal/refresh-ticker-directory` *(built — Post-Phase-5 Addition #2)* | Cron-triggered weekly bulk refresh of `ticker_directory` from Finnhub `/stock/symbol` | shared credential | Same dual-trigger pattern as every other job (NFR-1) |
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
| `prompts/chat_prompt_v1.md` *(post-Phase-5; superseded by v2 as the live default once Addition #4 lands, kept per NFR-5)* | Grounded chat reply — restricted to tracked companies only | list of every tracked company's wiki dict + chat history + the new user message | `{reply}` |
| `prompts/chat_prompt_v2.md` *(planned — Addition #4)* | Same grounded reply, plus per-answer source attribution | same inputs, with each article stamped with a reference id (`[N1]`, `[N2]`, …) (FR-48) | `{reply, cited_sources: [{type: news\|price\|verdict\|metric\|position, ticker, ref}]}` — for `news`, `ref` is a prompt-assigned article id the backend resolves to headline/source/url/published_at; the model never emits URLs |
| `prompts/forecast_prompt_v1.md` *(built dormant — Post-Phase-5 Addition #2; **written but UNVALIDATED**)* | Multi-horizon (30/60/90/180/360d) expected low/high forecast, second independent model (Groq) | `wiki_service.assemble(ticker)` dict | `{forecasts: [{horizon_days, expected_low, expected_high, confidence, rationale}]}` — confidence is per-horizon (FR-30), not one value for the set. json_object mode enforces valid JSON but not the schema — shape validated in `forecast_service` after parsing. UNVALIDATED against a live model until activation |

**The forecast prompt is the one exception to the sentence above** (FR-33b): with no Groq key
obtainable, it is authored from the same design principles as the validated prompts but has never
been run against a real model. Treat its wording *and* its response parsing as assumptions until
the deferred derisk run happens — expect adjustment on first real contact, the way Phase 0's
verdict prompt needed iteration.

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
  scheduled/on-demand/critique. Frontend: `/chat` route. *(Extended by Addition #4: each reply now
  also reports the articles it drew on — see that section.)*
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

### Verification run — 2026-08-04 (no new features; suite health check)
A full-stack check with nothing under construction, run to confirm the current state is green
before Addition #2 starts. Result: **210/210 pytest, frontend build clean, all 9 migrations
round-trip** — but it took a fixture fix to get there.

- **Backend suite initially 200/210**, with 10 failures across `test_chat_service.py`,
  `test_chat_router.py`, `test_holdings_service.py`, `test_holdings_router.py` — the **fourth
  recurrence of this project's recurring test-isolation bug class** (after `provider_call_log` in
  Phase 3, `ai_analyses` in Phase 4, and two more in Addition #1). Cause: the shared dev database
  now holds genuine user data — 2 real holdings (NVDA 1.18, MSFT 0.2985955 shares) and 9 real
  chat messages, from actually using the app — and those tests assert on totals (`== 0`, `== 1`,
  `== 2`, exact content lists).
- **Diagnosed before fixing, not assumed**: every failing assertion was a global count/list, while
  every behavioral assertion in the same tests (`pytest.raises(NoTrackedCompaniesError)`,
  `QuotaExhaustedError`, `PermanentProviderError`) passed. Re-running all 25 tests in those four
  files against a freshly-created throwaway database: **25/25 pass**. That isolates it definitively
  to test setup, not application code.
- **Fix follows the `Watchlist` precedent, not the `ai_analyses` one** — the distinction matters
  and is why this wasn't just copied from Phase 4. Phase 4's `ai_analyses` failures were the
  *tests'* fault: they asserted a global row count when they could have scoped to their own
  `company_id`, so the assertions were narrowed rather than broadening the fixture. Here,
  `holdings_service.list_holdings()` and `chat_service.list_messages()` are **global reads by
  design** ("all my positions", "the whole conversation") — `test_list_holdings_empty` has no
  company to scope to, and asserting emptiness is the correct test. That is exactly the
  `Watchlist` situation, so the same remedy applies: `tests/integration/conftest.py`'s
  `db_session` fixture now also deletes pre-existing `ChatMessage` and `Holding` rows inside the
  test's transaction, which is rolled back afterward.
- **Verified the rollback actually protects real data** (the whole premise of the fixture): after
  the full 210-test run, the dev DB still held exactly NVDA 1.18, MSFT 0.2985955, 9 chat messages,
  6 companies, 3 active watchlist entries — unchanged.
- **Frontend**: `tsc -b && vite build` clean (92 modules, 460 kB / 144 kB gzipped), `oxlint` 0
  errors and the same 2 known `AuthContext.tsx` fast-refresh warnings as Phase 5. Still no
  interactive browser in this session — the standing "open it yourself" caveat from Phase 5 and
  Addition #1 remains outstanding, unchanged.
- **Migration round-trip, newly covered**: `upgrade head` → `downgrade base` → `upgrade head` on
  a disposable database, all 9 migrations each direction, leaving only `alembic_version` behind at
  base. Phase 3's hardening ran this when only `0001`–`0003` existed, so `0004`–`0009`'s
  `downgrade()` functions had **never actually been executed** until now. They all work,
  including `0006`'s deliberate no-op (Postgres has no `DROP VALUE`, and dropping `0003`'s enum
  type covers it — proven by the clean re-upgrade).
- **Standing lesson, now four for four**: any service function that reads "everything" rather than
  "everything for company X" will eventually collide with real dev data, and the collision surfaces
  as a confusing test failure long after the feature shipped. When adding such a function, decide
  at that moment whether its tests scope their assertions or the fixture neutralizes the table.

### Post-Phase-5 Addition #2 — Portfolio Income Projections, Multi-Horizon Forecasts (Second LLM), Ticker Autocomplete
Three features requested directly by the user before starting Phase 6 (charts). Sized and
sequenced by the same habit as every prior multi-feature addition in this project: cheapest and
lowest-risk first, each step not depending on the next.

- [x] **Ticker directory / autocomplete** (build first — no AI, no quota risk) ✅ DONE (2026-08-05)
  - [x] **Derisk the bulk symbol endpoint live, before writing ingestion code.** This project's
    established habit, applied here because it was initially missed: Finnhub's free tier has
    already rejected two endpoints this plan assumed it had (`/stock/candle` in Addition #1,
    `/company-news` in Phase 4) and Alpha Vantage gated a third (`outputsize=full`,
    post-Phase-4). One `curl` against `/stock/symbol?exchange=US` with the real key confirms
    whether it returns a symbol array or an upsell message. **Fallback if gated:** Alpha
    Vantage's `LISTING_STATUS` (CSV of all active US symbols) — a once-weekly bulk pull is well
    within even AV's small daily budget, unlike anything on the refresh cadence.
    **Result: free-tier accessible, no fallback needed.** `/stock/symbol?exchange=US` responds
    with a `302` redirect to a signed downloadable JSON file (not an upsell) — following it
    (`curl -L` / httpx `follow_redirects`) yields **30,919 US symbols** with `symbol`,
    `description` (name), `mic` (exchange), `type` (security type). The client's `list_symbols()`
    is the one Finnhub call that needs `follow_redirects=True` and a longer timeout.
  - [x] `ticker_directory` table + migration `0010`. **No `pg_trgm`**: plain prefix `ILIKE` is
    exactly the wanted behavior when a single user types a ticker fragment, and 31k rows scan
    trivially — the UNIQUE index on `symbol` already serves prefix matches, so the extension
    would be speculative complexity. Round-trips (`downgrade 0010→0009 → upgrade head`) clean.
    **Note:** Addition #4 (chat citations) had also pencilled in "migration 0010"; whichever
    shipped first took the number — this did, and the Groq forecast (below) then took `0011`
    (enum) and `0012` (`price_forecasts`), so Addition #4's column becomes `0013` when built.
  - [x] `services/ticker_directory_service.py::refresh_directory()` — chunked bulk `ON
    CONFLICT(symbol)` upsert (deduped by symbol first, since one INSERT can't touch a conflict
    target twice and the dump lists some symbols under two MICs). Rate-limited/circuit-broken
    and logs a `job_runs` row on every path (ok/skipped/failed), never raises — same posture as
    `refresh_service.refresh_entry`.
  - [x] `GET /tickers/search?q=&limit=` — plain `ILIKE` search against the local table only,
    zero live provider calls (FR-34); orders symbol-prefix matches first, then shorter symbols,
    then alphabetical.
  - [x] `POST /internal/refresh-ticker-directory` + weekly APScheduler job
    (`ticker_directory_refresh_interval_seconds`, 7d), same dual-trigger pattern as every other
    job (NFR-1).
  - [x] Frontend: `TickerCombobox` type-ahead on the "Add Holding" form; manual entry preserved
    for symbols not yet in the directory (whatever is typed IS the value, FR-35).
  - **Verified (2026-08-05):** live bulk pull populated the dev DB with **30,919 symbols in one
    provider call**; local search returned correct matches (`AAP`→Advance Auto Parts, name match
    `nvidia`→NVDA) and **added zero `provider_call_log` rows** — the whole point of FR-34.
    Backend suite **229/229** green (was 214; +15: 4 provider-unit, 8 service-integration,
    3 router), migration `0010` round-trips. Frontend `tsc -b` + `vite build` clean, `oxlint` 0
    errors (only the 2 known `AuthContext.tsx` fast-refresh warnings).
  - **Not verified — same standing caveat as Phase 5/Addition #1:** no interactive browser this
    session, so the combobox's actual rendering/dropdown/keyboard behavior is confirmed only by
    type-check + build, not by clicking it. Open `/portfolio` yourself to confirm the dropdown.

- [x] **Portfolio income projection** (build second — pure computation, no new provider) ✅ DONE (2026-08-05)
  - [x] `services/portfolio_projection_service.py::compute_projected_income(db, tickers, horizons)`
    — eligibility + expected-profit math (FR-27, FR-28). Latest analysis per company via one
    `DISTINCT ON` query (same pattern as `chat_service._latest_verdicts`). Reason strings:
    `"not yet analyzed"` / `"no AI sell target"` / `"AI suggests holding longer than this horizon"`.
    **Scope decision:** the panel means one thing — "profit if you keep holding and sell when the
    AI's upside target is reached within H." A `sell` verdict doesn't fit that premise (it says
    "get out now", and its `sell_at_or_above` is anchored near resistance per the verdict prompt),
    so it's **excluded** with the reason `"AI recommends selling now — see current gain/loss"`
    rather than projected at an upside target the verdict contradicts — the real "sell today"
    figure is the holding's unrealized gain/loss already shown on the page. Keyed on
    `verdict == sell` (also the only case with a null `hold_period_days.min`). An expected *loss*
    on a buy/hold verdict (sell target below cost basis) is shown honestly as a negative number,
    never hidden or zeroed.
  - [x] `GET /portfolio/projected-income?horizon=&tickers=` (FR-29) on a new `portfolio.py`
    router — both params optional narrowing filters; bare call returns every holding × 30/60/90.
  - [x] Frontend: `ProjectionPanel` on `/portfolio` — a per-holding × 30/60/90 table with
    include/exclude chips; ineligible cells render the reason string (never hidden or zeroed).
    Totals are summed client-side from the server's per-holding `expected_profit` as the chips
    toggle (instant, no re-fetch); the server still owns each holding's value and eligibility.
  - **Verified (2026-08-05):** unit/integration tests cover every branch — eligible profit,
    no-analysis, no-sell-target, hold-period-vs-horizon bucketing (ineligible at 30d → eligible
    at 60d), sell-verdict exclusion (sell-now reason), expected-loss-shown-as-negative,
    latest-analysis selection, aggregate sums only eligible, `tickers` filter, `horizon` filter. Backend suite **241/241** green (+12:
    9 service, 3 router). **Live check against the real holdings**, hand-verified:
    NVDA (232.28−124.94)×1.18 = **126.66**, MSFT (525.0−498.4)×0.2985955 = **7.94**, total
    **134.60** — matches to the cent. Frontend `tsc -b` clean, `oxlint` 0 errors (2 known
    `AuthContext.tsx` warnings only).
  - **Not verified — standing caveat:** no interactive browser this session, so the panel's
    rendering/chip-toggling is confirmed by type-check + build, not by clicking it.

- [x] **Multi-horizon forecast — second LLM (Groq)** (build third — new provider, new prompt,
  highest complexity) — **SHIPPED DORMANT (2026-08-06): no API key obtainable as of 2026-08-05.**

  Everything in this block is buildable and verifiable *without* a key and is what "done" means
  for this addition. The tasks that genuinely need a live key are split out into "Groq activation
  (blocked on API key)" below — deliberately a separate checklist so this addition can close and
  Phase 6 can start without the key ever arriving. **Non-negotiable acceptance condition for every
  task here: with `GROQ_API_KEY` unset, the app must behave exactly as it does today** — same
  startup, same routes, same scheduler, same 210+ green tests, same migration round-trip (NFR-9,
  FR-33a). If any of those change, the standby has been implemented wrong. **Verified: full suite
  268/268 green with `GROQ_API_KEY` unset, 12 migrations round-trip. See
  [tests/groq-forecast-dormant.md](tests/groq-forecast-dormant.md).**
  - [x] ~~Derisk standalone first, same habit as Phase 0~~ — **impossible without a key; deferred
    to the activation checklist below, not skipped.** Recorded honestly as the one place this
    project's derisk-before-code habit is inverted: the client, prompt, and parsing are written on
    assumption (FR-33b). `scripts/test_groq_prompt.py` written *now*, mirroring
    `scripts/test_gemini_prompt.py` (`--fixture`/`--model`/`--repeat` flags, reusing the existing
    `scripts/fixtures/*.json`), so activation is one command rather than a fresh build.
  - [x] `settings.groq_api_key: str | None = None` + `groq_model` (`llama-3.3-70b-versatile`) /
    `groq_rate_limit_per_window` / `groq_rate_limit_window_seconds` config knobs, plus a
    `.env.example` entry with a comment saying the key is not yet obtainable and the feature is
    dormant without it. Same optional-key shape the other three providers already use — the model
    id is picked from Groq's docs rather than a live call, so re-check it during activation (§12).
  - [x] `GET /status` gains a `features` map (`{"forecast": <bool>}`) derived from key presence
    (FR-33a) — the single source the frontend uses to decide whether the button is live
  - [x] **`ProviderName.groq` + `ALTER TYPE providername ADD VALUE 'groq'` migration (`0011`) — did
    this before the client.** Called out as its own task because Phase 4 hit precisely this bug with
    `gemini`: the Python enum member was added, the Postgres `ALTER TYPE` was forgotten, and the
    very first rate-limiter check died on `invalid input value for enum providername` (fixed by
    migration `0006` — see Phase 4's bug list). The rate limiter, circuit breaker, and
    `provider_call_log` writer all key off this enum, so *no* Groq call can succeed until both
    halves exist. Copied `0006`'s pattern verbatim: `ALTER TYPE providername ADD VALUE IF NOT
    EXISTS 'groq'` on upgrade, documented no-op on downgrade (Postgres has no `DROP VALUE`).
    **Ships even though nothing uses it yet** — inert without a key, and this is the exact bug
    class that bites when deferred.
  - [x] `providers/groq_client.py` — own retry/backoff + rate-limit bucket, entirely independent
    of Gemini's budget (FR-33), plus an `is_available()`/key-presence check that callers consult
    *before* any network attempt, so a missing key never reaches the retry machinery (nothing to
    log, nothing to trip). Built on Groq's OpenAI-compatible endpoint with plain `httpx` (no new
    dependency), JSON-object mode, same Transient/Permanent taxonomy as every other client.
  - [x] `prompts/forecast_prompt_v1.md` — schema-forced JSON, all five horizons in one call to
    conserve quota, per-horizon `confidence` (FR-30). **UNVALIDATED** — written without a live
    derisk run (no key), so it's an assumption until activation (FR-33b).
  - [x] `price_forecasts` table + migration (`0012`) (FR-31)
  - [x] `services/forecast_service.py::build_forecast_prompt()` / `generate_forecast()` /
    `list_forecasts()` — reuses `ai_service`'s template helpers against the shared
    `wiki_service.assemble()` data; validates the parsed response into exactly the five expected
    horizons (missing horizon / `high < low` / malformed field → `PermanentProviderError` → 502).
  - [x] `POST /companies/{ticker}/forecast` — watchlist-only, on-demand-only, mirroring
    `/critique`'s gating exactly (FR-30, FR-32), **plus the key-absent `503` branch checked before
    the watchlist check** so the message names the real blocker (FR-33a)
  - [x] `GET /companies/{ticker}/forecasts` — works regardless of key state, empty structure when
    nothing has been generated
  - [x] Frontend: `ForecastPanel` on the wiki page (per-horizon low/high rendered as a
    single-series horizontal range-band per the `dataviz` skill — one hue, direct low/high labels,
    per-horizon confidence), "Generate Forecast" button gated the same way "Get Second Opinion" is
    for lookup-tier tickers, **and additionally disabled with a "Groq API key not configured"
    tooltip when `features.forecast` is false** — visibly on standby rather than hidden, so the
    feature's existence and its blocker are both obvious (FR-33a). The panel renders an explicit
    "on standby / not configured" empty state, not a spinner or a blank box.
  - **Verify (all achievable with no key — this is the addition's real exit criterion): ✅ DONE**
    unit tests for prompt assembly and response parsing against a *recorded/hand-written* Groq
    response fixture (mocked, like every other provider's parser tests); an integration test
    asserting the key-absent path returns `503` with a clear message and writes **no**
    `provider_call_log` and no `job_runs` row; `features.forecast == false` in `GET /status`;
    the frontend button disabled with its tooltip; `alembic upgrade head → downgrade base →
    upgrade head` still clean with the two new migrations; and the **full suite green with
    `GROQ_API_KEY` unset** — the whole point of the standby.
  - **Deferred, not required for this addition:** blending Groq's horizon-matched high/low into
    the income projection above (instead of relying solely on Gemini's single price target) —
    ship the two independently first; revisit once both have real usage.

- [ ] **Groq activation (blocked on API key)** — *not part of Addition #2's completion; do these
  in order, on the day a key exists.* Kept as a standing checklist so the deferred verification
  can't be quietly forgotten once the infrastructure looks finished.
  - [ ] Obtain a Groq API key (currently blocked: the user cannot sign in — 2026-08-05) and put it
    in `.env` only, never git (T0.7's handling, unchanged)
  - [ ] Re-check the configured `groq_model` against Groq's currently-live free-tier lineup before
    the first call — it was chosen from documentation, not a live call (§12)
  - [ ] **Run the deferred derisk: `scripts/test_groq_prompt.py`** against
    `sample_wiki_data.json`, `sample_wiki_thin.json`, and `aapl_live.json`, several repeats each.
    Confirm real, *varying* per-horizon bands (not five copies of one range), confidence that
    decays from 30d to 360d, honest low confidence on the thin fixture, and no refusal/hedge.
    **Expect prompt or parsing changes here** (FR-33b) — this is first real contact
  - [ ] Live end-to-end: a real forecast on a real watchlist ticker → 5 `price_forecasts` rows,
    band widening sensibly with horizon length, `model` stamped per row
  - [ ] Confirm the negative paths live: lookup-tier ticker → `400` (like `/critique`); Groq quota
    exhaustion → clear "try later", never a silent failure or generic 500 (FR-33)
  - [ ] Confirm `GET /status` flips `features.forecast` to `true` and the frontend button enables
    itself with no code change — if it needs one, the capability flag was wired wrong
  - [ ] Update this spec's status header and §11 open decision to reflect Groq as live rather than
    dormant

- **Verify (whole addition): ✅** each sub-feature's own verify step above passes; full test suite
  green **with `GROQ_API_KEY` unset** (268/268), 12 migrations round-trip. **Still outstanding:**
  all three UI additions visually/interactively confirmed in a real browser — for the forecast
  panel that means confirming the *disabled* standby state reads clearly (button greyed, tooltip
  explains why, panel shows "not configured"), since the live state can't be seen yet (carrying
  forward the same "open it yourself" caveat Phase 5 and its post-phase additions both flagged as
  outstanding — no interactive browser this session).
- **Definition of done for this addition:** ticker directory and income projection fully working;
  Groq infrastructure merged and dormant, with its activation checklist outstanding. Groq being
  dormant does **not** hold this addition open and does **not** block Phase 6.

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

### Token-efficiency pass — 2026-08-05 ✅ DONE
Requested directly by the user: fix the prompt duplication and any other token waste, so that
"simple and minor calls" can't eat the budget the user wants available for their own on-demand
stock evaluations. Small, code-only, no new tables or endpoints. **214/214 tests pass** (210 + 4
new).

- **The duplication was in chat, not in the verdict path.** Worth recording because the first
  guess was wrong: `ai_service.wiki_to_prompt_data()` already maps `assemble()` into a
  purpose-built subset and never sends `sections.news_digest`, so verdict/critique prompts were
  already lean. `chat_service._build_grounding_context()` was passing the **entire `assemble()`
  dict per tracked company**, which carried three prose sections that restate structured fields
  present in the same payload:
  - `sections.news_digest` → the same headlines already in `recent_news`
  - `sections.key_metrics` → `latest_price` / `market_cap` / `sector` / `price_summary`
  - `sections.overview` → `name` / `exchange` / `sector` / `market_cap`
- **Why chat specifically:** it is the only prompt whose size scales with how many companies the
  user tracks, and it is rebuilt from scratch on *every message* — a once-daily verdict paying a
  few hundred extra tokens is irrelevant; a per-message payload that grows with the watchlist is
  not.
- [x] `chat_service._slim_for_grounding()` — drops all `sections`, `logo_url`, `coverage_tier`,
  and each article's `url` (citations resolve server-side from reference ids per FR-48, so the
  model never needs a URL and shouldn't be handed one it could echo as if it had read the page);
  caps `description` and article `summary` length. `wiki_service.assemble()` is deliberately
  **unchanged** — it stays the shared read path (FR-10, NFR-10), and the slim payload is a strict
  subset of what the user can see, so the grounding guarantee is untouched.
- [x] Compact JSON separators instead of `indent=2` for the grounding blob (NFR-10c).
- [x] **Fixed a real capability gap found in passing:** the chat prompt has instructed the model
  since day one to ground comparisons in "each company's latest verdict", but `assemble()` — built
  for a page whose verdict banner is fetched separately — never carried one, so that instruction
  pointed at data that wasn't in the payload. `_latest_verdicts()` now supplies the latest
  `ai_analyses` row per company in a single `DISTINCT ON` query (not N queries), and the prompt
  tells the model to say so plainly when a company has never been analyzed rather than guessing.
- [x] Sizes moved to config (`chat_news_articles_per_company`, `chat_article_summary_chars`,
  `chat_description_chars`, `chat_max_tracked_companies`, `chat_max_history_messages`) rather than
  hardcoded — it is a quality-vs-tokens tradeoff only the user can judge, same reasoning as the
  budget fractions. Note `6` is the effective ceiling for articles-per-company, since
  `ingest_service.recent_news()` reads 6.
- **Measured against the real dev database** (6 tracked companies, 30 articles): grounding payload
  **33,600 → 17,035 chars (~8,400 → ~4,260 tokens), a 49% cut**, with verdicts now included rather
  than missing. Per-field breakdown after the pass: `recent_news` 11,501 · `latest_verdict` 992 ·
  `price_summary` 905 · `holding` 668 · `latest_price` 538 · everything else under 450.
- **Where the remaining weight is:** news is **68%** of the slimmed payload and scales as
  companies × 6 articles. That is the quantified case for the news-digest pipeline discussed with
  the user — compressing article bodies into a rolling per-company digest is the only remaining
  large win here, and it is deliberately *not* part of this pass (it needs its own AI call and its
  own derisking; see the discussion recorded in `plan.md` → "Source citations per reply" and the
  digest question).
- [x] Tests: 4 new integration tests asserting the payload keeps its shape — page-only and
  duplicated fields stay dropped, free-text caps hold, the per-company article cap is respected,
  the latest verdict is the *latest* one, and a never-analyzed company yields no verdict entry.
  These exist specifically so the payload can't quietly drift back to the full dict.

### Post-Phase-5 Addition #4 — Chat Source Citations
Requested directly by the user (2026-08-05): *"in the chat, for each answer give me the articles it
got the information from."* Small and self-contained — one new prompt version, one nullable column,
one migration, one chip row in the UI — and **independent of Additions #2 and #3**: it touches only
`chat_service`, `chat_messages`, and `ChatPage.tsx`, so it can be built before, after, or between
them without reordering anything. Completes the grounding guarantee: grounding proves the AI *could
only* have used visible data; citations show *which* visible data each answer actually used.

- [ ] **Reference-id stamping in the prompt context** (build first — everything else depends on the
  id map existing)
  - [ ] `chat_service._build_grounding_context()` assigns each article a stable per-request id
    (`N1`, `N2`, … across all tracked companies, deterministic ordering) and keeps an in-memory
    `{id: news_articles row}` map for the life of the request (FR-48)
  - [ ] Ids are injected into the `recent_news` entries the prompt sees; the underlying
    `wiki_service.assemble()` return value is **not** changed — the ids are a chat-prompt concern,
    and `assemble()` is shared with the verdict/critique/forecast paths and the wiki API route
    (FR-10), none of which should grow a chat-specific field
- [ ] **`prompts/chat_prompt_v2.md`** — new file, v1 untouched (NFR-5)
  - [ ] Output schema becomes `{reply, cited_sources[]}`; `response_schema` updated to match
  - [ ] Instructions: cite by id only, never write a URL; cite what was actually used; use the
    non-`news` types for price/verdict/position claims instead of attributing them to a headline;
    an empty list is correct when there is genuinely nothing to cite (FR-50)
  - [ ] Add the corresponding "What to watch for when testing" notes, matching v1's habit —
    specifically: does it cite ids that exist, does it over-cite (listing every article regardless
    of use), and does it fabricate an article for a price-only answer
- [ ] **Backend resolution + persistence**
  - [ ] `chat_service` resolves returned ids against the request's id map, drops and logs
    unrecognized ids, and builds the typed citation list with real headline/source/url/published_at
    (FR-47, FR-48)
  - [ ] `chat_messages.cited_sources` JSONB nullable column + migration `0010` (FR-49)
  - [ ] `POST /chat` and `GET /chat/messages` responses include `cited_sources` on assistant
    messages
- [ ] **Frontend**: source chips under each assistant message on `/chat`, styled like the verdict
  banner's existing `cited_sources` chips for consistency; `news` chips are links
  (`target="_blank"`, `rel="noopener noreferrer"`) showing headline + source + date; non-`news`
  chips are plain labels. When a reply has no `news` citations, render the explicit "based on price
  and verdict data — no articles available" note rather than an empty row (FR-50). Update
  `api/types.ts` + the chat hook.
- **Verify:**
  - unit tests: id stamping is deterministic and covers every article in context; resolution maps
    ids back to the right rows; **an unknown/hallucinated id is dropped, not rendered** (the
    single most important test in this addition); a reply with an empty citation list round-trips
    fine
  - integration test: `POST /chat` with a mocked Gemini response containing a mix of valid ids,
    one invalid id, and one non-`news` citation → stored row and HTTP response contain exactly the
    valid citations with real URLs; `GET /chat/messages` returns them unchanged after reload
  - migration `0010` round-trips (`upgrade head → downgrade base → upgrade head`), keeping the
    project's now-standard check
  - **live check against real Gemini and real data**: ask a question about a tracked company that
    genuinely has articles, confirm the cited URLs open the real articles and that the cited
    headlines actually support the claim in the reply (the point of the feature is that this is
    checkable — so check it); then ask about a tracked company with **no** news rows and confirm
    the reply cites price/verdict data and says so, instead of inventing an article
- **Note on existing history:** rows already in `chat_messages` predate the column and will have
  `cited_sources = NULL`. Render those as "no citations recorded" rather than backfilling —
  a citation can only honestly come from the call that produced the reply.

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
| 3 | No Groq API key is obtainable — the user cannot currently sign in to Groq (2026-08-05). Does the multi-horizon forecast (§3.9) block Addition #2 and Phase 6? | **Resolved — no.** User decision: build the infrastructure now, keep the feature dormant, and let a missing key be a non-event for the rest of the app (NFR-9, FR-33a). Addition #2 closes with Groq dormant; the live-key work is tracked in §9's "Groq activation" checklist. Consequence accepted deliberately: the client, prompt, and parsing ship **unvalidated** (FR-33b), inverting this project's derisk-first habit for the first time — see §12. Revisit only if sign-in stays blocked long enough that the dormant code starts drifting from Groq's API. |

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
- **A failed AI call costs the same budget slot as a successful one.** `rate_limiter.allow()`
  counts every `provider_call_log` row regardless of `status`, and `chat_service`/`ai_service` both
  write a failure row on `ProviderError`. That is correct behavior (a rejected request generally
  did consume provider quota), but it means anything that makes a call *fail* — an oversized
  prompt hitting a token-per-minute limit, a flaky network — silently eats from the same daily
  Gemini budget the user's own on-demand evaluations draw on, while returning nothing. This is the
  concrete reason NFR-10 exists. Note the Gemini paths do **not** consult the circuit breaker
  (that is wired only for Finnhub/Alpha Vantage in `provider_orchestrator`), so repeated chat
  failures burn quota but cannot trip a breaker that would block verdicts outright.
- **Chat grounding truncates silently at `chat_max_tracked_companies` (40), ordered by
  `Company.id`** — so if the user ever tracks more than 40 companies, chat would tell them it
  "can only discuss companies tracked here" about a company that genuinely *is* tracked, which
  breaks the honesty of the grounding guarantee rather than just trimming tokens. Latent today (6
  companies tracked) and left as-is deliberately, because the right fix is a design change, not a
  bigger number: send a **thin roster of every tracked company** (ticker/name/category/price/
  verdict, ~1 line each) plus full detail only for the companies the question actually mentions,
  matched by ticker/name against the message and recent history. That keeps grounding complete at
  any watchlist size while making the common single-company question far cheaper than it is today.
  Worth building if the tracked set grows past ~15, or alongside the news-digest pipeline.
- **A clickable chat citation is a claim the app makes on its own behalf** — if the model authored
  the URL, that claim could be a convincing fabrication (real-looking domain, dead link), which is
  worse than no citation at all because it *looks* verified. Mitigated structurally rather than by
  prompt wording (FR-48): the model cites prompt-assigned ids and the backend resolves them against
  the articles it actually sent, dropping anything unrecognized. Standing rule for any future
  feature that renders a model-produced link.
- **Chat citations are bounded by free-tier news coverage** — Finnhub withholds `/company-news` and
  the Alpha Vantage `NEWS_SENTIMENT` fallback doesn't cover every ticker, so some tracked companies
  have no articles and their answers will honestly cite price/verdict data instead (FR-50). Not a
  defect to engineer around, but it means "show me the articles" sometimes correctly answers "there
  are none for this company" — the UI must say that plainly instead of looking empty or broken.
- **No Groq API key is obtainable (2026-08-05), so the forecast ships unvalidated** (§11 #3,
  FR-33b). Its client, prompt, and response parsing are written without the live derisk run every
  other integration here got first — assumptions, not verified behavior. Mitigated by scope rather
  than by cleverness: on-demand-only and key-gated, so while dormant it cannot break, slow, or
  degrade anything the app already does (NFR-9), and the derisk script ships now so activation
  begins with verification. Residual risk accepted: wasted work if Groq proves unsuitable — the
  alternative was leaving the whole addition unbuilt.
- **A key-gated feature can rot silently.** Nothing exercises Groq while the key is missing, so
  its client could drift out of step with the shared provider interface — or with Groq's own API —
  and no failing test would notice. This is the standby's one genuine cost. Mitigated by holding
  `groq_client` to the same mocked-provider test coverage as every other client, so *interface*
  drift still breaks the suite with no key present; API-side drift can only be caught at
  activation.
- **Groq's free-tier model lineup drifts/deprecates over time** — the same class of risk
  already seen with Gemini model aliasing (§11 #2). Mitigated the same way: a config knob, not
  a hardcoded model id, and the exact model stamped into each `price_forecasts` row (NFR-5
  pattern). Sharper here: today's `groq_model` default is chosen from documentation rather than a
  live call, so it must be re-checked during activation instead of trusted.
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
.env / .env.example / .gitignore     — Gemini/Finnhub/Alpha Vantage API keys + DB URL handling
                                       (never committed). `GROQ_API_KEY` is documented in
                                       .env.example but intentionally unset — the forecast
                                       feature is dormant without it (FR-33a)
prompts/
  verdict_prompt_v1.md               — first-pass verdict prompt (Phase 0, done; superseded
                                        by v2 as the live default, kept for reproducibility)
  verdict_prompt_v2.md               — adds a "Your Position" section (post-Phase-5, current default)
  verdict_critique_prompt_v1.md      — adversarial second-opinion prompt (Phase 0, done)
  chat_prompt_v1.md                  — grounded chat reply prompt (post-Phase-5; superseded by
                                        v2 once Addition #4 lands, kept per NFR-5)
  chat_prompt_v2.md                  — planned (Addition #4): adds per-answer source citations,
                                        cited by prompt-assigned article id (FR-47, FR-48)
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
                                        Holding, ChatMessage (post-Phase-5 — ChatMessage gains a
                                        nullable cited_sources JSONB column in Addition #4)
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
      0010_chat_cited_sources.py     — planned (Addition #4): nullable cited_sources JSONB on
                                        chat_messages (FR-49)
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
                                        every tracked company's wiki_service.assemble() data (post-Phase-5),
                                        slimmed to a purpose-built subset by _slim_for_grounding()
                                        + _latest_verdicts() (token-efficiency pass 2026-08-05,
                                        NFR-10 — sizes tunable via settings.chat_*).
                                        Addition #4 adds article reference-id stamping + server-side
                                        citation resolution (FR-48) — the id map is chat-local, so
                                        wiki_service.assemble()'s shared return value is unchanged
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
                                        see that addition's test report for why) and clears
                                        pre-existing holdings/chat_messages rows (2026-08-04
                                        verification run — same reason, global-by-design reads),
                                        and provides a
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
      PortfolioPage.tsx, ChatPage.tsx (post-Phase-5; ChatPage gains per-reply source chips in
                                        Addition #4 — news chips link out to the real article URL)
```

A `fundamentals` table still does not exist — Phase 4 deliberately did not add one (see that
phase's scope-decision note above); the prompt's `financials_summary_last_4_periods` stays an
honest empty array until a future phase adds real fundamentals ingestion.

The Groq pieces now exist but are **dormant** (Addition #2, 2026-08-06): `providers/groq_client.py`,
`services/forecast_service.py`, `prompts/forecast_prompt_v1.md`, `scripts/test_groq_prompt.py`,
`api/routers/forecast.py` + `api/routers/status.py`, the `price_forecasts` table (migration `0012`)
and the `groq` `providername` value (migration `0011`), and the frontend
`components/ForecastPanel.tsx`. All present, all inert without a `GROQ_API_KEY` — marked as such
here so nobody reading the map later mistakes "the files exist" for "the feature works" (FR-33b).
Its prompt and response parsing remain **unvalidated against a live model** until the activation
checklist in §9 is run.
