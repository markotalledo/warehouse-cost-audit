"""Normalized query records, loaded from Snowflake or Redshift CSV exports.

Cost is attributed to each query by its share of compute time. That is an
estimate: it ignores cloud services credits on Snowflake and idle cluster time
on Redshift. Idle time is measured separately, from metering data.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# Credits per hour by Snowflake warehouse size (standard warehouses).
SNOWFLAKE_CREDITS_PER_HOUR = {
    "X-SMALL": 1,
    "SMALL": 2,
    "MEDIUM": 4,
    "LARGE": 8,
    "X-LARGE": 16,
    "2X-LARGE": 32,
    "3X-LARGE": 64,
    "4X-LARGE": 128,
}


@dataclass(frozen=True)
class Query:
    query_id: str
    user: str
    warehouse: str
    query_type: str
    text: str
    start: datetime
    execution_ms: float
    queued_ms: float
    rows: int
    bytes_scanned: int
    bytes_spilled: int
    partitions_scanned: int | None
    partitions_total: int | None
    cost_usd: float


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value.strip().replace("Z", "+00:00").replace(" ", "T", 1))


def _int(value: str | None) -> int:
    return int(float(value)) if value not in (None, "") else 0


def load_snowflake(path: str | Path, credit_price: float) -> list[Query]:
    """CSV from queries/snowflake_export.sql."""
    out = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            r = {k.lower(): v for k, v in r.items()}
            credits_per_hour = SNOWFLAKE_CREDITS_PER_HOUR.get((r["warehouse_size"] or "").upper(), 1)
            execution_ms = float(r["execution_time"] or 0)
            out.append(
                Query(
                    query_id=r["query_id"],
                    user=r["user_name"],
                    warehouse=r["warehouse_name"],
                    query_type=r["query_type"],
                    text=r["query_text"],
                    start=_ts(r["start_time"]),
                    execution_ms=execution_ms,
                    queued_ms=float(r["queued_overload_time"] or 0),
                    rows=_int(r["rows_produced"]),
                    bytes_scanned=_int(r["bytes_scanned"]),
                    bytes_spilled=_int(r["bytes_spilled_to_local_storage"])
                    + _int(r["bytes_spilled_to_remote_storage"]),
                    partitions_scanned=_int(r["partitions_scanned"]),
                    partitions_total=_int(r["partitions_total"]),
                    cost_usd=execution_ms / 3_600_000 * credits_per_hour * credit_price,
                )
            )
    return out


def load_redshift(path: str | Path, cluster_usd_per_hour: float) -> list[Query]:
    """CSV from queries/redshift_export.sql. Times in SYS views are microseconds."""
    raw = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            raw.append({k.lower(): v for k, v in r.items()})
    if not raw:
        return []
    out = []
    for r in raw:
        execution_ms = float(r["execution_time"] or 0) / 1000
        out.append(
            Query(
                query_id=r["query_id"],
                user=r["user_id"],
                warehouse="cluster",
                query_type=r["query_type"],
                text=r["query_text"],
                start=_ts(r["start_time"]),
                execution_ms=execution_ms,
                queued_ms=float(r["queue_time"] or 0) / 1000,
                rows=_int(r["returned_rows"]),
                bytes_scanned=_int(r.get("blocks_read")) * 1024 * 1024,
                bytes_spilled=_int(r.get("spilled_blocks")) * 1024 * 1024,
                partitions_scanned=None,
                partitions_total=None,
                # Busy time valued at the cluster's hourly price. Concurrency means the
                # sum can exceed wall-clock hours; findings use shares, not totals.
                cost_usd=execution_ms / 3_600_000 * cluster_usd_per_hour,
            )
        )
    return out


@dataclass(frozen=True)
class MeteringHour:
    warehouse: str
    start: datetime
    credits: float


def load_snowflake_metering(path: str | Path) -> list[MeteringHour]:
    """CSV from queries/snowflake_metering.sql."""
    with open(path, newline="") as f:
        return [
            MeteringHour(
                warehouse=r["WAREHOUSE_NAME"] if "WAREHOUSE_NAME" in r else r["warehouse_name"],
                start=_ts(r.get("START_TIME") or r["start_time"]),
                credits=float(r.get("CREDITS_USED_COMPUTE") or r["credits_used_compute"]),
            )
            for r in csv.DictReader(f)
        ]
