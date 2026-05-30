# Implementation Notes

This document covers the architecture, data model, and the reasoning behind key decisions
made while building this project. It is intended for a code reviewer or anyone picking
this project up fresh.

---

## What this project does

It builds a small PostgreSQL database of museums with more than 2,000,000 annual visitors,
sourced from the Wikipedia "List of most-visited museums" article. Each museum is linked
to its host city, and each city is enriched with a population figure from Wikidata.

Once the database is populated, a linear regression model is fit to explore whether city
population is a useful predictor of museum attendance. The results are presented in a
Jupyter notebook that imports and calls the same Python package used to build the database.

Everything runs inside Docker. A single `docker compose up` fetches the data, builds the
database, and starts the notebook.

---

## Project layout

```
ivado-museums/
├── museums/             # installable Python package
│   ├── config.py        # env var loading
│   ├── ingestion/
│   │   ├── wikipedia.py # MediaWiki API client and wikitext parser
│   │   └── population.py# Wikidata entity search and SPARQL client
│   ├── models/
│   │   └── schema.py    # SQLAlchemy ORM: City, Museum
│   ├── db/
│   │   └── session.py   # engine and session factory
│   ├── pipeline/
│   │   ├── etl.py       # ingest -> transform -> load
│   │   └── __main__.py  # entry point for python -m museums.pipeline
│   └── ml/
│       └── regression.py# linear regression and chart generation
├── notebooks/
│   └── analysis.ipynb   # visual analysis using the museums package
├── config/
│   └── city_overrides.yaml # static QID mappings for edge cases
├── tests/               # pytest suite (no network calls)
│   └── conftest.py      # global test fixtures (e.g., in-memory DB)
├── Dockerfile           # multi-stage build
├── docker-compose.yml   # db + app + notebook services
├── pyproject.toml       # project metadata, deps, tool config
└── Makefile             # common tasks
```

The `museums` package is installed with `pip install -e .`, which means the notebook
can do `from museums.ml.regression import run_regression` and get the same code that
the pipeline uses. This directly satisfies the brief's requirement that the notebook
"programmatically uses your other code."

---

## Data sources

### Museums - MediaWiki Action API

The brief requires using the Wikipedia APIs. The list of most-visited museums is a
human-curated wikitable on a single article page. There is no dedicated API endpoint
for it, so the right approach is:

```
GET https://en.wikipedia.org/w/api.php
  ?action=parse
  &page=List_of_most-visited_museums
  &prop=wikitext
  &format=json
  &section=1
```

This returns the raw wikitext for the table section. The wikitext is then parsed with
`mwparserfromhell`, a dedicated wikitext parser. This is the correct way to use the
Wikipedia API for list pages - using BeautifulSoup on the HTML endpoint is explicitly
discouraged by Wikimedia and would have been wrong to call "using the API."

The wikitext table has several inconsistencies that the parser handles:

- Visitor counts appear in multiple formats: `9,000,000`, `3.2 million`, `2.61 million`,
  `~4 million`. The `parse_visitors()` function normalizes all of these to integers.
- Each count includes the reporting year in parentheses, e.g. `9,000,000 (2025)`. The
  year is extracted and stored in `museum.visitor_year`.
- Inline `<ref>` citation tags appear mid-cell and must be stripped before parsing.
- Museum names use piped wikilinks: `[[Article Title|Display Name]]`. The display name
  is used as the museum name; the article title builds the Wikipedia URL.
- Some city cells contain multiple values: `[[Vatican City]], [[Rome]]`. The parser
  takes the first wikilink.
- Country cells use the `{{flag|France}}` template. The country name is extracted from
  the template parameter.
- The first table row has a stray rank number: `|1 |[[Louvre]]`. This is stripped
  before extracting the museum name.

Museums with fewer than 2,000,000 annual visitors are filtered out after parsing.

### City populations - Wikidata SPARQL

City populations are sourced from Wikidata rather than an external API like GeoNames or
the World Bank. The reasons:

1. No API key required.
2. Data provenance stays within the Wikimedia ecosystem, which is consistent with
   sourcing museum data from Wikipedia.
3. Wikidata population data (property P1082) is generally current and covers all cities
   in this dataset.

Population lookup is a two-step process:

**Step 1 - Resolve city name to QID**.
First, the pipeline checks `config/city_overrides.yaml`. If a city (like Vatican City or Singapore) is listed there, it bypasses the API to prevent fragile dynamic matching.
For all other cities, it queries the `wbsearchentities` REST endpoint:
```
GET https://www.wikidata.org/w/api.php
  ?action=wbsearchentities
  &search=Paris
  &language=en
  &type=item
  &format=json
```
The first result matching the country description is taken. For standard cities in this dataset, this API search is highly reliable.

