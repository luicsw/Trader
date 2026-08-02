"""
Standalone derisking script for the verdict prompt (prompts/verdict_prompt_v1.md).

Purpose: confirm Gemini will actually return a real buy/hold/sell verdict for this prompt
framing *before* building the rest of the AI pipeline (DB models, ai_service, etc.) around an
assumption that might not hold. Deliberately has zero dependency on the rest of the app — no
Postgres, no FastAPI, just the prompt template + a fixture dict + a raw API call.

Setup:
    pip install google-genai
    Put GEMINI_API_KEY=your-key-here in a .env file at the repo root (gitignored — see
    .env.example). This script loads it automatically; no need to export it in your shell.

Usage:
    python scripts/test_gemini_prompt.py                          # normal fixture
    python scripts/test_gemini_prompt.py --fixture thin           # thin/contradictory fixture
    python scripts/test_gemini_prompt.py --fixture thin --repeat 5   # check verdict consistency
    python scripts/test_gemini_prompt.py --fixture aapl --critique   # verdict + adversarial second opinion
"""

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
PROMPT_PATH = REPO_ROOT / "prompts" / "verdict_prompt_v1.md"
CRITIQUE_PROMPT_PATH = REPO_ROOT / "prompts" / "verdict_critique_prompt_v1.md"


def load_dotenv(path: Path) -> None:
    """Minimal .env loader — avoids a python-dotenv dependency for this standalone script."""
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

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["buy", "hold", "sell"]},
        "confidence": {"type": "number"},
        "reasoning": {"type": "string"},
        "price_targets": {
            "type": "object",
            "properties": {
                "buy_at_or_below": {"type": "number", "nullable": True},
                "sell_at_or_above": {"type": "number", "nullable": True},
                "stop_loss": {"type": "number", "nullable": True},
            },
            "required": ["buy_at_or_below", "sell_at_or_above", "stop_loss"],
        },
        "hold_period_days": {
            "type": "object",
            "properties": {
                "min": {"type": "integer", "nullable": True},
                "max": {"type": "integer", "nullable": True},
                "note": {"type": "string", "nullable": True},
            },
            "required": ["min", "max", "note"],
        },
        "cited_sources": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["news", "fundamental", "price", "metric"]},
                    "reference": {"type": "string"},
                },
                "required": ["type", "reference"],
            },
        },
    },
    "required": [
        "verdict",
        "confidence",
        "reasoning",
        "price_targets",
        "hold_period_days",
        "cited_sources",
    ],
}

CRITIQUE_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "agrees_with_verdict_direction": {"type": "boolean"},
        "biggest_weakness": {"type": "string"},
        "revised_price_targets": {
            "type": "object",
            "properties": {
                "buy_at_or_below": {"type": "number", "nullable": True},
                "sell_at_or_above": {"type": "number", "nullable": True},
                "stop_loss": {"type": "number", "nullable": True},
            },
            "required": ["buy_at_or_below", "sell_at_or_above", "stop_loss"],
        },
        "revised_confidence": {"type": "number", "nullable": True},
        "rationale": {"type": "string"},
    },
    "required": [
        "agrees_with_verdict_direction",
        "biggest_weakness",
        "revised_price_targets",
        "revised_confidence",
        "rationale",
    ],
}


def extract_template_block(prompt_md: str) -> str:
    """Pull the ```...``` fenced template block out of verdict_prompt_v1.md."""
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


def fill_critique_template(template: str, data: dict, original_verdict: dict) -> str:
    filled = fill_template(template, data)
    filled = filled.replace(
        "{{ORIGINAL_VERDICT_JSON}}", json.dumps(original_verdict, indent=2)
    )
    return filled


def call_gemini(prompt_text: str, model: str, schema: dict) -> str:
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: set GEMINI_API_KEY first.", file=sys.stderr)
        sys.exit(1)

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=prompt_text,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
        ),
    )
    return response.text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", choices=FIXTURES.keys(), default="normal")
    parser.add_argument("--repeat", type=int, default=1, help="run N times to check verdict consistency")
    parser.add_argument(
        "--model", default="gemini-flash-latest", help="Gemini model id (default: gemini-flash-latest)"
    )
    parser.add_argument(
        "--critique",
        action="store_true",
        help="after generating the verdict, run the adversarial second-opinion critique pass on it",
    )
    args = parser.parse_args()

    prompt_md = PROMPT_PATH.read_text(encoding="utf-8")
    template = extract_template_block(prompt_md)
    data = json.loads(FIXTURES[args.fixture].read_text(encoding="utf-8"))
    prompt_text = fill_template(template, data)

    critique_template = None
    if args.critique:
        critique_md = CRITIQUE_PROMPT_PATH.read_text(encoding="utf-8")
        critique_template = extract_template_block(critique_md)

    for i in range(args.repeat):
        raw = call_gemini(prompt_text, args.model, RESPONSE_SCHEMA)
        print(f"--- verdict run {i + 1}/{args.repeat} ---")
        try:
            parsed = json.loads(raw)
            print(json.dumps(parsed, indent=2))
        except json.JSONDecodeError:
            print("WARNING: response was not valid JSON despite response_schema:")
            print(raw)
            continue

        if critique_template is not None:
            critique_prompt = fill_critique_template(critique_template, data, parsed)
            raw_critique = call_gemini(critique_prompt, args.model, CRITIQUE_RESPONSE_SCHEMA)
            print(f"--- second opinion (critique) run {i + 1}/{args.repeat} ---")
            try:
                parsed_critique = json.loads(raw_critique)
                print(json.dumps(parsed_critique, indent=2))
            except json.JSONDecodeError:
                print("WARNING: critique response was not valid JSON despite response_schema:")
                print(raw_critique)


if __name__ == "__main__":
    main()
