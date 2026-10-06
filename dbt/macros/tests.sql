{# Generic test: the combination of columns is unique. #}
{% test unique_combination_of_columns(model, combination_of_columns) %}
    select {{ combination_of_columns | join(', ') }}, count(*) as n
    from {{ model }}
    group by {{ combination_of_columns | join(', ') }}
    having count(*) > 1
{% endtest %}


{# Generic test: within each group, `column_name` sums to `expected` (default 1). #}
{% test sums_to(model, column_name, group_by, expected=1, tolerance=0.000001) %}
    select {{ group_by | join(', ') }}, sum({{ column_name }}) as total
    from {{ model }}
    group by {{ group_by | join(', ') }}
    having abs(sum({{ column_name }}) - {{ expected }}) > {{ tolerance }}
{% endtest %}


{# Generic test: the column is never negative. #}
{% test non_negative(model, column_name) %}
    select * from {{ model }} where {{ column_name }} < 0
{% endtest %}
