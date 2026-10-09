"""Markdown report: summary table first, then one section per finding."""

from __future__ import annotations

from costaudit.detectors import Finding, top_patterns, window_days
from costaudit.model import Query


def _table(rows: list[dict]) -> str:
    if not rows:
        return ""
    cols = list(rows[0])
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for r in rows:
        lines.append("| " + " | ".join(str(r[c]).replace("|", "\\|") for c in cols) + " |")
    return "\n".join(lines)


def render(queries: list[Query], findings: list[Finding], source: str, billed_usd: float | None = None) -> str:
    days = window_days(queries)
    monthly = sum(q.cost_usd for q in queries) * 30 / days
    saving = sum(f.monthly_saving_usd for f in findings)
    out = [
        "# Warehouse cost audit",
        "",
        f"Source: {source}. Window: {days:.0f} days, {len(queries):,} queries.",
        "",
        f"Query execution time, valued and projected to a month: **${monthly:,.2f}**.",
    ]
    if billed_usd is not None:
        billed = billed_usd * 30 / days
        out.append(
            f"Compute actually billed, projected to a month: **${billed:,.2f}**. "
            f"The gap is time warehouses ran without doing work."
        )
    out += [
        "",
        f"Estimated saving across findings: **${saving:,.2f} a month**.",
        "",
        "## Findings",
        "",
    ]
    if findings:
        out.append(
            _table(
                [
                    {
                        "finding": f.title,
                        "monthly cost": f"${f.monthly_cost_usd:,.2f}",
                        "estimated saving": f"${f.monthly_saving_usd:,.2f}",
                    }
                    for f in findings
                ]
            )
        )
    else:
        out.append("No expensive patterns found.")
    for f in findings:
        out += [
            "",
            f"### {f.title}",
            "",
            _table(f.evidence[:5]),
            "",
            f"**What to do.** {f.recommendation}",
            "",
            f"**Assumption behind the saving.** {f.assumption}",
        ]
    out += [
        "",
        "## Most expensive query patterns",
        "",
        "Queries that differ only in literal values share a pattern.",
        "",
        _table(top_patterns(queries)),
        "",
        "## Method",
        "",
        "Each query is charged its execution time at the warehouse's hourly price. That leaves out "
        "Snowflake cloud services credits and Redshift idle time, so the total here is a floor; idle "
        "time is measured separately when metering data is provided. Savings are estimates for ranking "
        "the work, each with its assumption stated.",
        "",
    ]
    return "\n".join(out)
