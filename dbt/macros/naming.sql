{# Use the configured schema name as-is (staging, journeys, marts, ...) instead of
   dbt's default "<target>_<custom>" so the API can address marts.* directly. #}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}


{# Normalise free-text keys (campaign names, utm_campaign) so ad-platform campaign
   names and UTM tags join: "Prospecting Lookalike" -> "prospecting_lookalike". #}
{% macro normalize_key(column) -%}
    coalesce(
        nullif(trim(regexp_replace(lower(trim({{ column }})), '[^a-z0-9]+', '_', 'g'), '_'), ''),
        '(none)'
    )
{%- endmacro %}


{# Map CRM segment labels to smb / mid_market / enterprise / unknown. Loaders already
   normalise, this keeps staging robust to manual uploads and older loads. #}
{% macro normalize_segment(column) -%}
    case regexp_replace(lower(trim({{ column }})), '[^a-z]+', '_', 'g')
        when 'smb' then 'smb'
        when 'small_business' then 'smb'
        when 'small' then 'smb'
        when 'startup' then 'smb'
        when 'mid_market' then 'mid_market'
        when 'midmarket' then 'mid_market'
        when 'mid' then 'mid_market'
        when 'mm' then 'mid_market'
        when 'enterprise' then 'enterprise'
        when 'ent' then 'enterprise'
        when 'large' then 'enterprise'
        else 'unknown'
    end
{%- endmacro %}


{# Keep the most recently loaded version of each record. #}
{% macro latest_version(relation, keys) -%}
    select *
    from {{ relation }}
    qualify row_number() over (
        partition by {{ keys | join(', ') }}
        order by loaded_at desc nulls last
    ) = 1
{%- endmacro %}
