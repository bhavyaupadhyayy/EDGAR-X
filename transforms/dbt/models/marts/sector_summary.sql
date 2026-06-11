-- One row per sector: membership, valuation aggregates, signal activity.

with profiles as (

    select * from {{ ref('company_profile') }}

),

signals as (

    select
        companies.sector,
        count(*)                                  as signal_days,
        sum(signal_history.mention_count)         as total_mentions,
        sum(signal_history.options_volume)        as total_options_volume,
        avg(signal_history.composite_signal_score) as avg_signal_score
    from {{ ref('signal_history') }} as signal_history
    inner join {{ ref('stg_companies') }} as companies
        on signal_history.ticker = companies.ticker
    group by companies.sector

)

select
    profiles.sector,
    count(*)                       as company_count,
    sum(profiles.market_cap)       as total_market_cap,
    avg(profiles.pe_ratio)         as avg_pe_ratio,
    avg(profiles.net_margin)       as avg_net_margin,
    avg(profiles.debt_to_equity)   as avg_debt_to_equity,
    sum(profiles.total_filings)    as total_filings,
    signals.signal_days,
    signals.total_mentions,
    signals.total_options_volume,
    signals.avg_signal_score
from profiles
left join signals on profiles.sector = signals.sector
group by
    profiles.sector,
    signals.signal_days,
    signals.total_mentions,
    signals.total_options_volume,
    signals.avg_signal_score
