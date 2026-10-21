import pytest

from src.sample import ensure_sample
from src.workflow import ask


@pytest.mark.parametrize('question,canonical', [
    ('What are total sales?', 'What is the total revenue?'),
    ('What’s the total revenue?', 'What is the total revenue?'),
    ('  PLEASE show me TOTAL sales, please!  ', 'What is the total revenue?'),
    ('Revenue per month', 'Show monthly revenue'),
    ('Could you show me monthly sales?', 'Show monthly revenue'),
    ('Top 5 products by revenue', 'Which five products generated the most revenue?'),
    ('Which products earned the most?', 'Which five products generated the most revenue?'),
    ('Sales by country', 'Show revenue by country'),
    ('Number of orders', 'How many orders are there?'),
    ('How many invoices do we have?', 'How many orders are there?'),
])
async def test_variations_use_same_reviewed_calculation(store, question, canonical):
    chat = store.new_chat(ensure_sample(store))
    expected = await ask(store, chat, canonical)
    actual = await ask(store, chat, question)
    assert actual['status'] == 'answer'
    assert len(actual['queries']) == len(expected['queries']) == 1
    for field in ('sql', 'columns', 'rows', 'truncated'):
        assert actual['queries'][0][field] == expected['queries'][0][field]
    assert actual['answer'] == expected['answer']
    assert store.messages(chat)[-2]['payload']['answer'] == question.strip()
    assert actual['mode'] == 'offline'


@pytest.mark.parametrize('question', [
    'Total revenue in 2011',
    'Show monthly revenue excluding cancellations',
    'Sales by country for France',
    'Top 10 products by revenue',
    'Top 5 products by units',
    'Total gross sales',
    'Number of orders without cancellations',
    'Total revenue and number of orders',
    'What about last month?',
    'Do not show total revenue',
])
async def test_unsupported_qualifiers_never_run_unfiltered_query(store, question):
    chat = store.new_chat(ensure_sample(store))
    actual = await ask(store, chat, question)
    assert actual['status'] == 'unable'
    assert actual['queries'] == []


async def test_csv_variations_do_not_assume_retail_definitions(store, simple_dataset):
    chat = store.new_chat(simple_dataset)
    assert (await ask(store, chat, 'Number of rows'))['queries'][0]['rows'] == [[3]]
    assert len((await ask(store, chat, 'Show a few rows'))['queries'][0]['rows']) == 3
    assert (await ask(store, chat, 'Total sales'))['queries'] == []
