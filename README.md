# Ask Your Data Chatbot

Ask questions about a sales dataset in plain English and inspect the SQL behind each answer.

**Status: initial scaffold.** The Streamlit preview and project structure are ready. The AI model, LangGraph workflow, PostgreSQL connection, RAG index, and SQL validator are not implemented yet. Starting the preview makes no API calls and needs no API key.

## Problem statement

LLMs can answer data questions, but they can also invent facts or generate incorrect queries. This project aims to give users answers grounded in database results, with the executed SQL and relevant definitions available for inspection.

## Technology choices

| Component | Choice |
| --- | --- |
| Interface | Streamlit |
| Language | Python 3.11 or 3.12 |
| Agent workflow | LangGraph |
| Language model | GPT-4.1 mini |
| Embeddings | text-embedding-3-small |
| Retrieval index | FAISS |
| Database | PostgreSQL via SQLAlchemy and Psycopg |
| SQL parsing | SQLGlot, with application policy checks |

The model names are starting choices to evaluate, not a guarantee of answer accuracy. Dependencies in this initial scaffold are unpinned; create a tested lock file when implementing the backend.

## Start the interface preview

Run these commands from this repository's directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

On Windows, activate the environment with `.venv\Scripts\activate` instead.

Only Streamlit is needed for the preview. It shows the intended interface and the current development status; it does not answer data questions yet.

## Prepare for backend development

```bash
python -m pip install -r requirements-agent.txt
cp .env.example .env
```

Replace the placeholders in your local `.env`. Never commit the real file. The initial scaffold does not read or use these settings yet.

Use a restricted read-only database account for chatbot queries. Use a separate account for initial data imports; never give its credentials to the agent. The `.env.example` connection string does not create a database or database role.

## Repository structure

```text
app.py                    Streamlit preview
requirements.txt          Interface dependency
requirements-agent.txt    Planned backend dependencies
requirements-dev.txt      Test dependencies
.env.example              Configuration template, without secrets
src/
  workflow.py             LangGraph construction placeholder
  state.py                Shared workflow state
  prompts.py              Initial agent instructions
  tools.py                Planned tool contracts
  database.py             Database connection placeholder
  retrieval.py            RAG lookup placeholder
  validation.py           SQL validation placeholder (blocks all queries)
scripts/
  load_data.py            Future import entry point
  build_index.py          Future indexing entry point
data/
  sample/                 Place the selected dataset here
  knowledge/              RAG documentation templates
  indexes/                Generated indexes; contents ignored by Git
tests/                    Validation test plan
evaluation/               Held-out question template and runner placeholder
docs/                     Technical documentation as features are implemented
```

## Evaluation

Replace the examples in `evaluation/questions.json` with verified questions and expected results. The template entries are marked `draft` and contain no invented reference answers. Keep held-out questions out of `data/knowledge/sql_examples.json`.

Measure answer correctness separately from successful SQL execution. Also record clarification behaviour, failed queries, latency, and API usage. See `tests/README.md` for the validation cases to implement.

## References

- [OpenAI model documentation](https://developers.openai.com/api/docs/models/gpt-4.1-mini)
- [Function calling](https://developers.openai.com/api/docs/guides/function-calling)
- [LangGraph overview](https://docs.langchain.com/oss/python/langgraph/overview)
