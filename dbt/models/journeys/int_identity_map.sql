-- FR-02 identity stitching: link each Stripe customer to one CRM contact.
-- Priority: CRM id stored in Stripe metadata > hashed email > company domain
-- (free-mail domains never match). Ties go to the earliest-created contact.

with customers as (
    select * from {{ ref('stg_stripe_customers') }}
),

contacts as (
    select * from {{ ref('stg_crm_contacts') }}
),

free_domains as (
    select domain from {{ ref('free_email_domains') }}
),

candidates as (
    select c.customer_id, ct.contact_key, ct.created_at, 'crm_id' as match_method, 1 as priority
    from customers as c
    inner join contacts as ct on ct.contact_id = c.crm_contact_id

    union all

    select c.customer_id, ct.contact_key, ct.created_at, 'email' as match_method, 2 as priority
    from customers as c
    inner join contacts as ct on ct.email_hash = c.email_hash
    where c.email_hash is not null

    union all

    select c.customer_id, ct.contact_key, ct.created_at, 'domain' as match_method, 3 as priority
    from customers as c
    inner join contacts as ct on ct.company_domain = c.email_domain
    where c.email_domain is not null
      and c.email_domain not in (select domain from free_domains)
)

select
    customer_id,
    contact_key,
    match_method
from candidates
qualify row_number() over (
    partition by customer_id
    order by priority, created_at, contact_key
) = 1
