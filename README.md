# warehouse-cost-audit

Find out what makes a Snowflake or Redshift bill expensive, from one CSV export of query history. No access to the account needed: run the export query, hand over the file, get a report that ranks each problem by how much fixing it saves.

It is the sixth piece of a small end-to-end data platform for a fictional online coffee shop, and the one that keeps the other five cheap to run.

![The audit run on a synthetic week: $644 of query time against $7,560 of billed compute, and the findings ranked by estimated saving](docs/demo.gif)

The recording runs the CLI on the synthetic week in `tests/fixtures`. Re-record it with `vhs docs/demo.tape`.

## What it finds

| Pattern | Why it costs money | Saving estimated as |
|---|---|---|
| Warehouses kept running all day by polling and tiny loads | A query every few minutes means the warehouse never suspends: the whole hour is billed for seconds of work | 90% of the hours where that was the only work |
| Warehouses billed for hours with no queries | Auto-suspend set too long, or a session left open | All of those hours |
| Dashboards or tools polling the warehouse | The same small query hundreds of times a day | Runs above one every 30 minutes |
| Many tiny loads instead of fewer large ones | Every load pays a fixed overhead, whatever its size | Runs above one every 15 minutes |
| Queries that read almost the whole table | No pruning: every run pays for the full table | Half the cost of those queries |
| Queries spilling to disk | Not enough memory for the query, so it runs slower | 30% of the cost of those queries |
| Work piling up at the same hour | Schedules that start together and queue inside the warehouse | Reported as latency, no dollar figure |

Queries that differ only in literal values are grouped into one pattern before anything is counted, so 288 refreshes of the same dashboard tile show up as one line, not 288.

## Quickstart

```bash
make setup    # uv sync
make test     # 13 tests on a synthetic week of Snowflake activity
make sample   # writes docs/sample_report.md from that week
```

On a real account:

```bash
# 1. run queries/snowflake_export.sql and queries/snowflake_metering.sql, save as CSV
uv run costaudit snowflake queries.csv --metering metering.csv --credit-price 3 -o report.md

# or, for Redshift (run queries/redshift_export.sql as a superuser)
uv run costaudit redshift queries.csv --cluster-usd-per-hour 2.17 -o report.md
```

## Sample report

[docs/sample_report.md](docs/sample_report.md) is the audit of a synthetic week on three warehouses: a nightly dbt build, a second team's build scheduled at the same minute, three dashboard tiles refreshed every 5 minutes, a load every minute, analysts scanning a whole events table, and one dbt model that spills.

| | Per month |
|---|---:|
| Query execution time, valued at warehouse rates | $644.63 |
| Compute actually billed | $7,560.00 |
| Estimated saving | $5,284.82 |

The gap between the first two lines is the main finding: most of the bill is warehouses kept awake by polling and per-minute loads, not the queries themselves. Looking only at query cost would have ranked those patterns at $190 a month.

## Design decisions

- **CSV in, not credentials.** A cost audit should not need write access, or any access, to someone else's account. The export queries are in `queries/`, readable before anyone runs them.
- **Billed hours, not just query time.** Query time undercounts anything that runs often: what you pay for is the warehouse being up. When metering data is provided, each billed hour is matched with what actually ran in it.
- **No double counting.** The polling and tiny-load savings are counted once, inside the kept-awake finding, and the report says so.
- **Every estimate says what it assumes.** The numbers are for ranking the work. Each finding states the assumption behind its saving so it can be argued with.
- **Fingerprints from the parser.** Literals are replaced using sqlglot's syntax tree, with a regex fallback for statements it cannot parse, such as `COPY` options.

## Limits

- Cost is attributed by execution time at the warehouse's hourly rate. Snowflake cloud services credits and serverless features are not included.
- On Redshift, idle cluster time cannot be read from query history, so only query-level findings apply.
- The pruning ratio is Snowflake-only; Redshift reports blocks, not partitions.

## Repo layout

```
src/costaudit/model.py        loaders for Snowflake and Redshift exports
src/costaudit/fingerprint.py  query grouping
src/costaudit/detectors.py    one function per pattern
src/costaudit/report.py       markdown report
src/costaudit/synth.py        the synthetic week used by tests and the sample
queries/                      the export queries to run on the warehouse
```

## License

MIT
