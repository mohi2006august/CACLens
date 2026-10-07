-- Observability: last load time and row count per raw table (SYSTEM_ARCHITECTURE §8).

{% set tables = [
    ('ad_spend_daily', 'ads'), ('crm_contacts', 'crm'), ('crm_touchpoints', 'crm'),
    ('crm_deals', 'crm'), ('crm_score_history', 'crm'),
    ('stripe_customers', 'billing'), ('stripe_invoices', 'billing'),
    ('stripe_refunds', 'billing'), ('stripe_disputes', 'billing'),
    ('payroll_costs', 'costs'), ('tool_costs', 'costs')
] %}

{% for name, grp in tables %}
select
    '{{ name }}' as source_table,
    '{{ grp }}' as source_group,
    count(*) as row_count,
    max(loaded_at) as last_loaded_at
from {{ source('raw', name) }}
{% if not loop.last %}union all{% endif %}
{% endfor %}
