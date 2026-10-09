.PHONY: setup test lint fixtures sample

setup:
	uv sync

test:
	uv run pytest -q

lint:
	uv run ruff check .
	uv run ruff format --check .

fixtures:
	uv run python -m costaudit.synth tests/fixtures

sample:
	uv run costaudit snowflake tests/fixtures/snowflake_queries.csv --credit-price 3 \
		--metering tests/fixtures/snowflake_metering.csv -o docs/sample_report.md
