import json

import pytest

from src.retrieval import search_context
from src.sample import ensure_sample
from src.storage import Store
from src.tools import DatasetTools
from src.workflow import ask, recent_context


def test_definition_revision_persists_and_is_scoped(store, simple_dataset):
    chat = store.new_chat(simple_dataset)
    shared = store.new_chat(simple_dataset)
    sample = ensure_sample(store)
    other = store.new_chat(sample)
    store.append(chat, simple_dataset, 'user', {'answer': 'Old question'})
    store.append(shared, simple_dataset, 'user', {'answer': 'Old shared question'})
    text = 'amount is a line total in AUD. Negative amounts are refunds.'
    assert store.save_definitions(chat, text) == 1
    reopened = Store(store.home)
    sources = search_context(reopened, simple_dataset, 'revenue')
    assert sources[-1]['text'] == text
    assert sources[-1]['revision'] == '1'
    assert reopened.messages(chat, current_only=True) == []
    assert reopened.messages(shared, current_only=True) == []
    assert reopened.messages(other) == []
    assert all(text not in s['text'] for s in search_context(reopened, sample, 'revenue'))
    assert store.save_definitions(chat, text) == 1  # no-op does not reset conversation
    assert len(store.messages(chat)) == 2
    assert store.save_definitions(chat, '') == 2
    assert all(s['source'] != 'Your saved definitions' for s in search_context(store, simple_dataset, 'revenue'))


async def test_old_answers_keep_their_original_definition_snapshot(store, simple_dataset):
    chat = store.new_chat(simple_dataset)
    store.save_definitions(chat, 'amount is in AUD.')
    first = await ask(store, chat, 'how many rows')
    tools = DatasetTools(store, simple_dataset)
    store.save_definitions(chat, 'amount is in GBP.')
    second = await ask(store, chat, 'how many rows')
    assert first['sources'][-1]['text'] == 'amount is in AUD.'
    assert second['sources'][-1]['text'] == 'amount is in GBP.'
    assert tools.search_context('anything')[-1]['text'] == 'amount is in AUD.'


def test_sample_and_oversized_definitions_rejected(store, simple_dataset):
    with pytest.raises(ValueError, match='reviewed'):
        store.save_definitions(store.new_chat(ensure_sample(store)), 'revenue is 1')
    with pytest.raises(ValueError, match='8,000'):
        store.save_definitions(store.new_chat(simple_dataset), 'x' * 8001)


def test_recent_context_preserves_complete_filters_without_old_result_blobs():
    history = [{'role': 'user', 'payload': {'answer': 'Total revenue for August 2011?'}},
               {'role': 'assistant', 'payload': {'answer': 'Total is 1', 'status': 'answer',
                'queries': [{'sql': "SELECT SUM(amount) FROM records WHERE date >= '2011-08-01' AND date < '2011-09-01'", 'rows': [[1]]}],
                'sources': [{'text': 's' * 30000}]}},
               {'role': 'user', 'payload': {'answer': 'Break that down by product'}}]
    recent = recent_context(history)
    assert len(recent) == 3
    previous = json.loads(recent[1]['content'])
    assert '2011-09-01' in previous['previous_sql'][0]
    assert 'sources' not in previous and 'rows' not in previous
    assert json.loads(recent[2]['content'])['text'] == 'Break that down by product'


def test_context_omits_whole_oversized_messages():
    history = [{'role': 'assistant', 'payload': {'answer': 'x' * 20000}},
               {'role': 'user', 'payload': {'answer': 'A recent question'}}]
    recent = recent_context(history)
    assert len(recent) == 1
    assert json.loads(recent[0]['content'])['text'] == 'A recent question'
