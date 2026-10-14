.PHONY: run sync lint format typecheck test check

run:
	uv run --frozen main.py

sync:
	uv sync --frozen

lint:
	uv run --frozen ruff check main.py api tests

format:
	uv run --frozen ruff format --check main.py api tests

typecheck:
	uvx pyright --pythonpath .venv/bin/python

test:
	uv run --frozen pytest -q

check: lint format typecheck test
