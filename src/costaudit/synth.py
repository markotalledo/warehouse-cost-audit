"""Synthetic Snowflake export for a week of a small data platform.

It contains the patterns the audit looks for, each at a realistic scale:
a nightly dbt build and a second team's build scheduled at the same hour,
dashboards polling every 5 minutes, loads every minute, analysts scanning a
whole table, one model that spills, and a warehouse left running after dbt.

    python -m costaudit.synth tests/fixtures
"""

from __future__ import annotations

import csv
import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

START = datetime(2026, 1, 5, tzinfo=UTC)
DAYS = 7
COLUMNS = [
    "QUERY_ID",
    "USER_NAME",
    "WAREHOUSE_NAME",
    "WAREHOUSE_SIZE",
    "QUERY_TYPE",
    "QUERY_TEXT",
    "START_TIME",
    "TOTAL_ELAPSED_TIME",
    "EXECUTION_TIME",
    "QUEUED_OVERLOAD_TIME",
    "BYTES_SCANNED",
    "PARTITIONS_SCANNED",
    "PARTITIONS_TOTAL",
    "BYTES_SPILLED_TO_LOCAL_STORAGE",
    "BYTES_SPILLED_TO_REMOTE_STORAGE",
    "ROWS_PRODUCED",
]
WAREHOUSES = {"TRANSFORM_WH": "MEDIUM", "BI_WH": "SMALL", "LOAD_WH": "X-SMALL"}


def generate(seed: int = 7) -> tuple[list[dict], list[dict]]:
    rng = random.Random(seed)
    rows: list[dict] = []
    n = 0

    def add(user, wh, qtype, text, at, exec_s, queued_s=0.0, rows_out=0, parts=(0, 0), spill_gb=0.0):
        nonlocal n
        n += 1
        scanned, total = parts
        rows.append(
            {
                "QUERY_ID": f"q{n:07d}",
                "USER_NAME": user,
                "WAREHOUSE_NAME": wh,
                "WAREHOUSE_SIZE": WAREHOUSES[wh],
                "QUERY_TYPE": qtype,
                "QUERY_TEXT": text,
                "START_TIME": at.isoformat(timespec="seconds"),
                "TOTAL_ELAPSED_TIME": int((exec_s + queued_s) * 1000),
                "EXECUTION_TIME": int(exec_s * 1000),
                "QUEUED_OVERLOAD_TIME": int(queued_s * 1000),
                "BYTES_SCANNED": int(scanned * 16e6),
                "PARTITIONS_SCANNED": scanned,
                "PARTITIONS_TOTAL": total,
                "BYTES_SPILLED_TO_LOCAL_STORAGE": int(spill_gb * 1e9),
                "BYTES_SPILLED_TO_REMOTE_STORAGE": 0,
                "ROWS_PRODUCED": rows_out,
            }
        )

    for day in range(DAYS):
        d = START + timedelta(days=day)
        ds = d.date().isoformat()

        # Nightly dbt build at 13:00, and a second team's build at the same minute.
        t = d.replace(hour=13)
        for i in range(40):
            spill = 4.0 if i == 7 else 0.0
            exec_s = rng.uniform(150, 260) if i == 7 else rng.uniform(20, 120)
            add(
                "DBT",
                "TRANSFORM_WH",
                "CREATE_TABLE_AS_SELECT",
                f"create or replace table analytics.model_{i:02d} as select * from staging.src_{i:02d} "
                f"where loaded_at >= '{ds}'",
                t,
                exec_s,
                rows_out=rng.randint(10_000, 500_000),
                parts=(rng.randint(10, 60), 400),
                spill_gb=spill,
            )
            t += timedelta(seconds=exec_s)
        t = d.replace(hour=13)
        for i in range(20):
            exec_s = rng.uniform(20, 90)
            add(
                "DBT_MARKETING",
                "TRANSFORM_WH",
                "CREATE_TABLE_AS_SELECT",
                f"create or replace table marketing.model_{i:02d} as select * from analytics.model_{i:02d}",
                t,
                exec_s,
                queued_s=rng.uniform(60, 240),
                rows_out=rng.randint(1_000, 50_000),
                parts=(rng.randint(5, 30), 200),
            )
            t += timedelta(seconds=exec_s)

        # Three dashboard tiles refreshed every 5 minutes, all day.
        for minute in range(0, 24 * 60, 5):
            at = d + timedelta(minutes=minute)
            for tile in ("orders_today", "revenue_today", "active_sessions"):
                add(
                    "METABASE",
                    "BI_WH",
                    "SELECT",
                    f"select count(*), sum(total_cents) from analytics.{tile} "
                    f"where day = '{ds}' and source in ('web', 'ios')",
                    at,
                    rng.uniform(1.5, 5.0),
                    rows_out=rng.randint(1, 30),
                    parts=(rng.randint(1, 4), 50),
                )

        # A load every minute with a handful of rows.
        for minute in range(24 * 60):
            add(
                "LOADER",
                "LOAD_WH",
                "COPY",
                f"copy into raw.events from @events_stage/{ds}/{minute:04d}/ file_format = (type = json)",
                d + timedelta(minutes=minute),
                rng.uniform(0.8, 2.0),
                rows_out=rng.randint(3, 40),
            )

        # Analysts scanning the whole events table during business hours.
        for hour in range(15, 23):
            add(
                "ANALYST",
                "BI_WH",
                "SELECT",
                f"select customer_id, count(*) from analytics.events where lower(event_name) = 'order_completed' "
                f"and customer_id like 'c_{rng.randint(0, 9)}%' group by 1",
                d.replace(hour=hour, minute=rng.randint(0, 59)),
                rng.uniform(60, 180),
                rows_out=rng.randint(100, 5000),
                parts=(1950 + rng.randint(0, 50), 2000),
            )

    metering = []
    for day in range(DAYS):
        d = START + timedelta(days=day)
        for hour in range(24):
            at = (d + timedelta(hours=hour)).isoformat(timespec="seconds")
            metering.append({"WAREHOUSE_NAME": "BI_WH", "START_TIME": at, "CREDITS_USED_COMPUTE": 2.0})
            metering.append({"WAREHOUSE_NAME": "LOAD_WH", "START_TIME": at, "CREDITS_USED_COMPUTE": 1.0})
        # dbt finishes around 14:00, but auto-suspend is an hour: the warehouse runs until 16:00.
        for hour, credits in ((13, 4.0), (14, 4.0), (15, 4.0)):
            at = d.replace(hour=hour).isoformat(timespec="seconds")
            metering.append({"WAREHOUSE_NAME": "TRANSFORM_WH", "START_TIME": at, "CREDITS_USED_COMPUTE": credits})
    return rows, metering


def write(folder: str) -> None:
    out = Path(folder)
    out.mkdir(parents=True, exist_ok=True)
    queries, metering = generate()
    with open(out / "snowflake_queries.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(queries)
    with open(out / "snowflake_metering.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["WAREHOUSE_NAME", "START_TIME", "CREDITS_USED_COMPUTE"])
        w.writeheader()
        w.writerows(metering)
    print(f"{len(queries):,} queries, {len(metering):,} metering rows -> {out}")


if __name__ == "__main__":
    write(sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures")
