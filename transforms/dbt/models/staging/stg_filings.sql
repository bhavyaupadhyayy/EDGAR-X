-- SEC filings, deduplicated. Kafka delivery is at-least-once, so the same
-- accession number can land more than once; keep the latest ingestion.

with deduped as (

    select
        *,
        row_number() over (
            partition by accession_number
            order by ingested_at desc
        ) as _rn
    from {{ source('raw', 'raw_filings') }}

)

select
    accession_number,
    cik,
    upper(ticker)       as ticker,
    company_name,
    form_type,
    filing_date,
    document_url,
    mdna_text,
    risk_factors_text,
    ingested_at
from deduped
where _rn = 1
