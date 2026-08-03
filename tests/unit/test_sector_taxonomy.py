from app.services import sector_taxonomy


def test_categorize_none_is_other():
    assert sector_taxonomy.categorize(None) == "Other"


def test_categorize_empty_string_is_other():
    assert sector_taxonomy.categorize("") == "Other"


def test_categorize_unmapped_value_is_other():
    assert sector_taxonomy.categorize("Something Nobody Has Ever Classified") == "Other"


def test_categorize_real_observed_values():
    # These are real finnhubIndustry values seen from live Finnhub data during this project.
    assert sector_taxonomy.categorize("Technology") == "Technology"
    assert sector_taxonomy.categorize("Semiconductors") == "Technology"


def test_categorize_healthcare_beats_generic_technology_match():
    # "Health Care Technology" should hit Healthcare, not Technology -- order matters.
    assert sector_taxonomy.categorize("Health Care Technology") == "Healthcare"


def test_categorize_various_known_industries():
    assert sector_taxonomy.categorize("Biotechnology") == "Healthcare"
    assert sector_taxonomy.categorize("Oil & Gas E&P") == "Energy"
    assert sector_taxonomy.categorize("Banks - Regional") == "Financials"
    assert sector_taxonomy.categorize("REIT - Residential") == "Real Estate"
    assert sector_taxonomy.categorize("Utilities - Regulated Electric") == "Utilities"
    assert sector_taxonomy.categorize("Aerospace & Defense") == "Industrials"
    assert sector_taxonomy.categorize("Specialty Chemicals") == "Materials"
    assert sector_taxonomy.categorize("Telecom Services") == "Communication Services"
    assert sector_taxonomy.categorize("Restaurants") == "Consumer Discretionary"
    assert sector_taxonomy.categorize("Packaged Foods") == "Consumer Staples"


def test_categorize_is_case_insensitive():
    assert sector_taxonomy.categorize("SEMICONDUCTORS") == "Technology"
