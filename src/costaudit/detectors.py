"""Each detector looks for one expensive pattern and estimates what fixing it saves.

Savings are estimates with the assumption written next to them. They are meant to
rank the work, not to promise a number.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from statistics import median

from costaudit.fingerprint import fingerprint
from costaudit.model import MeteringHour, Query


@dataclass
class Finding:
    key: str
    title: str
    monthly_cost_usd: float
    monthly_saving_usd: float
    assumption: str
    recommendation: str
    evidence: list[dict] = field(default_factory=list)


def window_days(queries: list[Query]) -> float:
    if not queries:
        return 1.0
    span = max(q.start for q in queries) - min(q.start for q in queries)
    return max(1.0, math.ceil(span.total_seconds() / 86_400))


def _groups(queries: list[Query]) -> dict[str, list[Query]]:
    groups: dict[str, list[Query]] = defaultdict(list)
    for q in queries:
        groups[fingerprint(q.text)].append(q)
    return groups


def _example(text: str, width: int = 90) -> str:
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 3] + "..."


def top_patterns(queries: list[Query], n: int = 10) -> list[dict]:
    month = 30 / window_days(queries)
    rows = []
    for fp, qs in _groups(queries).items():
        rows.append(
            {
                "pattern": fp,
                "runs_per_day": round(len(qs) / window_days(queries), 1),
                "median_seconds": round(median(q.execution_ms for q in qs) / 1000, 1),
                "monthly_usd": round(sum(q.cost_usd for q in qs) * month, 2),
                "example": _example(qs[0].text),
            }
        )
    return sorted(rows, key=lambda r: r["monthly_usd"], reverse=True)[:n]


def _frequency_finding(queries, key, title, kinds, min_per_day, max_rows, target_per_day, assumption, recommendation):
    days = window_days(queries)
    month = 30 / days
    cost = saving = 0.0
    evidence = []
    for fp, qs in _groups(queries).items():
        if qs[0].query_type.upper() not in kinds:
            continue
        per_day = len(qs) / days
        if per_day < min_per_day or median(q.rows for q in qs) > max_rows:
            continue
        pattern_cost = sum(q.cost_usd for q in qs) * month
        cost += pattern_cost
        saving += pattern_cost * max(0.0, 1 - target_per_day / per_day)
        evidence.append(
            {
                "pattern": fp,
                "runs_per_day": round(per_day),
                "median_rows": int(median(q.rows for q in qs)),
                "monthly_usd": round(pattern_cost, 2),
                "example": _example(qs[0].text),
            }
        )
    if not evidence:
        return None
    evidence.sort(key=lambda r: r["monthly_usd"], reverse=True)
    return Finding(key, title, cost, saving, assumption, recommendation, evidence)


def polling(queries: list[Query]) -> Finding | None:
    return _frequency_finding(
        queries,
        key="polling",
        title="Dashboards or tools polling the warehouse",
        kinds={"SELECT"},
        min_per_day=100,
        max_rows=1_000,
        target_per_day=48,
        assumption="Refreshing every 30 minutes instead (48 runs a day) is enough for these results.",
        recommendation=(
            "Find the dashboard or service behind each pattern. Cache the result, lower the refresh "
            "rate, or precompute it once into a small table. Polling also keeps the warehouse awake, "
            "so the real saving is usually larger than the query time shown here."
        ),
    )


def small_loads(queries: list[Query]) -> Finding | None:
    return _frequency_finding(
        queries,
        key="small_loads",
        title="Many tiny loads instead of fewer large ones",
        kinds={"COPY", "INSERT", "MERGE"},
        min_per_day=50,
        max_rows=100,
        target_per_day=96,
        assumption="Batching into one load every 15 minutes (96 a day) keeps data fresh enough.",
        recommendation=(
            "Every load pays a fixed overhead regardless of size. Buffer upstream (a queue, Firehose "
            "or a stage) and load in micro-batches, or switch to a streaming ingestion feature."
        ),
    )


def unpruned_scans(queries: list[Query], min_partitions: int = 100, threshold: float = 0.8) -> Finding | None:
    month = 30 / window_days(queries)
    cost = 0.0
    evidence = []
    for fp, qs in _groups(queries).items():
        scans = [q for q in qs if q.partitions_total and q.partitions_total >= min_partitions]
        if not scans:
            continue
        ratio = median(q.partitions_scanned / q.partitions_total for q in scans)
        if ratio < threshold:
            continue
        pattern_cost = sum(q.cost_usd for q in scans) * month
        cost += pattern_cost
        evidence.append(
            {
                "pattern": fp,
                "share_of_partitions_read": f"{ratio:.0%}",
                "runs": len(scans),
                "monthly_usd": round(pattern_cost, 2),
                "example": _example(scans[0].text),
            }
        )
    if not evidence:
        return None
    evidence.sort(key=lambda r: r["monthly_usd"], reverse=True)
    return Finding(
        "unpruned_scans",
        "Queries that read almost the whole table",
        cost,
        cost * 0.5,
        "A date filter or clustering key lets these queries skip most partitions; we assume half the cost.",
        "Add a filter on the column the table is clustered or partitioned by, or cluster the table on "
        "the column these queries filter by. Check the query profile for the pruning ratio after.",
        evidence,
    )


def spill(queries: list[Query]) -> Finding | None:
    month = 30 / window_days(queries)
    cost = 0.0
    evidence = []
    for fp, qs in _groups(queries).items():
        spilled = [q for q in qs if q.bytes_spilled > 0]
        if not spilled:
            continue
        pattern_cost = sum(q.cost_usd for q in spilled) * month
        cost += pattern_cost
        evidence.append(
            {
                "pattern": fp,
                "runs_spilling": len(spilled),
                "median_gb_spilled": round(median(q.bytes_spilled for q in spilled) / 1e9, 2),
                "monthly_usd": round(pattern_cost, 2),
                "example": _example(spilled[0].text),
            }
        )
    if not evidence:
        return None
    evidence.sort(key=lambda r: r["monthly_usd"], reverse=True)
    return Finding(
        "spill",
        "Queries spilling to disk",
        cost,
        cost * 0.3,
        "Removing the spill usually cuts runtime by 30% or more; we assume 30%.",
        "Spilling means the query does not fit in memory. Reduce what it carries (select fewer columns, "
        "aggregate before joining, filter earlier) before reaching for a bigger warehouse.",
        evidence,
    )


def queueing(queries: list[Query], threshold: float = 0.2) -> Finding | None:
    days = window_days(queries)
    by_hour: dict[int, list[Query]] = defaultdict(list)
    for q in queries:
        by_hour[q.start.hour].append(q)
    evidence = []
    for hour in sorted(by_hour):
        qs = by_hour[hour]
        queued = sum(q.queued_ms for q in qs)
        busy = queued + sum(q.execution_ms for q in qs)
        if busy and queued / busy >= threshold:
            evidence.append(
                {
                    "hour_utc": f"{hour:02d}:00",
                    "queries_per_day": round(len(qs) / days),
                    "queued_share": f"{queued / busy:.0%}",
                    "queued_minutes_per_day": round(queued / 60_000 / days, 1),
                }
            )
    if not evidence:
        return None
    return Finding(
        "queueing",
        "Work piling up at the same hour",
        0.0,
        0.0,
        "No direct saving: the cost is latency and missed freshness, and on auto-scaling warehouses, extra clusters.",
        "Several schedules start at the same time. Stagger them, or cap concurrency on the orchestrator "
        "side (a pool) so jobs wait in line there instead of inside the warehouse.",
        evidence,
    )


def idle_warehouses(metering: list[MeteringHour], queries: list[Query], credit_price: float) -> Finding | None:
    active = {(q.warehouse, q.start.replace(minute=0, second=0, microsecond=0)) for q in queries}
    days = window_days(queries)
    per_wh: dict[str, list[float]] = defaultdict(list)
    for m in metering:
        hour = m.start.replace(minute=0, second=0, microsecond=0)
        if m.credits > 0 and (m.warehouse, hour) not in active:
            per_wh[m.warehouse].append(m.credits)
    if not per_wh:
        return None
    month = 30 / days
    evidence = [
        {
            "warehouse": wh,
            "idle_hours_billed_per_day": round(len(c) / days, 1),
            "monthly_usd": round(sum(c) * credit_price * month, 2),
        }
        for wh, c in sorted(per_wh.items(), key=lambda kv: -sum(kv[1]))
    ]
    cost = sum(e["monthly_usd"] for e in evidence)
    return Finding(
        "idle",
        "Warehouses billed for hours with no queries",
        cost,
        cost,
        "Hours with credits and not a single query are pure idle time.",
        "Lower AUTO_SUSPEND to 60 seconds on these warehouses and check nothing keeps a session open.",
        evidence,
    )


def kept_awake(
    metering: list[MeteringHour], queries: list[Query], trivial_patterns: set[str], credit_price: float
) -> Finding | None:
    """Billed hours in which the only work was polling or tiny loads.

    Query time undercounts these patterns: a query every few minutes keeps the warehouse
    from ever suspending, so the whole hour is billed for a few seconds of work.
    """
    hours: dict[tuple[str, object], set[str]] = defaultdict(set)
    for q in queries:
        hours[(q.warehouse, q.start.replace(minute=0, second=0, microsecond=0))].add(fingerprint(q.text))
    days = window_days(queries)
    per_wh: dict[str, list[float]] = defaultdict(list)
    for m in metering:
        fps = hours.get((m.warehouse, m.start.replace(minute=0, second=0, microsecond=0)))
        if m.credits > 0 and fps and fps <= trivial_patterns:
            per_wh[m.warehouse].append(m.credits)
    if not per_wh:
        return None
    month = 30 / days
    evidence = [
        {
            "warehouse": wh,
            "hours_awake_only_for_this_per_day": round(len(c) / days, 1),
            "monthly_usd": round(sum(c) * credit_price * month, 2),
        }
        for wh, c in sorted(per_wh.items(), key=lambda kv: -sum(kv[1]))
    ]
    cost = sum(e["monthly_usd"] for e in evidence)
    return Finding(
        "kept_awake",
        "Warehouses kept running all day by polling and tiny loads",
        cost,
        cost * 0.9,
        "With the polling and loads above batched or cached and AUTO_SUSPEND at 60 seconds, the "
        "warehouse runs a few minutes per batch instead of all hour; we assume 90% of these hours go away.",
        "Fix the polling and tiny-load findings first; this is where most of their cost really is. "
        "Then set AUTO_SUSPEND to 60 seconds and move what is left onto the smallest warehouse size.",
        evidence,
    )


def run_all(queries, metering=None, credit_price=None) -> list[Finding]:
    findings = [
        polling(queries),
        small_loads(queries),
        unpruned_scans(queries),
        spill(queries),
        queueing(queries),
    ]
    if metering and credit_price:
        findings.append(idle_warehouses(metering, queries, credit_price))
        trivial = {row["pattern"] for f in findings if f and f.key in ("polling", "small_loads") for row in f.evidence}
        awake = kept_awake(metering, queries, trivial, credit_price) if trivial else None
        if awake:
            findings.append(awake)
            # The query time of these patterns is part of the hours counted above.
            for f in findings:
                if f and f.key in ("polling", "small_loads"):
                    f.monthly_saving_usd = 0.0
                    f.assumption += f" Saving counted under '{awake.title}' to avoid double counting."
    return sorted((f for f in findings if f), key=lambda f: f.monthly_saving_usd, reverse=True)
