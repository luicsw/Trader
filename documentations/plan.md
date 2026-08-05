# Personal Investment Research App — Implementation Plan

## Context

The user wants a personal, single-user tool to decide which stocks to buy/hold/sell, with
always-fresh news/prices and an AI that reasons over that data rather than just showing raw
numbers. Requirements gathered through discussion:

- Python backend (chosen over Next.js for its data/quant ecosystem), fully free stack (free
  data APIs, free AI tier, free hosting) — no paid services anywhere.
- "As reliable as possible" — the app must degrade gracefully when an external API is
  down/rate-limited, never silently fail, and never corrupt data.
- The database should function like a **wiki**: every company gets a browsable
  encyclopedia-style page, not just rows in a dashboard — and that same wiki content is what
  the AI reasons over, so the AI's conclusions are always traceable to what the user can see.
- Every company in the market should be viewable this way on demand, not just a fixed
  watchlist — but only the user's actual watchlist gets continuous background tracking, to
  protect free-tier rate limits.
- A "full, professional, fintech-style" UI with a complete set of financial charts.
- Must work well on a phone as well as desktop, ideally installable like an app, without
  building a separate native app.
- No Claude/Anthropic API key is available for this project — AI reasoning uses Google
  Gemini's free tier instead.
- **No Groq API key is available either, as of 2026-08-05** — sign-up/sign-in for Groq is
  currently blocked for the user. The second-LLM multi-horizon forecast below is therefore
  built as **dormant infrastructure**: the code, migration, prompt, and UI ship, but the
  feature stays switched off and *must not* affect the app's working state or usage while
  `GROQ_API_KEY` is unset. Dropping a key into `.env` later is the only step needed to
  activate it (plus the standalone derisk run, which is deferred until then).

This plan combines two independent designs (backend/data/infra and frontend/UX) into one
buildable architecture, greenfield (repo is currently empty).

## Architecture Overview

```
 GitHub Actions (cron, free) ──POST /internal/refresh──▶ FastAPI backend (Render free) ──▶ Postgres (Neon free)
                                     every 15-30 min               │
 GitHub Actions (cron, free) ──POST /internal/analyze-scheduled──▶ │
                                     daily                          ├─▶ Finnhub (primary data)
                                                                     ├─▶ Alpha Vantage (fallback data)
                                                                     ├─▶ Gemini (verdict/critique/chat, free tier)
                                                                     └─▶ Groq (multi-horizon forecast, free tier,
                                                                          separate quota — on-demand only)
                                                                          ⚠ DORMANT: no API key yet; every
                                                                          other arrow above works without it

 React PWA (installable on phone/desktop) ──HTTPS/JSON──▶ FastAPI backend ──reads only──▶ Postgres
```

Postgres is always the source of truth the API/frontend reads from — no request path ever
blocks on a live external call. Background jobs are the only thing that write external data in.

## Deployment Decision (the "local vs website" question)

**Recommendation: deploy it, don't run it purely locally.** Local-only fails two hard
requirements at once: no background refresh happens while your laptop is off/asleep (breaks
"always up to date"), and phone access requires a VPN/tunnel set up on every device. Neither
is worth the hassle when a fully free hosted option exists.

**Chosen topology:**
- **Database**: Neon free Postgres — plain Postgres endpoint, no extra platform surface to
  learn, generous-enough free storage for this scale.
- **Backend**: FastAPI on Render's free web service tier. It spins down after ~15 min idle —
  acceptable because refresh doesn't depend on the process staying warm (see below).
- **Scheduler/heartbeat**: two GitHub Actions scheduled workflows (fully free, effectively
  always-available) — one every 15–30 min hitting `POST /internal/refresh`, one daily hitting
  `POST /internal/analyze-scheduled`. These both wake Render and trigger the actual jobs, so
  freshness never depends on any device being on.
- **Frontend**: the React PWA deployed to any free static host (Vercel/Netlify), installed to
  phone home screen — no App Store, no native app, works on any device with a browser.
- **Access control**: one shared HTTP Basic Auth / bearer credential in front of all
  non-trivial endpoints (env var/secret in Render + GitHub Actions) — no user accounts needed
  since this is single-user.

Rejected alternatives and why: Oracle Cloud's "Always Free" VM avoids cold starts but has a
documented risk of reclaiming under-utilized "free" instances — that directly undermines the
reliability requirement, so it's not worth the trade. Fly.io's free allowance has shrunk
before and is less predictable long-term. Celery+Redis was considered for the job queue but
rejected in favor of in-process **APScheduler** — there's no throughput need that justifies a
broker/worker process, and one fewer moving part is strictly better for a solo-maintained,
reliability-first project.

**Accepted tradeoff**: occasional 10–30s cold start on the first manual app open after a long
idle period. Fine for a personal research tool that isn't day-trading.

## Data Model (Postgres) — the "wiki" design

Core principle: **one assembly function, two consumers.** `wiki_service.assemble(ticker)`
reads all tables below for a symbol and returns one structured dict. The wiki API route
renders it as the company's page; the AI pipeline serializes the *same* dict into its prompt.
This guarantees the AI never reasons over data the user can't also see.

- `companies` — infobox data (name, exchange, sector, description, logo, market cap,
  `coverage_tier: watchlist|lookup`, `last_profile_refresh_at`).