**Step 2 - Fetch populations in one batched SPARQL query** for all resolved QIDs:
```sparql
SELECT ?city ?population WHERE {
    VALUES ?city { wd:Q90 wd:Q956 ... }
    ?city wdt:P1082 ?population .
}
```
`wdt:P1082` returns the preferred-rank value, which Wikidata uses to mark the most
current population figure when multiple exist. If a city has multiple P1082 values
(e.g. city proper vs metro area), the largest is kept.

Batching into a single SPARQL query avoids making N individual HTTP requests for N
cities and keeps within Wikidata's unauthenticated rate limits.

---

## Database

PostgreSQL 17 running as a Docker Compose service. The schema is managed by SQLAlchemy
using the 2.x declarative API with full type annotations (`Mapped[T]`).

### Schema

**city**

| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL PK | |
| name | TEXT | |
| country | TEXT | |
| population | BIGINT | Nullable - some cities may not resolve |
| wikidata_qid | TEXT UNIQUE | e.g. "Q90" for Paris, for traceability |

**museum**

| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL PK | |
| name | TEXT | |
| city_id | INT FK | References city.id |
| annual_visitors | BIGINT | Filtered to >= 2,000,000 |
| visitor_year | INT | Year the count was reported |
| museum_type | TEXT | Nullable - not present in the Wikipedia table |
| wikipedia_url | TEXT | Built from the article wikilink |

Multiple museums in the same city share one `city` row. The ETL pipeline upserts cities
so that the Louvre and the Musee d'Orsay, both in Paris, point to the same `city.id`.

### Why PostgreSQL and not SQLite

SQLite would work at this data size (roughly 30-40 rows). PostgreSQL was chosen because:

- It runs cleanly as a Compose service - anyone running `docker compose up` gets a
  production-grade database without installing anything locally.
- The connection string is the only thing that changes when scaling to a managed instance
  (RDS, Cloud SQL, etc.). The application code is identical.
- It gives a more realistic project structure for a team codebase.

To switch to a managed PostgreSQL instance, change `DATABASE_URL` in `.env`. Nothing else
needs to change.

### Why SQLAlchemy and not raw psycopg

SQLAlchemy 2.x with the declarative ORM gives a clean separation between the schema
definition (`models/schema.py`) and the data access logic (`db/session.py`, `pipeline/etl.py`).
The ORM models serve as the single source of truth for the schema - tables are created
from them with `Base.metadata.create_all(engine)`, no separate migration tool needed for
a project of this size.

---

## ETL pipeline

The pipeline runs in three steps:

1. `fetch_museums()` - hits the MediaWiki API and returns a list of `MuseumRecord` dataclasses.
2. `load_museums()` - upserts City rows and inserts Museum rows. Uses `session.flush()`
   after each new City to get its `id` assigned before the Museum FK is set, without
   committing early.
3. `enrich_populations()` - resolves each city to a Wikidata QID and fetches populations
   in a single batched SPARQL query. Updates the City rows in place.

Steps 2 and 3 run inside a single `get_session()` context manager, so the whole load
either commits or rolls back together.

Population enrichment is a separate function from museum loading deliberately. If Wikidata
is slow or partially unavailable, the museums are still loaded. The pipeline does not fail
on missing population data - cities that cannot be resolved get `population=NULL` and
`wikidata_qid='unknown'`.

Run the pipeline:
```bash
python -m museums.pipeline       # locally
docker compose up app            # in Docker
```

---

## ML model

A simple linear regression using `scikit-learn`'s `LinearRegression`.

- **Feature (X):** city population
- **Target (y):** annual museum visitors
- **Output:** slope, intercept, R-squared, number of observations, matplotlib figure

The `run_regression()` function takes a pandas DataFrame rather than a database URL.
This keeps the model function pure and testable without a database connection, and
lets the notebook manipulate the data before fitting if needed.

The `load_regression_data()` function handles the database query. Museums in cities
without a population value are excluded from the regression dataset.

### Interpreting the results

R-squared will likely be low (below 0.5) on this dataset. That is not a bug - it
reflects a real limitation of the model. Museums like the Louvre or the British Museum
draw visitors globally regardless of Paris or London's population. A city's size is a
weak predictor of any individual museum's attendance because attendance depends on
factors this model does not capture: tourism draw, admission price, collection prestige,
proximity to other attractions, and how long the museum has been operating.

