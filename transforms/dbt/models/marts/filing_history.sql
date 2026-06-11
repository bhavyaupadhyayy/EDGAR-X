-- One row per filing, enriched with language features and sector.

with filings as (

    select * from {{ ref('stg_filings') }}

),

features as (

    select * from {{ ref('int_filing_language_features') }}

),

companies as (

    select * from {{ ref('stg_companies') }}

)

select
    filings.accession_number,
    filings.ticker,
    companies.sector,
    filings.company_name,
    filings.form_type,
    filings.filing_date,
    filings.document_url,
    features.mdna_word_count,
    features.litigation_mentions,
    features.impairment_mentions,
    features.decline_mentions,
    features.uncertain_mentions,
    features.recession_mentions,
    features.risk_word_total,
    features.risk_words_per_1000
from filings
inner join companies on filings.ticker = companies.ticker
left join features on filings.accession_number = features.accession_number
