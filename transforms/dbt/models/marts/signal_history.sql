-- One row per ticker per day on which any signal fired: options flow,
-- retail sentiment, or a filing event. Composite score is a bounded 0-100
-- heuristic placeholder until the Layer 3 models replace it.

with options_flow as (

    select
        underlying       as ticker,
        activity_date    as signal_date,
        flagged_contracts,
        total_volume     as options_volume,
        call_put_volume_ratio,
        max_volume_oi_ratio
    from {{ ref('int_options_flow_daily') }}

),

sentiment as (

    select
        ticker,
        mention_date     as signal_date,
        mention_count,
        total_score      as sentiment_score
    from {{ ref('int_sentiment_daily') }}

),

filing_events as (

    select
        ticker,
        filing_date      as signal_date,
        count(*)         as filings_filed
    from {{ ref('stg_filings') }}
    group by ticker, filing_date

),

all_dates as (

    select ticker, signal_date from options_flow
    union
    select ticker, signal_date from sentiment
    union
    select ticker, signal_date from filing_events

),

joined as (

    select
        all_dates.ticker,
        all_dates.signal_date,
        coalesce(options_flow.flagged_contracts, 0)      as flagged_contracts,
        coalesce(options_flow.options_volume, 0)         as options_volume,
        options_flow.call_put_volume_ratio,
        options_flow.max_volume_oi_ratio,
        coalesce(sentiment.mention_count, 0)             as mention_count,
        coalesce(sentiment.sentiment_score, 0)           as sentiment_score,
        coalesce(filing_events.filings_filed, 0)         as filings_filed
    from all_dates
    left join options_flow
        on all_dates.ticker = options_flow.ticker
        and all_dates.signal_date = options_flow.signal_date
    left join sentiment
        on all_dates.ticker = sentiment.ticker
        and all_dates.signal_date = sentiment.signal_date
    left join filing_events
        on all_dates.ticker = filing_events.ticker
        and all_dates.signal_date = filing_events.signal_date

)

select
    joined.ticker || '|' || joined.signal_date as signal_id,
    joined.*,
    least(
        100.0,
        coalesce(joined.max_volume_oi_ratio, 0) * 8
            + joined.mention_count * 5
            + joined.filings_filed * 10
    )                                          as composite_signal_score
from joined
inner join {{ ref('stg_companies') }} as companies
    on joined.ticker = companies.ticker
