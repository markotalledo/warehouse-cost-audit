-- Run as a superuser (other users only see their own queries in SYS views) and export to CSV.
-- Times are in microseconds; spilled and read blocks are 1 MB each.
select
    h.query_id,
    h.user_id,
    h.query_type,
    h.query_text,
    h.start_time,
    h.elapsed_time,
    h.execution_time,
    h.queue_time,
    h.returned_rows,
    coalesce(d.spilled_blocks, 0) as spilled_blocks,
    coalesce(d.blocks_read, 0) as blocks_read
from sys_query_history as h
left join (
    select
        query_id,
        sum(spilled_block_local_disk + spilled_block_remote_disk) as spilled_blocks,
        sum(blocks_read) as blocks_read
    from sys_query_detail
    group by query_id
) as d using (query_id)
where h.start_time >= dateadd(day, -30, getdate())
  and h.status = 'success'
