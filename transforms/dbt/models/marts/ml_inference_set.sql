-- Most recent fiscal year per company: no FY(N+1) yet, so no label.
-- These rows are scored at inference time, never trained on.

select *
from {{ ref('int_ml_features') }}
where label is null
