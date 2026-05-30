"""ETL pipeline: ingest museum and city data, load into PostgreSQL."""

import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

from museums.db.session import get_session, init_db
from museums.ingestion.population import fetch_city_populations
from museums.ingestion.wikipedia import MuseumRecord, fetch_museums
from museums.models.schema import City, Museum

logger = logging.getLogger(__name__)


def _upsert_city(session: Session, name: str, country: str) -> City:
    """Return an existing City row or create a new one.

    Args:
        session: Active SQLAlchemy session.
        name: City name.
        country: Country name.

    Returns:
        The City ORM object (existing or newly created, not yet committed).
    """
    city = session.query(City).filter_by(name=name, country=country).first()
    if city is None:
        city = City(name=name, country=country)
        session.add(city)
        session.flush()  # assigns city.id without committing
    return city


def load_museums(records: list[MuseumRecord], session: Session) -> list[City]:
    """Insert museum and city rows into the database.

    Cities are upserted so that multiple museums in the same city share one City row.
    Population data is added in a subsequent step (see enrich_populations).

    Args:
        records: Parsed museum records from the Wikipedia ingestion module.
        session: Active SQLAlchemy session.

    Returns:
        List of City objects created (used later for population enrichment).
    """
    cities_created: list[City] = []
    city_cache: dict[tuple[str, str], City] = {}

    for record in records:
        key = (record.city, record.country)
        if key not in city_cache:
            city = _upsert_city(session, record.city, record.country)
            city_cache[key] = city
            cities_created.append(city)
        else:
            city = city_cache[key]

        museum = Museum(
            name=record.name,
            city_id=city.id,
            annual_visitors=record.annual_visitors,
            visitor_year=record.visitor_year,
            wikipedia_url=record.wikipedia_url,
        )
        session.add(museum)

    logger.info("Loaded %d museums across %d cities", len(records), len(city_cache))
    return cities_created


def enrich_populations(cities: list[City], session: Session) -> None:
    """Fetch and store population data for each city.

    Args:
        cities: City ORM objects already present in the session.
        session: Active SQLAlchemy session.
    """
    city_inputs = [(city.name, city.country) for city in cities]
    city_populations = fetch_city_populations(city_inputs)

    pop_map = {(cp.name, cp.country): cp for cp in city_populations}
    enriched = 0

    for city in cities:
        cp = pop_map.get((city.name, city.country))
        if cp and cp.population is not None:
            city.population = cp.population
            city.wikidata_qid = cp.wikidata_qid
            enriched += 1

    logger.info(
        "Enriched %d / %d cities with population data", enriched, len(cities)
    )


def run(database_url: str | None = None) -> None:
    """Run the full ETL pipeline.

    Steps:
        1. Create database tables (idempotent).
        2. Fetch and parse the Wikipedia museum list.
        3. Load museums and cities into PostgreSQL.
        4. Enrich cities with Wikidata population data.

    Args:
        database_url: Override the connection string. Defaults to DATABASE_URL env var.
    """
    logging.basicConfig(level=logging.INFO)
    logger.info("Starting museum ETL pipeline")

    init_db(database_url)

    museum_records = fetch_museums()

    with get_session(database_url) as session:
        # TRUNCATE tables to ensure the ETL pipeline is idempotent and doesn't duplicate data
        session.execute(text("TRUNCATE TABLE museum, city RESTART IDENTITY CASCADE"))
        session.commit()
        
        cities = load_museums(museum_records, session)
        enrich_populations(cities, session)
        session.commit()

    logger.info("Pipeline complete")