The notebook states this explicitly. Acknowledging model limitations is part of the
analysis, not a footnote to hide.

One structural note: cities with multiple museums in this dataset (London has six,
Paris has four) each contribute multiple data points that all share the same X value.
This is worth keeping in mind when reading the scatter plot.

---

## Testing

The test suite uses `pytest`. All external HTTP calls (Wikipedia, Wikidata) are mocked.
No real network calls are made when running `make test`.

```
tests/
├── conftest.py             # Global fixtures (e.g. in_memory_session, fake DataFrames)
├── ingestion/
│   ├── test_wikipedia.py   # parse_visitors formats, table edge cases, mocked fetch
│   └── test_population.py  # QID resolution, SPARQL batching, deduplication
├── pipeline/
│   └── test_etl.py         # city upsert, FK assignment, population enrichment
└── ml/
    └── test_regression.py  # model output, edge cases, figure creation
```

ETL tests use an in-memory SQLite database (via SQLAlchemy's engine abstraction) so
they run fast without a running PostgreSQL instance.

The test for `parse_visitors` covers every format variant that appears in the actual
Wikipedia API response, verified by pulling the real wikitext during development.

Run the suite:
```bash
make test
# or
pytest -v
```

---

## Docker setup

Two Docker images are defined - one used by both the `app` and `notebook` services.

### Dockerfile

Multi-stage build. The builder stage installs all dependencies (including jupyterlab).
The runtime stage copies only the installed site-packages and the application source.
`psycopg[binary]` ships with pre-built wheels, so no `libpq-dev` or C compiler is
needed in either stage.

Dependency installation is split into two layers:

```dockerfile
COPY pyproject.toml .
RUN pip install ...          # installs deps - cached unless pyproject.toml changes

COPY config/ config/
COPY museums/ museums/
RUN pip install .            # installs the package - re-runs on any source change
```

This keeps Docker layer caching effective. Changing application code does not
invalidate the dependency install layer.

### Compose services

| Service | Role | Ports |
|---------|------|-------|
| `db` | PostgreSQL 17 | 5432 |
| `app` | Runs the ETL pipeline once, then exits | - |
| `notebook` | Jupyter Lab | 8888 |

The `notebook` service has two `depends_on` conditions:
- `db: condition: service_healthy` - waits for Postgres to accept connections
- `app: condition: service_completed_successfully` - waits for data to be loaded

This ensures the notebook opens with data already in the database rather than an empty
schema.

The Postgres data volume (`postgres_data`) persists between `docker compose up/down`
cycles. To reset the database and re-run the pipeline from scratch:

```bash
docker compose down -v   # -v removes the volume
docker compose up
```

---

## Configuration

Two environment variables:

| Variable | Default (in Compose) | Description |
|----------|---------------------|-------------|
| `DATABASE_URL` | `postgresql+psycopg://museums:museums@db:5432/museums` | PostgreSQL connection string |
| `LOG_LEVEL` | `INFO` | Python logging level |

For local development outside Docker, copy `.env.example` to `.env` and run
`docker compose up db` to start only the database service.

---

## Dependencies and tooling

| Tool | Role |
|------|------|
| `httpx` | HTTP client for MediaWiki and Wikidata APIs |
| `mwparserfromhell` | Wikitext parser - handles templates, wikilinks, tables |
| `sqlalchemy[mypy]` | ORM with type stub support |
| `psycopg[binary]` | PostgreSQL driver (psycopg v3, binary wheels) |
| `scikit-learn` | Linear regression model |
| `matplotlib` | Scatter plot and regression line figure |
| `pandas` | DataFrame used as the input to `run_regression()` |
| `ruff` | Linting and formatting (replaces black + flake8 + isort) |
| `mypy` | Static type checking, strict mode |
| `pytest` | Test runner |
| `pre-commit` | Enforces ruff and mypy on every commit |

`httpx` was chosen over `requests` because it has complete type stubs, which matters
with mypy in strict mode. `requests` has historically incomplete typing.

`psycopg[binary]` (v3, not psycopg2) was chosen because it is the current version of
the driver, supports async if needed, and the binary wheel avoids any native build
dependency in Docker.

`mwparserfromhell` over regex or BeautifulSoup: wikitext has a formal grammar and nested
structures (templates inside links inside tables). Parsing it correctly requires a real
parser. Regex on wikitext breaks on edge cases that `mwparserfromhell` handles natively.
