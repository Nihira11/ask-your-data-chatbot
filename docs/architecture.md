# First working milestone

The terminal interface is Textual. SQLite holds chat metadata and messages, while
one separate database per dataset holds queryable records. Importing a custom CSV
copies it locally and creates a fresh dataset. Activating it inserts a visible
history marker; earlier answers retain their original dataset ID and SQL/results.
Only messages after the most recent dataset switch or definition update may enter model context.

The offline route matches a small explicit list of questions to reviewed SQL.
It is an evidence demo, not a general language model. `/sql` always runs locally.
The optional AI route uses a single OpenAI Agents SDK agent and three scoped tools:
get_schema, search_context, run_checked_query. The model cannot choose a file path
or dataset ID. API calls happen for questions after AI mode is explicitly enabled (with `--ai` or
Settings), and for an explicit connection test in Settings or `--check-ai`. SQL and result tables are saved locally.

## Query boundary

SQLGlot parses one SELECT or read-only set operation; checks apply to nested
statements and table/function references. Only the active database's tables and a
small analytic function allowlist are permitted. SQLite opens in mode=ro, enables
query_only, disables trusted_schema, and applies its own authorizer. Extension/file
functions, schema tables, database attachments, writes and recursive CTEs are blocked.
The query progress handler cancels after three seconds of SQLite execution. A result
contains at most 100 rows; this cap is applied after execution, not before aggregation.
Duplicate result-column labels retain positional values. SQLite values are capped at
1 MB; imported CSV cells are capped at 10,000 characters. This is a local demo boundary,
not an adversarial public-service sandbox or strict OS memory/CPU isolation.

The AI run has eight agent turns, a 90-second wall-clock timeout and at most three
SQL attempts (one initial attempt plus two repairs). Tracing is disabled, response
storage is disabled in model settings, and raw provider errors are not persisted.
These application settings are not a claim about provider-side retention policies.
A model data answer without a successful current query is rejected. A successful
query still does not prove the answer or explanation is semantically correct.

## CSV behaviour

UTF-8 with optional BOM, comma delimiter, at most 5 MB, 50,000 rows and 100 columns.
Strict width/header checks; case-insensitive duplicate headers are rejected. Integer
columns without leading zeros become INTEGER; all-decimal columns become REAL;
other columns remain TEXT. Dates stay as text and their format needs inspection.
Blanks become NULL. Business meanings are not inferred. Import preview confirms
file, schema and blank counts before activation. Files are snapshots, not live links.
The limits are enforced and unit-tested boundaries, not a published performance benchmark.

## Retrieval and pending work

The tiny bundled schema uses full schema plus two reviewed definition documents.
This baseline has no FAISS index, embeddings or reranker. Custom CSVs have dataset-
specific import notes and user-confirmed definitions editable through Settings. Definition
revisions are persisted with the dataset. Each answer stores the sources seen at the
start of its turn; updates create a context boundary in every chat using that dataset. General follow-ups are
prompted using recent context in AI mode and still need live-model evaluation.
The live model and billing route have not been verified with account credentials.
Local tests mock the SDK runner and check actual registered tool execution.

Next milestones: verify an authenticated model/tool round-trip, expand held-out questions and evaluate actual model accuracy; consider
vector retrieval only after comparison against the current small-schema baseline.

## Connection setup and bounded context

AIConfig keeps the API key out of reprs and chat payloads. The key entered in Settings
is session-only. Each run creates an explicit SDK client for api.openai.com with the
selected key/model and automatic SDK retries disabled. Switching keys does not depend
on a cached global SDK client. Provider failures map to fixed, actionable messages.
The explicit connection check uses a temporary database containing only 20 and 22;
it verifies a successful current query returned 42 before enabling the Settings button.
That check does not certify model accuracy. This implementation has been mock-tested;
no authenticated live request has been made during development.

Recent context includes at most twelve messages and 16,000 characters. It keeps
question/answer text and complete previous SQL to preserve date filters; it omits old
result tables and repeated definitions. Whole old messages are dropped when oversized,
never partial JSON or a truncated WHERE clause. The current schema, current saved
meanings and question are always supplied separately. Follow-up correctness still needs
live-model evaluation; these bounds and data-isolation behaviour are locally tested.
