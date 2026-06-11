-- Financial ratios per company per fiscal quarter.
-- PE uses annualised quarterly net income (x4) against period-end market cap.

with fundamentals as (

    select * from {{ ref('stg_fundamentals') }}

)

select
    fundamental_id,
    ticker,
    fiscal_year,
    fiscal_quarter,
    period_end_date,
    close_price * shares_outstanding                          as market_cap,
    (revenue - cost_of_revenue) / nullif(revenue, 0)          as gross_margin,
    net_income / nullif(revenue, 0)                           as net_margin,
    total_debt / nullif(total_equity, 0)                      as debt_to_equity,
    total_liabilities / nullif(total_assets, 0)               as liabilities_to_assets,
    (close_price * shares_outstanding)
        / nullif(net_income * 4, 0)                           as pe_ratio,
    net_income * 4 / nullif(total_equity, 0)                  as roe_annualised
from fundamentals
