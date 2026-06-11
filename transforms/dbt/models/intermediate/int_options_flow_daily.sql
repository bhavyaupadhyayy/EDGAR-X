-- Daily options-flow aggregation per underlying.

with activity as (

    select * from {{ ref('stg_options_activity') }}

)

select
    underlying || '|' || activity_date                            as flow_id,
    underlying,
    activity_date,
    count(*)                                                      as flagged_contracts,
    sum(day_volume)                                               as total_volume,
    sum(case when contract_type = 'call' then day_volume else 0 end)
        * 1.0
        / nullif(sum(case when contract_type = 'put' then day_volume else 0 end), 0)
                                                                  as call_put_volume_ratio,
    max(volume_oi_ratio)                                          as max_volume_oi_ratio,
    avg(implied_volatility)                                       as avg_implied_volatility
from activity
group by underlying, activity_date
