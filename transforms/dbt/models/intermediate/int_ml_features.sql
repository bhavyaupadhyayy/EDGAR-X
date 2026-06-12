-- Per company-fiscal-year ML feature base with the revenue-direction label.
--
-- Label: 1 if FY(N+1) revenue > FY(N) revenue, 0 if lower-or-equal, NULL when
-- FY(N+1) is not yet available (the most recent year per company — kept for
-- inference, excluded from training).
--
-- Leakage discipline: every feature is information available AT the FY(N)
-- 10-K filing — fundamentals of FY(N) and earlier, language features of the
-- FY(N) 10-K itself, and macro observations as of the filing date. Where no
-- filing was matched (fiscal years older than the 10-year filing lookback),
-- filing time is approximated as period end + 90 days (typical filing lag).
--
-- Financials (GICS) are excluded: bank/insurer "revenue" under the XBRL
-- concepts we extract is not economically comparable, and their coverage is
-- biased toward those that happen to tag totals.

with companies as (

    select * from {{ ref('stg_companies') }}
    where sector != 'Financials'

),

fundamentals as (

    select * from {{ ref('stg_fundamentals') }}

),

labelled as (

    select
        cur.fundamental_id,
        cur.ticker,
        cur.fiscal_year,
        cur.period_end_date,
        cur.revenue,
        case
            when prev.revenue is not null and prev.revenue != 0
                then cur.revenue / prev.revenue - 1
        end as revenue_growth_1y,
        case
            when nxt.revenue is null then null
            when nxt.revenue > cur.revenue then 1
            else 0
        end as label
    from fundamentals as cur
    left join fundamentals as nxt
        on cur.ticker = nxt.ticker and nxt.fiscal_year = cur.fiscal_year + 1
    left join fundamentals as prev
        on cur.ticker = prev.ticker and prev.fiscal_year = cur.fiscal_year - 1

),

filings_10k as (

    select ticker, accession_number, filing_date
    from {{ ref('stg_filings') }}
    where form_type = '10-K'

),

-- The 10-K covering FY(N) is the first one filed after the period end.
matched_filings as (

    select
        labelled.fundamental_id,
        filings_10k.accession_number,
        filings_10k.filing_date
    from labelled
    inner join filings_10k
        on filings_10k.ticker = labelled.ticker
        and filings_10k.filing_date > labelled.period_end_date
        and filings_10k.filing_date <= labelled.period_end_date + interval '180 days'
    qualify row_number() over (
        partition by labelled.fundamental_id
        order by filings_10k.filing_date
    ) = 1

),

macro_ranges as (

    select
        series_id,
        observation_date,
        value,
        lead(observation_date) over (
            partition by series_id order by observation_date
        ) as next_observation
    from {{ ref('stg_macro_observations') }}

),

cpi_yoy as (

    select
        observation_date,
        value / nullif(lag(value, 12) over (order by observation_date), 0) - 1 as yoy,
        lead(observation_date) over (order by observation_date) as next_observation
    from {{ ref('stg_macro_observations') }}
    where series_id = 'CPIAUCSL'

),

anchored as (

    select
        labelled.*,
        matched_filings.accession_number,
        matched_filings.filing_date,
        coalesce(
            matched_filings.filing_date,
            labelled.period_end_date + interval '90 days'
        ) as anchor_date
    from labelled
    left join matched_filings
        on labelled.fundamental_id = matched_filings.fundamental_id

)

select
    anchored.ticker || '|' || anchored.fiscal_year as ml_row_id,
    anchored.ticker,
    anchored.fiscal_year,
    anchored.period_end_date,
    anchored.accession_number,
    anchored.filing_date,
    anchored.label,
    companies.sector,
    -- fundamentals / ratio features (FY N)
    anchored.revenue,
    anchored.revenue_growth_1y,
    ratios.gross_margin,
    ratios.net_margin,
    ratios.debt_to_equity,
    ratios.liabilities_to_assets,
    ratios.roe_annualised,
    -- filing language features (FY N 10-K; NULL when outside filing lookback)
    language.mdna_word_count,
    language.litigation_mentions,
    language.impairment_mentions,
    language.decline_mentions,
    language.uncertain_mentions,
    language.recession_mentions,
    language.risk_word_total,
    language.risk_words_per_1000,
    -- macro regime as of the filing (or approximated filing) date
    fed_funds.value as fed_funds_rate,
    yield_curve.value as yield_curve_spread,
    unemployment.value as unemployment_rate,
    cpi.yoy as cpi_yoy
from anchored
inner join companies
    on anchored.ticker = companies.ticker
left join {{ ref('int_financial_ratios') }} as ratios
    on anchored.fundamental_id = ratios.fundamental_id
left join {{ ref('int_filing_language_features') }} as language
    on anchored.accession_number = language.accession_number
left join macro_ranges as fed_funds
    on fed_funds.series_id = 'FEDFUNDS'
    and anchored.anchor_date >= fed_funds.observation_date
    and (
        fed_funds.next_observation is null
        or anchored.anchor_date < fed_funds.next_observation
    )
left join macro_ranges as yield_curve
    on yield_curve.series_id = 'T10Y2Y'
    and anchored.anchor_date >= yield_curve.observation_date
    and (
        yield_curve.next_observation is null
        or anchored.anchor_date < yield_curve.next_observation
    )
left join macro_ranges as unemployment
    on unemployment.series_id = 'UNRATE'
    and anchored.anchor_date >= unemployment.observation_date
    and (
        unemployment.next_observation is null
        or anchored.anchor_date < unemployment.next_observation
    )
left join cpi_yoy as cpi
    on anchored.anchor_date >= cpi.observation_date
    and (cpi.next_observation is null or anchored.anchor_date < cpi.next_observation)
