-- Monthly paid spend and lead volume per channel: the bases that dynamic allocation
-- rules (`basis = spend | leads`) split team costs by.

with spend as (
    select cast(date_trunc('month', date_day) as date) as month, channel, sum(spend) as spend
    from {{ ref('stg_ad_spend') }}
    group by all
),

leads as (
    select cast(date_trunc('month', lead_date) as date) as month, channel, count(*) as leads
    from {{ ref('int_leads') }}
    group by all
),

combined as (
    select
        coalesce(s.month, l.month) as month,
        coalesce(s.channel, l.channel) as channel,
        coalesce(s.spend, 0) as spend,
        coalesce(l.leads, 0) as leads
    from spend as s
    full outer join leads as l on l.month = s.month and l.channel = s.channel
)

select
    *,
    coalesce(spend / nullif(sum(spend) over (partition by month), 0), 0) as spend_share,
    coalesce(leads / nullif(sum(leads) over (partition by month), 0), 0) as lead_share
from combined
