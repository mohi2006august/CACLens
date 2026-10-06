with deduped as (
    {{ latest_version(source('raw', 'payroll_costs'), ['month', 'employee_id']) }}
)

select
    cast(date_trunc('month', month) as date) as month,
    employee_id,
    lower(trim(team)) as team,
    role,
    cast(cost as double) as cost
from deduped
where month is not null
