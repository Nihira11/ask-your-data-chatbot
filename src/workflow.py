"""Offline evidence demo and an optional, explicit OpenAI Agents SDK route."""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from typing import Literal

from src.config import AIConfig, provider_error
from src.clarifications import pending_definition, remember_confirmation
from src.demo_intents import demo_question
from src.csv_profile import csv_profile
from src.formatting import format_gbp
from src.prompts import SYSTEM_PROMPT
from src.storage import Store
from src.tools import DatasetTools

REVENUE_FROM = '''FROM order_items i JOIN orders o ON o.order_id = i.order_id
WHERE i.unit_price >= 0'''
EXAMPLES = [
    'What is the total revenue?',
    'Show monthly revenue',
    'Which five products generated the most revenue?',
    'Show revenue by country',
    'How many orders are there?',
]
DEMO_SQL = {
    'what is the total revenue': f'SELECT ROUND(SUM(i.quantity * i.unit_price), 2) AS revenue_gbp {REVENUE_FROM}',
    'show monthly revenue': f"SELECT SUBSTR(o.order_date, 1, 7) AS month, ROUND(SUM(i.quantity * i.unit_price), 2) AS revenue_gbp {REVENUE_FROM} GROUP BY month ORDER BY month",
    'which five products generated the most revenue': '''SELECT p.product_id, p.name, ROUND(SUM(i.quantity * i.unit_price), 2) AS revenue_gbp
FROM order_items i JOIN products p ON p.product_id = i.product_id
WHERE i.unit_price >= 0 GROUP BY p.product_id, p.name ORDER BY revenue_gbp DESC, p.product_id LIMIT 5''',
    'show revenue by country': f'SELECT o.country, ROUND(SUM(i.quantity * i.unit_price), 2) AS revenue_gbp {REVENUE_FROM} GROUP BY o.country ORDER BY revenue_gbp DESC',
    'how many orders are there': 'SELECT COUNT(*) AS invoices_including_cancellations FROM orders',
}


def offline_answer(question: str, tools: DatasetTools, kind: str) -> dict:
    normalized = demo_question(question, kind)
    if kind == 'csv' and normalized in {'describe my data', 'show columns', 'show missing values'}:
        return csv_profile(normalized, tools)
    if question.lower().startswith('/sql '):
        sql = question[5:]
    elif re.search(r'\b(delete|drop|update|insert|alter|remove)\b', normalized):
        return {'status': 'unable', 'answer': 'This assistant can only read data. It cannot modify or delete records.'}
    elif 'best' in normalized or 'performed' in normalized:
        return {'status': 'clarify', 'answer': 'Which metric do you mean—revenue, units, or invoice count—and for what period? Offline mode supports the example questions or /sql SELECT ….'}
    elif kind == 'csv' and normalized in {'show data', 'preview', 'show first rows'}:
        sql = 'SELECT * FROM records LIMIT 10'
    elif kind == 'csv' and normalized in {'how many rows', 'how many rows are there'}:
        sql = 'SELECT COUNT(*) AS row_count FROM records'
    elif kind == 'sample' and normalized in DEMO_SQL:
        sql = DEMO_SQL[normalized]
    else:
        examples = ('Try “total revenue”, “revenue per month”, “top 5 products by revenue”, '
                    '“sales by country”, or “number of orders”.' if kind == 'sample'
                    else 'For your CSV, try “describe my data”, “show columns”, “show missing values”, “show data”, or “how many rows”.')
        return {'status': 'unable', 'answer': 'Demo mode could not match this to a supported calculation. '
                + examples + '\n\nDate filters, other metrics and conversational follow-ups need AI mode or /sql SELECT ….'}
    result = tools.run_checked_query(sql)
    if 'error' in result:
        return {'status': 'unable', 'answer': result['error']}
    if not result['rows']:
        answer = 'No matching rows were found.'
    elif len(result['rows']) == 1 and len(result['columns']) == 1:
        value = result['rows'][0][0]
        answer = f'{result["columns"][0]}: {value:,.2f}' if isinstance(value, float) else f'{result["columns"][0]}: {value}'
        if normalized == 'what is the total revenue' and kind == 'sample':
            answer = f'Net revenue is {format_gbp(value)}, including cancellation credits.' if value is not None else ''
        elif normalized == 'how many orders are there' and kind == 'sample':
            answer = f'There are {value:,} invoices, including cancellations.'
        elif kind == 'csv' and normalized in {'how many rows', 'how many rows are there'}:
            answer = f'Your file contains {value:,} rows.'
        if value is None:
            answer = 'The aggregate is NULL; there may be no matching non-null values.'
    elif normalized == 'show monthly revenue' and kind == 'sample':
        answer = 'Net revenue by month, including cancellation credits:\n\n' + '\n'.join(
            f'{datetime.strptime(month, "%Y-%m").strftime("%b %Y")} — {format_gbp(revenue)}'
            for month, revenue in result['rows']
        )
        answer += '\n\nBoth December periods are partial; these selected invoices do not represent a retailer-wide trend.'
    elif normalized == 'show revenue by country' and kind == 'sample':
        answer = 'Net revenue by country, including cancellation credits:\n\n' + '\n'.join(
            f'{country or "Unknown country"} — {format_gbp(revenue)}'
            for country, revenue in result['rows']
        )
    elif normalized == 'which five products generated the most revenue' and kind == 'sample':
        answer = 'The top five products by net revenue are:\n\n' + '\n'.join(
            f'{index}. {name or product_id} — {format_gbp(revenue)}'
            for index, (product_id, name, revenue) in enumerate(result['rows'], start=1)
        )
    else:
        answer = f'Found {len(result["rows"])} rows. Open “View results” beneath this answer to see the results.'
    if result['truncated']:
        answer += ' Output is limited to 100 rows; additional rows are not displayed.'
    if kind == 'sample':
        answer += '\n\nThese figures cover the sample dataset only.'
    return {'status': 'answer', 'answer': answer}


