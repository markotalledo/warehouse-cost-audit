from pathlib import Path

import pytest

from costaudit.model import load_snowflake, load_snowflake_metering

FIXTURES = Path(__file__).parent / "fixtures"
PRICE = 3.0


@pytest.fixture(scope="session")
def queries():
    return load_snowflake(FIXTURES / "snowflake_queries.csv", PRICE)


@pytest.fixture(scope="session")
def metering():
    return load_snowflake_metering(FIXTURES / "snowflake_metering.csv")
