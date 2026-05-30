"""Global Pytest Fixtures.

Hint: pytest automatically discovers conftest.py, making these fixtures globally
available without importing them. Keeps tests DRY.
"""

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from museums.models.schema import Base


# ---------------------------------------------------------------------------
# Database Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def in_memory_session() -> Session:
    """SQLite in-memory session for fast, isolated pipeline tests.
    
    Prevents unit tests from polluting the real Postgres DB.
    """
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    session = factory()
    yield session
    session.close()


# ---------------------------------------------------------------------------
# Machine Learning Data Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_df() -> pd.DataFrame:
    """Small, synthetic dataset with a clear linear trend.
    
    Tests regression math without needing real Wikipedia data.
    """
    return pd.DataFrame(
        {
            "museum_name": ["Museum A", "Museum B", "Museum C", "Museum D", "Museum E"],
            "city_name": ["City A", "City B", "City C", "City D", "City E"],
            "country": ["AA", "BB", "CC", "DD", "EE"],
            "annual_visitors": [2_000_000, 3_000_000, 4_000_000, 5_000_000, 6_000_000],
            "visitor_year": [2024, 2024, 2024, 2024, 2024],
            "city_population": [1_000_000, 2_000_000, 3_000_000, 4_000_000, 5_000_000],
        }
    )


@pytest.fixture
def noisy_df() -> pd.DataFrame:
    """Dataset where city population is a poor predictor (low expected R²).

    Tests edge cases to ensure the model correctly handles zero correlation.
    """
    return pd.DataFrame(
        {
            "museum_name": ["A", "B", "C", "D", "E", "F"],
            "city_name": ["X", "Y", "Z", "W", "V", "U"],
            "country": ["XX", "YY", "ZZ", "WW", "VV", "UU"],
            "annual_visitors": [9_000_000, 2_100_000, 6_500_000, 2_200_000, 8_000_000, 2_500_000],
            "visitor_year": [2024, 2024, 2024, 2024, 2024, 2024],
            "city_population": [2_000_000, 21_000_000, 3_000_000, 19_000_000, 1_500_000, 18_000_000],
        }
    )
