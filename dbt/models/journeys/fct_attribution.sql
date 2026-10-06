-- FR-05 attribution: credit per customer x model x channel x campaign. Credits for a
-- customer sum to 1 under every model. Customers with no touchpoints are credited to
-- the `unattributed` channel so the gap stays visible instead of disappearing.

with touches as (
    select
        *,
        pow(0.5, days_before_conversion / {{ var('time_decay_half_life_days') }}) as decay_weight
    from {{ ref('int_journey_touchpoints') }}
),

weighted as (
    select
        customer_id,
        channel,
        campaign,
        case when touch_position = 1 then 1.0 else 0.0 end as first_touch,
        case when touch_position = touch_count then 1.0 else 0.0 end as last_touch,
        1.0 / touch_count as linear,
        decay_weight / sum(decay_weight) over (partition by customer_id) as time_decay,
        case
            when touch_count = 1 then 1.0
            when touch_count = 2 then 0.5
            when touch_position = 1 or touch_position = touch_count then 0.4
            else 0.2 / (touch_count - 2)
        end as position_based
    from touches
),

credits as (
    select customer_id, channel, campaign, 'first_touch' as attribution_model, first_touch as credit
    from weighted
    union all
    select customer_id, channel, campaign, 'last_touch', last_touch from weighted
    union all
    select customer_id, channel, campaign, 'linear', linear from weighted
    union all
    select customer_id, channel, campaign, 'time_decay', time_decay from weighted
    union all
    select customer_id, channel, campaign, 'position_based', position_based from weighted
),

unattributed as (
    select
        c.customer_id,
        'unattributed' as channel,
        '(none)' as campaign,
        m.attribution_model,
        1.0 as credit
    from {{ ref('int_customers') }} as c
    cross join {{ ref('attribution_models') }} as m
    where not exists (select 1 from touches as t where t.customer_id = c.customer_id)
)

select
    customer_id,
    attribution_model,
    channel,
    campaign,
    sum(credit) as credit
from (
    select * from credits
    union all
    select * from unattributed
)
group by all
having sum(credit) > 0
