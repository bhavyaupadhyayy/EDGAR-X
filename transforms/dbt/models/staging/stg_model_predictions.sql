-- XGBoost revenue-direction predictions per company-fiscal-year (derived
-- artifact materialized by self_improvement/score_predictions.py). One row
-- per ticker-fiscal-year; latest scoring run replaces the table wholesale.

select
    upper(ticker)        as ticker,
    fiscal_year,
    predicted_score,
    predicted_direction,
    model_artifact,
    scored_at
from {{ source('raw', 'raw_model_predictions') }}
