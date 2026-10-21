import csv

from src.importer import import_csv, inspect_csv
from src.workflow import ask


async def test_profile_counts_blanks_without_guessing_meanings(store, tmp_path):
    path = tmp_path / 'sales.csv'
    path.write_text('id,amount,date,note\n001,0,2020-01-01,N/A\n002,,2020-01-02, \n003,-4.5,,\n')
    dataset = import_csv(store, inspect_csv(path))
    chat = store.new_chat(dataset)
    overview = await ask(store, chat, 'Describe my data')
    assert overview['status'] == 'answer'
    assert '3 rows and 4 columns' in overview['answer']
    assert '4 of 12 (33.3%)' in overview['answer']
    assert overview['queries'][0]['rows'] == [[3, 0, 1, 1, 2]]
    assert overview['queries'][0]['columns'] == [
        'row_count', 'empty_cells__id', 'empty_cells__amount', 'empty_cells__date', 'empty_cells__note',
    ]
    assert overview['queries'][0]['display'] == 'empty_cells_by_column'
    columns = await ask(store, chat, 'Show columns')
    assert 'id — text' in columns['answer']
    assert 'date — text' in columns['answer']
    assert 'business definitions' in columns['answer']
    assert columns['sources'][-1]['source'] == 'CSV column types'
    missing = await ask(store, chat, 'Show missing values')
    assert 'note: 2 (66.7%)' in missing['answer']
    assert 'id: 0 (0.0%)' in missing['answer']
    assert missing['mode'] == 'offline'
    path.write_text('new,contents\n99,99\n')
    again = await ask(store, chat, 'Data summary')
    assert again['answer'] == overview['answer']


async def test_wide_quoted_headers_stay_within_query_limits(store, tmp_path):
    path = tmp_path / 'wide.csv'
    headers = ['"' * 97 + f'{i:03d}' for i in range(100)]
    with path.open('w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(headers)
        writer.writerow([''] * 100)
    chat = store.new_chat(import_csv(store, inspect_csv(path)))
    answer = await ask(store, chat, 'show missing values')
    assert answer['status'] == 'answer'
    assert 1 <= len(answer['queries']) <= 3
    assert sum(len(q['columns']) - 1 for q in answer['queries']) == 100
    assert all(value == 1 for q in answer['queries'] for value in q['rows'][0])
    assert '25 columns' in answer['answer']
    columns = await ask(store, chat, 'show columns')
    assert not columns['queries']
    assert all(header in columns['answer'] for header in headers)


async def test_profile_follows_active_dataset_and_rejects_filters(store, simple_dataset, tmp_path):
    chat = store.new_chat(simple_dataset)
    first = await ask(store, chat, 'describe my data')
    path = tmp_path / 'another.csv'
    path.write_text('a\nhello\n')
    other = import_csv(store, inspect_csv(path))
    store.activate(chat, other)
    second = await ask(store, chat, 'describe my data')
    assert '3 rows and 2 columns' in first['answer']
    assert '1 row and 1 column' in second['answer']
    filtered = await ask(store, chat, 'Show missing values for 2020')
    assert filtered['status'] == 'unable'
    assert not filtered['queries']


async def test_tips_description_in_ai_mode_uses_checked_local_profile(store, monkeypatch):
    from src.storage import ROOT, Store
    async def no_ai(*args, **kwargs):
        raise AssertionError('A basic overview does not need a model query')
    monkeypatch.setattr('src.workflow.ai_answer', no_ai)
    dataset = import_csv(store, inspect_csv(ROOT / 'data/sample/tips.csv'))
    chat = store.new_chat(dataset)
    answer = await ask(store, chat, 'Describe this dataset', use_ai=True)
    assert answer['status'] == 'answer'
    assert answer['mode'] == 'offline'
    assert '244 rows and 7 columns' in answer['answer']
    assert '0 of 1,708' in answer['answer']
    assert answer['queries'][0]['rows'] == [[244, 0, 0, 0, 0, 0, 0, 0]]
    assert answer['query_errors'] == []
    reopened = Store(store.home)
    assert reopened.messages(chat)[-1]['payload']['queries'] == answer['queries']


async def test_filtered_description_still_uses_ai(store, simple_dataset, monkeypatch):
    calls = []
    async def fake_ai(question, tools, history, **kwargs):
        calls.append(question)
        tools.run_checked_query('SELECT COUNT(*) FROM records WHERE amount > 0')
        return {'status': 'answer', 'answer': '2 matching rows.'}
    monkeypatch.setattr('src.workflow.ai_answer', fake_ai)
    chat = store.new_chat(simple_dataset)
    result = await ask(store, chat, 'Describe this dataset for amount greater than zero', use_ai=True)
    assert result['mode'] == 'ai'
    assert result['queries'][0]['rows'] == [[2]]
    assert len(calls) == 1
