with deduped as (
    {{ latest_version(source('raw', 'stripe_refunds'), ['refund_id']) }}
)

select
    refund_id,
    customer_id,
    amount_cents / 100.0 as amount,
    cast(created_at as timestamp) as created_at
from deduped
where status = 'succeeded'
  and customer_id is not null
