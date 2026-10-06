-- Ad platforms do not know a buyer's segment. Spend, clicks and allocated costs are
-- split across segments by each channel's monthly lead mix (see BRAIN.md decision log).

with leads as (
    select
        cast(date_trunc('month', lead_date) as date) as month,
        channel,
        segment,
        count(*) as leads
    from {{ ref('int_leads') }}
    group by all
)

select
    month,
    channel,
    segment,
    leads / sum(leads) over (partition by month, channel) as segment_share
from leads