- `watchlist` — which companies get continuous tracking (`refresh_interval_minutes`,
  `last_scheduled_refresh_at`, `last_scheduled_analysis_at`, `active`, plus `is_benchmark`
  *(pre-Phase-6 addition)* — price-tracking-only rows that inherit none of watchlist
  membership's other consequences, see "Backtest vs. benchmark").
- `price_bars` — OHLCV time series, unique on `(company_id, ts, interval)` for idempotent
  upserts, indexed `(company_id, interval, ts DESC)` for chart range queries.
- `news_articles` — headline/summary/url/source/published_at/sentiment, unique on
  `(company_id, url)` to dedupe re-fetches.
- `fundamentals` — quarterly/annual financials (revenue, net income, EPS, margins, FCF...),
  unique on `(company_id, period, fiscal_period)`.
- `wiki_sections` — the actual wiki prose per company, one row per
  `section_key` (`overview|financials_summary|news_digest|key_metrics|risks_notes`), unique on
  `(company_id, section_key)` so each section is independently regenerable and timestamped.
  This is a derived cache computed from the raw tables above, and doubles as prompt input.
- `ai_analyses` — one row per verdict ever generated (never overwritten): `verdict`
  (buy/hold/sell), `confidence`, `reasoning_text`, `price_targets` (JSONB —
  `buy_at_or_below`/`sell_at_or_above`/`stop_loss`, nullable per field), `hold_period_days`
  (JSONB — `min`/`max`/`note`, null when verdict is `sell`), `cited_sources` (JSONB),
  `context_snapshot` (JSONB — the exact dict sent to Gemini, kept for reproducibility), `trigger`
  (`scheduled|on_demand|initial`), `generated_at`. Indexed `(company_id, generated_at DESC)`.
- `ai_critiques` — one row per second-opinion critique ever generated (never overwritten):
  `analysis_id` (FK → `ai_analyses`, the verdict being critiqued), `agrees_with_verdict_direction`
  (bool), `biggest_weakness` (text), `revised_price_targets` (JSONB, nullable per field),
  `revised_confidence` (nullable float), `rationale` (text), `generated_at`. Always on-demand,
  never scheduled — see AI pipeline section. Note it deliberately has **no** `context_snapshot`
  of its own: a critique is traceable to the analysis it points at, but since it reads whatever
  wiki data is current at *its* run time, it isn't reproducible the way an `ai_analyses` row is.
  Worth adding the column if critique history ever needs auditing.
- `provider_call_log` — append-only ledger per external call (`provider`, `status`,
  `called_at`) backing the rate limiter and circuit breaker, and doubling as an audit trail.
- `job_runs` — background job observability (`job_name`, `status`, `error_message`,
  `attempt`) so failures are visible, never silent.
- `verdict_outcomes` *(post-Phase-4, built)* — per analysis, whether the verdict was
  directionally correct at a fixed 30-day horizon (`analysis_id` FK, `horizon_days`,
  `price_at_verdict`, `price_at_horizon`, `price_change_pct`, `directionally_correct`,
  `evaluated_at`), append-only, unique on `(analysis_id)`. Turns "is the AI any good" from an
  assumption into something checkable — see spec.md's Post-Phase-4 Addition.
- `holdings` *(post-Phase-5, built)* — the user's actual positions (`company_id` unique,
  `shares`, `cost_basis_per_share`, `acquired_at`, `notes`). Deliberately not tax lots and not
  realized-gains accounting (explicit scope decision). This is the table the portfolio income
  projection below reads.
- `chat_messages` *(post-Phase-5, built)* — linear single-user chat history (`role`, `content`,
  `created_at`), append-only, no multi-conversation concept. Backs the grounded chat feature
  below. Gains a nullable `cited_sources` JSONB column *(2026-08-05 addition)* — populated on
  assistant rows only, same shape as `ai_analyses.cited_sources`, so each reply's article
  citations survive a page reload instead of being recomputed or lost.
- `price_forecasts` *(pre-Phase-6 addition)* — one row per horizon per Groq forecast
  generation (`company_id`, `horizon_days`, `expected_low`, `expected_high`, `confidence`,
  `rationale`, `model`, `trigger`, `generated_at`), append-only like `ai_analyses`.
  `confidence` is per-horizon, matching the prompt's per-horizon field — a single value for the
  whole set would just be copied into all five rows, and confidence genuinely should decay from
  30d to 360d.
- `ticker_directory` *(pre-Phase-6 addition)* — local cache of the tradable-symbol universe
  (`symbol` unique, `name`, `exchange`, `security_type`, `updated_at`), bulk-refreshed weekly
  from Finnhub's symbol listing endpoint, backing the Add Holding autocomplete without spending
  live search-API quota per keystroke.
- `alerts` *(pre-Phase-6 addition)* — `company_id`, `alert_type`
  (`verdict_change|sell_target_hit|stop_loss_hit`), `message`, `triggered_at`, `acknowledged`,
  `acknowledged_at`. Not append-only like the AI tables — `acknowledged` is a real state
  transition — with "at most one open alert per `(company, alert_type)`" enforced in
  `alert_service`, not a DB constraint.
- `push_subscriptions` *(pre-Phase-6 addition, only needed if the Web Push extension is built)*
  — `endpoint` (unique), `p256dh_key`, `auth_key`, `created_at`.

## Backend (FastAPI) Structure

```
app/
  main.py, config.py
  db/{session.py, models.py, migrations/}       # Alembic
  api/routers/{wiki.py, companies.py, watchlist.py, analysis.py, refresh.py, health.py}
  services/{wiki_service.py, lookup_service.py, watchlist_service.py, ai_service.py,
            refresh_service.py, rate_limiter.py, circuit_breaker.py}
  providers/{base.py, finnhub_client.py, alpha_vantage_client.py, gemini_client.py}
  jobs/{scheduler.py, tasks.py}                  # APScheduler; same functions the
                                                  # GitHub Actions endpoint calls
  core/{logging.py, sentry.py, errors.py}
tests/{unit/, integration/}
```

`app/api/routers/refresh.py` (hit by GitHub Actions) and `app/jobs/tasks.py` (run by
APScheduler when the process happens to be warm) call the exact same `refresh_service`
functions — one source of truth for refresh logic regardless of what triggered it, and calls
are idempotent (checked against `last_scheduled_refresh_at` and provider budget) so redundant
triggers are safe no-ops.

### Reliability mechanics
- **Provider fallback**: `providers/base.py` defines a common interface; a
  `fetch_with_fallback()` orchestrator tries Finnhub first, falls back to Alpha Vantage on
  rate-limit/downtime, guarded by a per-provider circuit breaker (opens after N consecutive
  failures, cooldown, half-open probe).
- **Rate limiting**: token-bucket per provider (Finnhub, Alpha Vantage, Gemini) seeded from
  `provider_call_log` on startup, budgeted conservatively below documented free-tier caps.
  Alpha Vantage's free daily cap is small — treated strictly as an emergency fallback, not a
  load-shared partner.
- **Retries**: transient errors (timeouts, 5xx, 429) retried with jittered exponential backoff
  (`tenacity`) before falling back to the other provider; permanent errors (bad ticker, auth
  errors) are never retried, logged loudly (structured log + Sentry), and recorded in
  `job_runs`.
- **Idempotent, transactional writes**: every refresh upserts via `INSERT ... ON CONFLICT DO
  UPDATE` against the unique constraints above — a mid-refresh crash can't corrupt data.
- **Freshness always visible**: every API response carries `last_updated` timestamps so
  staleness is shown, never hidden.

### AI pipeline (Gemini)
1. `ai_service.build_prompt(ticker)` calls the shared `wiki_service.assemble(ticker)`.
2. Renders a versioned prompt template requesting strict JSON:
   `{verdict, confidence, reasoning, cited_sources}` (use Gemini's JSON/schema mode if
   available to avoid brittle text parsing). Template lives at `prompts/verdict_prompt_v1.md`,
   derisked standalone in step 0 below before this service is built.
