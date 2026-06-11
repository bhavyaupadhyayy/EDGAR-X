-- Quarterly fundamentals per company, keyed by ticker + fiscal period.

select
    upper(ticker) || '|' || fiscal_year || 'Q' || fiscal_quarter as fundamental_id,
    upper(ticker)        as ticker,
    fiscal_year,
    fiscal_quarter,
    period_end_date,
    revenue,
    cost_of_revenue,
    net_income,
    total_assets,
    total_liabilities,
    total_equity,
    total_debt,
    shares_outstanding,
    close_price
from {{ source('raw', 'raw_fundamentals') }}
