"""Tests for the linear regression module."""

import pandas as pd
import pytest

from museums.ml.regression import RegressionResult, run_regression



# ---------------------------------------------------------------------------
# run_regression tests
# ---------------------------------------------------------------------------

class TestRunRegression:
    def test_returns_regression_result(self, sample_df: pd.DataFrame) -> None:
        """Verify the function correctly returns a structured RegressionResult object."""
        result = run_regression(sample_df)
        assert isinstance(result, RegressionResult)

    def test_perfect_linear_data_high_r_squared(self, sample_df: pd.DataFrame) -> None:
        """Ensure the regression model correctly calculates a high R² score for perfectly linear synthetic data."""
        result = run_regression(sample_df)
        # Perfectly linear data should have R² near 1.0.
        assert result.r_squared > 0.99

    def test_slope_is_positive(self, sample_df: pd.DataFrame) -> None:
        """Check that the slope correctly reflects the positive correlation in the sample dataset."""
        result = run_regression(sample_df)
        assert result.slope > 0

    def test_n_observations_correct(self, sample_df: pd.DataFrame) -> None:
        """Verify that the model accurately reports the number of valid observations used in training."""
        result = run_regression(sample_df)
        assert result.n_observations == 5

    def test_raises_on_insufficient_data(self) -> None:
        """Catch edge cases where the dataset is too small (e.g., < 2 rows) to perform a linear regression."""
        df = pd.DataFrame(
            {
                "museum_name": ["Only One"],
                "city_name": ["X"],
                "country": ["XX"],
                "annual_visitors": [5_000_000],
                "visitor_year": [2024],
                "city_population": [1_000_000],
            }
        )
        with pytest.raises(ValueError, match="at least 2"):
            run_regression(df)

