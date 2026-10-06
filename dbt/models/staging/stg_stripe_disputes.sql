with deduped as (
    {{ latest_version(source('raw', 'stripe_disputes'), ['dispute_id']) }}
)

-- Funds are withdrawn for real disputes until they are won; `warning_*` statuses are
-- inquiries with no funds moved, so they do not reduce revenue.
select
    dispute_id,
    customer_id,
    amount_cents / 100.0 as amount,
    status,
    cast(created_at as timestamp) as created_at
from deduped
where status in ('needs_response', 'under_review', 'lost')
  and customer_id is not null
