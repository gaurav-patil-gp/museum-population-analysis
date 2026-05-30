"""Wikidata population ingestion.

Resolves city names to Wikidata QIDs via the entity search API, then fetches
city populations in a single batched SPARQL query.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

import httpx
import yaml

logger = logging.getLogger(__name__)

WIKIDATA_API_URL = "https://www.wikidata.org/w/api.php"
WIKIDATA_SPARQL_URL = "https://query.wikidata.org/sparql"

# Load static mapping from YAML configuration file
CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "city_overrides.yaml"
try:
    with open(CONFIG_PATH) as f:
        MANUAL_CITY_QIDS = yaml.safe_load(f) or {}
except FileNotFoundError:
    logger.warning("Config file %s not found. Proceeding without static overrides.", CONFIG_PATH)
    MANUAL_CITY_QIDS = {}


@dataclass
class CityPopulation:
    """Population data for a city resolved from Wikidata."""

    name: str
    country: str
    wikidata_qid: str
    population: int | None


def resolve_city_qid(
    city_name: str,
    country: str,
    api_url: str = WIKIDATA_API_URL,
    client: httpx.Client | None = None,
) -> str | None:
    """Find the Wikidata QID for a city by name and country.

    Uses the wbsearchentities REST endpoint to search for the city, then picks
    the best match by checking the country field against the expected value.

    Args:
        city_name: City name string (e.g., "Paris").
        country: Country name used for disambiguation (e.g., "France").
        api_url: Wikidata API endpoint. Overridable for testing.
        client: Optional httpx.Client for connection reuse.

    Returns:
        Wikidata QID string (e.g., "Q90") or None if no match found.
    """
    if city_name in MANUAL_CITY_QIDS:
        qid = str(MANUAL_CITY_QIDS[city_name])
        logger.debug("Resolved %r (%s) -> %s (static mapping)", city_name, country, qid)
        return qid

    params = {
        "action": "wbsearchentities",
        "search": city_name,
        "language": "en",
        "type": "item",
        "format": "json",
        "limit": "5",
    }

    def do_get(c: httpx.Client) -> dict:  # type: ignore[type-arg]
        headers = {"User-Agent": "IvadoMuseums/1.0 (test@example.com)"}
        response = c.get(api_url, params=params, headers=headers, timeout=15)
        response.raise_for_status()
        return response.json()  # type: ignore[no-any-return]

    if client:
        data = do_get(client)
    else:
        with httpx.Client() as c:
            data = do_get(c)

    results = data.get("search", [])
    if not results:
        logger.debug("No Wikidata results for city %r", city_name)
        return None

    # Check if the country name appears in any of the top results' descriptions.
    for result in results:
        desc = result.get("description", "").lower()
        if country.lower() in desc:
            qid = str(result["id"])
            logger.debug("Resolved %r (%s) -> %s (matched description)", city_name, country, qid)
            return qid

    # Fallback to the first result if no description matches
    qid = str(results[0]["id"])
    logger.debug("Resolved %r (%s) -> %s (fallback to first result)", city_name, country, qid)
    return qid


def fetch_populations(
    qids: list[str],
    sparql_url: str = WIKIDATA_SPARQL_URL,
    client: httpx.Client | None = None,
) -> dict[str, int]:
    """Fetch population for a list of Wikidata QIDs in a single SPARQL query.

    Uses wdt:P1082 (population) with the "preferred" rank, which Wikidata uses
    to mark the most current value when multiple exist.

    Args:
        qids: List of Wikidata QID strings (e.g., ["Q90", "Q956"]).
        sparql_url: Wikidata SPARQL endpoint. Overridable for testing.
        client: Optional httpx.Client for connection reuse.

    Returns:
        Dict mapping QID -> population integer. Missing QIDs are omitted.
    """
    if not qids:
        return {}

    values_clause = " ".join(f"wd:{qid}" for qid in qids)
    query = f"""
    SELECT ?city ?population WHERE {{
        VALUES ?city {{ {values_clause} }}
        ?city wdt:P1082 ?population .
    }}
    """

    headers = {
        "Accept": "application/sparql-results+json",
        "User-Agent": "IvadoMuseums/1.0 (test@example.com)",
    }

    def do_query(c: httpx.Client) -> dict:  # type: ignore[type-arg]
        response = c.get(
            sparql_url,
            params={"query": query, "format": "json"},
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        return response.json()  # type: ignore[no-any-return]

    if client:
        data = do_query(client)
    else:
        with httpx.Client() as c:
            data = do_query(c)

    populations: dict[str, int] = {}
    for binding in data.get("results", {}).get("bindings", []):
        qid = binding["city"]["value"].split("/")[-1]  # "http://...entity/Q90" -> "Q90"
        pop_value = int(float(binding["population"]["value"]))
        # If a QID appears more than once (multiple P1082 values), keep the largest,
        # which is usually the metro area population.
        if qid not in populations or pop_value > populations[qid]:
            populations[qid] = pop_value

    logger.info("Fetched population data for %d / %d cities", len(populations), len(qids))
    return populations


def fetch_city_populations(
    cities: list[tuple[str, str]],
    api_url: str = WIKIDATA_API_URL,
    sparql_url: str = WIKIDATA_SPARQL_URL,
) -> list[CityPopulation]:
    """Resolve city names to QIDs and fetch their populations.

    Args:
        cities: List of (city_name, country) tuples.
        api_url: Wikidata API endpoint. Overridable for testing.
        sparql_url: Wikidata SPARQL endpoint. Overridable for testing.

    Returns:
        List of CityPopulation records, one per unique city. Cities that could
        not be resolved to a QID will have population=None and wikidata_qid="unknown".
    """
    # Deduplicate by (city, country) while preserving order.
    seen: set[tuple[str, str]] = set()
    unique_cities = [c for c in cities if not (c in seen or seen.add(c))]  # type: ignore[func-returns-value]

    qid_map: dict[tuple[str, str], str] = {}
    with httpx.Client() as client:
        for city_name, country in unique_cities:
            qid = resolve_city_qid(city_name, country, api_url=api_url, client=client)
            if qid:
                qid_map[(city_name, country)] = qid

    resolved_qids = list(set(qid_map.values()))
    logger.info("Resolved %d / %d cities to Wikidata QIDs", len(resolved_qids), len(unique_cities))

    populations = fetch_populations(resolved_qids, sparql_url=sparql_url)

    results: list[CityPopulation] = []
    for city_name, country in unique_cities:
        qid = qid_map.get((city_name, country))
        pop = populations.get(qid) if qid else None
        results.append(
            CityPopulation(
                name=city_name,
                country=country,
                wikidata_qid=qid or "unknown",
                population=pop,
            )
        )

    return results
