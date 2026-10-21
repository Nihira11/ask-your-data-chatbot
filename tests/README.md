# Tests

Run `.venv/bin/python -m pytest -q` from the repository root.
Tests use temporary SQLite databases, source CSV/Decimal reconciliation, a mocked SDK
runner, and Textual's headless Pilot. They make no paid model calls and do not use
private CSVs or normal chat history.

`python -m evaluation.evaluate` runs 12 deterministic offline reference cases.
These are regression checks, not a live LLM benchmark. Questions marked draft are
rejected. These offline checks do not measure model accuracy, follow-up success,
API latency or cost.

`python -m evaluation.evaluate_live` previews regression questions without API calls.
Adding `--live` explicitly uses API credits and isolated temporary chats. See the
repository README for suite selection and spending/latency bounds. The ordinary
pytest suite tests this runner with fakes and never invokes its paid mode.
