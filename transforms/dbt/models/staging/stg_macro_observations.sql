-- FRED macro observations, deduplicated on series + observation date.

with deduped as (

    select
        *,
        row_number() over (
            partition by series_id, observation_date
            order by ingested_at desc
        ) as _rn
    from {{ source('raw', 'raw_macro_observations') }}

)

select
    series_id || '|' || observation_date as macro_observation_id,
    series_id,
    observation_date,
    value,
    ingested_at
from deduped
where _rn = 1
