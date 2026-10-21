import csv
import json

import pytest

from src.export import export_chat_results
from src.formatting import format_gbp


def history():
    return [
        {'id': 1, 'role': 'user', 'payload': {'answer': 'Show sales'}},
        {'id': 2, 'role': 'assistant', 'dataset_id': 'old', 'payload': {'answer': 'Saved answer', 'queries': [
            {'columns': ['name', 'amount', 'note'], 'rows': [['=1+1', -40.0, 'comma, and\nnewline'], ['001', None, 'ok']],
             'sql': 'SELECT name, amount, note FROM records', 'truncated': True},
            {'columns': ['empty'], 'rows': [], 'sql': 'SELECT 1 WHERE 0', 'truncated': False},
        ]}},
        {'id': 3, 'role': 'user', 'payload': {'answer': 'Only branch A'}},
        {'id': 4, 'role': 'assistant', 'dataset_id': 'old', 'payload': {'answer': 'Is A the branch?', 'queries': []}},
        {'id': 5, 'role': 'user', 'payload': {'answer': 'yes please'}},
        {'id': 6, 'role': 'assistant', 'dataset_id': 'new', 'payload': {'answer': '3 units', 'queries': [
            {'columns': ['units'], 'rows': [[3]], 'sql': 'SELECT 3 AS units', 'truncated': False},
        ]}},
    ]


def test_export_all_answers_preserves_values_shapes_questions_and_limits(tmp_path):
    messages = history()
    datasets = {'old': 'First dataset', 'new': 'Second dataset'}
    folder = export_chat_results(tmp_path, 'chat-1', messages, datasets)
    with (folder / 'answer-001-query-01.csv').open(encoding='utf-8-sig', newline='') as file:
        rows = list(csv.reader(file))
    assert rows == [['name', 'amount', 'note'], ["'=1+1", '-40.0', 'comma, and\nnewline'], ['001', '', 'ok']]
    notes = json.loads((folder / 'details.json').read_text())
    assert len(notes['answers']) == 2
    assert notes['answers'][0]['results'][0]['truncated'] is True
    assert notes['answers'][0]['dataset'] == 'First dataset'
    assert notes['answers'][1]['question'] == 'yes please'
    assert notes['answers'][1]['dataset'] == 'Second dataset'
    assert (folder / 'answer-001-query-02.csv').read_text(encoding='utf-8-sig').strip() == 'empty'
    with (folder / 'index.csv').open(encoding='utf-8-sig', newline='') as file:
        index = list(csv.DictReader(file))
    assert len(index) == 3
    assert [row['question'] for row in index] == ['Show sales', 'Show sales', 'yes please']
    assert index[2]['answer'] == '3 units'
    assert index[2]['file'] == 'answer-002-query-01.csv'
    assert export_chat_results(tmp_path, 'chat-1', messages, datasets) != folder
    assert messages[1]['payload']['queries'][0]['rows'][0][0] == '=1+1'
    assert format_gbp(-40) == '−£40.00'


def test_no_results_creates_no_export(tmp_path):
    with pytest.raises(ValueError, match='no query results'):
        export_chat_results(tmp_path, 'empty', [], {})
    assert list(tmp_path.iterdir()) == []


def test_partial_export_failure_cleans_only_new_folder(tmp_path, monkeypatch):
    existing = tmp_path / 'keep.csv'
    existing.write_text('keep me')
    def fail(*args, **kwargs):
        raise OSError('disk full')
    monkeypatch.setattr('src.export.write_csv', fail)
    with pytest.raises(OSError):
        export_chat_results(tmp_path, 'chat-1', history(), {'old': 'Old', 'new': 'New'})
    assert list(tmp_path.iterdir()) == [existing]
    assert existing.read_text() == 'keep me'
