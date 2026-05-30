"""Tests for the ETL pipeline."""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from museums.ingestion.population import CityPopulation
from museums.ingestion.wikipedia import MuseumRecord
from museums.models.schema import Base, City, Museum
from museums.pipeline.etl import enrich_populations, load_museums


SAMPLE_RECORDS = [
    MuseumRecord(
        name="Louvre",
        city="Paris",
        country="France",
        annual_visitors=9_000_000,
        visitor_year=2025,
        wikipedia_url="https://en.wikipedia.org/wiki/Louvre",
    ),
    MuseumRecord(
        name="Musee d'Orsay",
        city="Paris",
        country="France",
        annual_visitors=3_750_000,
        visitor_year=2024,
        wikipedia_url="https://en.wikipedia.org/wiki/Musee_d%27Orsay",
    ),
    MuseumRecord(
        name="British Museum",
        city="London",
        country="United Kingdom",
        annual_visitors=6_440_000,
        visitor_year=2025,
        wikipedia_url="https://en.wikipedia.org/wiki/British_Museum",
    ),
]


# ---------------------------------------------------------------------------
# load_museums tests
# ---------------------------------------------------------------------------

class TestLoadMuseums:
    def test_inserts_museums_and_cities(self, in_memory_session: Session) -> None:
        """Verify that valid museum records correctly map to inserts in both Museum and City tables."""
        load_museums(SAMPLE_RECORDS, in_memory_session)
        in_memory_session.flush()

        museums = in_memory_session.query(Museum).all()
        cities = in_memory_session.query(City).all()

        assert len(museums) == 3
        assert len(cities) == 2  # Paris and London

    def test_two_museums_share_one_city_row(self, in_memory_session: Session) -> None:
        """Catch duplication bugs: Ensure that multiple museums in the same city link to a single City row."""
        load_museums(SAMPLE_RECORDS, in_memory_session)
        in_memory_session.flush()

        paris_museums = (
            in_memory_session.query(Museum)
            .join(City)
            .filter(City.name == "Paris")
            .all()
        )
        paris_cities = in_memory_session.query(City).filter_by(name="Paris").all()

        assert len(paris_museums) == 2
        assert len(paris_cities) == 1  # one City row, not two

    def test_museum_fields_stored_correctly(self, in_memory_session: Session) -> None:
        """Ensure all fields (visitors, year, URL) are successfully mapped and stored in the database."""
        load_museums(SAMPLE_RECORDS, in_memory_session)
        in_memory_session.flush()

        louvre = in_memory_session.query(Museum).filter_by(name="Louvre").one()

        assert louvre.annual_visitors == 9_000_000
        assert louvre.visitor_year == 2025
        assert "Louvre" in (louvre.wikipedia_url or "")


# ---------------------------------------------------------------------------
# enrich_populations tests
# ---------------------------------------------------------------------------

class TestEnrichPopulations:
    def test_enriches_matching_cities(self, in_memory_session: Session) -> None:
        """Check that API population data is successfully written to the correct City rows."""
        load_museums(SAMPLE_RECORDS, in_memory_session)
        in_memory_session.flush()
        cities = in_memory_session.query(City).all()

        mock_populations = [
            CityPopulation(name="Paris", country="France", wikidata_qid="Q90", population=2_161_000),
            CityPopulation(name="London", country="United Kingdom", wikidata_qid="Q84", population=8_982_000),
        ]

        with patch("museums.pipeline.etl.fetch_city_populations", return_value=mock_populations):
            enrich_populations(cities, in_memory_session)

        paris = in_memory_session.query(City).filter_by(name="Paris").one()
        assert paris.population == 2_161_000
        assert paris.wikidata_qid == "Q90"

    def test_skips_cities_without_population(self, in_memory_session: Session) -> None:
        """Catch null handling edge cases: Ensure the pipeline doesn't crash when a city's population is missing."""
        load_museums(SAMPLE_RECORDS, in_memory_session)
        in_memory_session.flush()
        cities = in_memory_session.query(City).all()

        mock_populations = [
            CityPopulation(name="Paris", country="France", wikidata_qid="Q90", population=None),
            CityPopulation(name="London", country="United Kingdom", wikidata_qid="unknown", population=None),
        ]

        with patch("museums.pipeline.etl.fetch_city_populations", return_value=mock_populations):
            enrich_populations(cities, in_memory_session)

        paris = in_memory_session.query(City).filter_by(name="Paris").one()
        assert paris.population is None
