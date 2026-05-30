.PHONY: install run test lint format build up down clean

install:
	pip install -e ".[dev,notebook]"

run:
	python -m museums.pipeline

test:
	pytest -v --cov=museums --cov-report=term-missing

lint:
	ruff check .
	mypy --strict museums/

format:
	ruff format .
	ruff check --fix .

build:
	docker compose build

up:
	docker compose up

down:
	docker compose down -v

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	find . -type d -name "dist" -exec rm -rf {} +
	find . -name "*.pyc" -delete