3. Call wrapped in the same retry/backoff + rate-limit-bucket pattern as the data providers,
   budgeted below Gemini's free RPM/RPD limits with headroom.
4. On quota exhaustion: scheduled analysis just skips the cycle (next day's run retries); an
   on-demand request gets a clear "AI quota reached, try later" response — never a silent
   failure or a generic 500.
5. Result stored as a new `ai_analyses` row (append-only history, not overwritten).
6. **Budget priority**: scheduled watchlist analyses (small, predictable) get priority over
   unbounded on-demand lookup analyses, which are rejected gracefully once the daily budget is
   spent.

### Second opinion (adversarial critique pass)
An explicit, **on-demand-only** `POST /companies/{ticker}/critique` action, never run as part of
scheduled analysis — it's a second full Gemini call on top of the first, and running it
automatically for every watchlist ticker would roughly double daily quota usage for no reason
most of the time. Template lives at `prompts/verdict_critique_prompt_v1.md`, derisked
standalone in step 0 alongside the main verdict prompt.
1. Takes the same `wiki_service.assemble(ticker)` data plus the specific `ai_analyses` row being
   critiqued (identified by `analysis_id`) as input.
2. Framed adversarially — told explicitly to find the single weakest assumption/number in the
   first-pass verdict rather than restate it — since a model self-critiquing within one
   generation tends to rubber-stamp far more than a genuinely separate pass does.
3. Returns `{agrees_with_verdict_direction, biggest_weakness, revised_price_targets,
   revised_confidence, rationale}`. Stored as an `ai_critiques` row: `analysis_id` (FK →
   `ai_analyses`), plus the same fields, `generated_at`. One-to-many (an analysis can be
   critiqued more than once on request) — never overwritten, same append-only philosophy as
   `ai_analyses`.
4. Subject to the same budget/rate-limit/quota-exhaustion handling as on-demand lookup analyses
   (clear "quota reached" message, never a silent failure) — and explicitly the lowest priority
   in the budget order below scheduled analyses and on-demand first-pass verdicts, since it's a
   nice-to-have refinement, not the primary analysis.
5. Surfaced in the UI as a "Get Second Opinion" button on the AI verdict banner (see wiki page
   layout below) — the user opts in per-ticker rather than it happening automatically.

### Second AI provider (Groq) — multi-horizon buy/sell forecast *(built dormant — no key yet)*

**Standby status (2026-08-05).** The user cannot currently sign in to Groq to obtain an API key.
Rather than block the feature or leave a half-designed hole in the plan, it is built as
**dormant infrastructure**: everything that doesn't need a live key ships now, and the feature
activates the moment `GROQ_API_KEY` appears in the environment. The hard constraint is that a
missing key must be a *non-event* for the rest of the app:

- **Treated as an absent optional provider, not an error.** `settings.groq_api_key` is
  `str | None = None`, exactly like `finnhub_api_key`/`alpha_vantage_api_key`/`gemini_api_key`
  already are — the app boots, the scheduler starts, and every existing route behaves
  identically whether or not the key exists. Nothing about Groq is on any startup path.
- **Nothing scheduled ever touches it.** The forecast pass is on-demand-only by design (point 5
  below), so there is no background job that could fail, retry, or pollute `job_runs` while the
  key is missing. This is the main reason the standby costs nothing.
- **A capability flag, not a mystery 500.** `groq_client` reports availability from the presence
  of the key; `GET /status` gains a small `features` map (e.g. `{"forecast": false}`) so the
  frontend can *disable* the "Generate Forecast" button with a plain "Groq API key not
  configured" tooltip instead of offering an action that cannot work. If the endpoint is called
  anyway, it returns a clear `503` with that same message — the same never-silent-failure
  posture as quota exhaustion (FR-16), just a different cause.
- **The migration ships anyway.** `ALTER TYPE providername ADD VALUE 'groq'` and the
  `price_forecasts` table are created now: they're inert without a key (an unused enum value and
  an empty table cost nothing), and deferring them is precisely how Phase 4's `gemini` enum bug
  happened. Migrations round-trip regardless of key state.
- **The test suite must not know the difference.** Groq tests mock the client like every other
  provider's, plus one explicit test for the key-absent path (`503`, clear message, no
  `provider_call_log` row written) so "works without a key" is asserted, not assumed.
- **Honest deviation from this project's derisk-first habit.** Every other provider/prompt here
  was validated live before code was written around it (Phase 0's Gemini prompt, `/stock/candle`,
  `outputsize=full`, `/company-news`). Groq's client and prompt are being written *without* that
  check because the key isn't obtainable — so `prompts/forecast_prompt_v1.md` and the response
  parsing are **unvalidated assumptions until the deferred derisk run happens** (point 6 below).
  Expect the first real run to need prompt/parsing adjustment; that's the price of building it
  out of order, and it's acceptable only because nothing else depends on this feature.

The design below is unchanged from the original plan — it's what gets activated, not rewritten,
once a key exists.

A second, fully independent free-tier LLM (**Groq**, Llama free tier — fast, generous free
quota) added specifically to go deeper than the single-target Gemini verdict: for a given
ticker, produce an **expected low/high price band at each of 30/60/90/180/360 days**, rather
than one point-in-time buy/hold/sell call. Deliberately a second, separate model rather than
asking Gemini to do this too — the value is an independently-reasoned second read, and keeping
it on a wholly separate provider/quota means it can never compete with or starve the primary
verdict/critique pipeline's Gemini budget.
1. `forecast_service.build_forecast_prompt(ticker)` calls the same shared
   `wiki_service.assemble(ticker)` used by every other AI pass — same traceability guarantee:
   Groq never reasons over data the user can't also see.
2. Renders `prompts/forecast_prompt_v1.md`, schema-forced JSON, requesting **all five horizons
   in one call** (`{forecasts: [{horizon_days, expected_low, expected_high, confidence,
   rationale}]}`) rather than five separate calls — five calls would cost five times the quota
   for output the model can reason about more coherently side by side anyway. Confidence is
   per-horizon, not one number for the whole set.
