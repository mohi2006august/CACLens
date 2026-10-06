-- Opportunities (CRM deals) inherit the channel/campaign/segment of their lead.

select
    d.deal_key,
    cast(d.created_at as date) as opportunity_date,
    coalesce(l.segment, 'unknown') as segment,
    coalesce(l.channel, 'unattributed') as channel,
    coalesce(l.campaign, '(none)') as campaign,
    d.is_won
from {{ ref('stg_crm_deals') }} as d
left join {{ ref('int_leads') }} as l on l.contact_key = d.contact_key
