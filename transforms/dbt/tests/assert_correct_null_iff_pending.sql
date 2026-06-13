-- Invariant: `correct` is NULL exactly when status = 'pending'.
-- A scored row must have a boolean correctness; a pending row must not.
-- Returns offending rows (the test passes when there are none).

select prediction_id, status, correct
from {{ ref('prediction_outcomes') }}
where (status = 'pending' and correct is not null)
   or (status = 'scored' and correct is null)