3. `providers/groq_client.py` follows the exact same interface/retry/rate-limit/circuit-breaker
   pattern as `finnhub_client.py`/`alpha_vantage_client.py`/`gemini_client.py` — one more
   provider, not a special case. **That sameness has a concrete prerequisite:** the rate
   limiter, circuit breaker, and `provider_call_log` all key off the `providername` enum, which
   exists in both Python and Postgres. Adding Groq means a migration
   (`ALTER TYPE providername ADD VALUE 'groq'`) alongside the Python enum member — Phase 4
   shipped the Python half for Gemini without the SQL half and the first rate-limiter check
   died immediately. Cheap to get right, guaranteed to break if skipped.
4. Stored as new `price_forecasts` rows, append-only (one row per horizon per generation,
   never overwritten), same philosophy as `ai_analyses`.
5. **On-demand only, watchlist-tickers only** — same quota-protection gating as the critique
   pass (never scheduled, never available for lookup-tier tickers), surfaced as a "Generate
   Forecast" button on the wiki page rendering a per-horizon low/high panel. While the key is
   missing, that button renders disabled with the "not configured" tooltip rather than being
   hidden — the feature is visibly on standby, not silently absent.
6. **Derisk standalone — deferred, not skipped.** The Phase 0/Gemini habit still applies: a
   small script (`scripts/test_groq_prompt.py`, mirroring `scripts/test_gemini_prompt.py`)
   against a real wiki fixture, confirming Groq returns real, sensibly-varying low/high numbers
   per horizon rather than a refusal or five copies of the same band. **This cannot run until a
   key exists**, so it becomes the *first* task of activation rather than a prerequisite of
   construction — the one place where the standby genuinely inverts this project's normal
   ordering. The script ships now so activation is a single command; do not treat the forecast
   feature as working until it has been run and its output reviewed.
7. **Future connection, not required now**: once this exists, the portfolio income projection
   below could optionally blend Groq's horizon-matched high/low into its expected-profit math
   instead of relying solely on Gemini's single price target — intentionally deferred so the
   two features ship independently first.

### Grounded chat (built, post-Phase-5)
A `/chat` route backed by `POST /chat` + `GET /chat/messages` and a linear `chat_messages` table
(single-user, no multi-conversation concept). The design decision worth recording here is the
grounding rule: **every reply is grounded in the `wiki_service.assemble()` data of the companies
the user actually tracks, and nothing else** — never Gemini's general world knowledge, never a
live market-wide scan. Ask about an untracked company and it says so and names tracked
alternatives. This is the same traceability guarantee the verdict pipeline has, applied
conversationally: the AI can only talk about what the user can also see on a wiki page.

Chat runs on its own lowest-priority slice of the Gemini budget
(`gemini_chat_budget_fraction`, 0.2) so casual conversation can never starve scheduled
watchlist analyses, on-demand verdicts, or critiques. Note the interaction with the benchmark
design below: grounding on "every tracked company" is precisely why a benchmark ticker needs to
be excluded from the tracked set rather than just promoted.

#### Source citations per reply (user request, 2026-08-05)
Every chat answer should show **which articles it drew on**, so a claim in the chat panel is
checkable the same way a verdict's `cited_sources` chips already are. This is the natural
completion of the grounding guarantee: grounding currently promises the AI *could only* have used
visible data; citations show *which* visible data it actually used, per answer.

- **The model never supplies the URL.** This is the whole design decision. Articles are already in
  the prompt via each company's `recent_news` (headline/summary/source/published_at/sentiment/url,
  6 most recent per company). Each one is stamped with a short **reference id** (`[N1]`, `[N2]`, …)
  when the prompt is assembled; the model cites those ids, and `chat_service` resolves each id back
  to the real `news_articles` row server-side. A model-authored URL is exactly the kind of thing an
  LLM invents convincingly — plausible domain, plausible slug, 404. Resolving ids server-side makes
  a fabricated citation *structurally impossible* rather than merely discouraged: an id that isn't
  in the map is dropped and logged, never rendered as a link.
- **Not every claim comes from an article.** Prices, computed technicals, AI verdicts, and the
  user's own position are also grounding data, and a reply about "you're up 12% since your cost
  basis" has no article behind it. So citations follow the verdict pipeline's existing shape —
  typed entries (`news|price|verdict|metric|position`), with `news` being the only type that
  carries a resolved URL. Forcing everything into "article" would just teach the model to
  mis-attribute price facts to whatever headline was nearby.
- **Same call, one extra output field** — `chat_prompt_v2.md` (new file, v1 kept per NFR-5) returns
  `{reply, cited_sources[]}` instead of `{reply}`. No second Gemini call, so the chat budget slice
  is unaffected; this is close to free.
- **Persisted, not recomputed.** `chat_messages` gains a nullable `cited_sources` JSONB column
  (assistant rows only), mirroring `ai_analyses.cited_sources`, so reopening `/chat` shows the same
  chips it showed originally rather than losing them on reload.
