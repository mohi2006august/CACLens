-- FR-04 customer x month grid from acquisition to the last complete month, with
-- recognised revenue, refunds/chargebacks (which reduce LTV) and activity flags.

with as_of as (
    -- Only complete months: a half-finished month would look like mass churn.
    select cast(date_trunc('month', max(paid_at) + interval 1 day) - interval 1 month as date)
        as as_of_month
    from {{ ref('stg_stripe_invoices') }}
),

grid as (
    select
        c.customer_id,
        c.cohort_month,
        cast(unnest(generate_series(
            cast(c.cohort_month as timestamp), cast(a.as_of_month as timestamp), interval 1 month
        )) as date) as revenue_month
    from {{ ref('int_customers') }} as c
    cross join as_of as a
    where c.cohort_month <= a.as_of_month
),

revenue as (
    select customer_id, revenue_month, sum(recognized_revenue) as recognized_revenue
    from {{ ref('int_invoice_months') }}
    group by all
),

refunds as (
    select customer_id, cast(date_trunc('month', created_at) as date) as revenue_month,
        sum(amount) as refunds
    from {{ ref('stg_stripe_refunds') }}
    group by all
),

chargebacks as (
    select customer_id, cast(date_trunc('month', created_at) as date) as revenue_month,
        sum(amount) as chargebacks
    from {{ ref('stg_stripe_disputes') }}
    group by all
),

joined as (
    select
        g.customer_id,
        g.cohort_month,
        g.revenue_month,
        date_diff('month', g.cohort_month, g.revenue_month) as months_since_acquisition,
        coalesce(r.recognized_revenue, 0) as recognized_revenue,
        coalesce(f.refunds, 0) as refunds,
        coalesce(cb.chargebacks, 0) as chargebacks
    from grid as g
    left join revenue as r
        on r.customer_id = g.customer_id and r.revenue_month = g.revenue_month
    left join refunds as f
        on f.customer_id = g.customer_id and f.revenue_month = g.revenue_month
    left join chargebacks as cb
        on cb.customer_id = g.customer_id and cb.revenue_month = g.revenue_month
)

select
    *,
    recognized_revenue - refunds - chargebacks as net_revenue,
    recognized_revenue > 0 as is_active,
    coalesce(
        lag(recognized_revenue > 0) over (partition by customer_id order by revenue_month),
        false
    ) as was_active
from joined
