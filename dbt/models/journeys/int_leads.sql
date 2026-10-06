-- Leads are attributed to the touch that created them (first touch at or before the
-- lead date). Lead counts feed the funnel and the CAC decomposition (FR-06).

with contacts as (
    select * from {{ ref('stg_crm_contacts') }}
    where lead_at is not null
),

lead_touch as (
    select
        c.contact_key,
        t.channel,
        t.campaign,
        row_number() over (partition by c.contact_key order by t.touched_at, t.touchpoint_key) as rn
    from contacts as c
    inner join {{ ref('stg_crm_touchpoints') }} as t
        on t.contact_key = c.contact_key
       and t.touched_at <= c.lead_at + interval 1 day
)

select
    c.contact_key,
    c.lead_at,
    cast(c.lead_at as date) as lead_date,
    c.segment,
    coalesce(lt.channel, 'unattributed') as channel,
    coalesce(lt.campaign, '(none)') as campaign
from contacts as c
left join lead_touch as lt
    on lt.contact_key = c.contact_key
   and lt.rn = 1
