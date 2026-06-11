{#- Use custom schema names verbatim (raw / staging / intermediate / marts)
    instead of dbt's default <target_schema>_<custom> concatenation, so schema
    names are identical between the DuckDB dev target and Snowflake prod. -#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
