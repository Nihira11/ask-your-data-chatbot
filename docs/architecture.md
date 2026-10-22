# Architecture

The current local-app milestone is complete. See the [product walkthrough](ask-your-data-walkthrough.pdf)
for the visual tour and the [README](../README.md) for setup and verification results.
The user has manually confirmed that the native macOS file picker opens correctly.

The terminal interface is Textual. SQLite holds chat metadata and messages, while
one separate database per dataset holds queryable records. Importing a custom CSV
copies it locally and creates a fresh dataset, or reuses an exact previously imported
file by SHA-256 content identity. Activating it inserts a visible
history marker; earlier answers retain their original dataset ID and SQL/results.
Only messages after the most recent dataset switch or context-resetting definition
update may enter model context.

The offline route matches a small explicit list of questions to reviewed SQL.
It is an evidence demo, not a general language model. `/sql` always runs locally.
The optional AI route uses a single OpenAI Agents SDK agent and three scoped tools:
get_schema, search_context, run_checked_query. The model cannot choose a file path
or dataset ID. API calls happen for questions after AI mode is explicitly enabled (with `--ai` or
Settings, including a restored Settings preference), and for an explicit connection
test in Settings or `--check-ai`. Startup makes no API calls. Basic CSV overview,
column and missing-value requests run locally in either mode; full phrase matching
keeps filtered questions on the AI route. SQL, result tables and query error messages
are saved locally.

## Query boundary

