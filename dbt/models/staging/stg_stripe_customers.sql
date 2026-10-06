with deduped as (
    {{ latest_version(source('raw', 'stripe_customers'), ['customer_id']) }}
)

select
    customer_id,
    email_hash,
    lower(email_domain) as email_domain,
    nullif(trim(crm_contact_id), '') as crm_contact_id,
    cast(created_at as timestamp) as created_at
from deduped