- **An empty citation list is a legitimate answer, not a bug.** The grounding refusal path ("I can
  only discuss X, Y, Z") has nothing to cite, and free-tier news coverage is genuinely patchy
  (Finnhub withholds `/company-news`; the Alpha Vantage `NEWS_SENTIMENT` fallback doesn't cover
  every ticker), so some tracked companies have zero articles. The rule is that a reply must cite
  what it used and must not manufacture an article when the answer came from price/verdict data —
  rendered honestly in the UI as "based on price and verdict data — no articles available for this
  company" rather than an empty chip row that looks broken.

### Portfolio income projection
The user's existing `holdings` (shares + cost basis, one row per company — not tax lots) plus the
latest `ai_analyses` row per company
already contain everything needed to answer "what would I make if I sold within
30/60/90 days" — no new AI call required, this is pure computation over data already collected.
- `portfolio_projection_service.compute_projected_income(holdings, horizon_days)`: for each
  holding, expected profit = `(price_targets.sell_at_or_above - cost_basis_per_share) *
  shares`, using the latest `ai_analyses` row for that company.
- **Bucketing rule**: a holding counts toward horizon *H* only if its own AI-suggested
  `hold_period_days.min` is ≤ *H* — i.e., only if the AI itself thinks the target is reachable
  within that window. If `hold_period_days.min > H`, or there's no sell target, or no analysis
  exists at all, the projection for that horizon is `null` with an explicit reason string
  ("AI suggests holding longer than this horizon" / "no AI sell target" / "not yet analyzed")
  — never silently zeroed or omitted, consistent with how null price targets are already
  rendered elsewhere in the UI.
- One endpoint (`GET /portfolio/projected-income`) serves all three of the user's requested
  views — whole portfolio, one stock, or an arbitrary selected subset — via an optional
  `tickers` filter, summing eligible holdings for the aggregate.

### Ticker directory (local autocomplete)
The existing `/search` route's `GET /companies/search` proxies Finnhub's live search API —
fine for occasional deliberate lookups, but wrong to reuse for a type-ahead dropdown that fires
on every keystroke while adding a holding, since that would burn Finnhub's free-tier search
quota on typing rather than genuine lookups. Instead:
- **Confirm the bulk endpoint is actually free before writing ingestion code** — the same habit
  applied to Gemini in step 0, to `outputsize=full`, to `/stock/candle`, and to the fundamentals
  endpoints below. This project's free-tier assumptions have been wrong three times already
  (Finnhub rejected `/company-news` and `/stock/candle`; Alpha Vantage gated `outputsize=full`),
  and `/stock/symbol?exchange=US` is one more unverified assumption of exactly that shape. One
  real call settles it. If it's gated, Alpha Vantage's `LISTING_STATUS` (CSV of active US
  symbols) is the fallback — a weekly bulk pull sits comfortably inside even AV's small daily
  budget, unlike anything on the refresh cadence.
- A new `ticker_directory` table, bulk-populated from whichever of those the check confirms,
  refreshed weekly (APScheduler + `POST /internal/refresh-ticker-directory`,
  same dual-trigger pattern as every other job).
- `GET /tickers/search?q=` searches this local table only (ILIKE/trigram — if trigram, the
  migration creates `pg_trgm`; it isn't on by default) — zero live provider calls, safe to call
  on every keystroke.
- The Add Holding form's dropdown is backed by this endpoint but never a hard gate: a ticker
  absent from the directory (newly listed, OTC, etc.) can still be typed manually and resolves
  through the existing lookup/promote path exactly as before.

### Observability (provider budget visibility + verdict-change diff)
Two cheap additions using data the app already collects, no new tables or providers:
- **Budget dashboard**: `rate_limiter.py` already computes sliding-window call counts per
  provider from `provider_call_log` on every check — expose that same computation as
  `GET /status/budget` (used-today vs. configured limit for Finnhub/Alpha Vantage/Gemini/Groq)
  so quota exhaustion is visible in Settings *before* a request gets rejected, not only after.
  Providers with no API key configured (Groq today) report an explicit **"not configured"** state
  rather than a 0-of-N usage bar — a zero bar reads as "plenty of quota left" when the truth is
  "this provider can't be called at all", which is exactly the kind of silent misreport NFR-4
  exists to prevent.
- **Verdict-change diff**: `ai_analyses` is already append-only, one row per generation — a
  small function comparing the latest row to the immediately-preceding one for the same
  company (verdict changed? confidence delta? price-target deltas? hold-period changed?) turns
  the existing history into a "what changed since last time" callout, attached to the existing
  `GET /companies/{ticker}/analyses` response rather than a new endpoint. **This is the same
  computation the alerts feature's `verdict_change` trigger needs**, so it's one shared function
  called from both places — the diff endpoint returns the whole thing, the alert path reads the
  verdict-flip field off it. Built here (it's the cheaper of the two) and reused there.

### Data retention (price_bars pruning)
Flagged as a risk since Phase 3 and never built: `"5m"` bars from the live-quote poller
accumulate fast (one row every ~20s while a company page is open) while `"1d"` bars accumulate
slowly and are the valuable long-term history. A `retention_service.prune_price_bars()` job
deletes `"5m"` rows older than a configured `price_bars_retention_days`, never touching `"1d"`
rows, wired through the same dual-trigger (cron + APScheduler) pattern as every other job —
cheap insurance against Neon's free storage cap before it ever actually binds.

### Fundamentals ingestion (resuming a table that was already speced, never built)
The `fundamentals` table has been in this plan's Data Model since the beginning — Phase 4
deliberately deferred implementing it (see spec.md's Phase 4 scope-decision note), leaving
`financials_summary_last_4_periods` an honest empty array in every verdict prompt since. This
closes that gap:
- Source is Alpha Vantage (`OVERVIEW`/`INCOME_STATEMENT`/`BALANCE_SHEET`/`CASH_FLOW`) — same
  provider already relied on for price fallback, news fallback, and historical backfill.
- **Derisk live first, same habit as the historical-backfill addition**: confirm these
  endpoints are actually free-tier accessible (not premium-gated) before writing any ingestion
  code — Alpha Vantage has already surprised this project once (`outputsize=full` turned out to
  be premium-only).
- **Deliberately low-frequency**: fundamentals change quarterly, so refresh on
  watchlist-promote plus a monthly scheduled re-check — never on the 15-30 min price/news
  cadence — to avoid this feature quietly draining Alpha Vantage's small daily budget, which is
  reserved as an emergency fallback, not a load-shared partner (see "Deployment Decision").

### Alerts (in-app feed, optional Web Push extension)
- **In-app feed**: after each scheduled refresh/analysis cycle, `alert_service.evaluate_alerts()`
  checks the latest daily bar against the stored `sell_at_or_above`/`stop_loss` targets and
  reuses the shared verdict-diff function above to see whether the verdict direction just
  changed, writing a new `alerts` row per newly-triggered condition. At most one *open*
  (unacknowledged) alert per `(company, alert_type)` — re-checking doesn't spam duplicates,
  acknowledging clears it. `GET /alerts` + `POST /alerts/{id}/acknowledge` back a bell-icon feed
  in the nav. Benchmark-only watchlist rows are skipped — they have no verdicts or targets.
- **Price crossings are checked against the daily bar's `high`/`low`, not its `close`** — a
  detail worth stating because getting it wrong is silent. A scheduled cycle only ever has one
  `"1d"` bar per company per day to work with (the `"5m"` bars come from the frontend's
  live-quote poll, which only runs while someone has a company page open, deliberately, to
  protect the free quote budget). Checking `close` alone would miss any stop-loss breached at
  midday that recovered by the close — the exact case you'd most want to know about. `high`/`low`
  are already in the row being written, so this costs nothing.
- **Accepted limitation**: even so, alerts are day-resolution. Nothing fires *while* a target is
  being crossed, only once the day's bar reflects it. That's consistent with everything else here
  (15–30 min refresh cadence, no trade execution, explicitly not day-trading) and isn't worth
  building a live price-watching process to fix.
- **Web Push extension (optional, sequenced after Phase 7)**: genuinely free (VAPID, no paid
  push service) but depends on Phase 7's service worker existing first to add a push event
  handler — a `push_subscriptions` table + `push_service.py` sends an OS-level notification
  whenever a new alert is created. Browser support (notably iOS Safari) is newer/patchier than
  desktop — treat as best-effort, the in-app feed is the reliable fallback, never the other way
  around.

### Backtest vs. benchmark (extends verdict track record)
`verdict_outcomes` already stores, per analysis, whether the verdict was directionally correct
at a fixed horizon — this turns that into an actual strategy comparison: "if I'd bought every
`buy` verdict at its verdict-time price and exited at horizon (or at its sell target, if hit
first), what would my aggregate return have been, versus just holding a benchmark ticker (default
SPY) the whole time?" Requires designating one or more **benchmark tickers that get
watchlist-level continuous price tracking regardless of whether the user holds them**, purely so
their `price_bars` history exists to compare against. `GET /verdicts/backtest?benchmark=SPY`
breaks the comparison down by confidence bucket, same as the existing track-record endpoint.

**A benchmark must be price-tracked and nothing else**, which needs an explicit
`watchlist.is_benchmark` flag rather than just calling `promote()` on SPY. Watchlist membership
has accreted five consequences over the phases, and a benchmark should inherit exactly one of
them: it *does* get scheduled price refresh and one-time historical backfill; it must *not* get
the `initial` AI analysis fired by `promote()`, the recurring scheduled analysis, a card in
`GET /watchlist` (the dashboard grid), inclusion in `chat_service`'s grounding set (which today
grounds every reply in *every* tracked company), or alert evaluation. Skipped, SPY would spend
real Gemini quota every single day on an index the user doesn't hold, and would quietly dilute
every chat answer — a good example of a "free" reuse of existing machinery that isn't free at all.

The comparable window is bounded by how much benchmark history exists: the one-time Alpha Vantage
backfill gives ~100 trading days from whenever the benchmark starts being tracked
(`outputsize=full` is premium-gated, confirmed live earlier in this project), so the endpoint
reports the window it actually covered and excludes verdicts predating it rather than comparing
them against nothing.
**Explicitly a simplified historical simulation, not a trading engine**: no fees/slippage, one
historical path (not Monte Carlo), and it says nothing about future performance — framed as an
honesty check on past verdicts, the same spirit as `verdict_outcomes` itself, not a backtest a
quant fund would rely on.

### Two-tier coverage (watchlist vs. any-company lookup)
- `lookup_service.get_or_fetch(ticker)`: if `companies` has a fresh-enough row, serve straight
  from Postgres; otherwise do **one** fetch-with-fallback pass (profile + latest bars + recent
  news), upsert, regenerate `wiki_sections` (template-based, no AI call), and return the page.
  This ticker is *not* added to `watchlist` and gets no recurring job — it just goes stale
  until re-viewed or promoted.
- `POST /watchlist/{ticker}/promote` inserts into `watchlist` and immediately triggers a
  refresh + an `initial`-trigger AI analysis, reusing the identical service functions as
  scheduled runs.

### Testing
- Unit tests: provider response parsers against recorded fixture JSON (`respx`/`responses`,
  no live network), prompt-assembly and verdict-parsing logic with mocked Gemini responses,
  rate-limiter/circuit-breaker state machines as pure logic tests.
- Integration tests: real Postgres (local Docker / CI), covering upsert idempotency (refresh
  run twice → no duplicate rows), `wiki_service.assemble()` against seeded fixtures, and
  watchlist promote/demote transitions.
- CI (GitHub Actions) runs both suites on every push; nothing depends on live third-party APIs
  being reachable.

## Frontend (React + Vite PWA)

### Stack
Vite + React + TypeScript, React Router, **TanStack React Query** for all server state,
Tailwind CSS for the dark-mode-first design system, `vite-plugin-pwa` for manifest/service
worker.

### Routes
`/login` (single shared-password gate) · `/` dashboard (watchlist grid, category filter chips,
portfolio allocation donut, recent verdict-change feed) · `/search` · `/company/:ticker` (the wiki
page — same component for watchlist and on-demand lookups, tier differences are data-driven not
route-driven) · `/portfolio` (holdings + gain/loss, later the income-projection panel) · `/chat`
(grounded AI chat) · `/compare` (2–5 tickers, normalized overlay + peer fundamentals) ·
`/settings`.

**Built as of the post-Phase-5 additions:** everything except `/compare` (waits on Phase 6's
chart components) and `/settings`. `/settings` was an oversight rather than a deferral — it's
referenced by the PWA install prompt below and by the provider-budget dashboard, but no phase ever
scheduled building it, so it's now the first task of the observability work in spec.md.

### Charts
- **`lightweight-charts` (TradingView, free)** for everything on a synced time axis:
  candlestick + volume, SMA/EMA/Bollinger overlays, RSI/MACD sub-panes, normalized
  stock-vs-benchmark comparison, and AI-verdict markers plotted directly on the price
  timeline. Chosen because it's purpose-built for exactly this and gives multi-pane sync
  (crosshair/zoom/pan) other libraries would require significant custom work to replicate.
- **Recharts** for non-time-series/comparative charts: quarterly revenue/earnings bars, EPS
  and P/E trend, news-sentiment-over-time, portfolio allocation donut, peer comparison bars.
- Chart color palettes/series-color assignment are implementation-time work — consult the
  **`dataviz` skill** when writing that code, not specified in this plan.

### Company wiki page layout (the core differentiator)
1. Infobox header (name/ticker/logo/price/sector tags + freshness indicator + action bar:
   Analyze with AI / Add-Remove Watchlist / Compare).
2. **AI verdict banner** directly below — large buy/hold/sell badge, one-paragraph rationale,
   confidence, a compact buy/sell/stop-loss price-target strip with the suggested hold period
   (rendered as null/dashes rather than hidden when the model didn't set them), cited source
   chips, and a "Get Second Opinion" button that triggers the adversarial critique pass and
   renders its result (agreement/disagreement, the named weakness, any revised numbers) inline
   below the original verdict rather than replacing it — the point is to show both takes, not
   silently overwrite one with the other. For never-analyzed lookup tickers this becomes an
   "Analyze with AI" call-to-action instead of a badge. Deliberately the *second* thing on the
   page, not buried.
3. Price chart panel (timeframe selector, candlesticks + volume, overlay toggles, RSI/MACD
   sub-panes collapsible on mobile, benchmark-compare toggle, verdict markers).
4. Overview (encyclopedia-style description) → Key Metrics (stat tiles) → Financials (bar
   charts) → Recent News (+ sentiment chart) → AI Analysis History (full verdict timeline,
   each expandable) → Risks/Notes.

Each section fetches/loads independently (own React Query key, own skeleton) so one slow
section never blocks the rest of the page.

### PWA / mobile
- `vite-plugin-pwa` manifest: `display: standalone`, icons incl. maskable, dark theme colors.
- Service worker (Workbox `generateSW`): app shell `StaleWhileRevalidate`; wiki/price/news/AI
  API responses `NetworkFirst` with short timeout + offline fallback to cache; static
  logos/images `CacheFirst`; mutation calls (watchlist add, analyze) excluded from caching and
  clearly toast "offline, will retry" instead of silently no-opping.
- Custom "Install app" prompt (capture `beforeinstallprompt`) surfaced in Settings + a one-time
  dashboard banner; iOS gets an instructional "Add to Home Screen" card since it has no
  programmatic install API.
- Mobile-first responsive layout: bottom tab bar on phone / left nav rail on desktop, RSI/MACD
  panes collapse to an accordion on narrow screens, dashboard grid collapses to a single-column
  card list, ≥44px touch targets throughout.

### Data fetching
React Query with one query key per resource (`['company', ticker, 'prices', timeframe]` etc.)
so sections load/cache independently; every response's backend `last_fetched_at` combined with
React Query's own cache metadata drives a `FreshnessIndicator` ("Live" / "Updated 4m ago" /
"Cached (offline)" / "Stale"). Optimistic updates for watchlist add/remove; honest
loading-not-optimistic state for "Analyze with AI" since it's a real async call.

## Suggested Build Order

0. **Derisk the Gemini verdict prompt, before anything else is built.** Whether Gemini's free
   tier will actually return a real buy/hold/sell verdict (vs. refusing or hedging like a
   consumer chatbot) is an assumption the entire AI pipeline depends on — cheaper to falsify now
   than after the DB schema and `ai_service` are built around it. `prompts/verdict_prompt_v1.md`
   is the versioned template (framed as a private single-user tool, schema-forced JSON output via
   Gemini's `response_schema`); `scripts/test_gemini_prompt.py` runs it standalone against two
   fixtures (`scripts/fixtures/sample_wiki_data.json` — normal case, `sample_wiki_thin.json` —
   thin/contradictory data) with zero dependency on Postgres/FastAPI. Get a Gemini API key, run
   the script a handful of times per fixture, and confirm: verdicts actually vary (not always
   "hold"), confidence tracks data quality, and the thin-data case produces an honest
   low-confidence "hold" rather than a refusal or false confidence. If this fails, it's cheaper to
   adjust the prompt framing or reconsider Gemini's suitability now than after step 4.
1. **Backend skeleton**: DB models + Alembic migrations, FastAPI app boot, Finnhub client
   only (no fallback yet), basic `/companies/{ticker}/wiki` returning real price/profile data
   for one hardcoded ticker. Verify against a local Postgres via Docker.
2. **Wiki assembly + lookup tier**: `wiki_service.assemble()`, `lookup_service` on-demand
   fetch, `wiki_sections` generation (template-based, no AI yet). Verify by looking up several
   arbitrary tickers end-to-end.
3. **Watchlist + scheduler**: `watchlist` CRUD, APScheduler + `/internal/refresh`, Alpha
   Vantage fallback, rate limiter/circuit breaker, `provider_call_log`/`job_runs`. Verify by
   watching scheduled refreshes populate Postgres over time.
4. **AI pipeline**: Gemini client, prompt template, `ai_analyses` storage, budget/priority
   logic. Verify by triggering on-demand analysis on a few tickers and inspecting
   `context_snapshot` matches the wiki page shown.
5. **Frontend core**: routing, React Query setup, dashboard + company wiki page (static
   sections first, no charts), auth gate. Verify against the running local backend.
5.4. **Categories, holdings, near-live chart, grounded chat** — four user-requested features
   built after Phase 5 and before the planned visual design pass, in the user's chosen
   cheapest-first order. Sector→category taxonomy wired additively into the existing assemble/
   list functions; `holdings` (shares + cost basis only) plus a position-aware
   `verdict_prompt_v2.md`; a `"5m"` `price_bars` interval aggregated from repeated `/quote` polls
   (confirmed live first that Finnhub's free tier withholds `/stock/candle`), driving a
   `lightweight-charts` candlestick panel that covers part of what Phase 6 had scoped; and the
   grounded chat described above. See spec.md's "Post-Phase-5 Addition" for the task-level record.
5.5. **Portfolio income projections, second-LLM (Groq) multi-horizon forecasts, ticker
   directory autocomplete** — three user-requested features added after Phase 5 shipped and
   before Phase 6 starts; see "Second AI provider (Groq)", "Portfolio income projection", and
   "Ticker directory" subsections above for design, and `spec.md`'s "Post-Phase-5 Addition #2"
   for the concrete task list. Built cheapest/lowest-risk first: ticker directory (no AI, no
   quota risk) → income projection (pure computation over existing data) → Groq forecast
   (new provider, new prompt, highest complexity) — same ordering habit as every prior
   multi-feature addition in this project. **The Groq step ships dormant** (no API key
   obtainable as of 2026-08-05): its infrastructure is built and merged, the feature stays
   switched off behind the missing key, and the addition counts as complete without it being
   live. Activation — drop the key in `.env`, run the deferred derisk script, verify — is
   tracked separately so it never blocks Phase 6.
5.6. **Observability, data retention, fundamentals, alerts, backtest-vs-benchmark** — a second
   round of user-requested additions, also sequenced cheapest-first: budget dashboard +
   verdict-change diff (pure UI over existing data) → `price_bars` retention → alerts in-app
   feed → backtest vs. benchmark → fundamentals ingestion (needs a live derisk check first,
   like step 0's Gemini derisking) → alerts' Web Push extension (deferred until step 7's
   service worker exists). See the subsections above and spec.md's "Post-Phase-5 Addition #3"
   for full detail.
5.7. **Chat source citations** — each chat reply shows the articles it drew on (see "Source
   citations per reply" above). Small and self-contained: one new prompt version, one nullable
   column, one migration, and a chip row in the chat UI. Deliberately **independent of 5.5 and
   5.6** — it touches only `chat_service`/`chat_messages`/`ChatPage`, so it can be built before,
   after, or between them without reordering anything. See spec.md's "Post-Phase-5 Addition #4".
6. **Charts**: lightweight-charts price panel + indicators, Recharts fundamentals/sentiment/
   allocation. Verify visually against real data for a few tickers.
7. **PWA + responsive polish**: manifest/service worker, mobile layout, install flow. Verify by
   installing on an actual phone browser and testing offline behavior.
8. **Deploy**: Neon (DB) → Render (backend) → GitHub Actions cron (heartbeat) → static host
   (frontend). Verify by killing your laptop and confirming data still refreshes and the phone
   PWA still loads fresh data the next day.

## Verification

- **Unit/integration tests** (`pytest`) run locally and in CI on every push — parsers, prompt
  assembly, rate-limiter/circuit-breaker logic, upsert idempotency, wiki assembly.
- **Local end-to-end**: `docker compose up` (Postgres + backend), run the frontend dev server
  against it, manually walk: search a random ticker → verify a wiki page renders with real
  data → add to watchlist → trigger on-demand analysis → verify verdict banner + history
  appear and match `context_snapshot`.
- **Reliability drill**: temporarily point the Finnhub client at an invalid API key/URL and
  confirm the circuit breaker trips and Alpha Vantage fallback kicks in without crashing a
  refresh cycle, and that `job_runs`/Sentry surface the failure instead of hiding it.
- **Post-deploy check**: confirm `GET /status` shows recent successful `job_runs` after
  waiting through a couple of GitHub Actions cron cycles with the laptop closed, then open the
  PWA from a phone on cellular data (not home wifi) to confirm it's genuinely
  internet-accessible and installable.

## Key risks/tradeoffs (flagged, not blockers)
- Gemini may refuse or hedge on a direct verdict rather than returning buy/hold/sell, similar to
  consumer-chatbot safety behavior — mitigated by prompt framing (private single-user tool,
  schema-forced JSON) and derisked explicitly in build-order step 0 before the rest of the AI
  pipeline is built around the assumption that it works.
- Render free-tier cold start: 10–30s on the first request after a long idle period.
- Alpha Vantage's free daily cap is small — fallback-only, never a routine parallel source.
- Gemini free-tier limits mean heavy on-demand usage in a single day could hit "try again
  later" — scheduled watchlist analyses are prioritized so this mainly affects ad-hoc lookups.
- Neon/Supabase free storage caps are unlikely to bind soon at this scale, but a price-bar
  retention/pruning policy is cheap insurance worth building in from day one.
- **No Groq API key is obtainable right now (2026-08-05), so the forecast feature ships
  unvalidated.** Its client, prompt, and response parsing are written without the live derisk run
  every other integration in this project got first — meaning `forecast_prompt_v1.md` and the
  JSON parsing around it are assumptions, not verified behavior, and the first real call may well
  need adjustment. Mitigated by scope, not by cleverness: the feature is on-demand-only and
  key-gated, so while it's dormant it cannot break, slow, or degrade anything the app already
  does; and the deferred derisk script is written now so activation starts with verification
  rather than with hope. The residual risk is wasted work if Groq turns out to be unsuitable —
  accepted deliberately, since the alternative is leaving the whole addition unbuilt.
- **A key-gated feature can rot quietly.** Because nothing exercises Groq while the key is
  missing, its client could drift out of step with the shared provider interface (or with Groq's
  own API) without any failing test noticing — the standby's one real cost. Mitigated by holding
  Groq to exactly the same mocked-provider test coverage as every other client, so interface
  drift breaks the suite even with no key present.
- Groq's free-tier model lineup drifts/deprecates over time, the same class of risk already
  seen with Gemini model aliasing — mitigated the same way (a config knob, not a hardcoded
  model id, and the exact model stamped into each `price_forecasts` row). Sharper here than for
  Gemini: whatever model id gets written into config today is picked from documentation rather
  than a live call, so it should be re-checked as part of activation, not trusted.
- The multi-horizon forecast is a **second independently-reasoned opinion, not a validated
  forecasting model** — like the Gemini verdict, its 180/360-day numbers in particular are
  heuristic synthesis with no backtesting behind them yet. Treat it the same way the existing
  "AI's investment judgment is unproven" risk (below) treats the verdict: a research input, not
  a trusted number, until real elapsed time lets it be checked against actual prices.
- **A chat citation the user can click is a claim the app is making on its own behalf** — if the
  model authored the URL, that claim can be a convincing fabrication (real-looking domain, dead
  link). Mitigated structurally, not by prompt wording: the model cites prompt-assigned reference
  ids and the backend resolves them against the `news_articles` rows it actually sent, dropping
  unrecognized ids. Worth stating as a standing rule for any future feature that renders
  model-produced links.
- **Chat citations are only as good as free-tier news coverage.** Finnhub's free tier withholds
  `/company-news` and the Alpha Vantage `NEWS_SENTIMENT` fallback doesn't cover every ticker, so
  some tracked companies have no articles at all and their answers will legitimately cite price or
  verdict data instead. Not a defect to engineer around — but it does mean "show me the articles"
  will sometimes honestly answer "there aren't any for this company", and the UI has to say that
  plainly rather than looking empty or broken.
- Fundamentals ingestion competes for Alpha Vantage's already-small daily budget (also used for
  price fallback, news fallback, and historical backfill) — mitigated by making it deliberately
  low-frequency (promote-time + monthly, never the main refresh cadence), but worth watching if
  AV's free cap ever tightens further.
- The backtest-vs-benchmark feature is a simplified historical simulation (no fees/slippage,
  single historical path), not a validated trading strategy — same "research input, not a
  trusted number" framing as the verdict/forecast risks above, just applied to an aggregate
  instead of a single call. It's also **window-bounded**: the benchmark's own history starts at
  the ~100 trading days the Alpha Vantage compact backfill provides, so early comparisons cover a
  short and correspondingly noisy period. Reporting the covered window is the mitigation;
  deepening it isn't possible on the free tier.
- Web Push notification delivery is best-effort — browser/OS support (especially iOS Safari)
  varies and isn't guaranteed — the in-app alerts feed is the reliable channel; push is a
  convenience layered on top, never the only way an alert surfaces.
- **Price-target alerts are day-resolution, not intraday.** A scheduled cycle has one `"1d"` bar
  per company per day to reason about; `"5m"` bars only exist while a company page is open in a
  browser, by design. Checking the bar's `high`/`low` rather than its `close` recovers same-day
  breaches that retraced — most of the gap, for free — but nothing can fire *while* a target is
  being crossed. Consistent with the rest of the system's cadence and with trade execution being
  explicitly out of scope; it would only matter if this became an execution tool, which it won't.
- **Every new provider touches two enums, not one.** `providername` exists in both the Python
  models and the Postgres schema, and the rate limiter, circuit breaker, and `provider_call_log`
  all key off it. Phase 4 added Gemini to the Python enum, forgot the `ALTER TYPE`, and the first
  rate-limiter check failed outright. Groq will hit the same wall unless the migration ships with
  the client — now an explicit task in spec.md rather than an assumption.
