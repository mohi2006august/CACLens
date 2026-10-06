-- FR-02 unified customer journey: one row per customer from first touch to first payment.

with touches as (
    select * from {{ ref('int_journey_touchpoints') }}
),

paths as (
    select
        customer_id,
        count(*) as touch_count,
        min(touched_at) as first_touch_at,
        max(case when touch_position = 1 then channel end) as first_touch_channel,
        max(case when touch_position = touch_count then channel end) as last_touch_channel,
        string_agg(channel, ' > ' order by touch_position) as channel_path
    from touches
    group by customer_id
),

position_based as (
    select customer_id, channel
    from {{ ref('fct_attribution') }}
    where attribution_model = 'position_based'
    qualify row_number() over (partition by customer_id order by credit desc, channel) = 1
),

won_deals as (
    select contact_key, min(closed_at) as deal_won_at, max(amount) as deal_amount
    from {{ ref('stg_crm_deals') }}
    where is_won
    group by contact_key
)

select
    c.customer_id,
    c.acquired_at,
    c.cohort_month,
    c.segment,
    c.match_method,
    coalesce(p.touch_count, 0) as touch_count,
    p.first_touch_at,
    coalesce(p.first_touch_channel, 'unattributed') as first_touch_channel,
    coalesce(p.last_touch_channel, 'unattributed') as last_touch_channel,
    coalesce(pb.channel, 'unattributed') as position_based_channel,
    p.channel_path,
    date_diff('day', p.first_touch_at, c.acquired_at) as days_to_convert,
    d.deal_won_at,
    d.deal_amount
from {{ ref('int_customers') }} as c
left join paths as p on p.customer_id = c.customer_id
left join position_based as pb on pb.customer_id = c.customer_id
left join won_deals as d on d.contact_key = c.contact_key
