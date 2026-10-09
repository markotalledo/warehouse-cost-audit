-- Run as a role with access to SNOWFLAKE.ACCOUNT_USAGE and export the result to CSV.
-- 30 days of successful queries. Query text is included: review it before sharing.
select
    query_id,
    user_name,
    warehouse_name,
    warehouse_size,
    query_type,
    query_text,
    start_time,
    total_elapsed_time,
    execution_time,
    queued_overload_time,
    bytes_scanned,
    partitions_scanned,
    partitions_total,
    bytes_spilled_to_local_storage,
    bytes_spilled_to_remote_storage,
    rows_produced
from snowflake.account_usage.query_history
where start_time >= dateadd(day, -30, current_timestamp())
  and warehouse_name is not null
  and execution_status = 'SUCCESS'
