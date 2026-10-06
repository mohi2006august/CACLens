select channel, channel_label, channel_group, is_paid, sort_order
from {{ ref('channels') }}
