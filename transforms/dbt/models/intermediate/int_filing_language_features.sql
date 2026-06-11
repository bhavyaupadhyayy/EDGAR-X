-- Language features extracted from filing section text.
-- Keyword occurrences are counted with the portable length/replace idiom so
-- the SQL runs identically on DuckDB and Snowflake.

{% set risk_keywords = ['litigation', 'impairment', 'decline', 'uncertain', 'recession'] %}

with filings as (

    -- Section parsing is best-effort on real filings: coalesce missing
    -- sections to empty text so feature counts are 0, never NULL.
    select
        accession_number,
        ticker,
        form_type,
        filing_date,
        coalesce(mdna_text, '')         as mdna_text,
        coalesce(risk_factors_text, '') as risk_factors_text
    from {{ ref('stg_filings') }}

),

features as (

    select
        accession_number,
        ticker,
        form_type,
        filing_date,
        length(mdna_text)                                            as mdna_chars,
        length(risk_factors_text)                                    as risk_factors_chars,
        cast(
            length(mdna_text) - length(replace(mdna_text, ' ', ''))
            as integer
        ) + 1                                                        as mdna_word_count,
        {% for kw in risk_keywords %}
        cast(
            (
                length(lower(mdna_text || ' ' || risk_factors_text))
                - length(replace(lower(mdna_text || ' ' || risk_factors_text), '{{ kw }}', ''))
            ) / {{ kw | length }}
            as integer
        )                                                            as {{ kw }}_mentions{% if not loop.last %},{% endif %}
        {% endfor %}
    from filings

)

select
    *,
    litigation_mentions
        + impairment_mentions
        + decline_mentions
        + uncertain_mentions
        + recession_mentions                                         as risk_word_total,
    (
        litigation_mentions
        + impairment_mentions
        + decline_mentions
        + uncertain_mentions
        + recession_mentions
    ) * 1000.0 / nullif(mdna_word_count, 0)                          as risk_words_per_1000
from features
