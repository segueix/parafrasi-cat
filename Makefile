.PHONY: install test lint typecheck check tree

install:
	pip install -e ".[dev]"

test:
	python -m pytest

lint:
	ruff check src tests examples
	ruff format --check src tests examples

format:
	ruff format src tests examples
	ruff check --fix src tests examples

typecheck:
	python -m mypy

check: lint typecheck test

tree:
	@find . -path ./.git -prune -o -path '*/__pycache__' -prune -o -path ./.mypy_cache -prune \
	  -o -path ./.pytest_cache -prune -o -path ./.ruff_cache -prune -o -path '*.egg-info' -prune \
	  -o -print | sed -e 's|[^/]*/|  |g'
