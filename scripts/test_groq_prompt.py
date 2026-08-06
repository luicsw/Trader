"""
Standalone derisking script for the multi-horizon forecast prompt
(prompts/forecast_prompt_v1.md), mirroring scripts/test_gemini_prompt.py.

Purpose: confirm Groq will actually return real, sensibly-varying per-horizon low/high bands
(not a refusal, not five copies of one range, with confidence that decays out to 360 days)
*before* trusting the forecast feature. Unlike the Gemini script, this could NOT be run before
the code around it was written -- no Groq API key is obtainable as of 2026-08-05 -- so it is
the FIRST task of activation, not a prerequisite of construction (spec.md's "Groq activation"
checklist, FR-33b). Expect prompt/parsing changes on first real contact.

Deliberately zero dependency on the rest of the app -- no Postgres, no FastAPI, just the prompt
template + a fixture dict + a raw HTTP call (httpx). Reuses the same fixtures as the Gemini
derisk script.

Setup:
    pip install httpx
    Put GROQ_API_KEY=your-key-here in a .env file at the repo root (gitignored -- see
    .env.example). This script loads it automatically; no need to export it in your shell.

Usage:
    python scripts/test_groq_prompt.py                            # normal fixture
    python scripts/test_groq_prompt.py --fixture thin             # thin/contradictory fixture
    python scripts/test_groq_prompt.py --fixture aapl --repeat 3  # check band/confidence variation
    python scripts/test_groq_prompt.py --model llama-3.1-8b-instant
"""

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
PROMPT_PATH = REPO_ROOT / "prompts" / "forecast_prompt_v1.md"

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
EXPECTED_HORIZONS = [30, 60, 90, 180, 360]


def load_dotenv(path: Path) -> None:
    """Minimal .env loader -- avoids a python-dotenv dependency for this standalone script."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


load_dotenv(REPO_ROOT / ".env")

FIXTURES = {
    "normal": Path(__file__).parent / "fixtures" / "sample_wiki_data.json",
    "thin": Path(__file__).parent / "fixtures" / "sample_wiki_thin.json",
    "aapl": Path(__file__).parent / "fixtures" / "aapl_live.json",
}


def extract_template_block(prompt_md: str) -> str:
    """Pull the ```...``` fenced template block out of forecast_prompt_v1.md."""
    start = prompt_md.index("## Template") + len("## Template")
    fence_start = prompt_md.index("```", start) + 3
    fence_end = prompt_md.index("```", fence_start)
    return prompt_md[fence_start:fence_end].strip()


def fill_template(template: str, data: dict) -> str:
    filled = template
    filled = filled.replace("{{TICKER}}", data["ticker"])
    filled = filled.replace("{{COMPANY_NAME}}", data["company_name"])
    filled = filled.replace("{{SECTOR}}", data["sector"])
    filled = filled.replace("{{EXCHANGE}}", data["exchange"])
    filled = filled.replace("{{AS_OF_TIMESTAMP}}", data["as_of_timestamp"])
    filled = filled.replace("{{OVERVIEW_TEXT}}", data["overview_text"])
    filled = filled.replace("{{KEY_METRICS_JSON}}", json.dumps(data["key_metrics"], indent=2))
    filled = filled.replace("{{PRICE_SUMMARY}}", json.dumps(data["price_summary"], indent=2))
    filled = filled.replace(
        "{{RECENT_SWING_LEVELS_JSON}}", json.dumps(data["recent_swing_levels"], indent=2)
    )
    financials = data["financials_summary_last_4_periods"]
    filled = filled.replace("{{FINANCIALS_PERIOD_COUNT}}", str(len(financials)))
    filled = filled.replace("{{FINANCIALS_SUMMARY_JSON}}", json.dumps(financials, indent=2))
    news = data["news_digest_last_6"]
    filled = filled.replace("{{NEWS_ITEM_COUNT}}", str(len(news)))
    filled = filled.replace("{{NEWS_DIGEST}}", json.dumps(news, indent=2))
    filled = filled.replace("{{RISKS_NOTES_TEXT}}", data["risks_notes_text"])
    return filled


def call_groq(prompt_text: str, model: str) -> str:
    import httpx

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        print(
            "ERROR: set GROQ_API_KEY first. As of 2026-08-05 no key is obtainable -- this "
            "script is the first activation step once one exists (spec.md).",
            file=sys.stderr,
        )
        sys.exit(1)

    response = httpx.post(
        GROQ_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt_text}],
            "response_format": {"type": "json_object"},
            "temperature": 0.4,
        },
        timeout=60.0,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def check_forecast(parsed: dict) -> None:
    """Print the honest pass/fail signals spec.md's activation checklist asks for."""
    forecasts = parsed.get("forecasts")
    if not isinstance(forecasts, list):
        print("  WARNING: no 'forecasts' array in response")
        return
    horizons = [f.get("horizon_days") for f in forecasts]
    print(f"  horizons: {horizons} (expected {EXPECTED_HORIZONS})")

    lows = [f.get("expected_low") for f in forecasts if isinstance(f, dict)]
    highs = [f.get("expected_high") for f in forecasts if isinstance(f, dict)]
    confs = [f.get("confidence") for f in forecasts if isinstance(f, dict)]
    widths = [
        (h - lo) for lo, h in zip(lows, highs) if isinstance(lo, (int, float)) and isinstance(h, (int, float))
    ]
    if len(set(f"{lo}/{hi}" for lo, hi in zip(lows, highs))) == 1:
        print("  WARNING: all five bands are identical -- prompt not biting (spec.md)")
    if widths and widths != sorted(widths):
        print("  NOTE: band width does not widen monotonically with horizon")
    if confs and confs != sorted(confs, reverse=True):
        print("  NOTE: confidence does not decay monotonically from 30d to 360d (spec.md)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", choices=FIXTURES.keys(), default="normal")
    parser.add_argument("--repeat", type=int, default=1, help="run N times to check variation")
    parser.add_argument(
        "--model",
        default="llama-3.3-70b-versatile",
        help="Groq model id (default: llama-3.3-70b-versatile -- re-check against Groq's live "
        "free-tier lineup during activation, it was picked from docs not a live call)",
    )
    args = parser.parse_args()

    prompt_md = PROMPT_PATH.read_text(encoding="utf-8")
    template = extract_template_block(prompt_md)
    data = json.loads(FIXTURES[args.fixture].read_text(encoding="utf-8"))
    prompt_text = fill_template(template, data)

    for i in range(args.repeat):
        raw = call_groq(prompt_text, args.model)
        print(f"--- forecast run {i + 1}/{args.repeat} ({args.fixture}) ---")
        try:
            parsed = json.loads(raw)
            print(json.dumps(parsed, indent=2))
            check_forecast(parsed)
        except json.JSONDecodeError:
            print("WARNING: response was not valid JSON despite json_object mode:")
            print(raw)


if __name__ == "__main__":
    main()
