-- Fully loaded costs in the mart equal payroll + tool totals (allocation conserves cost).

with source_total as (
    select
        (select coalesce(sum(cost), 0) from {{ ref('stg_payroll_costs') }})
        + (select coalesce(sum(cost), 0) from {{ ref('stg_tool_costs') }}) as total
),

mart_total as (
    select coalesce(sum(people_cost + tool_cost), 0) as total
    from {{ ref('fct_acquisition_daily') }}
    where attribution_model = 'position_based'
)

select s.total as source_total, m.total as mart_total
from source_total as s
cross join mart_total as m
where abs(m.total - s.total) > {{ var('reconciliation_tolerance') }} * greatest(s.total, 1)
