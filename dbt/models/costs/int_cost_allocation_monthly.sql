-- FR-03 fully loaded costs: allocate each team's monthly people/tool cost to channels
-- using dbt/seeds/cost_allocation_rules.csv. Anything without a rule (or whose basis is
-- empty that month) lands in `unallocated`, so allocated totals always equal the input.

with costs as (
    select * from {{ ref('int_team_costs_monthly') }}
),

rules as (
    select * from {{ ref('cost_allocation_rules') }}
),

basis as (
    select * from {{ ref('int_allocation_basis') }}
),

fixed as (
    select c.month, r.channel, c.cost_type, c.team, c.cost * r.share as allocated_cost
    from costs as c
    inner join rules as r on r.team = c.team and r.basis = 'fixed'
),

dynamic as (
    select
        c.month,
        b.channel,
        c.cost_type,
        c.team,
        c.cost * case r.basis when 'spend' then b.spend_share else b.lead_share end
            as allocated_cost
    from costs as c
    inner join rules as r on r.team = c.team and r.basis in ('spend', 'leads')
    inner join basis as b on b.month = c.month
    where case r.basis when 'spend' then b.spend_share else b.lead_share end > 0
),

allocated as (
    select * from fixed
    union all
    select * from dynamic
),

allocated_totals as (
    select month, team, cost_type, sum(allocated_cost) as allocated
    from allocated
    group by all
),

unallocated as (
    select
        c.month,
        'unallocated' as channel,
        c.cost_type,
        c.team,
        c.cost - coalesce(t.allocated, 0) as allocated_cost
    from costs as c
    left join allocated_totals as t
        on t.month = c.month and t.team = c.team and t.cost_type = c.cost_type
    where abs(c.cost - coalesce(t.allocated, 0)) > 0.005
)

select month, channel, cost_type, team, allocated_cost from allocated
union all
select month, channel, cost_type, team, allocated_cost from unallocated
