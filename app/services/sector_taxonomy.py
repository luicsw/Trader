"""Maps Finnhub's granular `finnhubIndustry` classification (e.g. "Semiconductors",
"Biotechnology") down to a small set of broad, human-familiar categories ("Technology",
"Healthcare", ...) for browsing/filtering -- the granular value stays available as
`sector` everywhere it already was; `category` is additive, not a replacement.

Keyword-matched rather than an exact lookup table: Finnhub's full industry taxonomy isn't
fully enumerable from documentation alone, and a keyword match degrades honestly (unmapped
values fall into "Other" instead of guessing wrong or crashing) rather than requiring an
exhaustive, brittle table kept in lockstep with a third party's classification system.

Order matters -- more specific categories are checked before broader ones that could also
match a substring (e.g. "Health Care Technology" must hit Healthcare, not Technology).
"""

CATEGORIES: list[tuple[str, list[str]]] = [
    ("Healthcare", ["health", "biotech", "pharma", "medical", "drug", "life sciences"]),
    (
        "Technology",
        ["technology", "semiconductor", "software", "internet", "electronic", "computer", "hardware"],
    ),
    (
        "Financials",
        ["bank", "insurance", "financial", "asset management", "capital markets", "credit", "brokerage"],
    ),
    ("Energy", ["oil", "gas", "energy", "coal", "petroleum"]),
    ("Utilities", ["utilit"]),
    ("Real Estate", ["real estate", "reit"]),
    (
        "Consumer Discretionary",
        ["retail", "consumer discretionary", "apparel", "restaurant", "leisure", "hotel", "auto", "e-commerce"],
    ),
    ("Consumer Staples", ["food", "beverage", "household", "tobacco", "grocery", "consumer staples"]),
    (
        "Communication Services",
        ["communication", "media", "telecom", "entertainment", "broadcasting", "advertising"],
    ),
    (
        "Industrials",
        [
            "industrial",
            "machinery",
            "aerospace",
            "defense",
            "construction",
            "transportation",
            "airlines",
            "railroad",
            "manufacturing",
        ],
    ),
    ("Materials", ["material", "chemical", "mining", "metal", "steel", "paper", "mineral"]),
]

OTHER = "Other"


def categorize(sector: str | None) -> str:
    if not sector:
        return OTHER

    lowered = sector.lower()
    for category, keywords in CATEGORIES:
        if any(keyword in lowered for keyword in keywords):
            return category
    return OTHER
