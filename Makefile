.PHONY: install test lint security check clean

install:  ## Install package + dev dependencies
	pip install -e ".[dev]"

test:  ## Run test suite
	python -m pytest tests/ -q --timeout=30

lint:  ## Run ruff linter
	ruff check steward/ tests/

format:  ## Auto-format with ruff
	ruff format steward/ tests/
	ruff check --fix steward/ tests/

security:  ## Run bandit security scan
	bandit -r steward/ -ll -q

check: lint security test  ## Run all checks (lint + security + tests)

clean:  ## Remove build artifacts
	rm -rf build/ dist/ *.egg-info .pytest_cache __pycache__
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
