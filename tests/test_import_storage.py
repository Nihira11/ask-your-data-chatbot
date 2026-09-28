from pathlib import Path

import pytest

from src.database import run_query
from src.importer import import_csv, inspect_csv
from src.storage import Store


def test_csv_copy_types_and_restoration(store, tmp_path):
    source = tmp_path / 'input.csv'
    source.write_text('customer,amount,note\n001,10.50,"hello, world"\n002,5.20,\n')
    data = inspect_csv(source)
    assert data['types'] == ['TEXT', 'REAL', 'TEXT']
    dataset = import_csv(store, data)
    chat = store.new_chat(dataset)
    source.unlink()
    reopened = Store(store.home)
    assert reopened.chat(chat)['dataset_id'] == dataset
    assert reopened.dataset_path(dataset).with_suffix('.csv').exists()
    result = run_query(reopened.dataset_path(dataset), 'SELECT * FROM records')
    assert result['rows'] == [['001', 10.5, 'hello, world'], ['002', 5.2, None]]


@pytest.mark.parametrize('text', ['', 'a,a\n1,2', 'A, a \n1,2', 'a,b\n1', 'a,b\n', ',b\n1,2', 'a\n"unclosed', 'a\nx\x00y'])
def test_bad_csv(store, tmp_path, text):
    file = tmp_path / 'bad.csv'
    file.write_text(text)
    with pytest.raises(ValueError):
        inspect_csv(file)
    assert store.chats() == []


def test_size_and_encoding_limits(tmp_path):
    file = tmp_path / 'big.csv'
    file.write_bytes(b'x' * (5 * 1024 * 1024 + 1))
    with pytest.raises(ValueError, match='5 MB'):
        inspect_csv(file)
    file.write_bytes(b'column\n\xff\n')
    with pytest.raises(ValueError, match='UTF-8'):
        inspect_csv(file)


def test_dataset_switch_and_chat_isolation(store, simple_dataset, tmp_path):
    first = store.new_chat(simple_dataset)
    second = store.new_chat(simple_dataset)
    store.append(first, simple_dataset, 'user', {'answer': 'old question'})
    path = tmp_path / 'new.csv'
    path.write_text('new_amount\n999\n')
    new = import_csv(store, inspect_csv(path))
    store.activate(first, new)
    assert store.chat(second)['dataset_id'] == simple_dataset
    assert store.messages(second) == []
    assert store.messages(first)[0]['dataset_id'] == simple_dataset
    assert store.messages(first, current_only=True) == []
    store.activate(first, simple_dataset)
    assert store.messages(first, current_only=True) == []


def test_path_traversal_is_rejected(store):
    with pytest.raises(ValueError):
        store.dataset_path('../../outside')
