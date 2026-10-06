with deduped as (
    {{ latest_version(source('raw', 'ad_spend_daily'), ['source_system', 'campaign_id', 'date_day']) }}
)

select
    cast(d.date_day as date) as date_day,
    d.source_system,
    coalesce(p.channel, 'other') as channel,
    cast(d.campaign_id as varchar) as campaign_id,
    d.campaign_name,
    {{ normalize_key('d.campaign_name') }} as campaign,
    cast(coalesce(d.spend, 0) as double) as spend,
    cast(coalesce(d.impressions, 0) as bigint) as impressions,
    cast(coalesce(d.clicks, 0) as bigint) as clicks,
    upper(d.currency) as currency
from deduped as d
left join {{ ref('ad_platform_channels') }} as p
    on p.source_system = d.source_system
where d.date_day is not null
