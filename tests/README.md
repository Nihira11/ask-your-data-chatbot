# Tests to add with implementation

No implementation tests have been written yet.

Prioritise meaningful checks for SQL validation and execution:

- Allowed aggregation, joins, and read-only CTEs work.
- Multiple statements, writes, data-modifying CTEs, prohibited tables, and
  prohibited functions are rejected.
- Database permissions still prevent writes if application validation fails.
- Database-side timeouts cancel expensive queries.
- Result limits are enforced and truncation is disclosed.
- Clarification and retry limits work in the complete workflow.

Use synthetic data and mocked model responses for ordinary automated tests.
Keep any paid live-model evaluations separate and explicitly invoked.
