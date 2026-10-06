with deduped as (
    {{ latest_version(source('raw', 'tool_costs'), ['month', 'tool']) }}
)

select
    cast(date_trunc('month', month) as date) as month,
    tool,
    lower(trim(team)) as team,
    cast(cost as double) as cost
from deduped
where month is not null
