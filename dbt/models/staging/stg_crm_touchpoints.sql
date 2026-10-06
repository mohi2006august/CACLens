with deduped as (
    {{ latest_version(source('raw', 'crm_touchpoints'), ['source_system', 'touchpoint_id']) }}
),

normalized as (
    select
        source_system || ':' || touchpoint_id as touchpoint_key,
        source_system || ':' || contact_id as contact_key,
        cast(touched_at as timestamp) as touched_at,
        coalesce(nullif(lower(trim(utm_source)), ''), '(direct)') as utm_source,
        coalesce(nullif(lower(trim(utm_medium)), ''), '(none)') as utm_medium,
        {{ normalize_key('utm_campaign') }} as campaign,
        touch_type
    from deduped
    where touched_at is not null
      and contact_id is not null
),

mapping as (
    select * from {{ ref('channel_mapping') }}
)

-- Most specific mapping wins: exact (source, medium) > any source + medium > source + any medium.
select
    n.*,
    coalesce(exact.channel, by_medium.channel, by_source.channel, 'other') as channel
from normalized as n
left join mapping as exact
    on exact.utm_source = n.utm_source and exact.utm_medium = n.utm_medium
left join mapping as by_medium
    on by_medium.utm_source = '*' and by_medium.utm_medium = n.utm_medium
left join mapping as by_source
    on by_source.utm_source = n.utm_source and by_source.utm_medium = '*'
