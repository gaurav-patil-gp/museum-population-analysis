"""Linear regression: city population vs museum annual visitors."""

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.metrics import r2_score

from museums.db.session import get_session
from museums.models.schema import City, Museum

logger = logging.getLogger(__name__)


@dataclass
class RegressionResult:
    """Output of the linear regression model."""

    slope: float
    intercept: float
    r_squared: float
    n_observations: int


def load_regression_data(database_url: str | None = None) -> pd.DataFrame:
    """Load museum and city data from the database for regression analysis.

    Returns a DataFrame with one row per museum, containing:
        - museum_name
        - city_name
        - country
        - annual_visitors
        - visitor_year
        - city_population

    Museums in cities with no population data are excluded.

    Args:
        database_url: Override the connection string. Defaults to DATABASE_URL env var.

    Returns:
        DataFrame ready for regression. May be empty if no data is loaded.
    """
    rows = []
    with get_session(database_url) as session:
        results = (
            session.query(Museum, City)
            .join(City, Museum.city_id == City.id)
            .filter(City.population.isnot(None))
            .all()
        )
        for museum, city in results:
            rows.append(
                {
                    "museum_name": museum.name,
                    "city_name": city.name,
                    "country": city.country,
                    "annual_visitors": museum.annual_visitors,
                    "visitor_year": museum.visitor_year,
                    "city_population": city.population,
                }
            )

    df = pd.DataFrame(rows)
    logger.info("Loaded %d museum rows for regression", len(df))
    return df


def run_regression(df: pd.DataFrame) -> RegressionResult:
    """Fit a simple linear regression of museum visitors on city population.

    Args:
        df: DataFrame produced by load_regression_data(). Must contain
            'city_population' and 'annual_visitors' columns.

    Returns:
        RegressionResult with model parameters and a matplotlib figure.

    Raises:
        ValueError: If the DataFrame has fewer than 2 rows.
    """
    if len(df) < 2:
        raise ValueError(f"Need at least 2 data points for regression, got {len(df)}")

    X = df[["city_population"]].to_numpy()
    y = df["annual_visitors"].to_numpy()

    model = LinearRegression()
    model.fit(X, y)

    y_pred = model.predict(X)
    r2 = float(r2_score(y, y_pred))
    slope = float(model.coef_[0])
    intercept = float(model.intercept_)  # type: ignore[arg-type]

    logger.info(
        "Regression: slope=%.4f, intercept=%.0f, R²=%.4f, n=%d",
        slope,
        intercept,
        r2,
        len(df),
    )

    return RegressionResult(
        slope=slope,
        intercept=intercept,
        r_squared=r2,
        n_observations=len(df),
    )