SQLGlot parses one SELECT, VALUES or read-only set operation; checks apply to nested
statements and table references. Only the active database's tables and explicitly
permitted JSON table functions are accessible. SQLite opens in mode=ro, enables
query_only, disables trusted_schema, and applies its own authorizer. Extension/file
functions, schema tables, database attachments, writes and recursive CTEs are blocked.
Function permissions come from `PRAGMA function_list` on the actual query connection.
The authorizer permits native built-ins carrying SQLite's `SQLITE_INNOCUOUS` flag,
plus reviewed built-in median/percentile aggregates on builds exposing them without
that flag. Extension/UDF names and built-ins with custom overloads are excluded;
`load_extension`, `sqlite_log`, `randomblob` and `zeroblob` are explicitly denied.
See [SQLite's function flags](https://www.sqlite.org/c3ref/c_deterministic.html).
The original SQL is executed unchanged, avoiding SQLGlot's normalized function names
and dialect transformations. Text, date, math, JSON/JSONB, aggregate and window
functions therefore follow the installed engine's capabilities. AI context includes
the engine version and actual permitted function list, including optional functions.

The four JSON/JSONB each/tree table functions are explicitly permitted when available.
Trusted literal-only initialization connects these SQLite modules before installing
the authorizer, so the user query never receives internal schema-write permissions.
Other table functions and schema reads stay blocked. JSON functions can transform
values in a result without modifying stored data.
Non-finite numeric results become labelled strings. BLOB results become hexadecimal
SQL literals. Both carry warnings saved with the answer and retained in export metadata.
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

For CSVs, AI context includes complete value lists for up to eight TEXT columns when
each has at most twenty distinct values, each at most 100 characters. These bounded
read-only inspections have a 0.5-second limit per column and are reference data, not
instructions or answer evidence. They are cached per turn. Direct equality filters
in model queries are checked for known case/day-name spelling mismatches against
these values (for example Sunday versus Sun). A mismatch returns a repair error
within the three-attempt budget, rather than silently changing SQL or presenting a
false zero. Derived queries are not checked this way; explicit `/sql` remains literal.

## CSV behaviour

UTF-8 with optional BOM, comma delimiter, at most 5 MB, 50,000 rows and 100 columns.
Strict width/header checks; case-insensitive duplicate headers are rejected. Integer
columns without leading zeros become INTEGER; columns containing decimals and
optional whole numbers become REAL;
other columns remain TEXT. Dates stay as text and their format needs inspection.
Blanks become NULL. Business meanings are not inferred. Import preview confirms
file, schema and blank counts before activation. Files are snapshots, not live links.
The limits are enforced and unit-tested boundaries, not a published performance benchmark.
Re-imports whose inferred types have changed create a fresh snapshot with copied
confirmed definitions. Existing chats and dataset databases are left intact.

## Definitions, context and evaluation

The tiny bundled schema uses full schema plus two reviewed definition documents.
This baseline has no FAISS index, embeddings or reranker. Custom CSVs have dataset-
specific import notes and user-confirmed definitions editable through Settings. Definition
revisions are persisted with the dataset. Each answer stores the sources seen at the
start of its turn; manual updates create a context boundary in every chat using that dataset.
AI clarification replies can include one structured column/meaning proposal. The app
checks it against the schema and displayed reply and stores it as pending, without
changing definitions. An explicit affirmative next reply appends the mapping locally,
under a revision check, before constructing that turn's tools and definition snapshot.
The confirming chat keeps its follow-up context; other chats get a context boundary.
Denials, qualified agreements, stale proposals and dataset switches do not save a mapping.
No additional model call is made to save it. Older replies without proposal metadata
are not retrospectively interpreted. These paths are tested with a mocked SDK runner;
a six-question live tips regression on 2026-10-21 also verified one size definition,
confirmation with `Yess`, and reuse in a new chat after reopening the store.
General follow-ups use recent context in AI mode. The same live regression checked
Dinner, Sunday and non-smoker filter retention; broader coverage remains outstanding.
On 2026-10-21, user-provided screenshots confirmed a live connection/tool check and
four sample answers: total revenue, a France follow-up, all-country top products,
and the absence of cost data for profit. The three displayed SQL queries were checked
locally against the source CSV. Broader model accuracy remains unmeasured.
Local tests mock the SDK runner and check actual registered tool execution.

`evaluation.evaluate_live` is a separate opt-in paid runner: without `--live`, it
only previews cases. CSV/Decimal supplies independent references. Temporary stores
isolate its conversations and definitions from normal use. It stops on a failed check
or missing usage, with configurable question limits and token/time stops checked
between questions. Reports contain actual answers, SQL, latency and SDK token usage,
plus code/dataset hashes. Numerical and behavioral checks are not a semantic judge;
reports still require human review. The first live tips run passed 6/6 with 15 model
requests (24,839 input tokens, 1,168 output tokens), including one rejected wrong-table
query that the model successfully repaired. No dollar cost has been inferred.

The retail and supermarket live suites also passed 3/3 each on 2026-10-21, bringing
the completed development regression to 12/12 cases across three datasets. Together
the runs reported 28 requests, 52,536 input tokens and 2,025 output tokens. These results
remain a small development regression, not a general model-accuracy benchmark.

## Future extensions

- Expand held-out questions and messy-data fixtures across unfamiliar schemas.
- Add native file and export dialogs for Windows and Linux.
- Offer optional charts backed by the same saved query evidence.
- Compare supported models on answer quality, latency and reported usage.
- Consider vector retrieval only after comparison against the current full-schema baseline.

## Connection setup and bounded context

AIConfig keeps the API key out of reprs and chat payloads. The key entered in Settings
is session-only. The local store persists only the selected mode and model. Startup
restores them with the environment/.env key, falling back to Demo with a setup notice
if configuration is incomplete. Explicit CLI mode flags override the preference;
CLI one-question requests still require `--ai`. Each AI run creates an explicit SDK client for api.openai.com with the
selected key/model and automatic SDK retries disabled. Switching keys does not depend
on a cached global SDK client. Provider failures map to fixed, actionable messages.
The explicit connection check uses a temporary database containing only 20 and 22;
it verifies a successful current query returned 42. It is optional; Use AI requires
a nonempty key and a syntactically valid model ID, without claiming verified access.
That check does not certify model accuracy. Automated tests use mocks; the user-run
live smoke test described above is separate evidence.

Recent context includes at most twelve messages and 16,000 characters. It keeps
question/answer text and complete previous SQL to preserve date filters; it omits old
result tables and repeated definitions. Whole old messages are dropped when oversized,
never partial JSON or a truncated WHERE clause. The current schema, current saved
meanings and question are always supplied separately. Follow-up correctness still needs
live-model evaluation; these bounds and data-isolation behaviour are locally tested.
