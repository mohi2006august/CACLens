-- Recognise each paid invoice evenly over the months of its service period
-- (monthly plans -> 1 month, annual plans -> 12), so churn is not mistaken for
-- an annual customer's 11 unbilled months.

with spans as (
    select
        i.invoice_id,
        i.customer_id,
        i.amount,
        -- A service period that starts before the first payment is recognised from
        -- the acquisition month, never before the customer existed.
        greatest(cast(date_trunc('month', i.period_start) as date), c.cohort_month) as first_month,
        greatest(
            1, cast(round(date_diff('day', i.period_start, i.period_end) / 30.4375) as integer)
        ) as n_months
    from {{ ref('stg_stripe_invoices') }} as i
    inner join {{ ref('int_customers') }} as c on c.customer_id = i.customer_id
),

expanded as (
    select
        invoice_id,
        customer_id,
        amount,
        first_month,
        n_months,
        unnest(range(n_months)) as month_offset
    from spans
)

select
    invoice_id,
    customer_id,
    cast(first_month + to_months(month_offset) as date) as revenue_month,
    amount / n_months as recognized_revenue
from expanded
