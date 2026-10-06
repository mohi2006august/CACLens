select attribution_model, label, description, sort_order
from {{ ref('attribution_models') }}
