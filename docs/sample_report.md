# Warehouse cost audit

Source: snowflake export `tests/fixtures/snowflake_queries.csv`. Window: 7 days, 16,604 queries.

Query execution time, valued and projected to a month: **$644.63**.
Compute actually billed, projected to a month: **$7,560.00**. The gap is time warehouses ran without doing work.

Estimated saving across findings: **$5,284.82 a month**.

## Findings

| finding | monthly cost | estimated saving |
|---|---|---|
| Warehouses kept running all day by polling and tiny loads | $5,040.00 | $4,536.00 |
| Warehouses billed for hours with no queries | $720.00 | $720.00 |
| Queries that read almost the whole table | $46.09 | $23.04 |
| Queries spilling to disk | $19.24 | $5.77 |
| Dashboards or tools polling the warehouse | $139.64 | $0.00 |
| Many tiny loads instead of fewer large ones | $50.26 | $0.00 |
| Work piling up at the same hour | $0.00 | $0.00 |

### Warehouses kept running all day by polling and tiny loads

| warehouse | hours_awake_only_for_this_per_day | monthly_usd |
|---|---|---|
| BI_WH | 16.0 | 2880.0 |
| LOAD_WH | 24.0 | 2160.0 |

**What to do.** Fix the polling and tiny-load findings first; this is where most of their cost really is. Then set AUTO_SUSPEND to 60 seconds and move what is left onto the smallest warehouse size.

**Assumption behind the saving.** With the polling and loads above batched or cached and AUTO_SUSPEND at 60 seconds, the warehouse runs a few minutes per batch instead of all hour; we assume 90% of these hours go away.

### Warehouses billed for hours with no queries

| warehouse | idle_hours_billed_per_day | monthly_usd |
|---|---|---|
| TRANSFORM_WH | 2.0 | 720.0 |

**What to do.** Lower AUTO_SUSPEND to 60 seconds on these warehouses and check nothing keeps a session open.

**Assumption behind the saving.** Hours with credits and not a single query are pure idle time.

### Queries that read almost the whole table

| pattern | share_of_partitions_read | runs | monthly_usd | example |
|---|---|---|---|---|
| 73407fb186 | 99% | 56 | 46.09 | select customer_id, count(*) from analytics.events where lower(event_name) = 'order_com... |

**What to do.** Add a filter on the column the table is clustered or partitioned by, or cluster the table on the column these queries filter by. Check the query profile for the pruning ratio after.

**Assumption behind the saving.** A date filter or clustering key lets these queries skip most partitions; we assume half the cost.

### Queries spilling to disk

| pattern | runs_spilling | median_gb_spilled | monthly_usd | example |
|---|---|---|---|---|
| b34a6153d4 | 7 | 4.0 | 19.24 | create or replace table analytics.model_07 as select * from staging.src_07 where loaded... |

**What to do.** Spilling means the query does not fit in memory. Reduce what it carries (select fewer columns, aggregate before joining, filter earlier) before reaching for a bigger warehouse.

**Assumption behind the saving.** Removing the spill usually cuts runtime by 30% or more; we assume 30%.

### Dashboards or tools polling the warehouse

| pattern | runs_per_day | median_rows | monthly_usd | example |
|---|---|---|---|---|
| 0170af12c0 | 288 | 15 | 46.8 | select count(*), sum(total_cents) from analytics.active_sessions where day = '2026-01-0... |
| 82e7965b11 | 288 | 15 | 46.59 | select count(*), sum(total_cents) from analytics.revenue_today where day = '2026-01-05'... |
| b82a16fbe8 | 288 | 15 | 46.24 | select count(*), sum(total_cents) from analytics.orders_today where day = '2026-01-05' ... |

**What to do.** Find the dashboard or service behind each pattern. Cache the result, lower the refresh rate, or precompute it once into a small table. Polling also keeps the warehouse awake, so the real saving is usually larger than the query time shown here.

**Assumption behind the saving.** Refreshing every 30 minutes instead (48 runs a day) is enough for these results. Saving counted under 'Warehouses kept running all day by polling and tiny loads' to avoid double counting.

### Many tiny loads instead of fewer large ones

| pattern | runs_per_day | median_rows | monthly_usd | example |
|---|---|---|---|---|
| 42a827ae22 | 1440 | 22 | 50.26 | copy into raw.events from @events_stage/2026-01-05/0000/ file_format = (type = json) |

**What to do.** Every load pays a fixed overhead regardless of size. Buffer upstream (a queue, Firehose or a stage) and load in micro-batches, or switch to a streaming ingestion feature.

**Assumption behind the saving.** Batching into one load every 15 minutes (96 a day) keeps data fresh enough. Saving counted under 'Warehouses kept running all day by polling and tiny loads' to avoid double counting.

### Work piling up at the same hour

| hour_utc | queries_per_day | queued_share | queued_minutes_per_day |
|---|---|---|---|
| 13:00 | 156 | 40% | 47.4 |

**What to do.** Several schedules start at the same time. Stagger them, or cap concurrency on the orchestrator side (a pool) so jobs wait in line there instead of inside the warehouse.

**Assumption behind the saving.** No direct saving: the cost is latency and missed freshness, and on auto-scaling warehouses, extra clusters.

## Most expensive query patterns

Queries that differ only in literal values share a pattern.

| pattern | runs_per_day | median_seconds | monthly_usd | example |
|---|---|---|---|---|
| 42a827ae22 | 1440.0 | 1.4 | 50.26 | copy into raw.events from @events_stage/2026-01-05/0000/ file_format = (type = json) |
| 0170af12c0 | 288.0 | 3.2 | 46.8 | select count(*), sum(total_cents) from analytics.active_sessions where day = '2026-01-0... |
| 82e7965b11 | 288.0 | 3.2 | 46.59 | select count(*), sum(total_cents) from analytics.revenue_today where day = '2026-01-05'... |
| b82a16fbe8 | 288.0 | 3.2 | 46.24 | select count(*), sum(total_cents) from analytics.orders_today where day = '2026-01-05' ... |
| 73407fb186 | 8.0 | 114.6 | 46.09 | select customer_id, count(*) from analytics.events where lower(event_name) = 'order_com... |
| b34a6153d4 | 1.0 | 178.1 | 19.24 | create or replace table analytics.model_07 as select * from staging.src_07 where loaded... |
| 03ba5a5814 | 1.0 | 97.5 | 9.13 | create or replace table analytics.model_23 as select * from staging.src_23 where loaded... |
| 679ca09c72 | 1.0 | 94.2 | 8.86 | create or replace table analytics.model_09 as select * from staging.src_09 where loaded... |
| 64260bceb5 | 1.0 | 103.1 | 8.83 | create or replace table analytics.model_02 as select * from staging.src_02 where loaded... |
| 7804bcd89f | 1.0 | 89.5 | 8.79 | create or replace table analytics.model_30 as select * from staging.src_30 where loaded... |

## Method

Each query is charged its execution time at the warehouse's hourly price. That leaves out Snowflake cloud services credits and Redshift idle time, so the total here is a floor; idle time is measured separately when metering data is provided. Savings are estimates for ranking the work, each with its assumption stated.
