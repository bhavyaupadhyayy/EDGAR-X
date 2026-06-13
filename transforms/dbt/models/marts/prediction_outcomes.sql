-- Outcome tracking: each materialized model prediction joined to the REALIZED
-- outcome (FY N+1 revenue vs FY N), which already exists — leakage-disciplined
-- — as `label` in int_ml_features.
--
-- status = 'scored' when the FY N+1 outcome has materialized, else 'pending'
-- (most recent year per company, no FY N+1 yet). Pending rows are kept but
-- carry NULL actual_direction / correct.
--
-- HONESTY: data_split flags whether the prediction was in-sample. The model
-- trained on FY <= 2023 and was held out on FY2024-2025, so realized accuracy
-- on 'train' rows is in-sample and must NOT be read as live performance — the
-- calibration engine separates 'test' (genuinely out-of-sample) from 'train'.
-- The inner join to int_ml_features also carries the universe scoping through:
-- Financials never receive an outcome row (they are excluded upstream).

with predictions as (

    select * from {{ ref('stg_model_predictions') }}

),

features as (

    select ticker, fiscal_year, sector, label
    from {{ ref('int_ml_features') }}

)

select
    predictions.ticker || '|' || predictions.fiscal_year as prediction_id,
    predictions.ticker,
    predictions.fiscal_year,
    features.sector,
    predictions.predicted_score,
    predictions.predicted_direction,
    features.label                                        as actual_direction,
    case
        when features.label is null then null
        when predictions.predicted_direction = features.label then true
        else false
    end                                                  as correct,
    case when features.label is null then 'pending' else 'scored' end as status,
    case
        when features.label is null then 'pending'
        when predictions.fiscal_year <= 2023 then 'train'
        else 'test'
    end                                                  as data_split,
    predictions.model_artifact,
    predictions.scored_at
from predictions
inner join features
    on predictions.ticker = features.ticker
    and predictions.fiscal_year = features.fiscal_year
