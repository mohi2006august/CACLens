-- PRD NFR: mart spend reconciles to ad-platform totals within tolerance.
-- Spend is repeated per attribution model, so compare a single model.

with source_total as (
    select coalesce(sum(spend), 0) as total from {{ ref('stg_ad_spend') }}
),

mart_total as (
    select coalesce(sum(paid_spend), 0) as total
    from {{ ref('fct_acquisition_daily') }}
    where attribution_model = 'position_based'
)

select s.total as source_total, m.total as mart_total
from source_total as s
cross join mart_total as m
where abs(m.total - s.total) > {{ var('reconciliation_tolerance') }} * greatest(s.total, 1)
