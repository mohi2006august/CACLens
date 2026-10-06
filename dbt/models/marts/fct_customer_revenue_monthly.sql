-- Semantic model `customer_revenue`: credit-weighted revenue, activity and churn per
-- revenue month x cohort x channel x campaign x segment x attribution model.
-- Gross margin comes from the `gross_margin` dbt var (FR-04).

select
    cm.revenue_month,
    cm.cohort_month,
    cm.months_since_acquisition,
    a.channel,
    a.campaign,
    c.segment,
    coalesce(ch.is_paid, false) as is_paid_channel,
    a.attribution_model,
    sum(case when cm.months_since_acquisition = 0 then a.credit else 0 end) as cohort_customers,
    sum(case when cm.is_active then a.credit else 0 end) as active_customers,
    sum(case when cm.was_active then a.credit else 0 end) as starting_customers,
    sum(case when cm.was_active and not cm.is_active then a.credit else 0 end)
        as churned_customers,
    sum(a.credit * cm.recognized_revenue) as gross_revenue,
    sum(a.credit * (cm.refunds + cm.chargebacks)) as refunds_and_chargebacks,
    sum(a.credit * cm.net_revenue) as net_revenue,
    sum(a.credit * cm.net_revenue) * {{ var('gross_margin') }} as gross_margin_revenue
from {{ ref('int_customer_months') }} as cm
inner join {{ ref('fct_attribution') }} as a on a.customer_id = cm.customer_id
inner join {{ ref('int_customers') }} as c on c.customer_id = cm.customer_id
left join {{ ref('channels') }} as ch on ch.channel = a.channel
group by all
