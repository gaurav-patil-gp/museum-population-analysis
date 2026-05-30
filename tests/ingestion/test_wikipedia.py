"""Tests for the Wikipedia ingestion module."""

import pytest

from museums.ingestion.wikipedia import (
    MuseumRecord,
    fetch_museums,
    parse_table,
    parse_visitors,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_WIKITEXT = """\
== List of most-visited museums ==

{| class="wikitable sortable"
|-
!Name
!Visitors!!City
!Country
|-
|1 |[[Louvre]] || 9,000,000 (2025) <ref>Some ref</ref>|| [[Paris]]
| {{flag|France}}
|-
|[[National Museum of China]] || 6,956,800 (2024)|| [[Beijing]]
| {{flag|China}}
|-
|[[Natural History Museum, London|Natural History Museum, South Kensington]] || 6,301,972 (2024)|| [[London]]
|{{flag|United Kingdom}}
|-
|[[Vatican Museums]] ||6,933,822 (2025)|| [[Vatican City]], [[Rome]]
|{{flag|Vatican}}
|-
|[[Musee National d'Histoire Naturelle]] ||3.2 million (2024)|| [[Paris]]
| {{flag|France}}
|-
|[[M+]] ||2.61 million (2024)|| [[Hong Kong]]
| {{flag|Hong Kong}}
|-
|[[Small Museum]] ||1,500,000 (2024)|| [[SomeCity]]
| {{flag|SomeCountry}}
|}
"""

SAMPLE_API_RESPONSE = {
    "parse": {
        "title": "List of most-visited museums",
        "pageid": 54754776,
        "wikitext": {"*": SAMPLE_WIKITEXT},
    }
}


# ---------------------------------------------------------------------------
# parse_visitors tests
# ---------------------------------------------------------------------------


class TestParseVisitors:
    def test_comma_integer_with_year(self) -> None:
        """Verify the parser correctly extracts standard comma-separated integers and ignores parenthetical years."""
        count, year = parse_visitors("9,000,000 (2025)")
        assert count == 9_000_000
        assert year == 2025

    def test_comma_integer_no_year(self) -> None:
        count, year = parse_visitors("6,956,800")
        assert count == 6_956_800
        assert year is None

    def test_decimal_million_with_year(self) -> None:
        """Catch edge cases where visitors are formatted as 'X.X million' instead of raw numbers."""
        count, year = parse_visitors("3.2 million (2024)")
        assert count == 3_200_000
        assert year == 2024

    def test_decimal_million_small(self) -> None:
        count, year = parse_visitors("2.61 million (2024)")
        assert count == 2_610_000
        assert year == 2024

    def test_approximate_prefix(self) -> None:
        """Ensure the parser handles strings with approximate symbols (e.g. '~')."""
        count, year = parse_visitors("~4 million")
        assert count == 4_000_000
        assert year is None

    def test_with_ref_tags(self) -> None:
        """Verify that HTML citation tags (like <ref>) appended to numbers are safely stripped out."""
        count, year = parse_visitors("6,933,822 (2025)<ref>Some journal</ref>")
        assert count == 6_933_822
        assert year == 2025

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_visitors("not a number")


# ---------------------------------------------------------------------------
# parse_table tests
# ---------------------------------------------------------------------------


class TestParseTable:
    def test_returns_museum_records(self) -> None:
        records = parse_table(SAMPLE_WIKITEXT)
        assert len(records) > 0
        assert all(isinstance(r, MuseumRecord) for r in records)

    def test_filters_below_2m(self) -> None:
        """Ensure the parser correctly enforces the core business logic rule: Drop museums with < 2M visitors."""
        records = parse_table(SAMPLE_WIKITEXT)
        assert all(r.annual_visitors >= 2_000_000 for r in records)
        names = [r.name for r in records]
        assert "Small Museum" not in names

    def test_louvre_parsed_correctly(self) -> None:
        records = parse_table(SAMPLE_WIKITEXT)
        louvre = next((r for r in records if "Louvre" in r.name), None)
        assert louvre is not None
        assert louvre.annual_visitors == 9_000_000
        assert louvre.visitor_year == 2025
        assert louvre.city == "Paris"
        assert louvre.country == "France"

    def test_piped_wikilink_uses_display_name(self) -> None:
        records = parse_table(SAMPLE_WIKITEXT)
        # The piped link [[Natural History Museum, London|Natural History Museum, South Kensington]]
        # should use the display text.
        names = [r.name for r in records]
        assert any("Natural History Museum" in n for n in names)

    def test_multi_city_takes_first(self) -> None:
        """Catch edge cases where a museum lists multiple cities (e.g., Vatican City, Rome) and pick the first one."""
        records = parse_table(SAMPLE_WIKITEXT)
        vatican = next((r for r in records if "Vatican" in r.name), None)
        assert vatican is not None
        assert "Vatican City" in vatican.city or "Rome" in vatican.city

    def test_decimal_million_format(self) -> None:
        records = parse_table(SAMPLE_WIKITEXT)
        mnhn = next((r for r in records if "Naturelle" in r.name), None)
        assert mnhn is not None
        assert mnhn.annual_visitors == 3_200_000

    def test_wikipedia_url_populated(self) -> None:
        records = parse_table(SAMPLE_WIKITEXT)
        louvre = next((r for r in records if "Louvre" in r.name), None)
        assert louvre is not None
        assert louvre.wikipedia_url is not None
        assert "wikipedia.org/wiki" in louvre.wikipedia_url


# ---------------------------------------------------------------------------
# fetch_museums integration test (mocked HTTP)
# ---------------------------------------------------------------------------


class TestFetchMuseums:
    def test_calls_mediawiki_api(self, respx_mock: pytest.FixtureRequest) -> None:
        """Verify fetch_museums hits the API and returns parsed records."""
        import respx
        from httpx import Response

        api_url = "https://en.wikipedia.org/w/api.php"
        with respx.mock:
            respx.get(api_url).mock(return_value=Response(200, json=SAMPLE_API_RESPONSE))
            records = fetch_museums(api_url=api_url)

        assert len(records) > 0
        assert all(r.annual_visitors >= 2_000_000 for r in records)
