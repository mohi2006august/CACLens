-- PRD NFR: revenue reconciles to Stripe within tolerance. Paid invoice totals must equal
-- revenue recognised in the mart (complete months) plus revenue deferred past the last
-- complete month. Catches attribution fan-out and dropped customers.

with as_of as (
    select max(revenue_month) as as_of_month from {{ ref('int_customer_months') }}
),

stripe_total as (
    select coalesce(sum(amount), 0) as total from {{ ref('stg_stripe_invoices') }}
),

mart_recognized as (
    select coalesce(sum(gross_revenue), 0) as total
    from {{ ref('fct_customer_revenue_monthly') }}
    where attribution_model = 'position_based'
),

deferred as (
    select coalesce(sum(recognized_revenue), 0) as total
    from {{ ref('int_invoice_months') }}
    where revenue_month > (select as_of_month from as_of)
)

select s.total as stripe_total, m.total as mart_total, d.total as deferred_total
from stripe_total as s
cross join mart_recognized as m
cross join deferred as d
where abs(m.total + d.total - s.total) > {{ var('reconciliation_tolerance') }} * greatest(s.total, 1)
