-- One row per paying customer: acquisition date (first paid invoice), cohort, segment
-- and the stitched CRM contact/account.

with first_paid as (
    select customer_id, min(paid_at) as acquired_at
    from {{ ref('stg_stripe_invoices') }}
    group by customer_id
),

free_domains as (
    select domain from {{ ref('free_email_domains') }}
)

select
    fp.customer_id,
    fp.acquired_at,
    cast(date_trunc('month', fp.acquired_at) as date) as cohort_month,
    im.contact_key,
    coalesce(im.match_method, 'unmatched') as match_method,
    coalesce(ct.segment, 'unknown') as segment,
    coalesce(
        ct.company_domain,
        case when c.email_domain not in (select domain from free_domains) then c.email_domain end
    ) as account_domain
from first_paid as fp
left join {{ ref('stg_stripe_customers') }} as c on c.customer_id = fp.customer_id
left join {{ ref('int_identity_map') }} as im on im.customer_id = fp.customer_id
left join {{ ref('stg_crm_contacts') }} as ct on ct.contact_key = im.contact_key
