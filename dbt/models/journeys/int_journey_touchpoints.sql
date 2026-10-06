-- Every touchpoint on a customer's path to purchase. B2B journeys are account based:
-- touches from colleagues at the same company domain count toward the purchase.

with customers as (
    select * from {{ ref('int_customers') }}
),

contacts as (
    select contact_key, company_domain from {{ ref('stg_crm_contacts') }}
),

journey_contacts as (
    select customer_id, contact_key
    from customers
    where contact_key is not null

    union

    select cu.customer_id, ct.contact_key
    from customers as cu
    inner join contacts as ct on ct.company_domain = cu.account_domain
    where cu.match_method <> 'unmatched'
      and cu.account_domain is not null
),

touches as (
    select distinct
        jc.customer_id,
        tp.touchpoint_key,
        tp.touched_at,
        tp.channel,
        tp.campaign,
        tp.touch_type,
        cu.acquired_at
    from journey_contacts as jc
    inner join {{ ref('stg_crm_touchpoints') }} as tp on tp.contact_key = jc.contact_key
    inner join customers as cu on cu.customer_id = jc.customer_id
    where tp.touched_at <= cu.acquired_at
      and tp.touched_at >= cu.acquired_at - interval {{ var('attribution_lookback_days') }} day
)

select
    *,
    date_diff('second', touched_at, acquired_at) / 86400.0 as days_before_conversion,
    row_number() over (partition by customer_id order by touched_at, touchpoint_key) as touch_position,
    count(*) over (partition by customer_id) as touch_count
from touches
