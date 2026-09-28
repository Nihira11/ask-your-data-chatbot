# Tests

Run `.venv/bin/python -m pytest -q` from the repository root.
Tests use temporary SQLite databases, source CSV/Decimal reconciliation, a mocked SDK
runner, and Textual's headless Pilot. They make no paid model calls and do not use
private CSVs or normal chat history.

`python -m evaluation.evaluate` runs 12 deterministic offline reference cases.
These are regression checks, not a live LLM benchmark. Questions marked draft are
rejected. Add a separate explicitly invoked live-model runner before reporting model
accuracy, follow-up success, latency or cost.
