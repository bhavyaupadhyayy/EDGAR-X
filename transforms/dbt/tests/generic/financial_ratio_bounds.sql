{#- Custom generic test: fail when a financial ratio falls outside a sane
    range. NULL ratios (e.g. PE with zero earnings) are allowed; not_null
    coverage is a separate concern. -#}
{% test financial_ratio_bounds(model, column_name, min_value, max_value) %}

select *
from {{ model }}
where {{ column_name }} is not null
  and (
        {{ column_name }} < {{ min_value }}
     or {{ column_name }} > {{ max_value }}
  )

{% endtest %}
