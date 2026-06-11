-- Reddit ticker mentions (one row per post x ticker), deduplicated.

with deduped as (

    select
        *,
        row_number() over (
            partition by post_id, ticker
            order by ingested_at desc
        ) as _rn
    from {{ source('raw', 'raw_sentiment_mentions') }}

)

select
    post_id || '|' || upper(ticker) as mention_id,
    post_id,
    subreddit,
    upper(ticker)        as ticker,
    title,
    score,
    num_comments,
    created_at,
    cast(created_at as date) as mention_date,
    ingested_at
from deduped
where _rn = 1
