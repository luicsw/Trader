# Personal Investment Research App — Spec & Task Breakdown

**Status:** Phase 0 through Phase 3 complete, Phase 4 not started · **Last updated:** 2026-08-03

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
  `/company/:ticker`, `/compare`, `/settings`.
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

---

## 4. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-1 | Reliability mechanics (FR-1 to FR-7) apply uniformly regardless of trigger source (cron vs. warm process) — refresh/analyze logic lives once in `services/`, called identically by `api/routers/refresh.py` and `jobs/tasks.py`. |
| NFR-2 | Entire stack must run at $0/month: Neon free Postgres, Render free web service, GitHub Actions free cron, Vercel/Netlify free static hosting, Gemini free tier. |
| NFR-3 | Mobile-first responsive: bottom tab bar on phone / nav rail on desktop, ≥44px touch targets, RSI/MACD panes collapse to accordion on narrow screens. |
| NFR-4 | No silent failures anywhere — every failure path (provider, AI, job) is logged to `job_runs` and/or Sentry and surfaced to the user in some form. |
| NFR-5 | Reproducibility: every `ai_analyses`/`ai_critiques` row stores the exact `context_snapshot` sent to Gemini; prompt changes are versioned by filename (`_v2.md`, etc.), never edited in place. |
| NFR-6 | Accepted cold-start tradeoff: first request after Render idle may take 10-30s — never treated as a bug. |

---

## 5. Architecture Summary

