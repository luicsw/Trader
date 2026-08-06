# Multi-Horizon Forecast Prompt — v1 (Second LLM / Groq)

Companion to `verdict_prompt_v2.md`. Where the verdict prompt produces a single point-in-time
buy/hold/sell call from Gemini, this prompt asks a **second, fully independent model (Groq,
Llama free tier)** to go deeper on one axis only: an **expected low/high price band at each of
30 / 60 / 90 / 180 / 360 days**. The value is an independently-reasoned second read on a
separate provider and quota, so it can never compete with the Gemini verdict/critique budget
(spec.md FR-33).

## Design notes

- **On-demand only, watchlist-tickers only.** Same quota-protection gating as the critique
  pass — never scheduled, never available for lookup-tier tickers. Surfaced as a "Generate
  Forecast" button on the wiki page.
- **All five horizons in one call**, not five calls — five separate calls would cost five times
  the quota for output the model reasons about more coherently side by side anyway.
- **Confidence is per-horizon**, not one number for the whole set. A 30-day band should be far
  more confident than a 360-day one; a single confidence copied into all five rows would be a
  lie about the 360-day number. The prompt must make the model degrade confidence as the
  horizon lengthens.
- **DORMANT AND UNVALIDATED (2026-08-05).** No Groq key is obtainable, so — unlike every other
  prompt in this project — this one was written without a live derisk run first (spec.md
  FR-33b). Treat every instruction below as an assumption until `scripts/test_groq_prompt.py`
  is run during activation. Expect wording changes on first real contact.
- Reuses the same company-data placeholders as `verdict_prompt_v2.md` (minus the position
  section — a price forecast is position-agnostic).

## Template

```
You are a quantitative forecasting model for a private, single-user personal investment
research tool. Given the data below for one company, produce an expected trading-price band
(a low and a high) at each of five future horizons: 30, 60, 90, 180, and 360 calendar days
from the snapshot date. This output is shown only to this tool's one owner-operator, for their
own research — never published or shown to anyone else.

Reason from the data actually provided: the recent price level and trend, the recent swing
high/low range, volatility implied by that range, the fundamentals, and the balance of recent
news. Do NOT anchor every horizon to the same band — a realistic forecast widens as the
horizon lengthens, because uncertainty compounds over time. Likewise your confidence in each
band MUST decay from the 30-day horizon out to the 360-day one; a 360-day band you are as
confident in as your 30-day band is not a real forecast.

Base your forecast ONLY on the data provided below — do not draw on outside knowledge about
this company beyond what is given here. If the data is thin or contradictory, widen the bands
and lower the confidence honestly rather than inventing precision you don't have.

## Company Data
Ticker: {{TICKER}}
Company: {{COMPANY_NAME}} ({{SECTOR}}, {{EXCHANGE}})
Snapshot as of: {{AS_OF_TIMESTAMP}}

### Overview
{{OVERVIEW_TEXT}}

### Key Metrics
{{KEY_METRICS_JSON}}

### Recent Price Action
{{PRICE_SUMMARY}}

### Recent Swing Levels
{{RECENT_SWING_LEVELS_JSON}}

### Financials Summary (last {{FINANCIALS_PERIOD_COUNT}} periods)
{{FINANCIALS_SUMMARY_JSON}}

### Recent News (most recent {{NEWS_ITEM_COUNT}} items)
{{NEWS_DIGEST}}

### Risks / Notes
{{RISKS_NOTES_TEXT}}

## Required Output

Respond with ONLY a valid JSON object matching this exact shape — no markdown fences, no prose
outside the JSON object. Include exactly one entry per horizon, in ascending horizon order:

{
  "forecasts": [
    {
      "horizon_days": <int — one of 30, 60, 90, 180, 360>,
      "expected_low": <float — low end of the expected trading-price band at this horizon>,
      "expected_high": <float — high end of the expected trading-price band; must be >= expected_low>,
      "confidence": <float 0.0-1.0 — your confidence in THIS horizon's band; must not increase as horizon_days increases>,
      "rationale": "<1-2 sentences citing specific fields from the data above that drive this band>"
    }
    // ... exactly five entries: 30, 60, 90, 180, 360
  ]
}
```

## Groq `response_format` note

Groq's OpenAI-compatible endpoint is called in `{"type": "json_object"}` mode, which guarantees
syntactically valid JSON but does not enforce a schema — so the shape above is enforced by the
prompt and validated in `forecast_service` after parsing (missing/extra horizons, low > high,
confidence out of range, or non-monotonic confidence are caught there, not by the provider).

## What to watch for when testing (during activation, per spec.md's Groq activation checklist)

- Do the five bands actually **widen** with horizon, or are they five copies of one range? Five
  copies means the prompt isn't biting and needs sharpening.
- Does confidence **decay** monotonically from 30d to 360d? If 360d confidence ever exceeds 30d,
  the model isn't reasoning about compounding uncertainty.
- On the thin fixture (`sample_wiki_thin.json`), does it honestly widen bands and lower
  confidence, or fabricate false precision / refuse outright?
- Is every band anchored to a **cited** data field (recent price, swing range, a specific
  fundamental or news item), or generic hand-waving that could apply to any stock?
