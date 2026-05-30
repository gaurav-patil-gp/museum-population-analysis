"""Wikipedia museum list ingestion.

Fetches the raw wikitext for the 'List of most-visited museums' article via the
MediaWiki Action API and parses the sortable wikitable into structured records.
"""

import logging
import re
from dataclasses import dataclass

import httpx
import mwparserfromhell

logger = logging.getLogger(__name__)

MEDIAWIKI_API_URL = "https://en.wikipedia.org/w/api.php"
WIKIPEDIA_BASE_URL = "https://en.wikipedia.org/wiki"
PAGE_TITLE = "List_of_most-visited_museums"
MIN_VISITORS = 2_000_000


@dataclass
class MuseumRecord:
    """Raw museum data parsed from the Wikipedia table, before DB insertion."""

    name: str
    city: str
    country: str
    annual_visitors: int
    visitor_year: int | None
    wikipedia_url: str | None


def fetch_wikitext(api_url: str = MEDIAWIKI_API_URL) -> str:
    """Fetch the raw wikitext for the museum list article.

    Args:
        api_url: MediaWiki Action API endpoint. Overridable for testing.

    Returns:
        Raw wikitext string.

    Raises:
        httpx.HTTPStatusError: If the API returns a non-2xx response.
        KeyError: If the response JSON structure is unexpected.
    """
    params = {
        "action": "parse",
        "page": PAGE_TITLE,
        "prop": "wikitext",
        "format": "json",
        "section": "1",
    }
    headers = {"User-Agent": "IvadoMuseums/1.0 (test@example.com)"}
    response = httpx.get(api_url, params=params, headers=headers, timeout=30)
    response.raise_for_status()
    data = response.json()
    wikitext: str = data["parse"]["wikitext"]["*"]
    logger.info("Fetched wikitext for %s", PAGE_TITLE)
    return wikitext


def _extract_wikilink_target(text: str) -> str:
    """Return the display text from a wikilink, stripping the article title if piped.

    Examples:
        [[Paris]] -> "Paris"
        [[Natural History Museum, London|Natural History Museum]] -> "Natural History Museum"
    """
    wikicode = mwparserfromhell.parse(text)
    links = wikicode.filter_wikilinks()
    if links:
        link = links[0]
        # If the link has a display text after the pipe, use that; otherwise use the target.
        display = str(link.text) if link.text else str(link.title)
        return display.strip()
    # Fallback: strip all markup and return plain text.
    return wikicode.strip_code().strip()


def _extract_flag_country(text: str) -> str:
    """Extract the country name from a {{flag|Country}} template.

    Falls back to stripping all markup if no flag template is found.
    """
    wikicode = mwparserfromhell.parse(text)
    for template in wikicode.filter_templates():
        if str(template.name).strip().lower() == "flag":
            return str(template.params[0].value).strip()
    return wikicode.strip_code().strip()


def parse_visitors(raw: str) -> tuple[int, int | None]:
    """Normalize a visitor count string to an integer and extract the year.

    Handles formats found in the actual Wikipedia table:
        "9,000,000 (2025)"
        "3.2 million (2024)"
        "2.61 million (2024)"
        "~4 million"

    Args:
        raw: Raw cell text from the wikitext table.

    Returns:
        Tuple of (visitor_count, year_or_None).

    Raises:
        ValueError: If no numeric value can be parsed.
    """
    # Strip ref tags and wiki markup first.
    text = re.sub(r"<ref[^>]*>.*?</ref>", "", raw, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", "", text)
    text = mwparserfromhell.parse(text).strip_code()
    text = text.strip()

    # Extract the year from parentheses, e.g. "(2025)".
    year: int | None = None
    year_match = re.search(r"\((\d{4})\)", text)
    if year_match:
        year = int(year_match.group(1))
        text = text[: year_match.start()].strip()

    # Strip leading approximation symbols.
    text = text.lstrip("~").strip()

    # Handle "X.Y million" or "X million" format.
    million_match = re.match(r"([\d.]+)\s*million", text, re.IGNORECASE)
    if million_match:
        count = int(float(million_match.group(1)) * 1_000_000)
        return count, year

    # Handle comma-formatted integers: "9,000,000".
    plain = text.replace(",", "").split()[0]
    try:
        return int(float(plain)), year
    except ValueError as exc:
        raise ValueError(f"Cannot parse visitor count from: {raw!r}") from exc


def parse_table(wikitext: str) -> list[MuseumRecord]:
    """Parse the wikitable into a list of MuseumRecord objects.

    Applies the >2M visitor filter after parsing.

    Args:
        wikitext: Raw wikitext string from the MediaWiki API.

    Returns:
        List of MuseumRecord for museums with >= 2,000,000 annual visitors.
    """
    wikicode = mwparserfromhell.parse(wikitext)
    tables = wikicode.filter_tags(matches=lambda n: n.tag == "table")
    if not tables:
        raise ValueError("No wikitable found in wikitext")

    records: list[MuseumRecord] = []

    for table in tables:
        rows = table.contents.filter_tags(matches=lambda n: n.tag == "tr")
        for row in rows:
            cells = row.contents.filter_tags(matches=lambda n: n.tag in ("td", "th"))
            if not cells or len(cells) < 4:
                continue

            # Skip the header row.
            cell_tags = [str(c.tag) for c in cells]
            if all(t == "th" for t in cell_tags):
                continue

            raw_cells = [str(c.contents) for c in cells]

            # The name cell may have a stray rank number (e.g., "1 |[[Louvre]]").
            # Strip leading digits and pipes.
            name_raw = re.sub(r"^\d+\s*\|", "", raw_cells[0]).strip()
            name = _extract_wikilink_target(name_raw)
            if not name:
                continue

            try:
                visitors, year = parse_visitors(raw_cells[1])
            except ValueError:
                logger.debug("Skipping row with unparseable visitor count: %r", raw_cells[1])
                continue

            if visitors < MIN_VISITORS:
                continue

            # City: take the first wikilink when multiple are present (e.g., Vatican City + Rome).
            city_raw = raw_cells[2]
            city = _extract_wikilink_target(city_raw)
            if not city:
                city = mwparserfromhell.parse(city_raw).strip_code().strip()

            country = _extract_flag_country(raw_cells[3])

            # Build the Wikipedia article URL from the piped link target (article title).
            wiki_url: str | None = None
            links = mwparserfromhell.parse(name_raw).filter_wikilinks()
            if links:
                article_title = str(links[0].title).strip().replace(" ", "_")
                wiki_url = f"{WIKIPEDIA_BASE_URL}/{article_title}"

            records.append(
                MuseumRecord(
                    name=name,
                    city=city,
                    country=country,
                    annual_visitors=visitors,
                    visitor_year=year,
                    wikipedia_url=wiki_url,
                )
            )

    logger.info("Parsed %d museums with >= %d visitors", len(records), MIN_VISITORS)
    return records


def fetch_museums(api_url: str = MEDIAWIKI_API_URL) -> list[MuseumRecord]:
    """Fetch and parse the Wikipedia museum list end to end.

    Args:
        api_url: MediaWiki Action API endpoint. Overridable for testing.

    Returns:
        List of MuseumRecord for museums with >= 2,000,000 annual visitors.
    """
    wikitext = fetch_wikitext(api_url)
    return parse_table(wikitext)
