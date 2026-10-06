-- People and tool costs per team and month (the "fully loaded" part of CAC).

select month, team, 'people' as cost_type, sum(cost) as cost
from {{ ref('stg_payroll_costs') }}
group by all

union all

select month, team, 'tools' as cost_type, sum(cost) as cost
from {{ ref('stg_tool_costs') }}
group by all
