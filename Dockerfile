# syntax=docker/dockerfile:1

# --- Stage 1: Builder ---
# Install all dependencies into a venv so we can copy only what's needed to the runtime stage.
FROM python:3.13-slim-bookworm AS builder

WORKDIR /app

# Install pip dependencies before copying source code so this layer is cached
# as long as pyproject.toml doesn't change.
COPY pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir ".[notebook]"

# Now copy the source and install the package itself (editable=false).
COPY config/ config/
COPY museums/ museums/
RUN pip install --no-cache-dir .

# --- Stage 2: Runtime ---
FROM python:3.13-slim-bookworm

WORKDIR /app

# Copy the installed site-packages, scripts, and Jupyter assets from the builder.
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /usr/local/share/jupyter /usr/local/share/jupyter

# Copy application source.
COPY --from=builder /app /app

# Also copy notebooks so they are available in the notebook service.
COPY config/ config/
COPY notebooks/ notebooks/

# Default command runs the ETL pipeline.
# The notebook service overrides this in docker-compose.yml.
CMD ["python", "-m", "museums.pipeline"]
