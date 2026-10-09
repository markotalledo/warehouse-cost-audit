-- Credits billed per warehouse per hour, same 30-day window.
select warehouse_name, start_time, credits_used_compute
from snowflake.account_usage.warehouse_metering_history
where start_time >= dateadd(day, -30, current_timestamp())
