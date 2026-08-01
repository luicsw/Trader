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

This plan combines two independent designs (backend/data/infra and frontend/UX) into one
buildable architecture, greenfield (repo is currently empty).

## Architecture Overview

```
 GitHub Actions (cron, free) ──POST /internal/refresh──▶ FastAPI backend (Render free) ──▶ Postgres (Neon free)
                                     every 15-30 min               │
 GitHub Actions (cron, free) ──POST /internal/analyze-scheduled──▶ │
                                     daily                          ├─▶ Finnhub (primary data)
                                                                     ├─▶ Alpha Vantage (fallback data)
                                                                     └─▶ Gemini (AI reasoning, free tier)

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
  `last_scheduled_refresh_at`, `last_scheduled_analysis_at`, `active`).
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
  (buy/hold/sell), `confidence`, `reasoning_text`, `cited_sources` (JSONB), `context_snapshot`
  (JSONB — the exact dict sent to Gemini, kept for reproducibility), `trigger`
  (`scheduled|on_demand|initial`), `generated_at`. Indexed `(company_id, generated_at DESC)`.
- `provider_call_log` — append-only ledger per external call (`provider`, `status`,
  `called_at`) backing the rate limiter and circuit breaker, and doubling as an audit trail.
- `job_runs` — background job observability (`job_name`, `status`, `error_message`,
  `attempt`) so failures are visible, never silent.

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
   available to avoid brittle text parsing).
3. Call wrapped in the same retry/backoff + rate-limit-bucket pattern as the data providers,
   budgeted below Gemini's free RPM/RPD limits with headroom.
4. On quota exhaustion: scheduled analysis just skips the cycle (next day's run retries); an
   on-demand request gets a clear "AI quota reached, try later" response — never a silent
   failure or a generic 500.
5. Result stored as a new `ai_analyses` row (append-only history, not overwritten).
6. **Budget priority**: scheduled watchlist analyses (small, predictable) get priority over
   unbounded on-demand lookup analyses, which are rejected gracefully once the daily budget is
   spent.

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
`/login` (single shared-password gate) · `/` dashboard (watchlist grid, portfolio allocation
donut, recent verdict-change feed) · `/search` · `/company/:ticker` (the wiki page — same
component for watchlist and on-demand lookups, tier differences are data-driven not
route-driven) · `/compare` (2–5 tickers, normalized overlay + peer fundamentals) · `/settings`.

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
   confidence, cited source chips. For never-analyzed lookup tickers this becomes an "Analyze
   with AI" call-to-action instead of a badge. Deliberately the *second* thing on the page, not
   buried.
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
- Render free-tier cold start: 10–30s on the first request after a long idle period.
- Alpha Vantage's free daily cap is small — fallback-only, never a routine parallel source.
- Gemini free-tier limits mean heavy on-demand usage in a single day could hit "try again
  later" — scheduled watchlist analyses are prioritized so this mainly affects ad-hoc lookups.
- Neon/Supabase free storage caps are unlikely to bind soon at this scale, but a price-bar
  retention/pruning policy is cheap insurance worth building in from day one.
