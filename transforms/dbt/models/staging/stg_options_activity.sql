-- Unusual options activity events, keyed by contract + detection time.

select
    contract_ticker || '|' || detected_at as activity_id,
    upper(underlying)     as underlying,
    contract_ticker,
    contract_type,
    strike,
    expiration,
    day_volume,
    open_interest,
    volume_oi_ratio,
    implied_volatility,
    detected_at,
    cast(detected_at as date) as activity_date
from {{ source('raw', 'raw_options_activity') }}
