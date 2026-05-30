"""Tests for the Wikidata population ingestion module."""

from unittest.mock import MagicMock, patch

import pytest

from museums.ingestion.population import (
    CityPopulation,
    fetch_city_populations,
    fetch_populations,
    resolve_city_qid,
)

# ---------------------------------------------------------------------------
# resolve_city_qid tests
# ---------------------------------------------------------------------------

SEARCH_RESPONSE_PARIS = {
    "search": [
        {"id": "Q90", "label": "Paris", "description": "capital of France"},
        {"id": "Q129392", "label": "Paris", "description": "city in Texas"},
    ]
}

SEARCH_RESPONSE_EMPTY = {"search": []}


class TestResolveCityQid:
    def test_returns_first_match(self, respx_mock: pytest.FixtureRequest) -> None:  # type: ignore[type-arg]
        """Verify the logic correctly handles Wikidata search results and extracts the QID from the primary match."""
        import respx
        from httpx import Response

        api_url = "https://www.wikidata.org/w/api.php"
        with respx.mock:
            respx.get(api_url).mock(
                return_value=Response(200, json=SEARCH_RESPONSE_PARIS)
            )
            qid = resolve_city_qid("Paris", "France", api_url=api_url)

        assert qid == "Q90"

    def test_returns_none_when_no_results(self, respx_mock: pytest.FixtureRequest) -> None:  # type: ignore[type-arg]
        """Ensure the pipeline doesn't crash when searching for a completely non-existent city, gracefully returning None instead."""
        import respx
        from httpx import Response

        api_url = "https://www.wikidata.org/w/api.php"
        with respx.mock:
            respx.get(api_url).mock(
                return_value=Response(200, json=SEARCH_RESPONSE_EMPTY)
            )
            qid = resolve_city_qid("Nonexistent City", "Mars", api_url=api_url)

        assert qid is None


# ---------------------------------------------------------------------------
# fetch_populations tests
# ---------------------------------------------------------------------------

SPARQL_RESPONSE = {
    "results": {
        "bindings": [
            {
                "city": {"value": "http://www.wikidata.org/entity/Q90"},
                "population": {"value": "2161000"},
            },
            {
                "city": {"value": "http://www.wikidata.org/entity/Q956"},
                "population": {"value": "21540000"},
            },
        ]
    }
}


class TestFetchPopulations:
    def test_returns_population_map(self, respx_mock: pytest.FixtureRequest) -> None:  # type: ignore[type-arg]
        """Check that the SPARQL response is correctly parsed into a dictionary mapping QIDs to integer populations."""
        import respx
        from httpx import Response

        sparql_url = "https://query.wikidata.org/sparql"
        with respx.mock:
            respx.get(sparql_url).mock(
                return_value=Response(200, json=SPARQL_RESPONSE)
            )
            result = fetch_populations(["Q90", "Q956"], sparql_url=sparql_url)

        assert result["Q90"] == 2_161_000
        assert result["Q956"] == 21_540_000

    def test_empty_qids_returns_empty_dict(self) -> None:
        """Catch edge case: An empty list of QIDs shouldn't break the SPARQL query string builder, but just return empty."""
        result = fetch_populations([])
        assert result == {}

    def test_keeps_largest_when_multiple_values(self, respx_mock: pytest.FixtureRequest) -> None:  # type: ignore[type-arg]
        """Catch duplicate population logic: If a city lists both a 'city proper' and 'metro' population in Wikidata, pick the largest."""
        import respx
        from httpx import Response

        # Same QID appears twice with different populations (city proper vs metro).
        duplicate_response = {
            "results": {
                "bindings": [
                    {"city": {"value": "http://www.wikidata.org/entity/Q90"}, "population": {"value": "2161000"}},
                    {"city": {"value": "http://www.wikidata.org/entity/Q90"}, "population": {"value": "12000000"}},
                ]
            }
        }
        sparql_url = "https://query.wikidata.org/sparql"
        with respx.mock:
            respx.get(sparql_url).mock(
                return_value=Response(200, json=duplicate_response)
            )
            result = fetch_populations(["Q90"], sparql_url=sparql_url)

        assert result["Q90"] == 12_000_000


# ---------------------------------------------------------------------------
# fetch_city_populations integration test
# ---------------------------------------------------------------------------

class TestFetchCityPopulations:
    def test_deduplicates_cities(self) -> None:
        """Duplicate (city, country) pairs should only be looked up once."""
        cities = [("Paris", "France"), ("Paris", "France"), ("Beijing", "China")]

        with (
            patch("museums.ingestion.population.resolve_city_qid") as mock_resolve,
            patch("museums.ingestion.population.fetch_populations") as mock_fetch,
        ):
            mock_resolve.side_effect = lambda name, country, **kwargs: {
                "Paris": "Q90",
                "Beijing": "Q956",
            }.get(name)
            mock_fetch.return_value = {"Q90": 2_161_000, "Q956": 21_540_000}

            results = fetch_city_populations(cities)

        # 2 unique cities, resolve called twice (not three times)
        assert mock_resolve.call_count == 2
        assert len(results) == 2

    def test_returns_none_population_for_unresolved_city(self) -> None:
        """Catch silent failures: When the API fails to find a city, it should yield a CityPopulation with population=None so the caller knows it failed."""
        cities = [("UnknownCity", "UnknownCountry")]

        with (
            patch("museums.ingestion.population.resolve_city_qid", return_value=None),
            patch("museums.ingestion.population.fetch_populations", return_value={}),
        ):
            results = fetch_city_populations(cities)

        assert len(results) == 1
        assert results[0].population is None
        assert results[0].wikidata_qid == "unknown"
