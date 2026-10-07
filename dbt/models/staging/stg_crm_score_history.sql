with deduped as (
    {{ latest_version(source('raw', 'crm_score_history'), ['source_system', 'contact_id', 'valid_from']) }}
)

select
    source_system || ':' || contact_id as contact_key,
    cast(score as double) as score,
    cast(valid_from as timestamp) as valid_from,
    observation
from deduped
where score is not null
  and valid_from is not null
