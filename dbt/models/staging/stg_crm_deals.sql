with deduped as (
    {{ latest_version(source('raw', 'crm_deals'), ['source_system', 'deal_id']) }}
)

select
    source_system || ':' || deal_id as deal_key,
    case when contact_id is not null then source_system || ':' || contact_id end as contact_key,
    cast(amount as double) as amount,
    stage,
    coalesce(is_won, false) as is_won,
    cast(created_at as timestamp) as created_at,
    cast(closed_at as timestamp) as closed_at
from deduped
where created_at is not null
