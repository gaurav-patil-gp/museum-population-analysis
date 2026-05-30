"""Application configuration loaded from environment variables."""

import logging
import os


def get_database_url() -> str:
    """Return the PostgreSQL connection string.

    Reads DATABASE_URL from the environment. Raises if not set.
    """
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL environment variable is not set. "
            "Copy .env.example to .env and fill in the value."
        )
    return url


def get_log_level() -> int:
    """Return the logging level from LOG_LEVEL env var (default: INFO)."""
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    return int(level)
