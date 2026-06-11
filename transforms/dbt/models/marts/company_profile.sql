-- One row per company: identity, sector, latest ratios, filing activity.

with companies as (

    select * from {{ ref('stg_companies') }}

),

latest_ratios as (

    select *
    from {{ ref('int_financial_ratios') }}
    qualify row_number() over (
        partition by ticker
        order by period_end_date desc
    ) = 1

),

filing_stats as (

    select
        ticker,
        count(*)         as total_filings,
        max(filing_date) as last_filing_date
    from {{ ref('stg_filings') }}
    group by ticker

)

select
    companies.ticker,
    companies.cik,
    companies.company_name,
    companies.sector,
    companies.industry,
    latest_ratios.period_end_date     as latest_fundamentals_date,
    latest_ratios.market_cap,
    latest_ratios.pe_ratio,
    latest_ratios.gross_margin,
    latest_ratios.net_margin,
    latest_ratios.debt_to_equity,
    latest_ratios.roe_annualised,
    coalesce(filing_stats.total_filings, 0) as total_filings,
    filing_stats.last_filing_date
from companies
left join latest_ratios on companies.ticker = latest_ratios.ticker
left join filing_stats on companies.ticker = filing_stats.ticker
