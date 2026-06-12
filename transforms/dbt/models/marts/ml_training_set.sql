-- Labelable company-fiscal-years for revenue-direction model training.
-- Rows whose FY(N+1) is not yet available live in ml_inference_set instead.

select *
from {{ ref('int_ml_features') }}
where label is not null
