-- Company dimension: the ticker universe with sector classification.

select
    upper(ticker)        as ticker,
    cik,
    company_name,
    sector,
    industry
from {{ source('raw', 'raw_companies') }}
