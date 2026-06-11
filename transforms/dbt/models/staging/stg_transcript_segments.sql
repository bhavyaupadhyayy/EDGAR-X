-- Earnings-call transcript speaker turns, deduplicated per transcript segment.

with deduped as (

    select
        *,
        row_number() over (
            partition by url, segment_index
            order by ingested_at desc
        ) as _rn
    from {{ source('raw', 'raw_transcript_segments') }}

)

select
    url || '|' || segment_index as segment_id,
    url                  as transcript_url,
    upper(ticker)        as ticker,
    company_name,
    fiscal_year,
    fiscal_quarter,
    segment_index,
    speaker,
    role,
    section,
    text,
    ingested_at
from deduped
where _rn = 1
