# Verdict Prompt — v1

This is the prompt template referenced by `ai_service.build_prompt(ticker)` in plan.md. It is
versioned (`v1`) because the plan stores `context_snapshot` per analysis for reproducibility —
if this wording changes meaningfully, save the next version as `verdict_prompt_v2.md` rather
than editing this one in place, so old `ai_analyses` rows stay interpretable against the prompt
that actually produced them.

## Design notes

- **Framing is the whole ballgame.** The instruction block explicitly tells the model this is a
  private, single-user tool and that a verdict is the explicit purpose — this is what
  distinguishes it from a public chatbot request and is what should get a real buy/hold/sell
  instead of a refusal or generic disclaimer. See the "will Gemini actually do this" discussion
  from earlier in this session.
- **Grounding constraint** ("base your verdict ONLY on the data provided") matters for two
  reasons: it keeps the reasoning traceable to `cited_sources` (the wiki-fidelity requirement in
  plan.md), and it reduces the chance of the model reaching for outside "knowledge" that may be
  stale relative to the fetched data.
- **Schema-forced output**: use Gemini's structured output mode (`response_mime_type:
  "application/json"` + `response_schema`) rather than relying on instructions alone — this
  makes the JSON contract a hard API constraint, not just a request the model might ignore or
  wrap in markdown fences.
- Placeholders (`{{LIKE_THIS}}`) are filled from the exact dict returned by
  `wiki_service.assemble(ticker)` — same data the user sees on the wiki page.
- **Price targets/hold period are heuristic, not technical analysis.** The model has no
  indicator engine behind it — it's pattern-matching over the price/fundamentals/news text you
  hand it. `recent_swing_levels` (20d/60d high-low) gives it *something* concrete to anchor
  buy/sell levels to instead of inventing numbers from nothing, but this is still a synthesis
  judgment, not a technical signal. If target precision matters more later, that's a case for a
  real indicator library (e.g. support/resistance from the actual `price_bars` series) computed
  in Python and handed to the model as a fact, not asking the model to eyeball it.

## Template

```
You are a research-synthesis assistant embedded in a private, single-user personal investment
research tool. The output you produce is shown only to this tool's one owner-operator, on their
own dashboard, for their own portfolio decisions. It is never published, broadcast, shown to any
other person, or used to solicit anyone. Producing a clear buy/hold/sell verdict is the explicit
purpose of this tool, and the user understands this is AI-generated synthesis of the data below,
not advice from a licensed advisor.

Do not include generic disclaimers or refuse to give a verdict. If the data is genuinely
insufficient or contradictory for a confident call, reflect that honestly through a "hold"
verdict with a low confidence score and explain the specific gap in your reasoning — that is a
real, useful answer. A deflection with no verdict at all is not.

Base your verdict ONLY on the data provided below. Do not draw on outside knowledge about this
company beyond what's given here — the data below may be more current than your training data,
and the wiki page the user is looking at only contains this. Every claim in "reasoning" must be
traceable to a specific field in the input below, and every entry in "cited_sources" must point
to something that actually appears in the input.

In addition to the verdict, provide concrete price levels and a hold duration, exactly as a
personal research note would: a buy-at-or-below entry price, a sell-at-or-above target, a
stop-loss level for downside protection, and a suggested holding period in days. Anchor these to
the recent swing levels and price action given below rather than inventing numbers — e.g. a
stop-loss below the recent swing low, a sell target near or above recent resistance and
consistent with the valuation/fundamentals picture, a hold period long enough to reach a
mentioned catalyst (earnings, contract decision, etc.) if the news/risks data references one.
These are honest best-effort estimates from the data given, not precise technical analysis — say
so implicitly by keeping the confidence score in sync with the verdict's confidence rather than
overstating precision. If the verdict is "sell," `hold_period_days` should be null (there is
nothing to hold). If the verdict is "hold" because data is too thin to call a level, set the
price target fields to null rather than guessing.

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

Respond with ONLY valid JSON matching this exact shape — no markdown fences, no prose outside
the JSON object:

{
  "verdict": "buy" | "hold" | "sell",
  "confidence": <float 0.0-1.0>,
  "reasoning": "<2-4 sentence plain-English rationale citing specific figures/news from the data above>",
  "price_targets": {
    "buy_at_or_below": <float or null>,
    "sell_at_or_above": <float or null>,
    "stop_loss": <float or null>
  },
  "hold_period_days": {
    "min": <int or null>,
    "max": <int or null>,
    "note": "<short reason for the range, e.g. 'until Q3 earnings on 2026-10-15' — or null>"
  },
  "cited_sources": [
    {"type": "news" | "fundamental" | "price" | "metric", "reference": "<short pointer, e.g. article headline or metric name>"}
  ]
}
```

## Gemini `response_schema` (for structured-output mode)

```json
{
  "type": "object",
  "properties": {
    "verdict": {"type": "string", "enum": ["buy", "hold", "sell"]},
    "confidence": {"type": "number"},
    "reasoning": {"type": "string"},
    "price_targets": {
      "type": "object",
      "properties": {
        "buy_at_or_below": {"type": ["number", "null"]},
        "sell_at_or_above": {"type": ["number", "null"]},
        "stop_loss": {"type": ["number", "null"]}
      },
      "required": ["buy_at_or_below", "sell_at_or_above", "stop_loss"]
    },
    "hold_period_days": {
      "type": "object",
      "properties": {
        "min": {"type": ["integer", "null"]},
        "max": {"type": ["integer", "null"]},
        "note": {"type": ["string", "null"]}
      },
      "required": ["min", "max", "note"]
    },
    "cited_sources": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "type": {"type": "string", "enum": ["news", "fundamental", "price", "metric"]},
          "reference": {"type": "string"}
        },
        "required": ["type", "reference"]
      }
    }
  },
  "required": ["verdict", "confidence", "reasoning", "price_targets", "hold_period_days", "cited_sources"]
}
```

Note: Gemini's structured-output mode has historically been stricter about JSON Schema features
than the full spec (e.g. `["number", "null"]` union-type nullability isn't always honored the
same way `nullable: true` is in older Vertex-style schemas). If the test script throws a schema
validation error, try `"type": "number", "nullable": true` per field instead of the union-type
array form above — check whichever `google-genai` SDK version you have installed for its current
supported subset.

## What to watch for when testing

- Does `verdict` actually vary (buy/hold/sell) across different tickers/data, or does the model
  default to "hold" every time as a safe middle ground? A model that never says buy/sell isn't
  meeting the tool's purpose even if it's not technically refusing.
- Does `reasoning` ever smuggle in a disclaimer sentence despite the instruction not to? Harmless
  if so (you're parsing structured fields, not displaying raw prose unfiltered), but worth
  knowing — strip it in `ai_service` if it shows up consistently.
- Does confidence correlate sensibly with data quality (e.g. a ticker with thin news/fundamentals
  should get a lower confidence, not a falsely confident verdict)?
- Try at least one deliberately thin/contradictory data set (see
  `scripts/fixtures/sample_wiki_thin.json`) to confirm the model produces an honest low-confidence
  "hold" rather than either refusing outright or fabricating false confidence.
- Sanity-check internal consistency of the new fields: is `buy_at_or_below` below
  `sell_at_or_above`? Is `stop_loss` below both (for a buy) or does it make sense relative to
  current price at all? Is `hold_period_days` null when verdict is "sell" as instructed? Is
  `hold_period_days` on the thin-data fixture appropriately null/absent rather than a confident
  guess? A model getting the verdict right but hallucinating internally-inconsistent price levels
  is a failure mode worth catching here, before it reaches a real UI.
