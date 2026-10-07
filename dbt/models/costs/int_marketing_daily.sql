-- Funnel and cost facts per day x channel x campaign x segment (attribution independent).

with ad as (
    select
        date_day,
        channel,
        campaign,
        spend as paid_spend,
        0.0 as people_cost,
        0.0 as tool_cost,
        impressions,
        clicks
    from {{ ref('stg_ad_spend') }}
),

month_days as (
    select
        month,
        cast(unnest(generate_series(
            cast(month as timestamp), cast(last_day(month) as timestamp), interval 1 day
        )) as date) as date_day,
        day(last_day(month)) as days_in_month
    from (select distinct month from {{ ref('int_cost_allocation_monthly') }})
),

-- Monthly people/tool costs are spread evenly across the days of the month.
allocated as (
    select
        d.date_day,
        a.channel,
        '(unallocated)' as campaign,
        0.0 as paid_spend,
        sum(case when a.cost_type = 'people' then a.allocated_cost else 0 end) / d.days_in_month
            as people_cost,
        sum(case when a.cost_type = 'tools' then a.allocated_cost else 0 end) / d.days_in_month
            as tool_cost,
        0 as impressions,
        0 as clicks
    from {{ ref('int_cost_allocation_monthly') }} as a
    inner join month_days as d on d.month = a.month
    group by d.date_day, a.channel, d.days_in_month
),

unsegmented as (
    select * from ad
    union all
    select * from allocated
),

segmented as (
    select
        u.date_day,
        u.channel,
        u.campaign,
        coalesce(s.segment, 'unknown') as segment,
        u.paid_spend * coalesce(s.segment_share, 1) as paid_spend,
        u.people_cost * coalesce(s.segment_share, 1) as people_cost,
        u.tool_cost * coalesce(s.segment_share, 1) as tool_cost,
        u.impressions * coalesce(s.segment_share, 1) as impressions,
        u.clicks * coalesce(s.segment_share, 1) as clicks,
        0.0 as leads,
        0.0 as opportunities
    from unsegmented as u
    left join {{ ref('int_segment_shares') }} as s
        on s.month = cast(date_trunc('month', u.date_day) as date)
       and s.channel = u.channel
),

leads as (
    select
        lead_date as date_day, channel, campaign, segment,
        0.0 as paid_spend, 0.0 as people_cost, 0.0 as tool_cost,
        0.0 as impressions, 0.0 as clicks,
        count(*) * 1.0 as leads,
        0.0 as opportunities
    from {{ ref('int_leads') }}
    group by all
),

opportunities as (
    select
        opportunity_date as date_day, channel, campaign, segment,
        0.0 as paid_spend, 0.0 as people_cost, 0.0 as tool_cost,
        0.0 as impressions, 0.0 as clicks,
        0.0 as leads,
        count(*) * 1.0 as opportunities
    from {{ ref('int_opportunities') }}
    group by all
)

select
    date_day,
    channel,
    campaign,
    segment,
    cast(sum(paid_spend) as double) as paid_spend,
    cast(sum(people_cost) as double) as people_cost,
    cast(sum(tool_cost) as double) as tool_cost,
    cast(sum(impressions) as double) as impressions,
    cast(sum(clicks) as double) as clicks,
    cast(sum(leads) as double) as leads,
    cast(sum(opportunities) as double) as opportunities
from (
    select * from segmented
    union all
    select * from leads
    union all
    select * from opportunities
)
group by all
