import csv

import pytest

from costaudit.fingerprint import fingerprint
from costaudit.model import load_redshift, load_snowflake


def test_queries_that_differ_only_in_literals_share_a_fingerprint():
    a = "select * from t where day = '2026-01-01' and n > 5"
    b = "select * from t where day = '2026-02-14' and n > 900"
    assert fingerprint(a) == fingerprint(b)
    assert fingerprint(a) != fingerprint("select * from u where day = '2026-01-01' and n > 5")


def test_unparseable_sql_still_gets_a_fingerprint():
    assert fingerprint("copy into x from @stage/2026/01 file_format = (type = json)") == fingerprint(
        "copy into x from @stage/2027/12 file_format = (type = json)"
    )


def _write(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def test_snowflake_cost_is_execution_time_at_warehouse_rate(tmp_path):
    row = {
        "QUERY_ID": "1",
        "USER_NAME": "u",
        "WAREHOUSE_NAME": "W",
        "WAREHOUSE_SIZE": "Medium",
        "QUERY_TYPE": "SELECT",
        "QUERY_TEXT": "select 1",
        "START_TIME": "2026-01-01 10:00:00",
        "TOTAL_ELAPSED_TIME": "3600000",
        "EXECUTION_TIME": "3600000",
        "QUEUED_OVERLOAD_TIME": "0",
        "BYTES_SCANNED": "0",
        "PARTITIONS_SCANNED": "0",
        "PARTITIONS_TOTAL": "0",
        "BYTES_SPILLED_TO_LOCAL_STORAGE": "0",
        "BYTES_SPILLED_TO_REMOTE_STORAGE": "0",
        "ROWS_PRODUCED": "1",
    }
    _write(tmp_path / "q.csv", [row])
    # One hour on a Medium warehouse = 4 credits.
    assert load_snowflake(tmp_path / "q.csv", credit_price=3.0)[0].cost_usd == pytest.approx(12.0)


def test_redshift_times_are_microseconds(tmp_path):
    row = {
        "query_id": "1",
        "user_id": "100",
        "query_type": "SELECT",
        "query_text": "select 1",
        "start_time": "2026-01-01 10:00:00",
        "elapsed_time": "2000000",
        "execution_time": "1500000",
        "queue_time": "500000",
        "returned_rows": "1",
        "spilled_blocks": "3",
        "blocks_read": "10",
    }
    _write(tmp_path / "r.csv", [row])
    q = load_redshift(tmp_path / "r.csv", cluster_usd_per_hour=3.6)[0]
    assert q.execution_ms == 1500 and q.queued_ms == 500
    assert q.bytes_spilled == 3 * 1024 * 1024
    assert q.cost_usd == pytest.approx(1500 / 3_600_000 * 3.6)