```
 GitHub Actions (cron) ──POST /internal/refresh──────▶ FastAPI (Render) ──▶ Postgres (Neon)
 GitHub Actions (cron) ──POST /internal/analyze-scheduled──▶  │                    │
                                                               ├─▶ Finnhub (primary)
                                                               ├─▶ Alpha Vantage (fallback)
                                                               └─▶ Gemini (verdict + critique)

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
| `watchlist` | company_id, refresh_interval_minutes, last_scheduled_refresh_at, last_scheduled_analysis_at, active | FK → companies |
| `price_bars` | company_id, ts, interval, open/high/low/close/volume | UNIQUE `(company_id, ts, interval)`; INDEX `(company_id, interval, ts DESC)` |
| `news_articles` | company_id, headline, summary, url, source, published_at, sentiment | UNIQUE `(company_id, url)` |
| `fundamentals` | company_id, period, fiscal_period, revenue, net_income, eps, margins, fcf... | UNIQUE `(company_id, period, fiscal_period)` |
| `wiki_sections` | company_id, section_key (overview\|financials_summary\|news_digest\|key_metrics\|risks_notes), body, generated_at | UNIQUE `(company_id, section_key)` |
| `ai_analyses` | company_id, verdict, confidence, reasoning_text, **price_targets** (JSONB: buy_at_or_below/sell_at_or_above/stop_loss), **hold_period_days** (JSONB: min/max/note), cited_sources (JSONB), context_snapshot (JSONB), trigger (scheduled\|on_demand\|initial), generated_at | Append-only; INDEX `(company_id, generated_at DESC)` |
| `ai_critiques` | analysis_id (FK → ai_analyses), agrees_with_verdict_direction (bool), biggest_weakness (text), revised_price_targets (JSONB, nullable per field), revised_confidence (nullable float), rationale (text), generated_at | Append-only; always on-demand-triggered |
| `provider_call_log` | provider, status, called_at | Backs rate limiter + circuit breaker; audit trail |
| `job_runs` | job_name, status, error_message, attempt | Never-silent-failure observability |

---

## 7. API Contract

| Method & Path | Purpose | Auth | Notes |
|---|---|---|---|
| `GET /health` | Liveness probe | none | For Render health checks |
| `GET /status` | Recent `job_runs` + provider health summary | shared credential | Post-deploy verification target |
| `GET /companies/search?q=` | Ticker/name search | shared credential | Backs `/search` route |
| `GET /companies/{ticker}/wiki` | Full assembled wiki page (FR-8, FR-9) | shared credential | `last_updated` on every field group |
| `POST /watchlist/{ticker}/promote` | Add to watchlist + trigger initial refresh/analysis (FR-11) | shared credential | Idempotent |
| `DELETE /watchlist/{ticker}` | Remove from watchlist (FR-12) | shared credential | Does not delete history |
| `POST /companies/{ticker}/analyze` | On-demand AI verdict (FR-14) | shared credential | 429-style clear response on quota exhaustion (FR-16) |
| `POST /companies/{ticker}/critique?analysis_id=` | On-demand second opinion (FR-18) | shared credential | Lowest budget priority (FR-20) |
| `POST /internal/refresh` | Cron-triggered refresh for all active watchlist tickers | shared credential | Idempotent, safe no-op if too soon |
| `POST /internal/analyze-scheduled` | Cron-triggered daily scheduled analyses | shared credential | Budget-priority applies (FR-17) |
| `GET /compare?tickers=A,B,C` | Normalized overlay + peer fundamentals data for 2-5 tickers | shared credential | Backs `/compare` route |

---

## 8. AI Prompt Contracts

Both prompt files are versioned by filename, never edited in place (NFR-5), and were validated
standalone in Phase 0 before any backend code was written (see §9).

| File | Purpose | Input | Output schema |
|---|---|---|---|
| `prompts/verdict_prompt_v1.md` | First-pass buy/hold/sell verdict | `wiki_service.assemble(ticker)` dict | `{verdict, confidence, reasoning, price_targets{buy_at_or_below, sell_at_or_above, stop_loss}, hold_period_days{min, max, note}, cited_sources[]}` |
| `prompts/verdict_critique_prompt_v1.md` | Adversarial second opinion on an existing verdict | same wiki dict + the `ai_analyses` row being critiqued | `{agrees_with_verdict_direction, biggest_weakness, revised_price_targets{...}, revised_confidence, rationale}` |

Both are schema-forced via Gemini's `response_schema` (not instruction-only parsing). Standalone
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

### Phase 4 — AI pipeline (verdict + second opinion)
- [ ] T4.1 `providers/gemini_client.py` wrapping `google-genai` with retry/backoff + rate-limit bucket
- [ ] T4.2 `services/ai_service.py::build_prompt(ticker)` rendering `verdict_prompt_v1.md` against `wiki_service.assemble()` (FR-14)
- [ ] T4.3 `ai_analyses` table + write path + budget/priority logic (FR-15, FR-16, FR-17)
- [ ] T4.4 `api/routers/analysis.py`: `POST /companies/{ticker}/analyze`, `POST /internal/analyze-scheduled`
- [ ] T4.5 `ai_critiques` table + `build_critique_prompt()` + `POST /companies/{ticker}/critique` (FR-18, FR-19, FR-20)
- **Verify:** trigger on-demand analysis on a few tickers, confirm `context_snapshot` matches the wiki page shown; trigger critique on one of them and confirm it lands below scheduled/on-demand analyses in budget priority under simulated quota pressure.
- **Open decision before starting (see §11):** should `/critique` be available for lookup-tier tickers too, or watchlist-only?

### Phase 5 — Frontend core
- [ ] T5.1 Vite + React + TypeScript scaffold, Tailwind, React Router, React Query provider
- [ ] T5.2 `/login` auth gate (shared bearer credential, stored client-side)
- [ ] T5.3 Dashboard route — static sections first, no charts (FR-21)
- [ ] T5.4 Company wiki page route — static sections first, AI verdict banner incl. "Get Second Opinion" button (FR-22)
- [ ] T5.5 `/search` route
- [ ] T5.6 Per-section independent query keys + skeletons (FR-23), `FreshnessIndicator` (FR-24)
- **Verify:** exercise all routes against the running local backend.

### Phase 6 — Charts
- [ ] T6.1 `lightweight-charts` price panel: candlestick+volume, SMA/EMA/Bollinger overlays, RSI/MACD sub-panes, benchmark-compare toggle, verdict markers
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
| 1 | Should `POST /companies/{ticker}/critique` be available for lookup-tier (non-watchlisted) tickers, or restricted to watchlist tickers only, as an extra layer of quota protection beyond the existing budget-priority ordering? | **Unresolved** — decide before Phase 4 |
| 2 | Gemini model id drifts as Google deprecates versions (`gemini-2.0-flash` and `gemini-2.5-flash` both already dead ends as of 2026-08-02). Current default is the `gemini-flash-latest` alias. | Monitor — re-check alias behavior when Phase 4 backend code is written, since backend retry/budget logic may want an explicit pinned version instead of a moving alias for reproducibility (tension with NFR-5). |

## 12. Key Risks (carried from `plan.md`, condensed)

- Gemini may refuse/hedge instead of giving a verdict — mitigated by framing, derisked in Phase 0.
- Render free-tier cold start (10-30s) — accepted (NFR-6).
- Alpha Vantage free daily cap is small — fallback-only, never load-shared.
- Gemini free-tier limits mean heavy on-demand + critique usage in one day could hit "try again
  later" — budget-priority ordering (FR-17, FR-20) mitigates.
- Neon/Supabase free storage caps unlikely to bind soon, but a `price_bars` retention/pruning
  policy is still cheap insurance worth building — not done in Phase 3 (wasn't in its task
  list); revisit before Phase 8 deploy if it hasn't been picked up by then.

---

## Appendix: Repository Map (current state)

```
plan.md                              — narrative design doc (architecture rationale, tradeoffs)
spec.md                              — this file (requirements + task breakdown)
.env / .env.example / .gitignore     — Gemini/Finnhub API key + DB URL handling (never committed)
prompts/
  verdict_prompt_v1.md               — first-pass verdict prompt (Phase 0, done)
  verdict_critique_prompt_v1.md      — adversarial second-opinion prompt (Phase 0, done)
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
                                        ProviderCallLog, JobRun (Phase 3)
    migrations/versions/
      0001_initial.py                — companies, price_bars (Phase 1)
      0002_wiki_sections.py          — wiki_sections (Phase 2)
      0003_watchlist_reliability.py  — watchlist, provider_call_log, job_runs (Phase 3)
  api/routers/
    health.py                        — GET /health (Phase 1)
    wiki.py                          — GET /companies/{ticker}/wiki, delegates to lookup_service (Phase 2)
    watchlist.py                     — POST /watchlist/{ticker}/promote, DELETE /watchlist/{ticker} (Phase 3)
    refresh.py                       — POST /internal/refresh (Phase 3)
  jobs/
    scheduler.py                     — APScheduler wiring; calls the same refresh_service
                                        function as the refresh router (NFR-1) (Phase 3)
  services/
    wiki_service.py                  — assemble(ticker) (Phase 2, T2.1)
    lookup_service.py                — get_or_fetch(ticker) (Phase 2, T2.2)
    wiki_sections_service.py         — template-based section generation (Phase 2, T2.3)
    ingest_service.py                — shared profile+quote upsert logic (Phase 3)
    provider_orchestrator.py         — fetch_with_fallback() (Phase 3, T3.3)
    rate_limiter.py                 — per-provider sliding window over provider_call_log (Phase 3, T3.4)
    circuit_breaker.py               — per-provider circuit state over provider_call_log (Phase 3, T3.5)
    refresh_service.py               — refresh_watchlist()/refresh_entry() (Phase 3, T3.2)
    watchlist_service.py             — promote()/remove() (Phase 3, T3.1)
  providers/
    base.py                          — DataProvider interface, Transient/PermanentProviderError
    finnhub_client.py                — primary provider, normalized output (Phase 1, updated Phase 3)
    alpha_vantage_client.py          — fallback provider, normalized output (Phase 3, T3.3)
tests/
  unit/                              — provider parsers, section-template rendering (respx, no network)
  integration/                       — real Postgres, conftest.py rolls back per test and clears
                                        provider_call_log so manual live testing can't poison
                                        rate_limiter/circuit_breaker assertions
```

The frontend does not exist yet — Phase 5 creates it. `fundamentals`, `news_articles`,
`ai_analyses`, and `ai_critiques` tables don't exist yet either — Phase 4 adds them.
