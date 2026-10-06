with deduped as (
    {{ latest_version(source('raw', 'stripe_invoices'), ['invoice_id']) }}
),

paid as (
    select
        invoice_id,
        customer_id,
        amount_paid_cents / 100.0 as amount,
        lower(currency) as currency,
        cast(paid_at as timestamp) as paid_at,
        cast(coalesce(period_start, paid_at) as timestamp) as period_start,
        cast(period_end as timestamp) as period_end
    from deduped
    where status = 'paid'
      and amount_paid_cents > 0
      and paid_at is not null
)

select
    invoice_id,
    customer_id,
    amount,
    currency,
    paid_at,
    period_start,
    -- Missing or zero-length service periods are treated as one month.
    case
        when period_end is null or period_end <= period_start
            then period_start + interval 1 month
        else period_end
    end as period_end
from paid