def recent_context(history: list[dict]) -> list[dict]:
    """Keep recent questions, answers and exact SQL, not repeated source/result blobs."""
    messages = []
    used = 0
    for message in reversed(history[-12:]):
        if message['role'] not in {'user', 'assistant'}:
            continue
        payload = message['payload']
        content = {'text': payload.get('answer', '')}
        if message['role'] == 'assistant':
            content['previous_sql'] = [q['sql'] for q in payload.get('queries', [])]
            content['status'] = payload.get('status', '')
        text = json.dumps(content)
        # Omit whole old messages rather than cutting JSON or a WHERE clause in half.
        if used + len(text) > 16000:
            break
        used += len(text)
        messages.append({'role': message['role'], 'content': text})
    return list(reversed(messages))


async def ai_answer(question: str, tools: DatasetTools, history: list[dict], *, config: AIConfig | None = None) -> dict:
    config = config or AIConfig.from_env()
    try:
        config.validate()
    except ValueError as exc:
        return {'status': 'unable', 'answer': str(exc)}
    try:
        from agents import Agent, ModelSettings, OpenAIResponsesModel, Runner, RunConfig, function_tool
        from openai import AsyncOpenAI
        from pydantic import BaseModel
    except ImportError:
        return {'status': 'unable', 'answer': 'Install requirements-agent.txt to enable AI mode.'}

    class ProposedDefinition(BaseModel):
        column: str
        meaning: str

    class AgentAnswer(BaseModel):
        status: Literal['answer', 'clarify', 'unable']
        answer: str
        proposed_definition: ProposedDefinition | None = None

    @function_tool
    def get_schema() -> str:
        """Return the active dataset tables and column types."""
        return json.dumps(tools.get_schema())

    @function_tool
    def search_context(question: str) -> str:
        """Return reviewed definitions for the active dataset."""
        return json.dumps(tools.search_context(question))

    @function_tool
    def run_checked_query(sql: str) -> str:
        """Validate and run one read-only SQLite query on the active dataset."""
        return json.dumps(tools.run_checked_query(sql))

    tools.check_categories = True
    recent = recent_context(history)
    recent.append({'role': 'user', 'content': json.dumps({
        'question': question, 'active_schema': tools.get_schema(),
        'category_values': tools.category_values(),
        'definitions': tools.search_context(question),
        'context_note': 'Earlier answers are history only. Query the current dataset for new numbers.'
    })})
    try:
        async with AsyncOpenAI(api_key=config.api_key, base_url='https://api.openai.com/v1',
                               max_retries=0, timeout=60) as client:
            agent = Agent(name='Ask Your Data', instructions=SYSTEM_PROMPT,
                          model=OpenAIResponsesModel(model=config.model, openai_client=client),
                          tools=[get_schema, search_context, run_checked_query], output_type=AgentAnswer,
                          model_settings=ModelSettings(parallel_tool_calls=False, max_tokens=2500, store=False))
            result = await asyncio.wait_for(Runner.run(agent, recent, max_turns=8,
                                                      run_config=RunConfig(tracing_disabled=True)), timeout=90)
        answer = result.final_output.model_dump()
        if answer['status'] == 'answer' and not tools.results:
            answer = {'status': 'unable', 'answer': 'No checked query completed, so I cannot provide a data answer.'}
        usage = result.context_wrapper.usage
        answer['usage'] = {'requests': usage.requests, 'input_tokens': usage.input_tokens, 'output_tokens': usage.output_tokens}
        return answer
    except TimeoutError:
        return {'status': 'unable', 'answer': 'The model timed out. Your chat is saved; please try again.'}
    except Exception as exc:
        return {'status': 'unable', 'answer': provider_error(exc)}


async def ask(store: Store, chat_id: str, question: str, *, use_ai: bool = False, config: AIConfig | None = None) -> dict:
    question = question.strip()
    if not question or len(question) > 4000:
        raise ValueError('Enter a question of 1–4,000 characters.')
    dataset_id = store.chat(chat_id)['dataset_id']
    history = store.messages(chat_id, current_only=True)
    kind = store.dataset(dataset_id)['kind']
    # Basic CSV inspection has a known, checked calculation. Run it locally in
    # either mode instead of depending on a model to invent an overview query.
    local_profile = kind == 'csv' and demo_question(question, kind) in {
        'describe my data', 'show columns', 'show missing values',
    }
    remote = use_ai and not question.lower().startswith('/sql ') and not local_profile
    store.append(chat_id, dataset_id, 'user', {'answer': question})
    memory_notice = remember_confirmation(store, chat_id, dataset_id, question, history) if remote else None
    # Capture the updated definitions before the model answers this confirmation.
    tools = DatasetTools(store, dataset_id)
    # Explicit SQL is always local, including when the user selected AI mode.
    if remote:
        response = await ai_answer(question, tools, history, config=config)
        pending_definition(response, tools)
    else:
        response = offline_answer(question, tools, kind)
    response.update(dataset_id=dataset_id, mode='ai' if remote else 'offline', queries=tools.results,
                    sources=tools.search_context(question), query_errors=tools.errors)
    if memory_notice:
        response['answer'] += '\n\n' + memory_notice
    store.append(chat_id, dataset_id, 'assistant', response)
    return response
