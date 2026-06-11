-- Daily retail-sentiment aggregation per ticker.

with mentions as (

    select * from {{ ref('stg_sentiment_mentions') }}

)

select
    ticker || '|' || mention_date         as sentiment_id,
    ticker,
    mention_date,
    count(*)                              as mention_count,
    sum(score)                            as total_score,
    sum(num_comments)                     as total_comments,
    avg(score)                            as avg_score
from mentions
group by ticker, mention_date
