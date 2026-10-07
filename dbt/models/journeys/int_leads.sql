-- Leads are attributed to the touch that created them (first touch at or before the
-- lead date). Lead counts feed the funnel and the CAC decomposition (FR-06).
-- `is_qualified` is known at form fill, so it is the earliest lead-quality signal. It
-- uses the lead score *as of lead time* (point in time): CRMs re-score leads after a deal
-- closes, so today's score would leak the outcome into lead quality and flatter any
-- backtest. Without a score from lead time, the time-invariant fit rule decides.

with contacts as (
    select * from {{ ref('stg_crm_contacts') }}
    where lead_at is not null
),

scores as (
    select * from {{ ref('stg_crm_score_history') }}
),

score_at_lead as (
    select c.contact_key, s.score
    from contacts as c
    inner join scores as s
        on s.contact_key = c.contact_key
       and s.valid_from <= c.lead_at + interval {{ var('lead_score_grace_hours') }} hour
    qualify row_number() over (partition by c.contact_key order by s.valid_from desc) = 1
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
    sl.score as lead_score_at_lead,
    case
        when sl.score is not null then sl.score >= {{ var('qualified_lead_score') }}
        else c.is_work_email and c.segment <> 'unknown'
    end as is_qualified,
    case when sl.score is not null then 'score_at_lead' else 'fit_rule' end as qualified_by,
    coalesce(lt.channel, 'unattributed') as channel,
    coalesce(lt.campaign, '(none)') as campaign
from contacts as c
left join score_at_lead as sl on sl.contact_key = c.contact_key
left join lead_touch as lt
    on lt.contact_key = c.contact_key
   and lt.rn = 1
