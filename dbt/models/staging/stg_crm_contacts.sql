with deduped as (
    {{ latest_version(source('raw', 'crm_contacts'), ['source_system', 'contact_id']) }}
)

select
    d.source_system || ':' || d.contact_id as contact_key,
    d.source_system,
    cast(d.contact_id as varchar) as contact_id,
    d.email_hash,
    lower(d.email_domain) as email_domain,
    case
        when lower(d.company_domain) in (select domain from {{ ref('free_email_domains') }})
            then null
        else nullif(lower(trim(d.company_domain)), '')
    end as company_domain,
    {{ normalize_segment('d.segment') }} as segment,
    d.lifecycle_stage,
    cast(d.created_at as timestamp) as created_at,
    cast(coalesce(d.became_lead_at, d.created_at) as timestamp) as lead_at
from deduped as d
where d.contact_id is not null
