-- Semantic model `acquisition`: additive spend, cost and funnel measures per
-- day x channel x campaign x segment x attribution model. Ratios such as CAC are
-- defined only in semantic/metrics.yml.
--
-- Spend and funnel volumes do not depend on the attribution model, so they are
-- repeated for every model; always filter or group by attribution_model.

with marketing as (
    select * from {{ ref('int_marketing_daily') }}
),

models as (
    select attribution_model from {{ ref('attribution_models') }}
),

new_customers as (
    select
        cast(c.acquired_at as date) as date_day,
        a.channel,
        a.campaign,
        c.segment,
        a.attribution_model,
        sum(a.credit) as new_customers
    from {{ ref('int_customers') }} as c
    inner join {{ ref('fct_attribution') }} as a on a.customer_id = c.customer_id
    group by all
),

combined as (
    select
        m.date_day, m.channel, m.campaign, m.segment, mo.attribution_model,
        m.paid_spend, m.people_cost, m.tool_cost, m.impressions, m.clicks,
        m.leads, m.opportunities, 0.0 as new_customers
    from marketing as m
    cross join models as mo

    union all

    select
        date_day, channel, campaign, segment, attribution_model,
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, new_customers
    from new_customers
)

select
    c.date_day,
    cast(date_trunc('month', c.date_day) as date) as cohort_month,
    c.channel,
    c.campaign,
    c.segment,
    coalesce(ch.is_paid, false) as is_paid_channel,
    c.attribution_model,
    sum(c.paid_spend) as paid_spend,
    sum(c.people_cost) as people_cost,
    sum(c.tool_cost) as tool_cost,
    sum(c.paid_spend + c.people_cost + c.tool_cost) as fully_loaded_spend,
    sum(c.impressions) as impressions,
    sum(c.clicks) as clicks,
    sum(c.leads) as leads,
    sum(c.opportunities) as opportunities,
    sum(c.new_customers) as new_customers
from combined as c
left join {{ ref('channels') }} as ch on ch.channel = c.channel
group by all
