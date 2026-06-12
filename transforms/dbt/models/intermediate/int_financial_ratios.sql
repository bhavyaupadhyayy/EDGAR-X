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
    -- Leverage/return-on-equity ratios are meaningless when equity is zero
    -- or negative (buyback-driven negative equity: MCD, SBUX, ABBV, ...).
    case
        when total_equity > 0 then total_debt / total_equity
    end                                                       as debt_to_equity,
    total_liabilities / nullif(total_assets, 0)               as liabilities_to_assets,
    (close_price * shares_outstanding)
        / nullif(net_income * 4, 0)                           as pe_ratio,
    case
        when total_equity > 0 then net_income * 4 / total_equity
    end                                                       as roe_annualised
from fundamentals
